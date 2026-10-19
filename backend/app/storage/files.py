import uuid
import mimetypes
import aiofiles
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass
from app.storage.database import execute_query, execute_write
from app.config import settings


@dataclass
class FileMetadata:
    id: str
    conversation_id: str
    path: str
    filename: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    viewed_at: Optional[datetime] = None
    origin: str = "upload"  # "upload" (from the user) or "generated" (from Molly)

    @classmethod
    def from_row(cls, row) -> "FileMetadata":
        return cls(
            id=row["id"],
            conversation_id=row["conversation_id"],
            path=row["path"],
            filename=row["filename"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"] or 0,
            created_at=datetime.fromisoformat(row["created_at"]),
            viewed_at=datetime.fromisoformat(row["viewed_at"]) if row["viewed_at"] else None,
            # `origin` may be absent on rows written before the column existed
            # (sqlite3.Row supports `in` but not .get()).
            origin=row["origin"] if "origin" in row.keys() and row["origin"] else "upload",
        )


def _extension_of(filename: str) -> str:
    return Path(filename).suffix.lower()


async def _persist_file(
    conversation_id: str,
    file_content: bytes,
    filename: str,
    mime_type: str,
    origin: str,
) -> FileMetadata:
    """Shared write path for both uploaded and agent-generated files."""
    file_id = f"file_{uuid.uuid4().hex[:12]}"
    ext = _extension_of(filename)
    safe_filename = f"{file_id}{ext}"

    upload_dir = settings.uploads_path / "conversations" / conversation_id / "files"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / safe_filename

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(file_content)

    metadata = FileMetadata(
        id=file_id,
        conversation_id=conversation_id,
        path=str(file_path),
        filename=filename,
        mime_type=mime_type,
        size_bytes=len(file_content),
        created_at=datetime.utcnow(),
        origin=origin,
    )

    execute_write(
        """INSERT INTO files (id, conversation_id, path, filename, mime_type, size_bytes, origin, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            metadata.id,
            metadata.conversation_id,
            metadata.path,
            metadata.filename,
            metadata.mime_type,
            metadata.size_bytes,
            metadata.origin,
            metadata.created_at.isoformat(),
        ),
    )

    return metadata


async def save_uploaded_file(
    conversation_id: str,
    file_content: bytes,
    filename: str,
    content_type: str,
) -> FileMetadata:
    """Save a file the user sent to Molly and return metadata.

    Any file type is accepted (logs, code, configs, zips, PDFs, office docs,
    ...) up to the configured size limit — Molly already has unsandboxed server
    access (see KNOWN_LIMITATIONS.md #29), so gatekeeping by extension here
    added restriction without adding safety. `read_file` handles text, zip
    archives, and PDFs directly; other binary types get a metadata summary.
    """
    if not filename:
        raise ValueError("Filename is required")

    if len(file_content) > settings.max_upload_size_mb * 1024 * 1024:
        raise ValueError(f"File too large: {len(file_content)} bytes")

    mime_type = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return await _persist_file(conversation_id, file_content, filename, mime_type, origin="upload")


async def register_generated_file(
    conversation_id: str,
    source_path: str,
    filename: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> FileMetadata:
    """Copy a file Molly already produced on disk (e.g. via write_file) into
    conversation storage and register it, so it gets a file_id, shows up in
    `GET .../files`, and is downloadable through the /content endpoint —
    the same lifecycle an uploaded file gets. Called by the agent executor
    after a `share_file` tool call, not by the tool itself (the tool doesn't
    know the conversation_id — see app/tools/sharing.py)."""
    src = Path(source_path)
    if not src.is_file():
        raise ValueError(f"Source path does not exist or is not a file: {source_path}")

    file_content = src.read_bytes()
    if len(file_content) > settings.max_upload_size_mb * 1024 * 1024:
        raise ValueError(f"File too large: {len(file_content)} bytes")

    resolved_filename = filename or src.name
    resolved_mime = mime_type or mimetypes.guess_type(resolved_filename)[0] or "application/octet-stream"
    return await _persist_file(conversation_id, file_content, resolved_filename, resolved_mime, origin="generated")


def get_file_metadata(file_id: str) -> Optional[FileMetadata]:
    rows = execute_query("SELECT * FROM files WHERE id = ?", (file_id,))
    if not rows:
        return None
    return FileMetadata.from_row(rows[0])


def get_conversation_files(conversation_id: str, limit: int = 50) -> List[FileMetadata]:
    rows = execute_query(
        "SELECT * FROM files WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
        (conversation_id, limit),
    )
    return [FileMetadata.from_row(r) for r in rows]


def mark_file_viewed(file_id: str) -> bool:
    execute_write(
        "UPDATE files SET viewed_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), file_id),
    )
    return True


def delete_file(file_id: str) -> bool:
    metadata = get_file_metadata(file_id)
    if metadata:
        try:
            Path(metadata.path).unlink(missing_ok=True)
        except Exception:
            pass
    execute_write("DELETE FROM files WHERE id = ?", (file_id,))
    return True


def cleanup_old_files(days: int = 30) -> int:
    """Delete files older than specified days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = execute_query(
        "SELECT id, path FROM files WHERE created_at < ?",
        (cutoff.isoformat(),),
    )
    count = 0
    for row in rows:
        try:
            Path(row["path"]).unlink(missing_ok=True)
            count += 1
        except Exception:
            pass
    execute_write("DELETE FROM files WHERE created_at < ?", (cutoff.isoformat(),))
    return count


def cleanup_conversation_files(conversation_id: str, keep_latest: int = 50) -> int:
    """Keep only the latest N files for a conversation."""
    rows = execute_query(
        "SELECT id, path FROM files WHERE conversation_id = ? ORDER BY created_at DESC",
        (conversation_id,),
    )
    to_delete = rows[keep_latest:]
    count = 0
    for row in to_delete:
        try:
            Path(row["path"]).unlink(missing_ok=True)
            count += 1
        except Exception:
            pass
    if to_delete:
        ids = [r["id"] for r in to_delete]
        placeholders = ",".join("?" * len(ids))
        execute_write(f"DELETE FROM files WHERE id IN ({placeholders})", tuple(ids))
    return count
