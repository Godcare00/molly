import mimetypes
from pathlib import Path
from typing import Optional
from PIL import Image
from app.tools.registry import BaseTool, ToolResult, RiskLevel, registry
from app.config import settings
from app.storage.images import get_image_metadata, ImageMetadata


class ViewImageTool(BaseTool):
    name = "view_image"
    description = "Load an image and attach it to Molly's multimodal context for visual reasoning. Validates path, checks MIME type, collects metadata."
    risk_level = RiskLevel.READ
    timeout_seconds = 15
    output_limit_chars = 2000

    async def execute(self, path: str, image_id: Optional[str] = None) -> ToolResult:
        try:
            # If image_id provided, look up metadata
            if image_id:
                metadata = get_image_metadata(image_id)
                if not metadata:
                    return ToolResult(success=False, error=f"Image not found: {image_id}")
                safe_path = Path(metadata.path)
            else:
                # Resolve path directly
                from app.security.paths import canonicalize_path, validate_path_safety
                safe_path = canonicalize_path(path)
                validate_path_safety(safe_path)

            if not safe_path.exists():
                return ToolResult(success=False, error=f"Image file does not exist: {path}")

            if not safe_path.is_file():
                return ToolResult(success=False, error=f"Path is not a file: {path}")

            # Check MIME type
            mime_type, _ = mimetypes.guess_type(str(safe_path))
            if mime_type not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
                return ToolResult(success=False, error=f"Unsupported image format: {mime_type}")

            # Get image metadata
            file_size = safe_path.stat().st_size
            if file_size > settings.max_image_size_mb * 1024 * 1024:
                return ToolResult(success=False, error=f"Image too large: {file_size} bytes")

            try:
                with Image.open(safe_path) as img:
                    width, height = img.size
                    format_name = img.format
            except Exception as e:
                return ToolResult(success=False, error=f"Invalid image file: {e}")

            # Return metadata - the actual image will be attached by the agent loop
            return ToolResult(
                success=True,
                output={
                    "image_id": image_id or safe_path.stem,
                    "path": str(safe_path),
                    "mime_type": mime_type,
                    "width": width,
                    "height": height,
                    "size_bytes": file_size,
                    "format": format_name,
                    "ready_for_multimodal": True,
                },
                metadata={
                    "resolved_path": str(safe_path),
                    "attach_to_next_request": True,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


def register_vision_tools():
    registry.register(ViewImageTool())