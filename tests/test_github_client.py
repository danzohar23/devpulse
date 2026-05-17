from __future__ import annotations

import json
import time
from datetime import datetime, timezone
UTC = timezone.utc
from unittest.mock import patch

import httpx

from pulse.ingestion.github_client import GitHubClient
from pulse.models import Commit


def _make_response(
    payload: object,
    status_code: int = 200,
    headers: dict | None = None,
) -> httpx.Response:
    default_headers = {
        "X-RateLimit-Remaining": "60",
        "X-RateLimit-Reset": str(int(time.time()) + 3600),
        "Content-Type": "application/json",
    }
    default_headers.update(headers or {})
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(payload).encode(),
        headers=default_headers,
        request=httpx.Request("GET", "https://api.github.com/test"),
    )


class TestGetCommitsSuccess:
    def test_get_commits_success(self, github_token: str, mock_github_responses: dict) -> None:
        raw = mock_github_responses["commits"]
        response = _make_response(raw)

        with patch("httpx.Client.get", return_value=response):
            client = GitHubClient(token=github_token)
            since = datetime(2026, 5, 1, tzinfo=UTC)
            commits = client.get_commits("alice/repo", since)

        assert len(commits) == 1
        c = commits[0]
        assert isinstance(c, Commit)
        assert c.sha == "abc123def456"
        assert c.repo == "alice/repo"
        assert c.message == "feat: add new feature"
        assert c.author_name == "Alice Dev"
        assert c.author_email == "alice@example.com"


class TestRetryOn429:
    def test_retry_on_429(self, github_token: str, mock_github_responses: dict) -> None:
        raw = mock_github_responses["commits"]
        error_resp = _make_response({"message": "rate limited"}, status_code=429)
        success_resp = _make_response(raw)

        call_count = 0

        def side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return error_resp
            return success_resp

        with (
            patch("httpx.Client.get", side_effect=side_effect),
            patch("time.sleep"),  # don't actually sleep in tests
        ):
            client = GitHubClient(token=github_token)
            since = datetime(2026, 5, 1, tzinfo=UTC)
            commits = client.get_commits("alice/repo", since)

        assert len(commits) == 1
        assert call_count == 3


class TestRetryOn500:
    def test_retry_on_500(self, github_token: str, mock_github_responses: dict) -> None:
        raw = mock_github_responses["commits"]
        error_resp = _make_response({"message": "server error"}, status_code=500)
        success_resp = _make_response(raw)

        call_count = 0

        def side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return error_resp
            return success_resp

        with (
            patch("httpx.Client.get", side_effect=side_effect),
            patch("time.sleep"),
        ):
            client = GitHubClient(token=github_token)
            since = datetime(2026, 5, 1, tzinfo=UTC)
            commits = client.get_commits("alice/repo", since)

        assert len(commits) == 1
        assert call_count == 2


class TestRateLimitSleep:
    def test_rate_limit_sleep(self, github_token: str, mock_github_responses: dict) -> None:
        raw = mock_github_responses["commits"]
        reset_ts = int(time.time()) + 120
        response = _make_response(
            raw,
            headers={
                "X-RateLimit-Remaining": "5",
                "X-RateLimit-Reset": str(reset_ts),
            },
        )

        with (
            patch("httpx.Client.get", return_value=response),
            patch("time.sleep") as mock_sleep,
        ):
            client = GitHubClient(token=github_token)
            since = datetime(2026, 5, 1, tzinfo=UTC)
            client.get_commits("alice/repo", since)

        mock_sleep.assert_called_once()
        sleep_duration = mock_sleep.call_args[0][0]
        # Should sleep approximately until reset_ts
        assert sleep_duration > 0
        assert sleep_duration <= 122  # reset_ts - now + 1, with small clock tolerance
