"""Tests for the ingestion worker's error-handling behaviour in main()."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pulse.ingestion.worker import main


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://api.github.com/repos/owner/repo/commits")
    resp = httpx.Response(status_code, request=req)
    return httpx.HTTPStatusError(f"HTTP {status_code}", request=req, response=resp)


def _patched_main(ingest_side_effect: object, repos: list[str] | None = None):
    """Return a context manager that patches all main() dependencies."""
    mock_settings = MagicMock()
    mock_settings.github_repo_list = repos if repos is not None else ["owner/repo-a", "owner/repo-b"]
    mock_settings.github_username = "testuser"

    mock_client_instance = MagicMock()
    mock_client_cm = MagicMock()
    mock_client_cm.__enter__ = MagicMock(return_value=mock_client_instance)
    mock_client_cm.__exit__ = MagicMock(return_value=False)

    return (
        patch("pulse.ingestion.worker.run_migrations", new_callable=AsyncMock),
        patch("pulse.ingestion.worker.settings", mock_settings),
        patch("pulse.ingestion.worker.GitHubClient", return_value=mock_client_cm),
        patch("pulse.ingestion.worker.ingest_repo", new_callable=AsyncMock, side_effect=ingest_side_effect),
    )


# ---------------------------------------------------------------------------
# Fatal errors — worker must abort and re-raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_aborts_on_401() -> None:
    """A 401 from any repo should abort the entire run immediately."""
    patches = _patched_main(_http_error(401))
    with patches[0], patches[1], patches[2], patches[3] as mock_ingest, pytest.raises(httpx.HTTPStatusError) as exc_info:
        await main()

    assert exc_info.value.response.status_code == 401
    # Must stop after the first failure — second repo never attempted
    assert mock_ingest.call_count == 1


@pytest.mark.asyncio
async def test_main_aborts_on_403() -> None:
    """A 403 (insufficient permissions) should abort identically to 401."""
    patches = _patched_main(_http_error(403))
    with patches[0], patches[1], patches[2], patches[3] as mock_ingest, pytest.raises(httpx.HTTPStatusError) as exc_info:
        await main()

    assert exc_info.value.response.status_code == 403
    assert mock_ingest.call_count == 1


@pytest.mark.asyncio
async def test_main_aborts_on_exhausted_429() -> None:
    """A 429 that survived all tenacity retries should abort the run."""
    patches = _patched_main(_http_error(429))
    with patches[0], patches[1], patches[2], patches[3] as mock_ingest, pytest.raises(httpx.HTTPStatusError) as exc_info:
        await main()

    assert exc_info.value.response.status_code == 429
    assert mock_ingest.call_count == 1


# ---------------------------------------------------------------------------
# Skippable errors — worker must log and continue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_skips_repo_on_404() -> None:
    """A 404 is repo-specific; the worker should skip it and ingest the next repo."""
    # First repo raises 404, second succeeds
    call_count = 0

    async def side_effect(repo: str, *args: object, **kwargs: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise _http_error(404)

    patches = _patched_main(side_effect)
    with patches[0], patches[1], patches[2], patches[3]:
        await main()  # must not raise

    assert call_count == 2  # both repos attempted


@pytest.mark.asyncio
async def test_main_skips_repo_on_generic_exception() -> None:
    """A non-HTTP exception (e.g. DB error) should be logged and skipped."""
    call_count = 0

    async def side_effect(repo: str, *args: object, **kwargs: object) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("connection refused")

    patches = _patched_main(side_effect)
    with patches[0], patches[1], patches[2], patches[3]:
        await main()

    assert call_count == 2
