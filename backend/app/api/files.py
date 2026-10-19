from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import FileResponse as FileContentResponse
from typing import List
from pydantic import BaseModel

from app.storage.files import (
    save_uploaded_file,
    get_file_metadata,
    get_conversation_files,
    mark_file_viewed,
    delete_file,
    cleanup_conversation_files,
)
from app.config import settings
from app.auth.dependencies import get_current_user

router = APIRouter(prefix="/conversations/{conversation_id}/files", tags=["files"], dependencies=[Depends(get_current_user)])


class FileResponse(BaseModel):
    file_id: str
    path: str
    filename: str
    mime_type: str
    size_bytes: int
    origin: str = "upload"


@router.post("", response_model=FileResponse)
async def upload_file(
    conversation_id: str,
    file: UploadFile = File(...),
):
    """Upload a (non-image) file for a conversation - logs, code, config, csv, etc."""
    content = await file.read()

    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(400, f"File too large: {len(content)} bytes (max {settings.max_upload_size_mb}MB)")

    try:
        metadata = await save_uploaded_file(conversation_id, content, file.filename, file.content_type)
    except ValueError as e:
        raise HTTPException(400, str(e))

    cleanup_conversation_files(conversation_id, keep_latest=settings.max_files_per_conversation)

    return FileResponse(
        file_id=metadata.id,
        path=metadata.path,
        filename=metadata.filename,
        mime_type=metadata.mime_type,
        size_bytes=metadata.size_bytes,
        origin=metadata.origin,
    )


@router.get("", response_model=List[FileResponse])
async def list_files(conversation_id: str, limit: int = 50):
    """List files for a conversation."""
    files = get_conversation_files(conversation_id, limit)
    return [
        FileResponse(
            file_id=f.id,
            path=f.path,
            filename=f.filename,
            mime_type=f.mime_type,
            size_bytes=f.size_bytes,
            origin=f.origin,
        )
        for f in files
    ]


@router.get("/{file_id}", response_model=FileResponse)
async def get_file(conversation_id: str, file_id: str):
    """Get file metadata."""
    metadata = get_file_metadata(file_id)
    if not metadata:
        raise HTTPException(404, "File not found")

    if metadata.conversation_id != conversation_id:
        raise HTTPException(404, "File not found in this conversation")

    return FileResponse(
        file_id=metadata.id,
        path=metadata.path,
        filename=metadata.filename,
        mime_type=metadata.mime_type,
        size_bytes=metadata.size_bytes,
        origin=metadata.origin,
    )


@router.get("/{file_id}/content")
async def get_file_content(conversation_id: str, file_id: str):
    """Stream the actual file bytes — for downloading an uploaded file, or
    one Molly sent back via the share_file tool. Metadata endpoints above
    only ever returned the record, never the content itself."""
    metadata = get_file_metadata(file_id)
    if not metadata or metadata.conversation_id != conversation_id:
        raise HTTPException(404, "File not found in this conversation")

    disk_path = Path(metadata.path)
    if not disk_path.is_file():
        raise HTTPException(410, "File is no longer available on disk")

    return FileContentResponse(
        path=disk_path,
        media_type=metadata.mime_type,
        filename=metadata.filename,
    )


@router.post("/{file_id}/view")
async def mark_viewed(conversation_id: str, file_id: str):
    """Mark a file as viewed."""
    metadata = get_file_metadata(file_id)
    if not metadata or metadata.conversation_id != conversation_id:
        raise HTTPException(404, "File not found")

    mark_file_viewed(file_id)
    return {"status": "viewed", "file_id": file_id}


@router.delete("/{file_id}")
async def delete_file_endpoint(conversation_id: str, file_id: str):
    """Delete a file."""
    metadata = get_file_metadata(file_id)
    if not metadata or metadata.conversation_id != conversation_id:
        raise HTTPException(404, "File not found")

    delete_file(file_id)
    return {"status": "deleted", "file_id": file_id}
