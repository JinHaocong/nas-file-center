from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any

from sqlalchemy import Integer, func, select, text
from sqlalchemy.orm import sessionmaker

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.config import Settings
from app.exceptions import StateConflictError
from app.models import AuditEvent, BatchPlan, WorkJob, utcnow
from app.path_safety import is_reserved_quarantine_path
from app.storage_optimization.capability import (
    probe_storage_optimization_between,
    probe_storage_optimization_capabilities,
)
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler
from app.tasks.media_mutation_lock import assert_media_mutation_lock
from app.tasks.recovery import (
    assert_active_worker_lease,
    assert_no_maintenance_reservation,
    renew_and_assert_worker_lease,
)

STORAGE_OPTIMIZATION_PROBE_JOB_KIND = "storage-optimization-capability-probe"
PLAN_VALIDATION_JOB_KIND = "batch-plan-validate"
_ACTIVE_JOB_STATUSES = ("queued", "running", "paused", "cancel_requested")


def _capture_probe_directory(raw_path: str, settings: Settings) -> dict[str, Any]:
    path = Path(raw_path).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Storage capability probe directory must be an absolute canonical path")
    if is_reserved_quarantine_path(path, settings.quarantine_root):
        raise ValueError("Storage capability probe cannot target reserved quarantine storage")

    # Open the selected directory by walking from ALLOWED_ROOTS without following
    # symlinks. The identity is frozen into the WorkJob and checked again by the
    # Worker inside the probe's own pinned parent descriptors.
    with safe_open_parent_fd(
        path / ".__nfc_storage_probe_anchor",
        settings.allowed_roots,
    ) as (parent_fd, _leaf):
        info = os.fstat(parent_fd)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Storage capability probe target is not a directory")
        return {
            "path": str(path),
            "device": int(info.st_dev),
            "inode": int(info.st_ino),
        }


def enqueue_storage_optimization_probe(
    session_factory: sessionmaker,
    settings: Settings,
    payload: Any,
    *,
    user_id: int | None,
) -> dict[str, Any]:
    if not settings.allow_mutation:
        raise ValueError("Storage capability probe requires ALLOW_MUTATION=true")

    raw = payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else dict(payload)
    if raw.get("directory") is not None:
        directory = _capture_probe_directory(str(raw["directory"]), settings)
        state = {
            "schema_version": 1,
            "mode": "directory",
            "directory": directory,
            "requested_by_user_id": user_id,
        }
        audit_path = directory["path"]
    else:
        if raw.get("source_directory") is None or raw.get("destination_directory") is None:
            raise ValueError("Provide directory or both source_directory and destination_directory")
        source = _capture_probe_directory(str(raw["source_directory"]), settings)
        destination = _capture_probe_directory(str(raw["destination_directory"]), settings)
        state = {
            "schema_version": 1,
            "mode": "between",
            "source_directory": source,
            "destination_directory": destination,
            "requested_by_user_id": user_id,
        }
        audit_path = f"{source['path']} -> {destination['path']}"

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        if not settings.allow_mutation:
            raise ValueError("Storage capability probe requires ALLOW_MUTATION=true")
        job = WorkJob(
            kind=STORAGE_OPTIMIZATION_PROBE_JOB_KIND,
            status="queued",
            state_json=json.dumps(state, ensure_ascii=False, sort_keys=True),
            progress_current=0,
            progress_total=1,
            progress_message="Queued storage capability probe",
            created_at=utcnow(),
        )
        session.add(job)
        session.flush()
        session.add(AuditEvent(
            operation="storage_optimization.capability_probe_enqueue",
            path=audit_path,
            result="queued",
            details_json=json.dumps({
                "work_job_id": int(job.id),
                "requested_by_user_id": user_id,
                "mode": state["mode"],
            }, ensure_ascii=False, sort_keys=True),
        ))
        session.commit()
        return {"work_job_id": int(job.id), "status": "queued"}


def plan_requires_worker_validation(
    session_factory: sessionmaker,
    plan_id: int,
) -> bool:
    with session_factory() as session:
        plan = session.get(BatchPlan, int(plan_id))
        if plan is None:
            raise KeyError(f"Plan #{plan_id} not found")
        return session.scalar(select(BatchPlanItem.id).where(
            BatchPlanItem.plan_id == int(plan_id),
            BatchPlanItem.operation.in_(("hardlink_optimize", "reflink_optimize")),
        ).limit(1)) is not None


def enqueue_plan_validation(
    session_factory: sessionmaker,
    plan_id: int,
    *,
    user_id: int | None,
) -> dict[str, Any]:
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        plan = session.get(BatchPlan, int(plan_id))
        if plan is None:
            raise KeyError(f"Plan #{plan_id} not found")
        if plan.status not in {"frozen", "partial", "ready", "stale"}:
            raise StateConflictError(
                f"Plan must be frozen before validation, current status={plan.status}"
            )

        active_execution = session.scalar(select(WorkJob.id).where(
            WorkJob.kind == "batch-plan-execute",
            WorkJob.status.in_(_ACTIVE_JOB_STATUSES),
            func.cast(func.json_extract(WorkJob.state_json, "$.plan_id"), Integer) == int(plan_id),
        ).limit(1))
        if active_execution is not None:
            raise StateConflictError(
                f"Cannot validate plan #{plan_id}: active execution task #{active_execution}"
            )

        active_validation = session.scalar(select(WorkJob.id).where(
            WorkJob.kind == PLAN_VALIDATION_JOB_KIND,
            WorkJob.status.in_(_ACTIVE_JOB_STATUSES),
            func.cast(func.json_extract(WorkJob.state_json, "$.plan_id"), Integer) == int(plan_id),
        ).limit(1))
        if active_validation is not None:
            raise StateConflictError(
                f"Plan #{plan_id} already has an active validation task #{active_validation}"
            )

        if plan.kind == "media-sort":
            active_stage = session.scalar(select(WorkJob.id).where(
                WorkJob.kind == "media-sort-plan-stage",
                WorkJob.status.in_(_ACTIVE_JOB_STATUSES),
                func.cast(func.json_extract(WorkJob.state_json, "$.plan_id"), Integer) == int(plan_id),
            ).limit(1))
            if active_stage is not None:
                raise StateConflictError(
                    f"Plan #{plan_id} has active freeze/validation task #{active_stage}"
                )

        state = {
            "schema_version": 1,
            "plan_id": int(plan_id),
            "requested_by_user_id": user_id,
        }
        job = WorkJob(
            kind=PLAN_VALIDATION_JOB_KIND,
            status="queued",
            state_json=json.dumps(state, ensure_ascii=False, sort_keys=True),
            progress_current=0,
            progress_total=0,
            progress_message=f"Queued validation for plan #{plan_id}",
            created_at=utcnow(),
        )
        session.add(job)
        session.flush()
        session.add(AuditEvent(
            operation="plan.validate_enqueue",
            path=f"plan:{plan_id}",
            result="queued",
            details_json=json.dumps({
                "plan_id": int(plan_id),
                "work_job_id": int(job.id),
                "requested_by_user_id": user_id,
            }, ensure_ascii=False, sort_keys=True),
        ))
        session.commit()
        return {
            "plan_id": int(plan_id),
            "work_job_id": int(job.id),
            "status": "queued",
        }


def _assert_worker_mutation_authority(context: JobContext, settings: Settings) -> None:
    if not context.worker_id:
        raise PermissionError("Storage operation requires active Worker authority")
    assert_media_mutation_lock(settings)
    with context.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, context.worker_id)
        assert_no_maintenance_reservation(session)
        session.commit()
    renew_and_assert_worker_lease(context.SessionLocal, context.worker_id)


def _probe_directory_state(raw: Any, *, label: str) -> tuple[Path, tuple[int, int]]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} snapshot is missing")
    path = raw.get("path")
    device = raw.get("device")
    inode = raw.get("inode")
    if (
        type(path) is not str or not path or not Path(path).is_absolute()
        or type(device) is not int or type(inode) is not int
        or device < 0 or inode <= 0
    ):
        raise ValueError(f"{label} snapshot is invalid")
    return Path(path), (device, inode)


@register_handler
class StorageOptimizationCapabilityProbeHandler(TaskHandler):
    job_type = STORAGE_OPTIMIZATION_PROBE_JOB_KIND
    supports_pause = False
    supports_cancel = False
    supports_retry = False
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        state = json.loads(job.state_json or "{}")
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            raise ValueError("Storage capability probe job state is invalid")
        if not settings.allow_mutation:
            raise ValueError("Storage capability probe requires ALLOW_MUTATION=true")
        _assert_worker_mutation_authority(context, settings)
        context.checkpoint(progress_message="Running storage capability probes")

        if state.get("mode") == "directory":
            directory, identity = _probe_directory_state(
                state.get("directory"), label="directory",
            )
            result = probe_storage_optimization_capabilities(
                directory,
                settings.allowed_roots,
                expected_parent_identity=identity,
            )
        elif state.get("mode") == "between":
            source, source_identity = _probe_directory_state(
                state.get("source_directory"), label="source_directory",
            )
            destination, destination_identity = _probe_directory_state(
                state.get("destination_directory"), label="destination_directory",
            )
            result = probe_storage_optimization_between(
                source,
                destination,
                settings.allowed_roots,
                expected_source_parent_identity=source_identity,
                expected_destination_parent_identity=destination_identity,
            )
        else:
            raise ValueError("Storage capability probe job mode is invalid")

        context.checkpoint(
            progress_current=1,
            progress_total=1,
            progress_message="Storage capability probes completed",
            checkpoint_data={
                "schema_version": 1,
                "phase": "completed",
                "result": result,
            },
        )
        context.log(
            "storage_capability_probe_completed",
            "Storage capability probe completed under Worker authority",
            context={"mode": state["mode"], "result": result},
        )


@register_handler
class PlanValidationHandler(TaskHandler):
    job_type = PLAN_VALIDATION_JOB_KIND
    supports_pause = False
    supports_cancel = False
    supports_retry = False
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        state = json.loads(job.state_json or "{}")
        plan_id = state.get("plan_id") if isinstance(state, dict) else None
        if type(plan_id) is not int or plan_id <= 0:
            raise ValueError("Plan validation job is missing plan_id")
        _assert_worker_mutation_authority(context, settings)
        context.checkpoint(progress_message=f"Validating plan #{plan_id}")

        from app.service import FileCenterService

        service = FileCenterService(settings)
        last_total = 0

        def progress(current: int, total: int) -> None:
            nonlocal last_total
            last_total = max(0, int(total))
            if last_total <= 0:
                return
            context.checkpoint(
                progress_current=int(current),
                progress_total=last_total,
                progress_message=f"Validating plan #{plan_id}: {current}/{total}",
            )

        result = service.validate_plan(int(plan_id), progress_callback=progress)
        plan_status = str(result.get("status") or "unknown")
        final_total = max(1, last_total)
        context.checkpoint(
            progress_current=final_total,
            progress_total=final_total,
            progress_message=f"Plan #{plan_id} validation finished: {plan_status}",
            checkpoint_data={
                "schema_version": 1,
                "phase": "completed",
                "plan_id": int(plan_id),
                "status": plan_status,
            },
        )
        context.log(
            "plan_validation_completed",
            "Plan validation completed under Worker authority",
            context={"plan_id": int(plan_id), "status": plan_status},
        )
