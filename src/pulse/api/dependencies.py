"""FastAPI dependency providers for shared resources."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from pulse.db.engine import _SessionFactory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield one AsyncSession per request; commit on success, rollback on error.

    Designed for use with FastAPI's Depends() system. Tests override this via
    app.dependency_overrides to inject an in-memory SQLite session.
    """
    async with _SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
