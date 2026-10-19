import mimetypes
from pathlib import Path
from typing import Optional

from app.tools.registry import BaseTool, ToolResult, RiskLevel, registry
from app.security.paths import canonicalize_path, validate_path_safety

IMAGE_MIME_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")

# 25MB is comfortably under settings.max_upload_size_mb's default (50) while
# staying well clear of what a mobile client should be asked to pull over a
# cellular connection in one shot.
MAX_SHARE_BYTES = 25 * 1024 * 1024


class ShareFileTool(BaseTool):
    name = "share_file"
    description = (
        "Send a file back to the user as a downloadable attachment on this message — the "
        "counterpart to the files/images the user can send Molly. Point it at a path already "
        "on disk (e.g. something just produced with write_file, or an existing project file); "
        "it does not create content itself. Images (png/jpeg/webp/gif) are shared as an image "
        "attachment the app can preview inline; anything else is shared as a generic file "
        "the user can download. Do not use this for secrets (.env, private keys, credentials) "
        "unless the user explicitly asked for that exact file."
    )
    risk_level = RiskLevel.READ
    timeout_seconds = 15
    output_limit_chars = 2000

    async def execute(self, path: str, display_name: Optional[str] = None) -> ToolResult:
        try:
            safe_path = canonicalize_path(path)
            validate_path_safety(safe_path)

            if not safe_path.exists():
                return ToolResult(success=False, error=f"Path does not exist: {path}")
            if not safe_path.is_file():
                return ToolResult(success=False, error=f"Path is not a file: {path}")

            file_size = safe_path.stat().st_size
            if file_size > MAX_SHARE_BYTES:
                return ToolResult(
                    success=False,
                    error=f"File too large to share: {file_size} bytes (max {MAX_SHARE_BYTES})",
                )
            if file_size == 0:
                return ToolResult(success=False, error="File is empty")

            filename = display_name or safe_path.name
            mime_type = mimetypes.guess_type(filename)[0] or mimetypes.guess_type(str(safe_path))[0]
            kind = "image" if mime_type in IMAGE_MIME_TYPES else "file"

            # The actual DB row (and its file_id/URL) is created by the agent
            # executor, which knows the conversation_id this run belongs to —
            # this tool only validates the source and describes what to share.
            # See AgentExecutor._maybe_share_attachment in agent/executor.py.
            return ToolResult(
                success=True,
                output={
                    "path": str(safe_path),
                    "filename": filename,
                    "mime_type": mime_type or "application/octet-stream",
                    "size_bytes": file_size,
                    "kind": kind,
                },
                metadata={
                    "resolved_path": str(safe_path),
                    "share_as_attachment": True,
                    "share_filename": filename,
                    "share_mime_type": mime_type,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


def register_sharing_tools():
    registry.register(ShareFileTool())
