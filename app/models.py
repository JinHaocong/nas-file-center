from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.dbtypes import FilesystemId


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(32), default="normal")
    roots_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    fclones_args_json: Mapped[str] = mapped_column(Text, default="{}")
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    raw_report_path: Mapped[str | None] = mapped_column(Text)
    total_groups: Mapped[int] = mapped_column(Integer, default=0)
    total_files_in_groups: Mapped[int] = mapped_column(Integer, default=0)
    reclaimable_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    error_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    groups: Mapped[list[DuplicateGroup]] = relationship(back_populates="scan_job", cascade="all, delete-orphan")
    plans: Mapped[list[Plan]] = relationship(back_populates="scan_job", cascade="all, delete-orphan")


class DuplicateGroup(Base):
    __tablename__ = "duplicate_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_job_id: Mapped[int] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"), index=True)
    content_hash: Mapped[str] = mapped_column(String(256), index=True)
    file_size: Mapped[int] = mapped_column(BigInteger)
    member_count: Mapped[int] = mapped_column(Integer)

    scan_job: Mapped[ScanJob] = relationship(back_populates="groups")
    files: Mapped[list[DuplicateFile]] = relationship(back_populates="group", cascade="all, delete-orphan")


class DuplicateFile(Base):
    __tablename__ = "duplicate_files"
    __table_args__ = (Index("ix_duplicate_files_group_root", "group_id", "root_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("duplicate_groups.id", ondelete="CASCADE"), index=True)
    root_id: Mapped[int] = mapped_column(Integer)
    absolute_path: Mapped[str] = mapped_column(Text)
    relative_path: Mapped[str] = mapped_column(Text)
    top_level_dir: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    device: Mapped[int] = mapped_column(FilesystemId(), default=0)
    inode: Mapped[int] = mapped_column(FilesystemId(), default=0)

    group: Mapped[DuplicateGroup] = relationship(back_populates="files")


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_job_id: Mapped[int] = mapped_column(ForeignKey("scan_jobs.id", ondelete="CASCADE"), index=True)
    policy: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    frozen_at: Mapped[datetime | None]
    expected_reclaim_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    scan_job: Mapped[ScanJob] = relationship(back_populates="plans")
    items: Mapped[list[PlanItem]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("duplicate_groups.id", ondelete="CASCADE"), index=True)
    keep_path: Mapped[str] = mapped_column(Text)
    delete_path: Mapped[str] = mapped_column(Text)
    expected_size: Mapped[int] = mapped_column(BigInteger)
    discovery_hash: Mapped[str] = mapped_column(String(256))
    verification_hash: Mapped[str | None] = mapped_column(String(128))
    expected_keep_device: Mapped[int] = mapped_column(FilesystemId(), default=0)
    expected_keep_inode: Mapped[int] = mapped_column(FilesystemId(), default=0)
    expected_keep_mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    expected_delete_device: Mapped[int] = mapped_column(FilesystemId(), default=0)
    expected_delete_inode: Mapped[int] = mapped_column(FilesystemId(), default=0)
    expected_delete_mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    state: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    reason: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[Plan] = relationship(back_populates="items")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    path: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(32))
    details_json: Mapped[str] = mapped_column(Text, default="{}")


class TaskLock(Base):
    __tablename__ = "task_lock"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    owner: Mapped[str | None] = mapped_column(String(128))
    acquired_at: Mapped[datetime | None]


class IndexedPath(Base):
    __tablename__ = "indexed_paths"
    __table_args__ = (
        Index("ix_indexed_paths_root_relative", "root_key", "relative_path"),
        Index("ix_indexed_paths_basename", "basename"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    root_key: Mapped[str] = mapped_column(String(255), index=True)
    absolute_path: Mapped[str] = mapped_column(Text, unique=True)
    relative_path: Mapped[str] = mapped_column(Text)
    basename: Mapped[str] = mapped_column(Text)
    stem: Mapped[str] = mapped_column(Text)
    suffix: Mapped[str] = mapped_column(String(255), default="")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    device: Mapped[int] = mapped_column(FilesystemId(), default=0)
    inode: Mapped[int] = mapped_column(FilesystemId(), default=0)
    is_dir: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    scan_generation: Mapped[str] = mapped_column(String(128), index=True)


class BatchPlan(Base):
    __tablename__ = "batch_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    frozen_at: Mapped[datetime | None]
    expected_changes: Mapped[int] = mapped_column(Integer, default=0)
    expected_reclaim_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")

    items: Mapped[list["BatchPlanItem"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class BatchPlanItem(Base):
    __tablename__ = "batch_plan_items"
    __table_args__ = (Index("ix_batch_plan_items_plan_state", "plan_id", "state"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("batch_plans.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(64), index=True)
    source_path: Mapped[str] = mapped_column(Text)
    target_path: Mapped[str | None] = mapped_column(Text)
    keep_path: Mapped[str | None] = mapped_column(Text)
    expected_size: Mapped[int] = mapped_column(BigInteger, default=0)
    expected_mtime_ns: Mapped[int] = mapped_column(BigInteger, default=0)
    expected_device: Mapped[int] = mapped_column(FilesystemId(), default=0)
    expected_inode: Mapped[int] = mapped_column(FilesystemId(), default=0)
    expected_hash: Mapped[str | None] = mapped_column(String(128))
    state: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")

    plan: Mapped[BatchPlan] = relationship(back_populates="items")


class WorkJob(Base):
    __tablename__ = "work_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    progress_current: Mapped[int] = mapped_column(BigInteger, default=0)
    progress_total: Mapped[int] = mapped_column(BigInteger, default=0)
    progress_message: Mapped[str | None] = mapped_column(Text)
    state_json: Mapped[str] = mapped_column(Text, default="{}")
    checkpoint_json: Mapped[str | None] = mapped_column(Text, default="{}")
    error_text: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64))
    pause_requested_at: Mapped[datetime | None]
    cancel_requested_at: Mapped[datetime | None]
    heartbeat_at: Mapped[datetime | None]
    retry_of: Mapped[int | None] = mapped_column(ForeignKey("work_jobs.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    events: Mapped[list["TaskEvent"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    @property
    def job_type(self) -> str:
        return self.kind

    @job_type.setter
    def job_type(self, val: str) -> None:
        self.kind = val


class WorkerState(Base):
    __tablename__ = "worker_state"

    worker_key: Mapped[str] = mapped_column(String(64), primary_key=True, default="default")
    worker_id: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    heartbeat_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (
        Index("ix_task_events_job_id_id", "job_id", "id"),
        Index("ix_task_events_timestamp", "timestamp"),
        Index("ix_task_events_level", "level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("work_jobs.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[datetime] = mapped_column(default=utcnow)
    level: Mapped[str] = mapped_column(String(16), default="info")
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    context_json: Mapped[str] = mapped_column(Text, default="{}")

    job: Mapped[WorkJob] = relationship(back_populates="events")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None]

    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    favorite_paths: Mapped[list["FavoritePath"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    recent_paths: Mapped[list["RecentPath"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    organizer_profiles: Mapped[list["OrganizerProfile"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    revoked_at: Mapped[datetime | None] = mapped_column(index=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class FavoritePath(Base):
    __tablename__ = "favorite_paths"
    __table_args__ = (
        UniqueConstraint("user_id", "path", name="uq_user_favorite_path"),
        Index("ix_favorite_paths_user_pos", "user_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="favorite_paths")


class RecentPath(Base):
    __tablename__ = "recent_paths"
    __table_args__ = (
        UniqueConstraint("user_id", "path", name="uq_user_recent_path"),
        Index("ix_recent_paths_user_time", "user_id", "last_used_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(Text)
    last_used_at: Mapped[datetime] = mapped_column(default=utcnow)

    user: Mapped[User] = relationship(back_populates="recent_paths")


class OrganizerProfile(Base):
    __tablename__ = "organizer_profiles"
    __table_args__ = (
        Index("ix_organizer_profiles_user", "user_id"),
        Index("ix_organizer_profiles_builtin", "is_builtin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    slug: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    builtin_version: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    root: Mapped[str | None] = mapped_column(Text, nullable=True)
    recursive: Mapped[bool] = mapped_column(Boolean, default=False)

    image_extensions: Mapped[str] = mapped_column(Text, default="[]")
    video_extensions: Mapped[str] = mapped_column(Text, default="[]")

    rename_template: Mapped[str] = mapped_column(String(500), default="{name} {statistics}")
    statistics_template: Mapped[str] = mapped_column(String(500), default="[{images}P{?videos: {videos}V} {size}]")

    preserve_tags: Mapped[str] = mapped_column(Text, default="[]")
    cleanup_patterns: Mapped[str] = mapped_column(Text, default="[]")

    numbering_mode: Mapped[str] = mapped_column(String(32), default="none")
    numbering_start: Mapped[int] = mapped_column(Integer, default=1)
    numbering_padding: Mapped[int] = mapped_column(Integer, default=3)

    mtime_mode: Mapped[str] = mapped_column(String(32), default="none")
    mtime_delay_seconds: Mapped[float] = mapped_column(Float, default=2.0)

    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    user: Mapped[User | None] = relationship(back_populates="organizer_profiles")
