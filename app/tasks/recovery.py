from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import sqlite3
from typing import Any
from sqlalchemy import Integer, func, or_, select, update, text
from sqlalchemy.exc import OperationalError as SQLAlchemyOperationalError
from sqlalchemy.orm import sessionmaker

from app.models import BatchPlan, ResourcePolicy, ScanJob, TaskLock, TaskEvent, WorkJob, WorkerState, utcnow
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


class WorkerHeartbeatDatabaseBusy(RuntimeError):
    """SQLite writer contention, not evidence that the Worker lost its lease."""


def _is_sqlite_writer_contention(error: Exception) -> bool:
    original = getattr(error, "orig", error)
    code = getattr(original, "sqlite_errorcode", None)
    return code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or any(
        token in str(original).lower()
        for token in ("database is locked", "database table is locked", "database is busy")
    )
RESOURCE_CONTROLLED_JOB_KINDS: tuple[str, ...] = (
    "index-root",
    "fclones-scan",
    "workflow-scheduled",
    "download-verify-webdav",
)

_EXECUTION_KIND = "media-organizer-execute"
_CLEANUP_KIND = "media-organizer-cleanup"
_READ_ONLY_PREVIEWS = ("media-organizer-preview", "media_package-package-preview", "media-sort-preview")
_MAINTENANCE_MODE = "maintenance_window"


class MaintenanceReservationActive(PermissionError):
    """A frozen maintenance family still owns the application mutation window."""


def _json_object(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _positive_id(value: Any) -> bool:
    return type(value) is int and value > 0


def organizer_recovery_predecessor(
    job_id: int, retry_of: int | None, state: dict[str, Any],
) -> int | None:
    """Classify only the canonical persisted organizer recovery predecessor."""
    if "recover_from_job_id" in state:
        raise ValueError("noncanonical organizer recovery predecessor")
    if "recovery_of_job_id" not in state and retry_of is None:
        return None
    parent = state.get("recovery_of_job_id")
    if not _positive_id(parent) or parent >= job_id or type(retry_of) is not int or retry_of != parent:
        raise ValueError("organizer recovery predecessor differs from the durable retry link")
    return parent


@dataclass(frozen=True)
class _OrganizerJob:
    id: int
    status: str
    state: dict[str, Any]
    checkpoint: dict[str, Any]
    retry_of: int | None


def _matches_fields(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    return all(key in actual and type(actual[key]) is type(value) and actual[key] == value
               for key, value in expected.items())


def _sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _approved_predecessors(jobs: dict[int, _OrganizerJob]) -> dict[int, int | None]:
    predecessors = {}
    for job in jobs.values():
        if not _matches_fields(job.state, {
            "execution_mode": _MAINTENANCE_MODE, "maintenance_window_confirmed": True,
            "approved_job_id": job.id,
        }):
            continue
        try:
            predecessors[job.id] = organizer_recovery_predecessor(job.id, job.retry_of, job.state)
        except ValueError:
            continue
    return predecessors


def _publication_binding(job: _OrganizerJob, family_id: int) -> bool:
    unit = job.state.get("unit")
    preview_id = job.state.get("preview_job_id")
    return (
        type(unit) is str and bool(unit) and _positive_id(preview_id)
        and _sha256(job.checkpoint.get("manifest_checksum"))
        and _matches_fields(job.checkpoint, {
            "schema_version": 1, "execution_mode": _MAINTENANCE_MODE,
            "frozen_job_id": family_id, "unit": unit, "preview_job_id": preview_id,
        })
    )


def _execution_families(executions: dict[int, _OrganizerJob]) -> dict[int, int]:
    from app.batch.media_organizer_execute_jobs import RECOVERABLE_PHASES

    predecessors = _approved_predecessors(executions)
    families = {}
    for job_id, predecessor in predecessors.items():
        if predecessor is None:
            families[job_id] = job_id
            continue
        job = executions[job_id]
        original = executions.get(predecessor)
        if (
            original is not None and original.status == JobState.FAILED.value
            and predecessor in predecessors and predecessors[predecessor] is None
            and _publication_binding(original, predecessor)
            and type(original.state.get("selection")) is str and original.state["selection"]
            and original.checkpoint.get("phase") in RECOVERABLE_PHASES
            and _matches_fields(job.state, {
                "unit": original.state["unit"], "preview_job_id": original.state["preview_job_id"],
                "selection": original.state.get("selection"),
                "recovery_manifest_checksum": original.checkpoint["manifest_checksum"],
                "recovery_phase": original.checkpoint["phase"],
            })
        ):
            families[job_id] = predecessor
    return families


def _eligible_cleanups(
    cleanups: dict[int, _OrganizerJob],
    publications: dict[int, _OrganizerJob],
    families: dict[int, int],
) -> dict[int, dict[str, Any]]:
    predecessors = _approved_predecessors(cleanups)
    eligible = {}
    # Parents precede recoveries. Match each predecessor to the same reviewed
    # publication so an old cancellation or another cleanup cannot confer scope.
    for cleanup_id in sorted(predecessors):
        cleanup = cleanups[cleanup_id]
        publication_id = cleanup.state.get("execution_job_id")
        if not _positive_id(publication_id) or publication_id not in publications:
            continue
        publication = publications[publication_id]
        binding = {
            "execution_job_id": publication_id,
            "frozen_job_id": families[publication_id],
            "unit": publication.state["unit"],
            "manifest_checksum": publication.checkpoint["manifest_checksum"],
            "plan_sha256": publication.checkpoint["cleanup_plan_sha256"],
        }
        predecessor = predecessors[cleanup_id]
        if not _matches_fields(cleanup.state, binding):
            continue
        if predecessor is not None and (
            eligible.get(predecessor) != binding or cleanups[predecessor].status != JobState.FAILED.value
        ):
            continue
        eligible[cleanup_id] = binding
    return eligible


def _maintenance_mutation_gate(session: Any) -> tuple[set[int], set[int]]:
    rows = session.execute(
        select(
            WorkJob.id, WorkJob.kind, WorkJob.status, WorkJob.state_json, WorkJob.checkpoint_json, WorkJob.retry_of,
        ).where(WorkJob.kind.in_((_EXECUTION_KIND, _CLEANUP_KIND)))
    )
    executions = {}
    cleanups = {}
    reserved = set()
    for job_id, kind, status, raw_state, raw_checkpoint, retry_of in rows:
        state = _json_object(raw_state)
        checkpoint = _json_object(raw_checkpoint)
        job = _OrganizerJob(job_id, status, state, checkpoint, retry_of)
        if kind == _EXECUTION_KIND:
            if _MAINTENANCE_MODE in (state.get("execution_mode"), checkpoint.get("execution_mode")):
                executions[job_id] = job
                # A failed pre-publication task can be explicitly ended by
                # its Worker after proving the private stage is absent. Keep its
                # manifest/audit row, but do not reserve the mutation window forever.
                if (
                    status == JobState.FAILED.value
                    and _matches_fields(checkpoint, {
                        "phase": "abandoned_before_publish", "operator_abandoned": True,
                    })
                    and _positive_id(checkpoint.get("abandoned_by_job_id"))
                ):
                    continue
                frozen_id = checkpoint.get("frozen_job_id")
                checksum = checkpoint.get("manifest_checksum")
                if _positive_id(frozen_id) and type(checksum) is str and checksum:
                    reserved.add(frozen_id)
        elif state.get("execution_mode") == _MAINTENANCE_MODE:
            cleanups[job_id] = job
    if not reserved:
        return reserved, set()

    families = _execution_families(executions)
    publications = {
        job_id: job for job_id, job in executions.items()
        if job_id in families and job.status == JobState.COMPLETED.value
        and _publication_binding(job, families[job_id])
        and _sha256(job.checkpoint.get("cleanup_plan_sha256"))
        and job.checkpoint.get("phase") in ("manual_cleanup_required", "completed")
        and (families[job_id] == job_id
             or job.checkpoint["manifest_checksum"] == job.state["recovery_manifest_checksum"])
    }
    eligible_cleanups = _eligible_cleanups(cleanups, publications, families)

    for job_id, publication in publications.items():
        checkpoint = publication.checkpoint
        if not _matches_fields(checkpoint, {
            "phase": "completed", "second_scan_needed_moves": 0, "second_scan_renamed_count": 0,
        }):
            continue
        finalizer_id = checkpoint.get("finalized_by_cleanup_job_id")
        if not _positive_id(finalizer_id) or finalizer_id not in eligible_cleanups:
            continue
        binding = eligible_cleanups[finalizer_id]
        finalizer = cleanups[finalizer_id]
        phase = finalizer.checkpoint.get("phase")
        # The Worker persists the scanned-zero checkpoint before updating the
        # publication. Its separate terminal DB commit may still be pending.
        if (
            binding["execution_job_id"] == job_id
            and finalizer.status in {JobState.RUNNING.value, JobState.COMPLETED.value, JobState.FAILED.value}
            and phase in ("cleanup-scanned-zero", "completed")
            and (finalizer.status != JobState.COMPLETED.value or phase == "completed")
            and _matches_fields(finalizer.checkpoint, {
                **binding, "schema_version": 1, "execution_mode": _MAINTENANCE_MODE,
                "cleanup_job_id": finalizer_id,
            })
        ):
            reserved.discard(families[job_id])

    allowed = set()
    if len(reserved) == 1:
        family_id = next(iter(reserved))
        allowed.update(job_id for job_id, root_id in families.items()
                       if root_id == family_id and job_id != root_id)
        allowed.update(cleanup_id for cleanup_id, binding in eligible_cleanups.items()
                       if binding["frozen_job_id"] == family_id)
    return reserved, allowed


def reserved_maintenance_family_ids(session: Any) -> set[int]:
    """Return the frozen execution IDs that still own a mutation window."""
    reserved, _ = _maintenance_mutation_gate(session)
    return reserved


def assert_no_maintenance_reservation(session: Any) -> None:
    """Require a free mutation window for a caller outside WorkJob dispatch."""
    if reserved_maintenance_family_ids(session):
        raise MaintenanceReservationActive("A frozen media organizer maintenance window is active")


def work_job_allowed_by_maintenance_reservation(session: Any, job: WorkJob) -> bool:
    if job.kind in _READ_ONLY_PREVIEWS:
        return True
    reserved, allowed = _maintenance_mutation_gate(session)
    return not reserved or job.id in allowed


def _queued_jobs_allowed_by_reservation(session: Any):
    query = select(WorkJob.id).where(WorkJob.status == JobState.QUEUED.value)
    reserved, allowed = _maintenance_mutation_gate(session)
    if reserved:
        query = query.where(or_(WorkJob.kind.in_(_READ_ONLY_PREVIEWS), WorkJob.id.in_(allowed)))
    return query.order_by(WorkJob.id).limit(1)


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
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        # Waiting for SQLite's writer lock can outlive the lease. A timestamp
        # captured before acquisition must never renew an already-stale owner.
        now = utcnow()
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
    *,
    raise_on_busy: bool = False,
) -> bool:
    """
    Renew only a fresh lease owned by this worker, in a short write transaction.

    False means the lease was rejected (expired, replaced or unavailable).
    When raise_on_busy=True, a SQLITE_BUSY/LOCKED writer-contention failure
    raises WorkerHeartbeatDatabaseBusy instead of being indistinguishable from
    a definitively lost lease. The heartbeat loop can retry promptly, but it
    MUST NOT extend the lease or authorize filesystem operations while busy.
    """
    try:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            # Sample time AFTER acquiring the write lock. Never resurrect an
            # expired lease just because BEGIN IMMEDIATE blocked.
            now = utcnow()
            try:
                assert_active_worker_lease(session, worker_id, now=now, timeout_seconds=timeout_seconds)
            except JobLeaseLost as exc:
                session.rollback()
                logger.warning("Worker heartbeat lease denied for %s: %s", worker_id, exc)
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
    except (sqlite3.OperationalError, SQLAlchemyOperationalError) as exc:
        if raise_on_busy and _is_sqlite_writer_contention(exc):
            raise WorkerHeartbeatDatabaseBusy("SQLite writer lock prevented heartbeat") from exc
        logger.warning(
            "Worker heartbeat database operation failed for %s (busy=%s): %s",
            worker_id, _is_sqlite_writer_contention(exc), exc,
        )
        return False
    except Exception:
        logger.exception("Worker heartbeat unexpectedly failed for %s", worker_id)
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

            queue = _queued_jobs_allowed_by_reservation(session)
            if not resource_jobs_admitted or job_priority == "background":
                candidate_id = session.scalar(queue.where(WorkJob.kind.not_in(RESOURCE_CONTROLLED_JOB_KINDS)))
                if candidate_id is None and resource_jobs_admitted:
                    candidate_id = session.scalar(queue.where(WorkJob.kind.in_(RESOURCE_CONTROLLED_JOB_KINDS)))
            else:
                candidate_id = session.scalar(queue)

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
            _queued_jobs_allowed_by_reservation(session)
            .where(WorkJob.kind.not_in(RESOURCE_CONTROLLED_JOB_KINDS))
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


def _linked_plan_id_expr():
    return func.cast(func.json_extract(WorkJob.state_json, "$.plan_id"), Integer)


def _repair_orphaned_executing_plans(
    session_factory: sessionmaker,
    *,
    worker_id: str | None = None,
    timeout_seconds: float = WORKER_LEASE_TIMEOUT_SECONDS,
) -> int:
    """Repair historical plans left in executing after their WorkJob became terminal.

    This is intentionally conservative: an executing plan is only rewritten when
    no active execution WorkJob exists and a linked terminal execution WorkJob is
    available as durable evidence. Plans without such evidence remain untouched.
    """
    from app.tasks.sync import sync_batch_plan_status

    with session_factory() as session:
        candidate_ids = list(
            session.scalars(
                select(BatchPlan.id)
                .where(BatchPlan.status == "executing")
                .order_by(BatchPlan.id)
            )
        )

    repaired = 0
    active_statuses = (
        JobState.QUEUED.value,
        JobState.RUNNING.value,
        JobState.PAUSED.value,
        JobState.CANCEL_REQUESTED.value,
    )
    terminal_statuses = (
        JobState.COMPLETED.value,
        JobState.FAILED.value,
        JobState.CANCELLED.value,
    )

    for plan_id in candidate_ids:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if worker_id is not None:
                try:
                    assert_active_worker_lease(
                        session,
                        worker_id,
                        now=now,
                        timeout_seconds=timeout_seconds,
                    )
                except JobLeaseLost:
                    session.rollback()
                    return repaired

            plan = session.get(BatchPlan, plan_id)
            if plan is None or plan.status != "executing":
                session.rollback()
                continue

            active_job = session.scalars(
                select(WorkJob)
                .where(
                    WorkJob.kind == "batch-plan-execute",
                    WorkJob.status.in_(active_statuses),
                    _linked_plan_id_expr() == plan_id,
                )
                .order_by(WorkJob.id.desc())
            ).first()
            if active_job is not None:
                session.rollback()
                continue

            terminal_job = session.scalars(
                select(WorkJob)
                .where(
                    WorkJob.kind == "batch-plan-execute",
                    WorkJob.status.in_(terminal_statuses),
                    _linked_plan_id_expr() == plan_id,
                )
                .order_by(WorkJob.id.desc())
            ).first()
            if terminal_job is None:
                session.rollback()
                continue

            sync_batch_plan_status(
                session,
                terminal_job,
                terminal_job.status,
                finished_at=terminal_job.finished_at,
                error_text=terminal_job.error_text,
            )
            log_task_event(
                session,
                job_id=terminal_job.id,
                event_type="plan_recovered_after_worker_restart",
                message=(
                    f"Plan #{plan_id} recovered from orphaned executing state "
                    f"using terminal task #{terminal_job.id} ({terminal_job.status})"
                ),
                level="warning",
                context={"plan_id": plan_id, "work_job_id": terminal_job.id},
            )
            session.commit()
            repaired += 1

    return repaired


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
        "repaired_orphan_plans": 0,
    }

    from app.tasks.sync import sync_batch_plan_status, sync_scan_job_status

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
                sync_batch_plan_status(
                    session,
                    job,
                    "cancelled",
                    finished_at=mutation_now,
                    error_text="Cancelled by user",
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
                    sync_batch_plan_status(
                        session,
                        job,
                        "failed",
                        finished_at=mutation_now,
                        error_text="Worker restarted while job was running",
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

    stats["repaired_orphan_plans"] = _repair_orphaned_executing_plans(
        session_factory,
        worker_id=worker_id,
        timeout_seconds=timeout_seconds,
    )
    return stats
