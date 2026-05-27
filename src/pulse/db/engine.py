from __future__ import annotations

import importlib.resources
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pulse.config import settings


# Convert psycopg2 URL to asyncpg-compatible URL for async usage.
# We support both postgresql+psycopg2 (sync, used by worker) and
# postgresql+asyncpg / sqlite+aiosqlite (async, used by API and tests).
def _async_url(url: str) -> str:
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _connect_args_for(url: str) -> dict[str, object]:
    """Driver-specific kwargs for create_async_engine's connect_args.

    asyncpg gets a 10-second per-query timeout so a hung Postgres connection
    surfaces as an error instead of blocking the MCP server (and the agent
    subprocess that drives it) indefinitely. aiosqlite has no equivalent and
    rejects unknown kwargs, so SQLite-backed engines (tests, dev) get an
    empty dict.
    """
    if "asyncpg" in url:
        return {"command_timeout": 10}
    return {}


_async_db_url = _async_url(settings.database_url)
_engine = create_async_engine(
    _async_db_url,
    echo=False,
    connect_args=_connect_args_for(_async_db_url),
)
_SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _engine, expire_on_commit=False
)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def run_migrations() -> None:
    """Execute schema.sql against the configured database.

    asyncpg's prepared-statement API rejects multi-statement strings, so we
    split the file on ``;`` and run each statement individually. The schema
    is plain DDL with no dollar-quoted bodies or string literals containing
    semicolons, so a simple split is safe here.
    """
    sql = importlib.resources.files("pulse.db").joinpath("schema.sql").read_text()
    async with _engine.begin() as conn:
        for raw_stmt in sql.split(";"):
            stmt = raw_stmt.strip()
            if not stmt:
                continue
            await conn.exec_driver_sql(stmt)
