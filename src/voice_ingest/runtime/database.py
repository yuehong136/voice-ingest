"""Persistence records; contracts remain independent of SQLAlchemy."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return uuid4().hex


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    filename: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    ready: Mapped[bool] = mapped_column(default=False)
    deleted: Mapped[bool] = mapped_column(default=False)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    media_info: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Upload(Base):
    __tablename__ = "uploads"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), unique=True)
    multipart_id: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(32), default="creating")
    operation_token: Mapped[str | None] = mapped_column(String(32))
    operation_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    state: Mapped[str] = mapped_column(String(32), default="queued")
    options: Mapped[dict[str, Any]] = mapped_column(JSON)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    provider_task_id: Mapped[str | None] = mapped_column(String(200))
    result_url: Mapped[str | None] = mapped_column(Text)
    result_key: Mapped[str | None] = mapped_column(String(512))
    raw_key: Mapped[str | None] = mapped_column(String(512))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    remote_may_run: Mapped[bool] = mapped_column(default=False)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_run_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    attempt_started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    __table_args__ = (Index("jobs_claim", "state", "next_run_at", "lease_until"),)


class Attempt(Base):
    __tablename__ = "attempts"
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), primary_key=True)
    number: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    region: Mapped[str] = mapped_column(String(32))
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    provider_task_id: Mapped[str | None] = mapped_column(String(200))
    raw_key: Mapped[str | None] = mapped_column(String(512))
    result_key: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    state: Mapped[str] = mapped_column(String(32))
    code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class SchedulerLock(Base):
    __tablename__ = "scheduler_lock"
    id: Mapped[int] = mapped_column(primary_key=True)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime())


def database(url: str):
    engine = create_async_engine(url, pool_pre_ping=True)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
