"""FastAPI application entrypoint.

Run locally with:
    uvicorn pulse.api.main:app --reload

OpenAPI docs are auto-generated at /docs (Swagger) and /redoc.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from pulse.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    # Migrations are run by the worker or a dedicated migrate command,
    # not the API process. This hook is here for future milestone hooks.
    yield


app = FastAPI(
    title="Pulse",
    version="0.2.0",
    description=(
        "Personal GitHub activity agent — ingests commits, PRs, and issues "
        "and exposes them for querying via REST and (in a future milestone) "
        "natural language through an MCP-backed Claude agent."
    ),
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health", summary="Health check", tags=["meta"])
async def health() -> dict[str, str]:
    """Returns ok when the service is up."""
    return {"status": "ok"}
