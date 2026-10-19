import json
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
class ImageMetadata:
    id: str
    conversation_id: str
    path: str
    mime_type: str
    width: int
    height: int
    size_bytes: int
    created_at: datetime
    viewed_at: Optional[datetime] = None
    origin: str = "upload"  # "upload" (from the user) or "generated" (from Molly)

    @classmethod
    def from_row(cls, row) -> "ImageMetadata":
        return cls(
            id=row["id"],
            conversation_id=row["conversation_id"],
            path=row["path"],
            mime_type=row["mime_type"],
            width=row["width"] or 0,
            height=row["height"] or 0,
            size_bytes=row["size_bytes"] or 0,
            created_at=datetime.fromisoformat(row["created_at"]),
            viewed_at=datetime.fromisoformat(row["viewed_at"]) if row["viewed_at"] else None,
            origin=row["origin"] if "origin" in row.keys() and row["origin"] else "upload",
        )


async def _persist_image(
    conversation_id: str,
    file_content: bytes,
    content_type: str,
    origin: str,
) -> ImageMetadata:
    """Shared write path for both uploaded and agent-generated images."""
    image_id = f"img_{uuid.uuid4().hex[:12]}"
    ext = mimetypes.guess_extension(content_type) or ".png"
    safe_filename = f"{image_id}{ext}"

    upload_dir = settings.uploads_path / "conversations" / conversation_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_path = upload_dir / safe_filename

    async with aiofiles.open(file_path, "wb") as f:
        await f.write(file_content)

    from PIL import Image
    with Image.open(file_path) as img:
        width, height = img.size

    metadata = ImageMetadata(
        id=image_id,
        conversation_id=conversation_id,
        path=str(file_path),
        mime_type=content_type,
        width=width,
        height=height,
        size_bytes=len(file_content),
        created_at=datetime.utcnow(),
        origin=origin,
    )

    execute_write(
        """INSERT INTO images (id, conversation_id, path, mime_type, width, height, size_bytes, origin, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            metadata.id,
            metadata.conversation_id,
            metadata.path,
            metadata.mime_type,
            metadata.width,
            metadata.height,
            metadata.size_bytes,
            metadata.origin,
            metadata.created_at.isoformat(),
        ),
    )

    return metadata


async def save_uploaded_image(
    conversation_id: str,
    file_content: bytes,
    filename: str,
    content_type: str,
) -> ImageMetadata:
    """Save an image the user sent to Molly and return metadata."""
    if content_type not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise ValueError(f"Unsupported image type: {content_type}")

    if len(file_content) > settings.max_image_size_mb * 1024 * 1024:
        raise ValueError(f"Image too large: {len(file_content)} bytes")

    return await _persist_image(conversation_id, file_content, content_type, origin="upload")


async def register_generated_image(
    conversation_id: str,
    source_path: str,
    mime_type: Optional[str] = None,
) -> ImageMetadata:
    """Copy an image Molly already produced on disk into conversation storage
    and register it, mirroring register_generated_file() in storage/files.py.
    Called by the agent executor after a `share_file` tool call targeting an
    image path."""
    src = Path(source_path)
    if not src.is_file():
        raise ValueError(f"Source path does not exist or is not a file: {source_path}")

    resolved_mime = mime_type or mimetypes.guess_type(str(src))[0]
    if resolved_mime not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise ValueError(f"Unsupported image type: {resolved_mime}")

    file_content = src.read_bytes()
    if len(file_content) > settings.max_image_size_mb * 1024 * 1024:
        raise ValueError(f"Image too large: {len(file_content)} bytes")

    return await _persist_image(conversation_id, file_content, resolved_mime, origin="generated")


def get_image_metadata(image_id: str) -> Optional[ImageMetadata]:
    rows = execute_query("SELECT * FROM images WHERE id = ?", (image_id,))
    if not rows:
        return None
    return ImageMetadata.from_row(rows[0])


def get_conversation_images(conversation_id: str, limit: int = 50) -> List[ImageMetadata]:
    rows = execute_query(
        "SELECT * FROM images WHERE conversation_id = ? ORDER BY created_at DESC LIMIT ?",
        (conversation_id, limit),
    )
    return [ImageMetadata.from_row(r) for r in rows]


def mark_image_viewed(image_id: str) -> bool:
    execute_write(
        "UPDATE images SET viewed_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), image_id),
    )
    return True


def delete_image(image_id: str) -> bool:
    metadata = get_image_metadata(image_id)
    if metadata:
        try:
            Path(metadata.path).unlink(missing_ok=True)
        except Exception:
            pass
    execute_write("DELETE FROM images WHERE id = ?", (image_id,))
    return True


def cleanup_old_images(days: int = 7) -> int:
    """Delete images older than specified days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    rows = execute_query(
        "SELECT id, path FROM images WHERE created_at < ?",
        (cutoff.isoformat(),),
    )
    count = 0
    for row in rows:
        try:
            Path(row["path"]).unlink(missing_ok=True)
            count += 1
        except Exception:
            pass
    execute_write("DELETE FROM images WHERE created_at < ?", (cutoff.isoformat(),))
    return count


def cleanup_conversation_images(conversation_id: str, keep_latest: int = 50) -> int:
    """Keep only the latest N images for a conversation."""
    rows = execute_query(
        "SELECT id, path FROM images WHERE conversation_id = ? ORDER BY created_at DESC",
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
        execute_write(f"DELETE FROM images WHERE id IN ({placeholders})", tuple(ids))
    return count