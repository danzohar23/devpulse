from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from pulse.config import settings
from pulse.models import Commit, Issue, PullRequest


def _is_retryable(exc: BaseException) -> bool:
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in (429, 500, 502, 503, 504)
    )


class GitHubClient:
    _BASE = "https://api.github.com"

    def __init__(self, token: str | None = None) -> None:
        tok = token or settings.github_token
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {tok}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        @retry(
            retry=retry_if_exception(_is_retryable),
            wait=wait_exponential(multiplier=1, min=4, max=60),
            stop=stop_after_attempt(5),
            reraise=True,
        )
        def _do() -> Any:
            response = self._client.get(f"{self._BASE}{path}", params=params)
            response.raise_for_status()
            self._handle_rate_limit(response)
            return response.json()

        return _do()

    def _get_paginated(self, path: str, params: dict[str, Any] | None = None) -> list[Any]:
        base_params: dict[str, Any] = {"per_page": 100, **(params or {})}
        results: list[Any] = []
        page = 1
        while True:
            base_params["page"] = page
            page_data = self._get(path, base_params)
            if not page_data:
                break
            results.extend(page_data)
            if len(page_data) < 100:
                break
            page += 1
        return results

    @staticmethod
    def _handle_rate_limit(response: httpx.Response) -> None:
        remaining = int(response.headers.get("X-RateLimit-Remaining", "60"))
        if remaining <= 10:
            reset_ts = int(response.headers.get("X-RateLimit-Reset", "0"))
            now = int(time.time())
            sleep_secs = max(reset_ts - now + 1, 1)
            time.sleep(sleep_secs)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_repos(self, username: str) -> list[str]:
        data = self._get_paginated(f"/users/{username}/repos", {"type": "owner"})
        return [r["full_name"] for r in data]

    def get_commits(self, repo: str, since: datetime) -> list[Commit]:
        data = self._get_paginated(
            f"/repos/{repo}/commits",
            {"since": since.isoformat()},
        )
        commits: list[Commit] = []
        for item in data:
            commit_data = item.get("commit", {})
            author_data = commit_data.get("author") or {}
            commits.append(
                Commit(
                    sha=item["sha"],
                    repo=repo,
                    message=commit_data.get("message", ""),
                    author_name=author_data.get("name", ""),
                    author_email=author_data.get("email", ""),
                    timestamp=datetime.fromisoformat(
                        author_data.get("date", "1970-01-01T00:00:00Z").replace("Z", "+00:00")
                    ),
                    url=item.get("html_url", ""),
                )
            )
        return commits

    def get_pull_requests(
        self, repo: str, since: datetime, state: str = "all"
    ) -> list[PullRequest]:
        data = self._get_paginated(
            f"/repos/{repo}/pulls",
            {"state": state, "sort": "created", "direction": "desc"},
        )
        prs: list[PullRequest] = []
        for item in data:
            created_at = datetime.fromisoformat(
                item["created_at"].replace("Z", "+00:00")
            )
            if created_at < since:
                break
            merged_at: datetime | None = None
            if item.get("merged_at"):
                merged_at = datetime.fromisoformat(item["merged_at"].replace("Z", "+00:00"))
            prs.append(
                PullRequest(
                    pr_id=item["number"],
                    repo=repo,
                    title=item.get("title", ""),
                    body=item.get("body") or "",
                    state=item.get("state", ""),
                    merged_at=merged_at,
                    created_at=created_at,
                    url=item.get("html_url", ""),
                )
            )
        return prs

    def get_issues(self, repo: str, since: datetime, state: str = "all") -> list[Issue]:
        data = self._get_paginated(
            f"/repos/{repo}/issues",
            {"state": state, "since": since.isoformat(), "filter": "created"},
        )
        issues: list[Issue] = []
        for item in data:
            # GitHub issues endpoint also returns PRs; skip them
            if "pull_request" in item:
                continue
            closed_at: datetime | None = None
            if item.get("closed_at"):
                closed_at = datetime.fromisoformat(item["closed_at"].replace("Z", "+00:00"))
            issues.append(
                Issue(
                    issue_id=item["number"],
                    repo=repo,
                    title=item.get("title", ""),
                    body=item.get("body") or "",
                    state=item.get("state", ""),
                    created_at=datetime.fromisoformat(
                        item["created_at"].replace("Z", "+00:00")
                    ),
                    closed_at=closed_at,
                    url=item.get("html_url", ""),
                )
            )
        return issues

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
