from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
