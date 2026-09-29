from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.job_queue import (
    EnqueuedJob,
    enqueue_index_work,
    enqueue_media_work,
    enqueue_scan_work,
)
from app.models import IndexRoot, Schedule, ScheduleRun, WorkJob, utcnow
from app.scheduler.cron import next_occurrence
from app.scheduler.schema import (
    FclonesScanScheduleTarget,
    IndexRootScheduleTarget,
    MediaAnalysisScheduleTarget,
    MediaIntegrityVerificationScheduleTarget,
    ScheduleTarget,
)
from app.scheduler.service import (
    acquire_scheduler_lease,
    assert_scheduler_lease,
)
from app.tasks.state_machine import TERMINAL_STATES


_TARGET_ADAPTER = TypeAdapter(ScheduleTarget)


@dataclass(frozen=True)
class SchedulerTickResult:
    lease_acquired: bool
    due_seen: int = 0
    dispatched: int = 0
    skipped_overlap: int = 0
    missed_skipped: int = 0
    failed: int = 0
    duplicate_slots: int = 0

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "lease_acquired": self.lease_acquired,
            "due_seen": self.due_seen,
            "dispatched": self.dispatched,
            "skipped_overlap": self.skipped_overlap,
            "missed_skipped": self.missed_skipped,
            "failed": self.failed,
            "duplicate_slots": self.duplicate_slots,
        }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _minute_floor(value: datetime) -> datetime:
    value = _as_utc(value)
    return value.replace(second=0, microsecond=0)


def _parse_target(schedule: Schedule) -> ScheduleTarget:
    try:
        target = _TARGET_ADAPTER.validate_json(schedule.target_json)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid stored schedule target: {exc}") from exc
    if target.type != schedule.target_type:
        raise ValueError(
            f"Stored schedule target type mismatch: row={schedule.target_type!r}, payload={target.type!r}"
        )
    return target


def _active_prior_run(session: Session, schedule_id: int) -> tuple[ScheduleRun, WorkJob | None] | None:
    rows = list(
        session.scalars(
            select(ScheduleRun)
            .where(
                ScheduleRun.schedule_id == schedule_id,
                ScheduleRun.status.in_(["pending", "dispatched"]),
            )
            .order_by(ScheduleRun.scheduled_for_utc.desc(), ScheduleRun.id.desc())
        )
    )
    for run in rows:
        if run.status == "pending":
            return run, None
        # Dispatched runs are atomically bound to a WorkJob. A later NULL link
        # is the expected result of terminal task-history deletion via
        # ON DELETE SET NULL, so it must not block the schedule forever.
        if run.work_job_id is None:
            continue
        work = session.get(WorkJob, run.work_job_id)
        if work is not None and work.status not in TERMINAL_STATES:
            return run, work
    return None


def _attach_scheduler_metadata(
    queued: EnqueuedJob,
    *,
    schedule: Schedule,
    run: ScheduleRun,
    slot: datetime,
) -> None:
    work = queued.work_job
    try:
        state = json.loads(work.state_json or "{}")
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}
    state["scheduler"] = {
        "schedule_id": int(schedule.id),
        "schedule_revision": int(schedule.revision),
        "schedule_run_id": int(run.id),
        "scheduled_for_utc": _as_utc(slot).isoformat(),
    }
    work.state_json = json.dumps(state, ensure_ascii=False, sort_keys=True)


def _enqueue_target(
    session: Session,
    settings: Settings,
    *,
    schedule: Schedule,
    run: ScheduleRun,
    target: ScheduleTarget,
    slot: datetime,
) -> EnqueuedJob:
    if isinstance(target, IndexRootScheduleTarget):
        idx_root = session.get(IndexRoot, target.root_id)
        if idx_root is None:
            raise ValueError(f"Index root #{target.root_id} not found")
        queued = enqueue_index_work(
            session,
            settings,
            root=idx_root.root,
            existing_index_root_id=target.root_id,
            allow_create_index_root=False,
        )
    elif isinstance(target, FclonesScanScheduleTarget):
        scan_name = f"Scheduled: {schedule.name}"[:255]
        queued = enqueue_scan_work(
            session,
            settings,
            name=scan_name,
            roots=target.roots,
            isolate=target.isolate,
            min_size=target.min_size,
            name_patterns=target.name_patterns,
            exclude_patterns=target.exclude_patterns,
            require_existing_dirs=True,
            require_unique_roots=True,
        )
    elif isinstance(target, MediaAnalysisScheduleTarget):
        queued = enqueue_media_work(
            session,
            settings,
            kind="media-analysis",
            root_keys=target.root_keys,
            require_unreserved=True,
        )
    elif isinstance(target, MediaIntegrityVerificationScheduleTarget):
        queued = enqueue_media_work(
            session,
            settings,
            kind="media-integrity-verify",
            root_keys=target.root_keys,
            require_unreserved=True,
        )
    else:  # pragma: no cover - TypeAdapter + closed union make this unreachable.
        raise ValueError(f"Unsupported schedule target: {type(target).__name__}")

    _attach_scheduler_metadata(
        queued,
        schedule=schedule,
        run=run,
        slot=slot,
    )
    return queued


def _process_due_schedule(
    session_factory: sessionmaker,
    settings: Settings,
    *,
    owner: str,
    schedule_id: int,
    now: datetime,
) -> str:
    """Process one due schedule in one BEGIN IMMEDIATE transaction.

    Returns one of: dispatched, skipped_overlap, missed_skipped, failed,
    duplicate_slot, not_due.
    """

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_scheduler_lease(session, owner, now_utc=now)

        schedule = session.get(Schedule, schedule_id)
        if (
            schedule is None
            or not schedule.enabled
            or schedule.next_scheduled_for_utc is None
        ):
            session.rollback()
            return "not_due"

        slot = _as_utc(schedule.next_scheduled_for_utc)
        if slot > now:
            session.rollback()
            return "not_due"

        # V1 missed_run_policy=skip. A slot is eligible only during its own
        # UTC minute; older slots are advanced without creating ScheduleRun or
        # WorkJob rows.
        if slot < _minute_floor(now):
            schedule.next_scheduled_for_utc = next_occurrence(
                schedule.cron_expression,
                schedule.timezone,
                after_utc=now,
            )
            schedule.updated_at = now
            session.commit()
            return "missed_skipped"

        existing = session.scalar(
            select(ScheduleRun).where(
                ScheduleRun.schedule_id == schedule.id,
                ScheduleRun.scheduled_for_utc == slot,
            )
        )
        if existing is not None:
            # The unique slot is already accounted for. Heal a stale next-run
            # pointer without replaying the slot.
            schedule.next_scheduled_for_utc = next_occurrence(
                schedule.cron_expression,
                schedule.timezone,
                after_utc=slot,
            )
            schedule.updated_at = now
            session.commit()
            return "duplicate_slot"

        active = _active_prior_run(session, schedule.id)

        run = ScheduleRun(
            schedule_id=schedule.id,
            schedule_revision=schedule.revision,
            scheduled_for_utc=slot,
            dispatched_at=None,
            status="pending",
            work_job_id=None,
            error_code=None,
            error_text=None,
            target_snapshot_json=schedule.target_json,
            created_at=now,
        )
        session.add(run)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return "duplicate_slot"

        schedule.last_scheduled_for_utc = slot
        schedule.next_scheduled_for_utc = next_occurrence(
            schedule.cron_expression,
            schedule.timezone,
            after_utc=slot,
        )
        schedule.updated_at = now

        if active is not None:
            prior_run, prior_work = active
            run.status = "skipped_overlap"
            run.error_code = "OVERLAP_ACTIVE"
            run.error_text = (
                f"Skipped because schedule run #{prior_run.id} is still active"
                + (
                    f" via WorkJob #{prior_work.id} ({prior_work.status})"
                    if prior_work is not None
                    else ""
                )
            )
            session.commit()
            return "skipped_overlap"

        try:
            target = _parse_target(schedule)
            # SAVEPOINT keeps the durable failed ScheduleRun if a queue helper
            # rejects the target while ensuring no partial ScanJob/WorkJob rows
            # escape the failed dispatch.
            with session.begin_nested():
                queued = _enqueue_target(
                    session,
                    settings,
                    schedule=schedule,
                    run=run,
                    target=target,
                    slot=slot,
                )
                session.flush()
        except Exception as exc:
            run.status = "failed"
            run.error_code = "SCHEDULE_TARGET_INVALID"
            run.error_text = str(exc)[:4000]
            run.work_job_id = None
            run.dispatched_at = None
            session.commit()
            return "failed"

        run.work_job_id = int(queued.work_job.id)
        run.status = "dispatched"
        run.dispatched_at = now
        run.error_code = None
        run.error_text = None
        session.commit()
        return "dispatched"


def run_scheduler_tick(
    session_factory: sessionmaker,
    settings: Settings,
    *,
    owner: str,
    now_utc: datetime | None = None,
    lease_ttl_seconds: float = 90.0,
) -> SchedulerTickResult:
    now = _as_utc(now_utc or utcnow())

    if not acquire_scheduler_lease(
        session_factory,
        owner,
        ttl_seconds=lease_ttl_seconds,
        now_utc=now,
    ):
        return SchedulerTickResult(lease_acquired=False)

    with session_factory() as session:
        due_ids = list(
            session.scalars(
                select(Schedule.id)
                .where(
                    Schedule.enabled.is_(True),
                    Schedule.next_scheduled_for_utc.is_not(None),
                    Schedule.next_scheduled_for_utc <= now,
                )
                .order_by(Schedule.next_scheduled_for_utc, Schedule.id)
            )
        )

    counts: dict[str, int] = {
        "dispatched": 0,
        "skipped_overlap": 0,
        "missed_skipped": 0,
        "failed": 0,
        "duplicate_slot": 0,
    }
    for schedule_id in due_ids:
        outcome = _process_due_schedule(
            session_factory,
            settings,
            owner=owner,
            schedule_id=int(schedule_id),
            now=now,
        )
        if outcome in counts:
            counts[outcome] += 1

    return SchedulerTickResult(
        lease_acquired=True,
        due_seen=len(due_ids),
        dispatched=counts["dispatched"],
        skipped_overlap=counts["skipped_overlap"],
        missed_skipped=counts["missed_skipped"],
        failed=counts["failed"],
        duplicate_slots=counts["duplicate_slot"],
    )
