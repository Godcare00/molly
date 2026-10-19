import pytest
import asyncio
from pathlib import Path
from PIL import Image
import io

from app.storage.images import (
    save_uploaded_image,
    get_image_metadata,
    get_conversation_images,
    mark_image_viewed,
    delete_image,
    cleanup_conversation_images,
)
from app.config import settings


@pytest.fixture
def sample_image():
    """Create a sample PNG image in memory."""
    img = Image.new("RGB", (100, 100), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_save_uploaded_image(sample_image, conversation_id):
    metadata = await save_uploaded_image(
        conversation_id=conversation_id,
        file_content=sample_image,
        filename="test.png",
        content_type="image/png",
    )

    assert metadata.id.startswith("img_")
    assert metadata.conversation_id == conversation_id
    assert metadata.mime_type == "image/png"
    assert metadata.width == 100
    assert metadata.height == 100
    assert metadata.size_bytes == len(sample_image)
    assert Path(metadata.path).exists()


@pytest.mark.asyncio
async def test_save_uploaded_image_invalid_type(conversation_id):
    with pytest.raises(ValueError, match="Unsupported image type"):
        await save_uploaded_image(
            conversation_id=conversation_id,
            file_content=b"not an image",
            filename="test.txt",
            content_type="text/plain",
        )


@pytest.mark.asyncio
async def test_save_uploaded_image_too_large(conversation_id):
    # Create image larger than max size
    large_content = b"x" * (settings.max_image_size_mb * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="too large"):
        await save_uploaded_image(
            conversation_id=conversation_id,
            file_content=large_content,
            filename="test.png",
            content_type="image/png",
        )


@pytest.mark.asyncio
async def test_get_image_metadata(sample_image, conversation_id):
    metadata = await save_uploaded_image(
        conversation_id=conversation_id,
        file_content=sample_image,
        filename="test.png",
        content_type="image/png",
    )

    retrieved = get_image_metadata(metadata.id)
    assert retrieved is not None
    assert retrieved.id == metadata.id
    assert retrieved.path == metadata.path


@pytest.mark.asyncio
async def test_get_conversation_images(sample_image, conversation_id):
    for i in range(3):
        await save_uploaded_image(
            conversation_id=conversation_id,
            file_content=sample_image,
            filename=f"test{i}.png",
            content_type="image/png",
        )

    images = get_conversation_images(conversation_id, limit=10)
    assert len(images) == 3


@pytest.mark.asyncio
async def test_mark_image_viewed(sample_image, conversation_id):
    metadata = await save_uploaded_image(
        conversation_id=conversation_id,
        file_content=sample_image,
        filename="test.png",
        content_type="image/png",
    )

    assert metadata.viewed_at is None
    mark_image_viewed(metadata.id)
    retrieved = get_image_metadata(metadata.id)
    assert retrieved.viewed_at is not None


@pytest.mark.asyncio
async def test_delete_image(sample_image, conversation_id):
    metadata = await save_uploaded_image(
        conversation_id=conversation_id,
        file_content=sample_image,
        filename="test.png",
        content_type="image/png",
    )

    assert Path(metadata.path).exists()
    delete_image(metadata.id)
    assert not Path(metadata.path).exists()
    assert get_image_metadata(metadata.id) is None


@pytest.mark.asyncio
async def test_cleanup_conversation_images(sample_image, conversation_id):
    # Save more than the limit
    for i in range(60):
        await save_uploaded_image(
            conversation_id=conversation_id,
            file_content=sample_image,
            filename=f"test{i}.png",
            content_type="image/png",
        )

    # Cleanup should keep only 50 (default)
    deleted = cleanup_conversation_images(conversation_id, keep_latest=50)
    assert deleted == 10

    remaining = get_conversation_images(conversation_id, limit=100)
    assert len(remaining) == 50