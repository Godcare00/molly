import os
import shutil
import subprocess
import zipfile
import mimetypes
from pathlib import Path
from typing import Optional, List, Dict, Any
from app.tools.registry import BaseTool, ToolResult, RiskLevel, registry
from app.security.paths import canonicalize_path, validate_path_safety
from app.tools.ast_edit import (
    insert_inside_class,
    parse_file,
    extract_symbols,
    find_symbol,
    replace_symbol,
    insert_after_symbol,
    insert_before_symbol,
    add_import,
    is_ast_supported,
    get_supported_operations,
    Symbol,
)

MAX_ARCHIVE_ENTRIES_LISTED = 500
MAX_ARCHIVE_ENTRY_READ_BYTES = 5 * 1024 * 1024  # per-entry cap, guards against zip-bomb-style single entries


class ListDirectoryTool(BaseTool):
    name = "list_directory"
    description = "List a directory with bounded output. Returns filename, type, size, permissions."
    risk_level = RiskLevel.READ
    timeout_seconds = 10
    output_limit_chars = 5000

    async def execute(self, path: str, limit: int = 200) -> ToolResult:
        try:
            safe_path = canonicalize_path(path)
            validate_path_safety(safe_path)

            if not safe_path.exists():
                return ToolResult(success=False, error=f"Path does not exist: {path}")

            if not safe_path.is_dir():
                return ToolResult(success=False, error=f"Path is not a directory: {path}")

            entries = []
            for entry in safe_path.iterdir():
                try:
                    stat = entry.stat()
                    entries.append(
                        {
                            "name": entry.name,
                            "type": "directory" if entry.is_dir() else "file" if entry.is_file() else "other",
                            "size": stat.st_size,
                            "permissions": oct(stat.st_mode)[-3:],
                            "modified": stat.st_mtime,
                        }
                    )
                except (OSError, PermissionError):
                    entries.append(
                        {
                            "name": entry.name,
                            "type": "unknown",
                            "size": 0,
                            "permissions": "???",
                            "modified": 0,
                        }
                    )

            # Sort: directories first, then files, alphabetically
            entries.sort(key=lambda e: (e["type"] != "directory", e["name"].lower()))

            truncated = len(entries) > limit
            if truncated:
                entries = entries[:limit]

            return ToolResult(
                success=True,
                output={"path": str(safe_path), "entries": entries, "total_count": len(entries) + (len(entries) - limit if truncated else 0)},
                truncated=truncated,
                metadata={"resolved_path": str(safe_path)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "Search for files by name pattern or content. Returns bounded results."
    risk_level = RiskLevel.READ
    timeout_seconds = 30
    output_limit_chars = 8000

    async def execute(
        self,
        path: str,
        pattern: str,
        content_search: bool = False,
        case_sensitive: bool = False,
        file_type: Optional[str] = None,
        max_results: int = 100,
        max_depth: int = 10,
    ) -> ToolResult:
        try:
            safe_path = canonicalize_path(path)
            validate_path_safety(safe_path)

            if not safe_path.exists():
                return ToolResult(success=False, error=f"Path does not exist: {path}")

            results = []

            if content_search:
                # Use grep for content search
                cmd = ["grep", "-r", "-l"]
                if not case_sensitive:
                    cmd.append("-i")
                if file_type:
                    cmd.extend(["--include", f"*.{file_type}"])
                cmd.extend([pattern, str(safe_path)])

                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    for line in result.stdout.strip().split("\n"):
                        if line and len(results) < max_results:
                            results.append({"path": line, "match_type": "content"})
                except subprocess.TimeoutExpired:
                    pass
            else:
                # Use find for name pattern
                cmd = ["find", str(safe_path), "-maxdepth", str(max_depth)]
                if file_type:
                    cmd.extend(["-name", f"*.{file_type}"])
                else:
                    cmd.extend(["-name", pattern])

                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    for line in result.stdout.strip().split("\n"):
                        if line and len(results) < max_results:
                            p = Path(line)
                            try:
                                stat = p.stat()
                                results.append(
                                    {
                                        "path": line,
                                        "name": p.name,
                                        "type": "directory" if p.is_dir() else "file",
                                        "size": stat.st_size,
                                        "match_type": "name",
                                    }
                                )
                            except OSError:
                                results.append({"path": line, "name": p.name, "type": "unknown", "size": 0, "match_type": "name"})
                except subprocess.TimeoutExpired:
                    pass

            truncated = len(results) >= max_results
            return ToolResult(
                success=True,
                output={"results": results, "search_path": str(safe_path), "pattern": pattern},
                truncated=truncated,
                metadata={"resolved_path": str(safe_path)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "Read a file. Handles plain text (with optional line range), zip-family archives "
        "(.zip/.docx/.xlsx/.pptx/.jar/... — lists entries, or reads one entry's text via "
        "archive_entry), PDFs (extracts text, optionally by page range via page_start/page_end), "
        "and falls back to a binary summary (mime type, size, hex preview) for anything else."
    )
    risk_level = RiskLevel.READ
    timeout_seconds = 15
    output_limit_chars = 50000

    async def execute(
        self,
        path: str,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        max_chars: Optional[int] = None,
        archive_entry: Optional[str] = None,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None,
    ) -> ToolResult:
        try:
            safe_path = canonicalize_path(path)
            validate_path_safety(safe_path)

            if not safe_path.exists():
                return ToolResult(success=False, error=f"File does not exist: {path}")

            if not safe_path.is_file():
                return ToolResult(success=False, error=f"Path is not a file: {path}")

            file_size = safe_path.stat().st_size
            max_chars = max_chars or self.output_limit_chars

            # Zip-family archives are listed/read entry-by-entry rather than
            # loaded whole, so they're exempt from the flat size cap below.
            if zipfile.is_zipfile(safe_path):
                return self._read_zip(safe_path, file_size, archive_entry, max_chars)

            if file_size > 10 * 1024 * 1024:  # 10MB limit
                return ToolResult(success=False, error=f"File too large: {file_size} bytes (max 10MB)")

            with open(safe_path, "rb") as f:
                head = f.read(8)
            if head.startswith(b"%PDF"):
                return self._read_pdf(safe_path, file_size, page_start, page_end, max_chars)

            with open(safe_path, "rb") as f:
                sample = f.read(8192)
            if b"\x00" in sample:
                return self._read_binary_summary(safe_path, file_size)

            encoding_note = None
            try:
                with open(safe_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except UnicodeDecodeError:
                with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                encoding_note = "File is not valid UTF-8; invalid bytes were replaced with \ufffd."

            total_lines = len(lines)

            if start_line is not None or end_line is not None:
                start = max(0, (start_line or 1) - 1)
                end = min(total_lines, end_line or total_lines)
                selected_lines = lines[start:end]
                content = "".join(selected_lines)
                line_range = f"lines {start + 1}-{end} of {total_lines}"
            else:
                content = "".join(lines)
                line_range = f"all {total_lines} lines"

            truncated = len(content) > max_chars
            if truncated:
                content = content[:max_chars]
                line_range += f" (truncated to {max_chars} chars)"

            output = {
                "kind": "text",
                "path": str(safe_path),
                "content": content,
                "line_range": line_range,
                "total_lines": total_lines,
                "file_size": file_size,
            }
            if encoding_note:
                output["encoding_note"] = encoding_note

            return ToolResult(
                success=True,
                output=output,
                truncated=truncated,
                metadata={"resolved_path": str(safe_path)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _read_zip(
        self,
        safe_path: Path,
        file_size: int,
        archive_entry: Optional[str],
        max_chars: int,
    ) -> ToolResult:
        try:
            with zipfile.ZipFile(safe_path) as zf:
                infos = zf.infolist()

                if archive_entry:
                    matches = [i for i in infos if i.filename == archive_entry]
                    if not matches:
                        return ToolResult(success=False, error=f"Entry not found in archive: {archive_entry}")
                    info = matches[0]
                    if info.is_dir():
                        return ToolResult(success=False, error=f"'{archive_entry}' is a directory in the archive")
                    if info.file_size > MAX_ARCHIVE_ENTRY_READ_BYTES:
                        return ToolResult(
                            success=False,
                            error=f"Archive entry too large: {info.file_size} bytes (max {MAX_ARCHIVE_ENTRY_READ_BYTES})",
                        )

                    raw = zf.read(info)
                    if b"\x00" in raw[:8192]:
                        return ToolResult(
                            success=True,
                            output={
                                "kind": "archive_entry_binary",
                                "path": str(safe_path),
                                "entry": archive_entry,
                                "entry_size": info.file_size,
                                "message": "This entry is binary and can't be shown as text.",
                            },
                            metadata={"resolved_path": str(safe_path)},
                        )

                    encoding_note = None
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        text = raw.decode("utf-8", errors="replace")
                        encoding_note = "Entry is not valid UTF-8; invalid bytes were replaced with \ufffd."

                    truncated = len(text) > max_chars
                    if truncated:
                        text = text[:max_chars]

                    output = {
                        "kind": "archive_entry",
                        "path": str(safe_path),
                        "entry": archive_entry,
                        "content": text,
                        "entry_size": info.file_size,
                    }
                    if encoding_note:
                        output["encoding_note"] = encoding_note

                    return ToolResult(
                        success=True,
                        output=output,
                        truncated=truncated,
                        metadata={"resolved_path": str(safe_path)},
                    )

                # No entry requested: list the archive's contents.
                total_uncompressed = sum(i.file_size for i in infos)
                truncated = len(infos) > MAX_ARCHIVE_ENTRIES_LISTED
                entries = [
                    {
                        "name": i.filename,
                        "size": i.file_size,
                        "compressed_size": i.compress_size,
                        "is_dir": i.is_dir(),
                    }
                    for i in infos[:MAX_ARCHIVE_ENTRIES_LISTED]
                ]

                return ToolResult(
                    success=True,
                    output={
                        "kind": "archive",
                        "path": str(safe_path),
                        "file_size": file_size,
                        "entry_count": len(infos),
                        "total_uncompressed_size": total_uncompressed,
                        "entries": entries,
                        "hint": 'Pass archive_entry="<name>" to read one file inside this archive.',
                    },
                    truncated=truncated,
                    metadata={"resolved_path": str(safe_path)},
                )
        except zipfile.BadZipFile:
            return ToolResult(success=False, error="File has a zip signature but could not be read as an archive")

    def _read_pdf(
        self,
        safe_path: Path,
        file_size: int,
        page_start: Optional[int],
        page_end: Optional[int],
        max_chars: int,
    ) -> ToolResult:
        try:
            from pypdf import PdfReader
        except ImportError:
            return ToolResult(
                success=True,
                output={
                    "kind": "pdf_unavailable",
                    "path": str(safe_path),
                    "file_size": file_size,
                    "message": "pypdf isn't installed on this server, so PDF text extraction isn't available.",
                },
                metadata={"resolved_path": str(safe_path)},
            )

        try:
            reader = PdfReader(str(safe_path))
        except Exception as e:
            return ToolResult(success=False, error=f"Could not open PDF: {e}")

        total_pages = len(reader.pages)
        start = max(0, (page_start or 1) - 1)
        end = min(total_pages, page_end or total_pages)

        text_parts = []
        for i in range(start, end):
            try:
                text_parts.append(reader.pages[i].extract_text() or "")
            except Exception:
                text_parts.append("")
        content = "\n\n".join(text_parts)

        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]

        return ToolResult(
            success=True,
            output={
                "kind": "pdf",
                "path": str(safe_path),
                "content": content,
                "page_range": f"pages {start + 1}-{end} of {total_pages}",
                "total_pages": total_pages,
                "file_size": file_size,
            },
            truncated=truncated,
            metadata={"resolved_path": str(safe_path)},
        )

    def _read_binary_summary(self, safe_path: Path, file_size: int) -> ToolResult:
        mime_type = mimetypes.guess_type(str(safe_path))[0] or "application/octet-stream"
        with open(safe_path, "rb") as f:
            head = f.read(32)
        return ToolResult(
            success=True,
            output={
                "kind": "binary",
                "path": str(safe_path),
                "file_size": file_size,
                "mime_type": mime_type,
                "hex_preview": head.hex(),
                "message": (
                    "This file is binary and can't be shown as text. "
                    "Use view_image() for images; otherwise the mime_type/hex_preview "
                    "above are the best available signal."
                ),
            },
            metadata={"resolved_path": str(safe_path)},
        )


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Create or replace a file. This is a potentially consequential operation."
    risk_level = RiskLevel.MODERATE
    timeout_seconds = 10
    output_limit_chars = 2000

    async def execute(self, path: str, content: str, create_dirs: bool = True) -> ToolResult:
        try:
            safe_path = canonicalize_path(path)
            validate_path_safety(safe_path)

            if create_dirs:
                safe_path.parent.mkdir(parents=True, exist_ok=True)

            # Write atomically using temp file
            temp_path = safe_path.with_suffix(safe_path.suffix + ".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)

            temp_path.replace(safe_path)

            return ToolResult(
                success=True,
                output={"path": str(safe_path), "bytes_written": len(content.encode("utf-8"))},
                metadata={"resolved_path": str(safe_path)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class EditFileTool(BaseTool):
    name = "edit_file"
    description = "Perform targeted file modifications. Supports text operations (replace, insert, append, delete_section) and AST-aware operations (ast_replace_function, ast_replace_class, ast_add_import, ast_add_function, ast_get_symbols, etc.)."
    risk_level = RiskLevel.MODERATE
    timeout_seconds = 15
    output_limit_chars = 5000

    async def execute(
        self,
        path: str,
        operation: str,
        old_text: Optional[str] = None,
        new_text: Optional[str] = None,
        line_number: Optional[int] = None,
        count: int = 1,
        # AST-aware parameters
        symbol_name: Optional[str] = None,
        symbol_type: Optional[str] = None,
        parent_name: Optional[str] = None,
        import_statement: Optional[str] = None,
    ) -> ToolResult:
        try:
            safe_path = canonicalize_path(path)
            validate_path_safety(safe_path)

            if not safe_path.exists():
                return ToolResult(success=False, error=f"File does not exist: {path}")

            if not safe_path.is_file():
                return ToolResult(success=False, error=f"Path is not a file: {path}")

            with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            original_content = content
            diff_summary = ""

            # --- Text-based operations (original) ---
            if operation == "replace":
                if old_text is None:
                    return ToolResult(success=False, error="old_text required for replace operation")

                occurrences = content.count(old_text)
                if occurrences == 0:
                    return ToolResult(success=False, error="old_text not found in file")
                if occurrences > count:
                    return ToolResult(success=False, error=f"old_text found {occurrences} times, expected at most {count}. Use more specific text.")

                content = content.replace(old_text, new_text or "", count)
                diff_summary = f"Replaced {count} occurrence(s)"

            elif operation == "insert":
                if line_number is None or new_text is None:
                    return ToolResult(success=False, error="line_number and new_text required for insert operation")

                lines = content.splitlines(keepends=True)
                line_idx = max(0, min(line_number - 1, len(lines)))
                lines.insert(line_idx, new_text + ("\n" if not new_text.endswith("\n") else ""))
                content = "".join(lines)
                diff_summary = f"Inserted at line {line_number}"

            elif operation == "append":
                if new_text is None:
                    return ToolResult(success=False, error="new_text required for append operation")

                content = content + ("\n" if content and not content.endswith("\n") else "") + new_text
                diff_summary = "Appended to end of file"

            elif operation == "delete_section":
                if old_text is None:
                    return ToolResult(success=False, error="old_text required for delete_section operation")

                occurrences = content.count(old_text)
                if occurrences == 0:
                    return ToolResult(success=False, error="old_text not found in file")
                if occurrences > count:
                    return ToolResult(success=False, error=f"old_text found {occurrences} times, expected at most {count}")

                content = content.replace(old_text, "", count)
                diff_summary = f"Deleted {count} occurrence(s)"

            # --- AST-aware operations ---
            elif operation in get_supported_operations():
                if not is_ast_supported(path):
                    return ToolResult(success=False, error=f"AST editing not supported for {Path(path).suffix} files. Supported: .py, .js, .jsx, .ts, .tsx, .go, .rs")

                tree = parse_file(content, path)
                if not tree:
                    return ToolResult(success=False, error="Failed to parse file")

                if operation == "ast_get_symbols":
                    symbols = extract_symbols(tree, content.encode('utf-8'), path)
                    return ToolResult(
                        success=True,
                        output={
                            "path": str(safe_path),
                            "symbols": [
                                {
                                    "name": s.name,
                                    "type": s.type,
                                    "start_line": s.start_line,
                                    "end_line": s.end_line,
                                    "parent": s.parent,
                                    "signature": s.signature,
                                    "docstring": s.docstring,
                                }
                                for s in symbols
                            ],
                        },
                        metadata={"resolved_path": str(safe_path)},
                    )

                elif operation == "ast_find_symbol":
                    if not symbol_name:
                        return ToolResult(success=False, error="symbol_name required for ast_find_symbol")
                    symbol = find_symbol(tree, content.encode('utf-8'), symbol_name, symbol_type, parent_name, path)
                    if not symbol:
                        return ToolResult(success=False, error=f"Symbol '{symbol_name}' not found")
                    return ToolResult(
                        success=True,
                        output={
                            "path": str(safe_path),
                            "symbol": {
                                "name": symbol.name,
                                "type": symbol.type,
                                "start_line": symbol.start_line,
                                "end_line": symbol.end_line,
                                "parent": symbol.parent,
                                "signature": symbol.signature,
                                "docstring": symbol.docstring,
                            },
                        },
                        metadata={"resolved_path": str(safe_path)},
                    )

                elif operation == "ast_replace_function":
                    if not symbol_name or new_text is None:
                        return ToolResult(success=False, error="symbol_name and new_text required for ast_replace_function")
                    symbol = find_symbol(tree, content.encode('utf-8'), symbol_name, 'function', parent_name, path)
                    if not symbol:
                        return ToolResult(success=False, error=f"Function '{symbol_name}' not found")
                    content = replace_symbol(content, tree, symbol, new_text)
                    diff_summary = f"Replaced function '{symbol_name}' (lines {symbol.start_line}-{symbol.end_line})"

                elif operation == "ast_replace_class":
                    if not symbol_name or new_text is None:
                        return ToolResult(success=False, error="symbol_name and new_text required for ast_replace_class")
                    symbol = find_symbol(tree, content.encode('utf-8'), symbol_name, 'class', parent_name, path)
                    if not symbol:
                        return ToolResult(success=False, error=f"Class '{symbol_name}' not found")
                    content = replace_symbol(content, tree, symbol, new_text)
                    diff_summary = f"Replaced class '{symbol_name}' (lines {symbol.start_line}-{symbol.end_line})"

                elif operation == "ast_replace_method":
                    if not symbol_name or new_text is None:
                        return ToolResult(success=False, error="symbol_name and new_text required for ast_replace_method")
                    if not parent_name:
                        return ToolResult(success=False, error="parent_name (class name) required for ast_replace_method")
                    symbol = find_symbol(tree, content.encode('utf-8'), symbol_name, 'method', parent_name, path)
                    if not symbol:
                        return ToolResult(success=False, error=f"Method '{symbol_name}' not found in class '{parent_name}'")
                    content = replace_symbol(content, tree, symbol, new_text)
                    diff_summary = f"Replaced method '{symbol_name}' in class '{parent_name}' (lines {symbol.start_line}-{symbol.end_line})"

                elif operation == "ast_add_import":
                    if not import_statement:
                        return ToolResult(success=False, error="import_statement required for ast_add_import")
                    content = add_import(content, tree, import_statement, path)
                    diff_summary = f"Added import: {import_statement}"

                elif operation == "ast_add_function":
                    if not new_text:
                        return ToolResult(success=False, error="new_text required for ast_add_function")
                    # Add after last function/class or at end
                    symbols = extract_symbols(tree, content.encode('utf-8'), path)
                    func_symbols = [s for s in symbols if s.type in ('function', 'class')]
                    if func_symbols:
                        last_symbol = func_symbols[-1]
                        content = insert_after_symbol(content, tree, last_symbol, new_text)
                        diff_summary = f"Added function after '{last_symbol.name}'"
                    else:
                        # Append at end
                        content = content + ("\n" if content and not content.endswith("\n") else "") + new_text
                        diff_summary = "Added function at end of file"

                elif operation == "ast_add_method":
                    if not symbol_name or new_text is None:
                        return ToolResult(success=False, error="symbol_name and new_text required for ast_add_method")
                    if not parent_name:
                        return ToolResult(success=False, error="parent_name (class name) required for ast_add_method")
                    # Find class and add method before its closing
                    class_symbol = find_symbol(tree, content.encode('utf-8'), parent_name, 'class', file_path=path)
                    if not class_symbol:
                        return ToolResult(success=False, error=f"Class '{parent_name}' not found")
                    content = insert_inside_class(content, tree, class_symbol, new_text, path)
                    diff_summary = f"Added method '{symbol_name}' to class '{parent_name}'"

                else:
                    return ToolResult(success=False, error=f"Unknown AST operation: {operation}")

            else:
                return ToolResult(success=False, error=f"Unknown operation: {operation}. Supported: replace, insert, append, delete_section, {', '.join(get_supported_operations())}")

            # Write back atomically
            temp_path = safe_path.with_suffix(safe_path.suffix + ".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
            temp_path.replace(safe_path)

            return ToolResult(
                success=True,
                output={
                    "path": str(safe_path),
                    "operation": operation,
                    "diff_summary": diff_summary,
                    "bytes_changed": len(content) - len(original_content),
                },
                metadata={"resolved_path": str(safe_path)},
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


def register_filesystem_tools():
    registry.register(ListDirectoryTool())
    registry.register(SearchFilesTool())
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())