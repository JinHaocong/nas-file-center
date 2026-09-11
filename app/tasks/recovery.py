from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any
from sqlalchemy import select, update, text
from sqlalchemy.orm import sessionmaker

from app.models import ResourcePolicy, ScanJob, TaskLock, TaskEvent, WorkJob, WorkerState, utcnow
from app.resource_control import (
    ResourcePolicySnapshot,
    evaluate_resource_policy,
    resolve_timezone,
    resource_policy_row_fingerprint,
    validate_resource_policy_snapshot,
)
from app.tasks.handlers import get_job_capabilities
from app.tasks.logging import log_task_event
from app.tasks.state_machine import JobLeaseLost, JobState

logger = logging.getLogger(__name__)

WORKER_ONLINE_THRESHOLD_SECONDS = 30.0
WORKER_STALE_THRESHOLD_SECONDS = 90.0
WORKER_LEASE_TIMEOUT_SECONDS: float = 30.0


def assert_active_worker_lease(
    session: Any,
    worker_id: str,
    now: datetime | None = None,
    timeout_seconds: float = WORKER_LEASE_TIMEOUT_SECONDS,
) -> TaskLock:
    """
    Assert that worker_id holds the active, unexpired exclusive lease in task_lock.
    Raises JobLeaseLost if:
    - TaskLock does not exist or locked == False
    - lock.owner != worker_id
    - lock.acquired_at is None
    - lease age > timeout_seconds (expired)
    """
    if now is None:
        now = utcnow()
    now_utc = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)

    lock = session.get(TaskLock, 1)
    if not lock or not lock.locked:
        raise JobLeaseLost(f"Worker lease not held (locked={lock.locked if lock else False})")
    if lock.owner != worker_id:
        raise JobLeaseLost(f"Worker '{worker_id}' lost exclusive lease (current owner: '{lock.owner}')")
    if not lock.acquired_at:
        raise JobLeaseLost(f"Worker '{worker_id}' lease invalid: missing acquired_at")

    lock_time = lock.acquired_at if lock.acquired_at.tzinfo is not None else lock.acquired_at.replace(tzinfo=timezone.utc)
    age = (now_utc - lock_time).total_seconds()
    if age > timeout_seconds:
        raise JobLeaseLost(f"Worker '{worker_id}' lease expired (age: {age:.1f}s > {timeout_seconds}s)")

    return lock


def renew_and_assert_worker_lease(
    session_factory: sessionmaker,
    worker_id: str,
    timeout_seconds: float = WORKER_LEASE_TIMEOUT_SECONDS,
) -> None:
    """
    Pattern A fence: Short committed lease fence for filesystem syscalls.
    Opens a dedicated write transaction, asserts the worker lease is active,
    refreshes acquired_at to now, and COMMITS immediately.
    No lock/transaction remains open across the filesystem syscall.
    """
    now = utcnow()
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = assert_active_worker_lease(session, worker_id, now=now, timeout_seconds=timeout_seconds)
        lock.acquired_at = now
        session.commit()


def compute_worker_status(
    heartbeat_at: datetime | None,
    current_time: datetime | None = None,
) -> tuple[str, float | None]:
    """Calculate worker health status and age in seconds."""
    if heartbeat_at is None:
        return "offline", None
    now = current_time or utcnow()
    if heartbeat_at.tzinfo is None:
        heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age = max(0.0, (now - heartbeat_at).total_seconds())
    if age <= WORKER_ONLINE_THRESHOLD_SECONDS:
        return "online", age
    if age <= WORKER_STALE_THRESHOLD_SECONDS:
        return "stale", age
    return "offline", age


import os
import socket
import uuid


def generate_worker_id() -> str:
    host = socket.gethostname() or "host"
    pid = os.getpid()
    uid = uuid.uuid4().hex[:8]
    return f"{host}-{pid}-{uid}"


def acquire_worker_ownership(
    engine: Any,
    session_factory: sessionmaker,
    worker_id: str,
    timeout_seconds: float = WORKER_LEASE_TIMEOUT_SECONDS,
) -> bool:
    """
    Acquire single-worker exclusive ownership in task_lock and register worker_state.
    Strict lease semantics using SQLite BEGIN IMMEDIATE:
    - If no lock exists: acquire -> True
    - If current owner == worker_id: renew lease -> True
    - If current owner != worker_id:
        - If (now - acquired_at) <= timeout_seconds: lease is FRESH -> False (rejected)
        - If (now - acquired_at) > timeout_seconds: lease is STALE -> takeover -> True
    """
    try:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            now_utc = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
            lock = session.get(TaskLock, 1)
            if lock is None:
                lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=now)
                session.add(lock)
            else:
                if lock.locked and lock.owner and lock.owner != worker_id:
                    if lock.acquired_at is not None:
                        lock_time = lock.acquired_at if lock.acquired_at.tzinfo is not None else lock.acquired_at.replace(tzinfo=timezone.utc)
                        age = (now_utc - lock_time).total_seconds()
                        if age <= timeout_seconds:
                            # Active lease held by another worker: reject acquisition
                            session.rollback()
                            return False

                lock.locked = True
                lock.owner = worker_id
                lock.acquired_at = now

            # Update or insert worker_state
            state = session.get(WorkerState, "default")
            if state is None:
                state = WorkerState(
                    worker_key="default",
                    worker_id=worker_id,
                    started_at=now,
                    heartbeat_at=now,
                    updated_at=now,
                )
                session.add(state)
            else:
                state.worker_id = worker_id
                state.started_at = now
                state.heartbeat_at = now
                state.updated_at = now

            session.commit()
            return True
    except Exception:
        return False


def update_worker_heartbeat(
    engine: Any,
    session_factory: sessionmaker,
    worker_id: str,
    timeout_seconds: float = WORKER_LEASE_TIMEOUT_SECONDS,
) -> bool:
    """
    Update worker heartbeat in worker_state and task_lock.
    Only the current active, unexpired lease owner is allowed to renew the lease.
    Expired leases CANNOT be resurrected by heartbeat and return False.
    """
    try:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            try:
                assert_active_worker_lease(session, worker_id, now=now, timeout_seconds=timeout_seconds)
            except JobLeaseLost:
                session.rollback()
                return False

            lock = session.get(TaskLock, 1)
            if lock is not None:
                lock.acquired_at = now
            state = session.get(WorkerState, "default")
            if state:
                state.heartbeat_at = now
                state.updated_at = now
            session.commit()
            return True
    except Exception:
        return False


def get_policy_row_for_check(session: Any) -> ResourcePolicy | None:
    return session.get(ResourcePolicy, 1)


def claim_next_job(
    engine: Any,
    session_factory: sessionmaker,
    worker_id: str,
    timeout_seconds: float = WORKER_LEASE_TIMEOUT_SECONDS,
) -> int | None:
    MAX_POLICY_ATTEMPTS = 3

    for attempt in range(MAX_POLICY_ATTEMPTS):
        policy_error_reason: str | None = None
        # Phase A: Outside write transaction (no write lock, no authoritative lease check)
        with session_factory() as session:
            row = session.get(ResourcePolicy, 1)
            expected_fingerprint = resource_policy_row_fingerprint(row)
            if row is None:
                policy_valid = False
                snapshot = None
                prepared_tz = None
                policy_error_reason = "ResourcePolicy singleton row missing"
            else:
                try:
                    snapshot = ResourcePolicySnapshot(
                        scan_threads=row.scan_threads,
                        hash_threads=row.hash_threads,
                        io_limit=row.io_limit,
                        job_priority=row.job_priority,
                        active_window_enabled=row.active_window_enabled,
                        active_window_start=row.active_window_start,
                        active_window_end=row.active_window_end,
                        active_window_timezone=row.active_window_timezone,
                        outside_window_mode=row.outside_window_mode,
                        revision=row.revision,
                    )
                    validate_resource_policy_snapshot(snapshot)
                    policy_valid = True
                    prepared_tz = (
                        resolve_timezone(snapshot.active_window_timezone)
                        if snapshot.active_window_enabled and snapshot.active_window_timezone
                        else None
                    )
                except Exception as exc:
                    policy_valid = False
                    snapshot = None
                    prepared_tz = None
                    policy_error_reason = str(exc)

        if not policy_valid:
            logger.warning(
                "ResourcePolicy invalid or unavailable (%s); resource-controlled jobs held fail-closed",
                policy_error_reason or "unknown error",
            )

        # Phase B: Short BEGIN IMMEDIATE write transaction
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            claim_now = utcnow()
            assert_active_worker_lease(session, worker_id, now=claim_now, timeout_seconds=timeout_seconds)

            current_row = get_policy_row_for_check(session)
            current_fingerprint = resource_policy_row_fingerprint(current_row)

            # Strict comparison of FULL policy fingerprint
            if current_fingerprint != expected_fingerprint:
                session.rollback()
                continue

            # Active-window eligibility evaluated against fresh transaction-time claim_now
            if not policy_valid or snapshot is None:
                resource_jobs_admitted = False
                job_priority = "normal"
            else:
                eff = evaluate_resource_policy(snapshot, now_utc=claim_now, resolved_timezone=prepared_tz)
                resource_jobs_admitted = eff.resource_jobs_admitted
                job_priority = snapshot.job_priority

            candidate_id = None
            if not resource_jobs_admitted:
                candidate_id = session.scalar(
                    select(WorkJob.id)
                    .where(
                        WorkJob.status == JobState.QUEUED.value,
                        WorkJob.kind.not_in(["index-root", "fclones-scan"]),
                    )
                    .order_by(WorkJob.id)
                    .limit(1)
                )
            elif job_priority == "background":
                candidate_id = session.scalar(
                    select(WorkJob.id)
                    .where(
                        WorkJob.status == JobState.QUEUED.value,
                        WorkJob.kind.not_in(["index-root", "fclones-scan"]),
                    )
                    .order_by(WorkJob.id)
                    .limit(1)
                )
                if candidate_id is None:
                    candidate_id = session.scalar(
                        select(WorkJob.id)
                        .where(
                            WorkJob.status == JobState.QUEUED.value,
                            WorkJob.kind.in_(["index-root", "fclones-scan"]),
                        )
                        .order_by(WorkJob.id)
                        .limit(1)
                    )
            else:
                candidate_id = session.scalar(
                    select(WorkJob.id)
                    .where(WorkJob.status == JobState.QUEUED.value)
                    .order_by(WorkJob.id)
                    .limit(1)
                )

            if candidate_id is None:
                session.rollback()
                return None

            stmt = (
                update(WorkJob)
                .where(WorkJob.id == candidate_id, WorkJob.status == JobState.QUEUED.value)
                .values(
                    status=JobState.RUNNING.value,
                    started_at=claim_now,
                    heartbeat_at=claim_now,
                    error_code=None,
                    error_text=None,
                )
            )
            result = session.execute(stmt)
            session.commit()
            if result.rowcount == 1:
                return candidate_id
            return None

    # Retry exhaustion fallback: after 3 unstable snapshot attempts
    # MUST NOT use stale policy, MUST NOT claim resource-controlled jobs
    logger.warning(
        "ResourcePolicy invalid or unavailable (%s); resource-controlled jobs held fail-closed",
        "snapshot unstable after max retry attempts",
    )
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        fallback_now = utcnow()
        assert_active_worker_lease(session, worker_id, now=fallback_now, timeout_seconds=timeout_seconds)
        candidate_id = session.scalar(
            select(WorkJob.id)
            .where(
                WorkJob.status == JobState.QUEUED.value,
                WorkJob.kind.not_in(["index-root", "fclones-scan"]),
            )
            .order_by(WorkJob.id)
            .limit(1)
        )
        if candidate_id is None:
            session.rollback()
            return None

        stmt = (
            update(WorkJob)
            .where(WorkJob.id == candidate_id, WorkJob.status == JobState.QUEUED.value)
            .values(
                status=JobState.RUNNING.value,
                started_at=fallback_now,
                heartbeat_at=fallback_now,
                error_code=None,
                error_text=None,
            )
        )
        result = session.execute(stmt)
        session.commit()
        if result.rowcount == 1:
            return candidate_id
        return None


def recover_interrupted_jobs(
    engine: Any,
    session_factory: sessionmaker,
    worker_id: str | None = None,
    timeout_seconds: float = WORKER_LEASE_TIMEOUT_SECONDS,
) -> dict[str, int]:
    """
    Worker restart recovery protocol:
    1. cancel_requested -> cancelled
    2. running & supports_resume with valid checkpoint -> queued
    3. running & non-resumable -> failed (WORKER_INTERRUPTED)
    4. queued, paused, completed, failed, cancelled -> preserved

    If worker_id is specified, each recovery mutation runs in a short BEGIN IMMEDIATE
    write transaction protected by assert_active_worker_lease.
    """
    stats = {
        "recovered_requeued": 0,
        "failed_interrupted": 0,
        "cancelled": 0,
    }

    from app.tasks.sync import sync_scan_job_status

    # 1. Initial lease validation & fetch candidate job IDs
    with session_factory() as session:
        now = utcnow()
        if worker_id is not None:
            try:
                assert_active_worker_lease(session, worker_id, now=now, timeout_seconds=timeout_seconds)
            except JobLeaseLost:
                return stats

        candidate_ids = list(
            session.scalars(
                select(WorkJob.id)
                .where(WorkJob.status.in_([JobState.RUNNING.value, JobState.CANCEL_REQUESTED.value]))
                .order_by(WorkJob.id)
            )
        )

    # 2. Recover candidate jobs under short atomic write transactions with current status dispatch
    for jid in candidate_ids:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            mutation_now = utcnow()
            if worker_id is not None:
                try:
                    assert_active_worker_lease(session, worker_id, now=mutation_now, timeout_seconds=timeout_seconds)
                except JobLeaseLost:
                    session.rollback()
                    return stats

            job = session.get(WorkJob, jid)
            if not job:
                session.rollback()
                continue

            if job.status == JobState.CANCEL_REQUESTED.value:
                job.status = JobState.CANCELLED.value
                job.finished_at = mutation_now
                job.error_text = "Cancelled by user"
                stats["cancelled"] += 1
                sync_scan_job_status(
                    session,
                    job,
                    "cancelled",
                    finished_at=mutation_now,
                    error_text="Cancelled by user",
                    cleanup_partial_results=True,
                )
                log_task_event(
                    session,
                    job_id=job.id,
                    event_type="cancelled",
                    message="Job cancelled during worker restart recovery",
                    level="warning",
                )
                session.commit()
            elif job.status == JobState.RUNNING.value:
                caps = get_job_capabilities(job.kind)
                has_checkpoint = False
                if job.checkpoint_json:
                    try:
                        data = json.loads(job.checkpoint_json)
                        has_checkpoint = isinstance(data, dict) and bool(data.get("schema_version"))
                    except Exception:
                        has_checkpoint = False

                if caps.get("supports_resume") and has_checkpoint:
                    job.status = JobState.QUEUED.value
                    stats["recovered_requeued"] += 1
                    log_task_event(
                        session,
                        job_id=job.id,
                        event_type="recovered_after_worker_restart",
                        message="Resumable job requeued after worker restart",
                        level="info",
                    )
                else:
                    job.status = JobState.FAILED.value
                    job.error_code = "WORKER_INTERRUPTED"
                    job.error_text = "Worker restarted while job was running"
                    job.finished_at = mutation_now
                    stats["failed_interrupted"] += 1
                    sync_scan_job_status(
                        session,
                        job,
                        "failed",
                        finished_at=mutation_now,
                        error_text="Worker restarted while job was running",
                        cleanup_partial_results=True,
                    )
                    log_task_event(
                        session,
                        job_id=job.id,
                        event_type="failed",
                        message="Non-resumable job marked failed after worker restart",
                        level="error",
                        context={"error_code": "WORKER_INTERRUPTED"},
                    )
                session.commit()
            else:
                session.rollback()

    return stats
