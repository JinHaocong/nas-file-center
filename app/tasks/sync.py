from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    BatchPlan,
    BatchPlanItem,
    DuplicateFile,
    DuplicateGroup,
    ScanJob,
    WorkJob,
    utcnow,
)


def sync_scan_job_status(
    session: Session,
    work_job: WorkJob,
    target_status: str,
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_text: str | None = None,
    cleanup_partial_results: bool = False,
) -> ScanJob | None:
    """
    Synchronize linked ScanJob lifecycle with its parent WorkJob.
    Handles status transitions, started/finished timestamps, error text,
    and cleanup of partial DuplicateGroup/DuplicateFile records if cancelled or failed.
    """
    if work_job.kind != "fclones-scan":
        return None

    try:
        st = json.loads(work_job.state_json or "{}")
        scan_id = st.get("scan_job_id")
        if not scan_id:
            return None

        scan = session.get(ScanJob, int(scan_id))
        if not scan:
            return None

        now = utcnow()
        if target_status == "running":
            scan.status = "running"
            scan.started_at = scan.started_at or started_at or now
        elif target_status == "completed":
            scan.status = "completed"
            scan.finished_at = scan.finished_at or finished_at or now
            scan.error_text = None
        elif target_status == "cancelled":
            scan.status = "cancelled"
            scan.finished_at = scan.finished_at or finished_at or now
            scan.error_text = error_text or "Cancelled by user"
            if cleanup_partial_results:
                group_ids_subq = select(DuplicateGroup.id).where(DuplicateGroup.scan_job_id == scan.id)
                session.execute(delete(DuplicateFile).where(DuplicateFile.group_id.in_(group_ids_subq)))
                session.execute(delete(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan.id))
                scan.total_groups = 0
                scan.total_files_in_groups = 0
                scan.reclaimable_bytes = 0
        elif target_status == "failed":
            scan.status = "failed"
            scan.finished_at = scan.finished_at or finished_at or now
            scan.error_text = error_text
            if cleanup_partial_results:
                group_ids_subq = select(DuplicateGroup.id).where(DuplicateGroup.scan_job_id == scan.id)
                session.execute(delete(DuplicateFile).where(DuplicateFile.group_id.in_(group_ids_subq)))
                session.execute(delete(DuplicateGroup).where(DuplicateGroup.scan_job_id == scan.id))
                scan.total_groups = 0
                scan.total_files_in_groups = 0
                scan.reclaimable_bytes = 0
        return scan
    except Exception:
        return None


def sync_batch_plan_status(
    session: Session,
    work_job: WorkJob,
    target_status: str,
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    error_text: str | None = None,
) -> BatchPlan | None:
    """
    Synchronize linked BatchPlan lifecycle with its parent WorkJob.
    """
    if work_job.kind != "batch-plan-execute":
        return None

    try:
        st = json.loads(work_job.state_json or "{}")
        plan_id = st.get("plan_id")
        if not plan_id:
            return None

        plan = session.get(BatchPlan, int(plan_id))
        if not plan:
            return None

        if target_status == "running":
            plan.status = "executing"
        elif target_status in ("completed", "cancelled", "failed"):
            items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)))
            states = {item.state for item in items}
            if states and states <= {"completed"}:
                plan.status = "completed"
            elif any(s == "completed" for s in states):
                plan.status = "partial"
            elif target_status == "completed":
                plan.status = "completed" if states <= {"completed"} else "partial"
            else:
                plan.status = "failed"
        elif target_status == "paused":
            items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id)))
            states = {item.state for item in items}
            if any(s == "completed" for s in states):
                plan.status = "partial"
        return plan
    except Exception:
        return None

