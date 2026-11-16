"""Resumable, safely staged large media Move Plan creation.

Every partial Plan remains status='building' and is impossible to freeze or
execute. We commit only bounded insert batches, verify committed rows on
restart, and atomically publish the final Draft together with its owning
WorkJob result. The existing fully-atomic small Plan builder remains available.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.orm import sessionmaker

from app.batch.media_sort_bulk_plan import (
    INSERT_BATCH_SIZE,
    _validated_move,
)
from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, WorkJob, utcnow
from app.tasks.recovery import assert_active_worker_lease

MAX_BUILD_ITEMS = 300_000


def _counts(summary: dict, skip_conflicts: bool) -> tuple[int, int, int]:
    count = summary.get("count")
    conflicts = summary.get("conflict_count")
    ready = summary.get("ready_count")
    if not all(isinstance(n, int) and not isinstance(n, bool)
               for n in (count, conflicts, ready)):
        raise ValueError("Invalid media preview summary counts")
    if (count <= 0 or count > MAX_BUILD_ITEMS or ready <= 0 or ready > count
            or ready + conflicts != count or conflicts < 0):
        raise ValueError("Inconsistent media-sort preview counts")
    if conflicts and not skip_conflicts:
        raise ValueError("Preview has conflicts; explicit skip confirmation required")
    return count, ready, conflicts


def _metadata(job_id: int, preview_id: int, summary: dict, skip_conflicts: bool,
              conflicts: int) -> dict:
    return {
        "source": "media-sort",
        "preview_job_id": preview_id,
        "generation_job_id": job_id,
        "recursive": summary.get("recursive", False),
        "smart_skip": summary.get("smart_skip", True),
        "conflict_policy": "skip" if skip_conflicts else "block",
        "skipped_conflict_count": conflicts if skip_conflicts else 0,
    }


def _find_or_create_stage(session_factory: sessionmaker, settings: Settings,
                          *, job_id: int, preview_id: int, summary: dict,
                          ready: int, skip_conflicts: bool, conflicts: int) -> tuple[int, int, str]:
    expected_meta = _metadata(job_id, preview_id, summary, skip_conflicts, conflicts)
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        plan = session.scalar(
            select(BatchPlan).where(
                BatchPlan.kind == "media-sort",
                func.json_extract(BatchPlan.metadata_json, "$.generation_job_id") == job_id,
            ).order_by(BatchPlan.id.desc()).limit(1)
        )
        if plan is None:
            plan = BatchPlan(
                name=("媒体文件递归分类（每目录 P / V）" if summary.get("recursive")
                      else "媒体文件分类（P / V）"),
                kind="media-sort", status="building", expected_changes=ready,
                metadata_json=json.dumps(expected_meta, ensure_ascii=False),
            )
            session.add(plan)
            session.flush()
        else:
            if plan.status not in ("building", "draft"):
                raise ValueError(f"Unexpected media Plan generation status: {plan.status}")
            if (plan.expected_changes != ready
                    or json.loads(plan.metadata_json or "{}") != expected_meta):
                raise ValueError("Existing generation Plan no longer matches its preview")
        count = session.scalar(select(func.count(BatchPlanItem.id)).where(
            BatchPlanItem.plan_id == plan.id,
        )) or 0
        max_sequence = session.scalar(select(func.max(BatchPlanItem.sequence)).where(
            BatchPlanItem.plan_id == plan.id,
        )) or 0
        if count != max_sequence or count > ready:
            raise ValueError("Committed Plan sequence count is inconsistent")
        if plan.status == "draft" and count != ready:
            raise ValueError("Published Plan is missing committed items")
        plan_id, status = int(plan.id), plan.status
        session.commit()
        return plan_id, int(count), status


def _assert_lease(session, worker_id: str | None) -> None:
    if worker_id is not None:
        assert_active_worker_lease(session, worker_id, now=utcnow())


def cleanup_unpublished_plan(session_factory: sessionmaker, *, job_id: int,
                             worker_id: str | None = None) -> None:
    """Retire only this WorkJob's private, *unpublished* staging Plan."""
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        _assert_lease(session, worker_id)
        plan = session.scalar(select(BatchPlan).where(
            BatchPlan.kind == "media-sort",
            BatchPlan.status == "building",
            func.json_extract(BatchPlan.metadata_json, "$.generation_job_id") == job_id,
        ).limit(1))
        if plan is not None:
            session.execute(delete(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
            session.execute(delete(BatchPlan).where(BatchPlan.id == plan.id))
        session.commit()


def _published_result(session_factory: sessionmaker, *, plan_id: int,
                      job_id: int, worker_id: str | None = None) -> int:
    """Publish Draft and job.plan_id in one durable SQLite transaction."""
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        _assert_lease(session, worker_id)
        plan = session.get(BatchPlan, plan_id)
        work = session.get(WorkJob, job_id)
        if plan is None or work is None or work.kind != "media-sort-plan":
            raise ValueError("Missing generation Plan or owning Worker job")
        count = session.scalar(select(func.count(BatchPlanItem.id)).where(
            BatchPlanItem.plan_id == plan_id,
        )) or 0
        max_sequence = session.scalar(select(func.max(BatchPlanItem.sequence)).where(
            BatchPlanItem.plan_id == plan_id,
        )) or 0
        if count != plan.expected_changes or max_sequence != count:
            raise ValueError("Cannot publish incomplete media-sort Plan")
        if plan.status not in ("draft", "building"):
            raise ValueError("Plan is not in a publishable state")
        plan.status = "draft"
        state = json.loads(work.state_json or "{}")
        if state.get("plan_id") not in (None, plan_id):
            raise ValueError("Worker generation job is already bound to another Plan")
        state["plan_id"] = plan_id
        work.state_json = json.dumps(state, ensure_ascii=False)
        session.commit()
    return plan_id


def create_media_sort_resumable_plan(
    session_factory: sessionmaker,
    settings: Settings,
    *,
    job_id: int,
    preview_job_id: int,
    items_file: Path,
    summary: dict,
    skip_conflicts: bool,
    worker_id: str | None = None,
    on_committed: Callable[[int, int], None] | None = None,
) -> int:
    """Create a large Plan in committed chunks, resuming by source row sequence.

    All previously committed rows must match the authoritative preview before
    continuing; the publication gate validates every row count. Each committed
    chunk is still hidden behind a non-executable 'building' Plan status.
    """
    count, ready, conflicts = _counts(summary, skip_conflicts)
    plan_id, persisted, status = _find_or_create_stage(
        session_factory, settings,
        job_id=job_id, preview_id=preview_job_id,
        summary=summary, ready=ready,
        skip_conflicts=skip_conflicts, conflicts=conflicts,
    )
    if status == "draft":
        return _published_result(
            session_factory, plan_id=plan_id, job_id=job_id, worker_id=worker_id,
        )
    if on_committed:
        on_committed(persisted, ready)

    seen_rows = 0
    ready_rows = 0
    conflict_rows = 0
    seen_targets: set[str] = set()
    existing_chunk: dict[int, tuple[str, str | None, int]] = {}
    staged: list[dict] = []
    inserted = persisted

    def _save_batch() -> None:
        nonlocal inserted
        if not staged:
            return
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            _assert_lease(session, worker_id)
            plan = session.get(BatchPlan, plan_id)
            if plan is None or plan.status != "building":
                raise ValueError("Media Plan is no longer in private building state")
            current = session.scalar(select(func.count(BatchPlanItem.id)).where(
                BatchPlanItem.plan_id == plan_id,
            )) or 0
            if current != inserted:
                raise ValueError("Concurrent or inconsistent staged media Plan rows")
            session.execute(insert(BatchPlanItem), staged)
            session.commit()
        inserted += len(staged)
        staged.clear()
        if on_committed:
            on_committed(inserted, ready)

    with items_file.open("r", encoding="utf-8") as stream:
        for line in stream:
            seen_rows += 1
            if seen_rows > count:
                raise ValueError("Preview file has extra rows")
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError(f"Malformed preview row {seen_rows}")
            if raw.get("conflict") is True:
                if not skip_conflicts:
                    raise ValueError("Preview contains conflicting rows")
                conflict_rows += 1
                continue
            if raw.get("conflict") is not False:
                raise ValueError(f"Invalid preview conflict marker at row {seen_rows}")

            ready_rows += 1
            if ready_rows <= persisted:
                # Compare previously committed rows in bounded DB chunks:
                # restart does not trust a changed preview artifact.
                if (ready_rows - 1) % INSERT_BATCH_SIZE == 0:
                    with session_factory() as session:
                        existing_chunk = {
                            seq: (src, target, size)
                            for seq, src, target, size in session.execute(
                                select(
                                    BatchPlanItem.sequence, BatchPlanItem.source_path,
                                    BatchPlanItem.target_path, BatchPlanItem.expected_size,
                                ).where(
                                    BatchPlanItem.plan_id == plan_id,
                                    BatchPlanItem.sequence >= ready_rows,
                                    BatchPlanItem.sequence < ready_rows + INSERT_BATCH_SIZE,
                                )
                            ).all()
                        }
                actual = existing_chunk.get(ready_rows)
                if actual != (raw.get("source"), raw.get("target"), raw.get("expected_size")):
                    raise ValueError("Preview changed since last committed batch; cannot resume")
                folded = str(actual[1]).casefold()
            else:
                item = _validated_move(raw, settings, sequence=ready_rows)
                folded = item["target_path"].casefold()
                item["plan_id"] = plan_id
                staged.append(item)

            if folded in seen_targets:
                raise ValueError("Duplicate target in media Plan preview")
            seen_targets.add(folded)
            if len(staged) >= INSERT_BATCH_SIZE:
                _save_batch()

    if seen_rows != count or ready_rows != ready or conflict_rows != conflicts:
        raise ValueError("Preview row counts changed; refusing partial Plan")
    _save_batch()
    if inserted != ready:
        raise ValueError("Unfinished media Plan after final batch")

    return _published_result(
        session_factory, plan_id=plan_id, job_id=job_id, worker_id=worker_id,
    )
