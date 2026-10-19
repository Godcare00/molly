"""
Authentication database session management.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.auth.config import auth_settings
from app.auth.models import Base


# Create async engine
engine = create_async_engine(
    f"sqlite+aiosqlite:///{auth_settings.auth_database_path}",
    echo=False,
    poolclass=NullPool,
    connect_args={"check_same_thread": False},
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_auth_db():
    """Initialize auth database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_auth_db():
    """Close auth database connections."""
    await engine.dispose()


@asynccontextmanager
async def get_auth_session() -> AsyncGenerator[AsyncSession, None]:
    """Get auth database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Dependency for FastAPI
async def get_auth_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_auth_session() as session:
        yield session