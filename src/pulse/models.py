from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ---------------------------------------------------------------------------
# VectorType — pgvector on PostgreSQL, JSON text on SQLite (for tests)
# ---------------------------------------------------------------------------

EMBEDDING_DIM = 1536


class VectorType(TypeDecorator[list[float]]):
    """Stores a float vector as pgvector on PostgreSQL and as JSON text on SQLite."""

    impl = Text
    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: list[float] | None, dialect: Any) -> Any:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return json.dumps(value)

    def process_result_value(self, value: Any, dialect: Any) -> list[float] | None:
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return json.loads(value)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Pydantic models (data transport / API boundary)
# ---------------------------------------------------------------------------


class Commit(BaseModel):
    sha: str
    repo: str
    message: str
    author_name: str
    author_email: str
    timestamp: datetime
    url: str


class PullRequest(BaseModel):
    pr_id: int
    repo: str
    title: str
    body: str
    state: str
    merged_at: datetime | None = None
    created_at: datetime
    url: str


class Issue(BaseModel):
    issue_id: int
    repo: str
    title: str
    body: str
    state: str
    created_at: datetime
    closed_at: datetime | None = None
    url: str


class SearchResult(BaseModel):
    """A single hit from a vector similarity search across all activity types."""

    type: Literal["commit", "pull_request", "issue"]
    score: float  # cosine similarity — 1.0 is identical, 0.0 is orthogonal
    repo: str
    url: str
    title: str  # commit message, PR title, or issue title
    body: str | None = None  # None for commits
    state: str | None = None  # None for commits
    created_at: datetime


# ---------------------------------------------------------------------------
# SQLAlchemy ORM models (persistence)
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class CommitRecord(Base):
    __tablename__ = "commits"

    sha: Mapped[str] = mapped_column(String(40), primary_key=True)
    repo: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str] = mapped_column(String(255), nullable=False)
    author_email: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(VectorType(), nullable=True)


class PullRequestRecord(Base):
    __tablename__ = "pull_requests"

    pr_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(VectorType(), nullable=True)


class IssueRecord(Base):
    __tablename__ = "issues"

    issue_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repo: Mapped[str] = mapped_column(String(255), primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(VectorType(), nullable=True)
