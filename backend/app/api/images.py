from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import FileResponse as ImageContentResponse
from typing import List
from pydantic import BaseModel

from app.storage.images import (
    save_uploaded_image,
    get_image_metadata,
    get_conversation_images,
    mark_image_viewed,
    delete_image,
    cleanup_conversation_images,
)
from app.config import settings
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/conversations/{conversation_id}/images", tags=["images"], dependencies=[Depends(get_current_user)])


class ImageResponse(BaseModel):
    image_id: str
    path: str
    mime_type: str
    width: int
    height: int
    size_bytes: int
    origin: str = "upload"


@router.post("", response_model=ImageResponse)
async def upload_image(
    conversation_id: str,
    file: UploadFile = File(...),
):
    """Upload an image for a conversation."""
    # Validate content type
    if file.content_type not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
        raise HTTPException(400, f"Unsupported image type: {file.content_type}")

    # Read file
    content = await file.read()

    # Check size
    if len(content) > settings.max_image_size_mb * 1024 * 1024:
        raise HTTPException(400, f"Image too large: {len(content)} bytes (max {settings.max_image_size_mb}MB)")

    try:
        metadata = await save_uploaded_image(conversation_id, content, file.filename, file.content_type)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Cleanup old images for this conversation
    cleanup_conversation_images(conversation_id, keep_latest=settings.max_images_per_conversation)

    return ImageResponse(
        image_id=metadata.id,
        path=metadata.path,
        mime_type=metadata.mime_type,
        width=metadata.width,
        height=metadata.height,
        size_bytes=metadata.size_bytes,
        origin=metadata.origin,
    )


@router.get("", response_model=List[ImageResponse])
async def list_images(conversation_id: str, limit: int = 50):
    """List images for a conversation."""
    images = get_conversation_images(conversation_id, limit)
    return [
        ImageResponse(
            image_id=img.id,
            path=img.path,
            mime_type=img.mime_type,
            width=img.width,
            height=img.height,
            size_bytes=img.size_bytes,
            origin=img.origin,
        )
        for img in images
    ]


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(conversation_id: str, image_id: str):
    """Get image metadata."""
    metadata = get_image_metadata(image_id)
    if not metadata:
        raise HTTPException(404, "Image not found")

    if metadata.conversation_id != conversation_id:
        raise HTTPException(404, "Image not found in this conversation")

    return ImageResponse(
        image_id=metadata.id,
        path=metadata.path,
        mime_type=metadata.mime_type,
        width=metadata.width,
        height=metadata.height,
        size_bytes=metadata.size_bytes,
        origin=metadata.origin,
    )


@router.get("/{image_id}/content")
async def get_image_content(conversation_id: str, image_id: str):
    """Stream the actual image bytes for display/download."""
    metadata = get_image_metadata(image_id)
    if not metadata or metadata.conversation_id != conversation_id:
        raise HTTPException(404, "Image not found in this conversation")

    disk_path = Path(metadata.path)
    if not disk_path.is_file():
        raise HTTPException(410, "Image is no longer available on disk")

    return ImageContentResponse(path=disk_path, media_type=metadata.mime_type)


@router.post("/{image_id}/view")
async def mark_viewed(conversation_id: str, image_id: str):
    """Mark an image as viewed."""
    metadata = get_image_metadata(image_id)
    if not metadata or metadata.conversation_id != conversation_id:
        raise HTTPException(404, "Image not found")

    mark_image_viewed(image_id)
    return {"status": "viewed", "image_id": image_id}


@router.delete("/{image_id}")
async def delete_image_endpoint(conversation_id: str, image_id: str):
    """Delete an image."""
    metadata = get_image_metadata(image_id)
    if not metadata or metadata.conversation_id != conversation_id:
        raise HTTPException(404, "Image not found")

    delete_image(image_id)
    return {"status": "deleted", "image_id": image_id}