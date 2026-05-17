from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    github_token: str
    github_username: str
    database_url: str
    anthropic_api_key: str
    # Comma-separated list of "owner/repo" strings; empty means ingest all user repos
    github_repos: str = ""

    @property
    def github_repo_list(self) -> list[str]:
        if not self.github_repos.strip():
            return []
        return [r.strip() for r in self.github_repos.split(",") if r.strip()]


settings = Settings()  # type: ignore[call-arg]
