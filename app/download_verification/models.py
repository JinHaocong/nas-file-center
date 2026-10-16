"""Additive result ledger independent from mutation Plans and Quarantine."""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import ForeignKey, Index, Integer, String, Text, BigInteger, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, utcnow


class DownloadVerificationRun(Base):
    __tablename__ = "download_verification_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_job_id: Mapped[int] = mapped_column(ForeignKey("work_jobs.id", ondelete="SET NULL"), index=True)
    remote_root: Mapped[str] = mapped_column(Text)
    local_root: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(40), default="INCOMPLETE")
    checked: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    bytes_checked: Mapped[int] = mapped_column(BigInteger, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]


class DownloadVerificationItem(Base):
    __tablename__ = "download_verification_items"
    __table_args__ = (
        UniqueConstraint("run_id", "relative_path", name="uq_download_verify_run_path"),
        Index("ix_download_verify_items_status", "run_id", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("download_verification_runs.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(40))
    remote_size: Mapped[int | None] = mapped_column(BigInteger)
    local_size: Mapped[int | None] = mapped_column(BigInteger)
    remote_sha256: Mapped[str | None] = mapped_column(String(64))
    local_sha256: Mapped[str | None] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(64))
