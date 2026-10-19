from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

if settings.database_url.startswith("sqlite"):
    Path("data").mkdir(exist_ok=True)

engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_models() -> None:
    """create_all for local dev/demo. A real deployment should use Alembic
    migrations (the worker's backend/alembic/ is a template for this
    service's own migration history) instead of create_all so schema
    changes are reviewable and reversible."""
    from app import models  # noqa: F401  (registers models on Base.metadata)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
