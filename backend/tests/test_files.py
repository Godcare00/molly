import pytest
from pathlib import Path

from app.storage.files import (
    save_uploaded_file,
    get_file_metadata,
    get_conversation_files,
    mark_file_viewed,
    delete_file,
    cleanup_conversation_files,
)
from app.config import settings


@pytest.fixture
def sample_file():
    """A small text file's content."""
    return b"2024-01-01T00:00:00 INFO service started\n2024-01-01T00:00:05 WARN disk 80% full\n"


@pytest.mark.asyncio
async def test_save_uploaded_file(sample_file, conversation_id):
    metadata = await save_uploaded_file(
        conversation_id=conversation_id,
        file_content=sample_file,
        filename="service.log",
        content_type="text/plain",
    )

    assert metadata.id.startswith("file_")
    assert metadata.conversation_id == conversation_id
    assert metadata.filename == "service.log"
    assert metadata.mime_type == "text/plain"
    assert metadata.size_bytes == len(sample_file)
    assert Path(metadata.path).exists()


@pytest.mark.asyncio
async def test_save_uploaded_file_any_type(conversation_id):
    """Non-text/binary files (e.g. zips) are accepted — read_file handles the rest."""
    zip_bytes = b"PK\x03\x04" + b"\x00" * 30  # not a fully valid zip, just needs to upload
    metadata = await save_uploaded_file(
        conversation_id=conversation_id,
        file_content=zip_bytes,
        filename="archive.zip",
        content_type="application/zip",
    )

    assert metadata.id.startswith("file_")
    assert metadata.filename == "archive.zip"
    assert metadata.mime_type == "application/zip"
    assert Path(metadata.path).exists()


@pytest.mark.asyncio
async def test_save_uploaded_file_too_large(conversation_id):
    large_content = b"x" * (settings.max_upload_size_mb * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="too large"):
        await save_uploaded_file(
            conversation_id=conversation_id,
            file_content=large_content,
            filename="big.txt",
            content_type="text/plain",
        )


@pytest.mark.asyncio
async def test_get_file_metadata(sample_file, conversation_id):
    metadata = await save_uploaded_file(
        conversation_id=conversation_id,
        file_content=sample_file,
        filename="service.log",
        content_type="text/plain",
    )

    retrieved = get_file_metadata(metadata.id)
    assert retrieved is not None
    assert retrieved.id == metadata.id
    assert retrieved.path == metadata.path


@pytest.mark.asyncio
async def test_get_conversation_files(sample_file, conversation_id):
    for i in range(3):
        await save_uploaded_file(
            conversation_id=conversation_id,
            file_content=sample_file,
            filename=f"test{i}.log",
            content_type="text/plain",
        )

    files = get_conversation_files(conversation_id, limit=10)
    assert len(files) == 3


@pytest.mark.asyncio
async def test_mark_file_viewed(sample_file, conversation_id):
    metadata = await save_uploaded_file(
        conversation_id=conversation_id,
        file_content=sample_file,
        filename="service.log",
        content_type="text/plain",
    )

    assert metadata.viewed_at is None
    mark_file_viewed(metadata.id)
    retrieved = get_file_metadata(metadata.id)
    assert retrieved.viewed_at is not None


@pytest.mark.asyncio
async def test_delete_file(sample_file, conversation_id):
    metadata = await save_uploaded_file(
        conversation_id=conversation_id,
        file_content=sample_file,
        filename="service.log",
        content_type="text/plain",
    )

    assert Path(metadata.path).exists()
    delete_file(metadata.id)
    assert not Path(metadata.path).exists()
    assert get_file_metadata(metadata.id) is None


@pytest.mark.asyncio
async def test_cleanup_conversation_files(sample_file, conversation_id):
    for i in range(60):
        await save_uploaded_file(
            conversation_id=conversation_id,
            file_content=sample_file,
            filename=f"test{i}.log",
            content_type="text/plain",
        )

    deleted = cleanup_conversation_files(conversation_id, keep_latest=50)
    assert deleted == 10

    remaining = get_conversation_files(conversation_id, limit=100)
    assert len(remaining) == 50
