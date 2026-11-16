"""Durable, paginated media-sort previews and observable Plan lifecycle jobs.

All filesystem scans are read-only and run on the existing single-owner Worker.
Preview artifacts live in CONFIG_DIR/reports (never in a selected NAS directory).
Actual moves continue to require an ordinary frozen, validated Move Plan.
"""
from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_sort import preview_media_sort
from app.config import Settings
from app.models import BatchPlan, BatchPlanItem, WorkJob
from app.path_safety import require_allowed_path, require_unreserved_path
from app.tasks.handlers_base import TaskHandler, register_handler
from app.tasks.context import JobContext

PREVIEW_KIND = "media-sort-preview"
GENERATE_KIND = "media-sort-plan"
STAGE_KIND = "media-sort-plan-stage"
ACTIVE_STATUSES = ("queued", "running", "paused", "cancel_requested")
MAX_PLAN_ITEMS = 300_000
PAGE_INDEX_STRIDE = 256  # at most 255 JSONL rows skipped for deep pages


def _folder(settings: Settings) -> Path:
    folder = settings.reports_dir / "media-sort-previews"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def _paths(settings: Settings, job_id: int) -> tuple[Path, Path, Path]:
    if not isinstance(job_id, int) or job_id <= 0:
        raise ValueError("Invalid media preview job id")
    folder = _folder(settings)
    return (
        folder / f"{job_id}.items.jsonl",
        folder / f"{job_id}.skipped.jsonl",
        folder / f"{job_id}.summary.json",
    )


def _write_new(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    return os.fdopen(fd, "w", encoding="utf-8")


def _index_path(path: Path) -> Path:
    return path.with_name(path.name + ".idx")


def _read_page(path: Path, offset: int, page_size: int) -> list[dict]:
    # Sparse byte offsets are produced by the same Worker writing the JSONL.
    # Historic previews without an index use the original safe linear reader.
    row_base = 0
    byte_pos = 0
    index_file = _index_path(path)
    if index_file.is_file():
        try:
            with index_file.open("r", encoding="utf-8") as index:
                for line in index:
                    raw_row, raw_pos = line.rstrip("\n").split("\t", 1)
                    candidate_row, candidate_pos = int(raw_row), int(raw_pos)
                    if candidate_row > offset:
                        break
                    if (candidate_row < row_base or candidate_row < 0
                            or candidate_pos < byte_pos):
                        raise ValueError("Invalid preview page index ordering")
                    row_base, byte_pos = candidate_row, candidate_pos
        except (OSError, ValueError):
            # Index is only a speed hint; it must never influence correctness.
            row_base, byte_pos = 0, 0
    with path.open("r", encoding="utf-8") as stream:
        if byte_pos:
            stream.seek(byte_pos)
        return [
            json.loads(line) for line in
            itertools.islice(stream, offset - row_base, offset - row_base + page_size)
        ]


def enqueue_media_preview(session_factory, settings: Settings, *, parent: str,
                          recursive: bool, smart_skip: bool) -> dict:
    raw = Path(parent).expanduser()
    if not raw.is_absolute() or raw.is_symlink():
        raise ValueError("Selected parent must be an absolute non-symlink directory")
    safe = require_unreserved_path(
        require_allowed_path(raw, settings.allowed_roots), settings.quarantine_root
    )
    if not safe.is_dir():
        raise ValueError("Selected parent directory does not exist")
    fd = _open_directory_nofollow(safe)
    os.close(fd)
    with session_factory() as session:
        active = session.scalar(select(func.count(WorkJob.id)).where(
            WorkJob.kind == PREVIEW_KIND, WorkJob.status.in_(ACTIVE_STATUSES)
        )) or 0
        if active >= 4:
            raise ValueError("已有过多媒体预览任务，请先完成或取消现有任务")
        job = WorkJob(
            kind=PREVIEW_KIND, status="queued", progress_current=0, progress_total=0,
            progress_message="等待 Worker 开始扫描",
            state_json=json.dumps({"parent": str(safe), "recursive": recursive,
                                   "smart_skip": smart_skip}, ensure_ascii=False),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return {"job_id": int(job.id), "status": job.status}


def get_media_preview(session_factory, settings: Settings, job_id: int, *,
                      page: int = 1, page_size: int = 25, skip_page: int = 1,
                      skip_page_size: int = 25) -> dict:
    with session_factory() as session:
        job = session.get(WorkJob, job_id)
        if job is None or job.kind != PREVIEW_KIND:
            raise KeyError(job_id)
        status = job.status
        error = job.error_text
        state = json.loads(job.state_json or "{}")
        checkpoint = json.loads(job.checkpoint_json or "{}")
        progress = {
            "current": job.progress_current or 0,
            "total": job.progress_total or 0,
            "message": job.progress_message,
            "scanned_directories": checkpoint.get("scanned_directories", 0),
            "scanned_entries": checkpoint.get("scanned_entries", 0),
            "candidate_count": checkpoint.get("candidate_count", 0),
            "skipped_directory_count": checkpoint.get("skipped_directory_count", 0),
            "current_directory": checkpoint.get("current_directory", ""),
        }
    summary: dict | None = None
    items: list[dict] = []
    skipped: list[dict] = []
    if status == "completed":
        items_file, skips_file, summary_file = _paths(settings, job_id)
        if not all(p.is_file() for p in (items_file, skips_file, summary_file)):
            raise ValueError("Completed media preview artifacts are missing; run a new preview")
        with summary_file.open("r", encoding="utf-8") as stream:
            summary = json.load(stream)
        items = _read_page(items_file, (page - 1) * page_size, page_size)
        skipped = _read_page(skips_file, (skip_page - 1) * skip_page_size, skip_page_size)

    return {
        "job_id": job_id, "status": status, "error": error, "progress": progress,
        "parent": state.get("parent", ""),
        "recursive": state.get("recursive", False),
        "smart_skip": state.get("smart_skip", True),
        "summary": summary, "items": items, "skipped_directories": skipped,
        "page": page, "page_size": page_size, "skip_page": skip_page,
        "skip_page_size": skip_page_size,
    }


def enqueue_media_plan(session_factory, settings: Settings, job_id: int) -> dict:
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        preview = session.get(WorkJob, job_id)
        if preview is None or preview.kind != PREVIEW_KIND:
            raise KeyError(job_id)
        if preview.status != "completed":
            raise ValueError("Media preview must finish before generating a Plan")
        _, _, summary_file = _paths(settings, job_id)
        if not summary_file.is_file():
            raise ValueError("Preview results were removed; please preview again")
        with summary_file.open("r", encoding="utf-8") as stream:
            summary = json.load(stream)
        if not 0 < int(summary.get("count", 0)) <= MAX_PLAN_ITEMS:
            raise ValueError("No valid media files, or too many items for one Plan")
        if int(summary.get("conflict_count", 0)) > 0:
            raise ValueError("Preview contains conflicting paths; fix them first")
        # A completed job is also returned to prevent duplicate plans from
        # browser retries or simultaneous clicks.
        previous = session.scalar(
            select(WorkJob).where(
                WorkJob.kind == GENERATE_KIND,
                func.json_extract(WorkJob.state_json, "$.preview_job_id") == job_id,
            ).order_by(WorkJob.id.desc()).limit(1)
        )
        if previous is not None and previous.status in (*ACTIVE_STATUSES, "completed"):
            return {"job_id": previous.id, "status": previous.status}
        work = WorkJob(
            kind=GENERATE_KIND, status="queued",
            progress_current=0, progress_total=0,
            progress_message="等待 Worker 生成移动计划",
            state_json=json.dumps({"preview_job_id": job_id}),
        )
        session.add(work)
        session.commit()
        session.refresh(work)
        return {"job_id": int(work.id), "status": work.status}


def get_media_plan_job(session_factory, job_id: int) -> dict:
    with session_factory() as session:
        job = session.get(WorkJob, job_id)
        if job is None or job.kind != GENERATE_KIND:
            raise KeyError(job_id)
        state = json.loads(job.state_json or "{}")
        return {
            "job_id": int(job.id), "status": job.status, "error": job.error_text,
            "plan_id": state.get("plan_id"),
            "progress": {"current": job.progress_current or 0, "total": job.progress_total or 0,
                         "message": job.progress_message},
        }


def enqueue_plan_stage(session_factory, plan_id: int, stage: str) -> dict:
    if stage not in {"freeze", "validate"}:
        raise ValueError("Unsupported stage")
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        plan = session.get(BatchPlan, plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if plan.kind != "media-sort":
            raise ValueError("Background stage is only supported for media-sort plans")
        valid = plan.status == "draft" if stage == "freeze" else plan.status in (
            "frozen", "ready", "partial", "stale"
        )
        if not valid:
            raise ValueError(f"Plan cannot {stage} while status={plan.status}")
        active = session.scalar(select(WorkJob.id).where(
            WorkJob.kind.in_((STAGE_KIND, "batch-plan-execute")),
            WorkJob.status.in_(ACTIVE_STATUSES),
            func.json_extract(WorkJob.state_json, "$.plan_id") == plan_id,
        ).limit(1))
        if active is not None:
            raise ValueError(f"Another Plan stage or execution task #{active} is already active")
        total = session.scalar(select(func.count(BatchPlanItem.id)).where(
            BatchPlanItem.plan_id == plan_id
        )) or 0
        job = WorkJob(kind=STAGE_KIND, status="queued", progress_total=total,
                      progress_message="等待 Worker 开始" + ("冻结" if stage == "freeze" else "校验"),
                      state_json=json.dumps({"plan_id": plan_id, "stage": stage}))
        session.add(job)
        session.commit()
        session.refresh(job)
        return {"job_id": job.id, "status": job.status, "stage": stage}


def get_plan_stage(session_factory, plan_id: int) -> dict | None:
    with session_factory() as session:
        plan = session.get(BatchPlan, plan_id)
        if plan is None:
            raise KeyError(plan_id)
        if plan.kind != "media-sort":
            return None
        job = session.scalar(
            select(WorkJob).where(
                WorkJob.kind == STAGE_KIND,
                func.json_extract(WorkJob.state_json, "$.plan_id") == plan_id,
            ).order_by(WorkJob.id.desc()).limit(1)
        )
        if job is None:
            return None
        state = json.loads(job.state_json or "{}")
        return {
            "job_id": job.id, "stage": state.get("stage"),
            "status": job.status, "error": job.error_text,
            "progress": {"current": job.progress_current or 0,
                         "total": job.progress_total or 0, "message": job.progress_message},
        }


def _worker_plan_service(settings: Settings, context: JobContext):
    """Use the Worker's existing DB sessions; do not replay startup reconciliation.

    The generic create/freeze/validate Plan methods need only settings and the
    SessionLocal factory. Instantiating the full API Service during a live Worker
    task would unnecessarily call init_db and startup reconciliation.
    """
    from app.service import FileCenterService
    service = object.__new__(FileCenterService)
    service.settings = settings
    service.SessionLocal = context.SessionLocal
    return service


@register_handler
class MediaSortPreviewHandler(TaskHandler):
    job_type = PREVIEW_KIND
    supports_cancel = True
    supports_retry = False
    supports_pause = False
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        payload = json.loads(job.state_json or "{}")
        items_file, skipped_file, summary_file = _paths(settings, int(job.id))
        items_index, skipped_index = _index_path(items_file), _index_path(skipped_file)
        for path in (items_file, skipped_file, summary_file, items_index, skipped_index):
            path.unlink(missing_ok=True)
        try:
            with (_write_new(items_file) as items, _write_new(skipped_file) as skipped,
                  _write_new(items_index) as item_offsets, _write_new(skipped_index) as skip_offsets):
                written_items = 0
                written_skipped = 0

                def _write_rows(batch: list[dict]) -> None:
                    nonlocal written_items
                    for row in batch:
                        if written_items % PAGE_INDEX_STRIDE == 0:
                            item_offsets.write(f"{written_items}\t{items.tell()}\n")
                        items.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                        written_items += 1

                def _write_skipped(batch: list[dict]) -> None:
                    nonlocal written_skipped
                    for row in batch:
                        if written_skipped % PAGE_INDEX_STRIDE == 0:
                            skip_offsets.write(f"{written_skipped}\t{skipped.tell()}\n")
                        skipped.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                        written_skipped += 1

                def _progress(facts: dict) -> None:
                    scanned = int(facts["scanned_entries"])
                    dirs = int(facts["scanned_directories"])
                    name = str(facts["current_directory"] or "")
                    context.checkpoint(
                        progress_current=scanned,
                        progress_message=f"已检查 {scanned:,} 项，{dirs:,} 个目录；当前 {name[-140:]}",
                        checkpoint_data={"schema_version": 1, **facts},
                    )

                summary = preview_media_sort(
                    payload["parent"], recursive=payload["recursive"],
                    smart_skip=payload["smart_skip"],
                    allowed_roots=settings.allowed_roots,
                    quarantine_root=settings.quarantine_root,
                    on_rows=_write_rows, on_skipped=_write_skipped,
                    on_progress=_progress, collect_items=False,
                )
                for stream in (items, skipped, item_offsets, skip_offsets):
                    stream.flush()
                    os.fsync(stream.fileno())
            with _write_new(summary_file) as stream:
                clean_summary = {key: value for key, value in summary.items()
                                 if key not in {"items", "skipped_directories"}}
                json.dump(clean_summary, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            context.checkpoint(
                progress_current=summary["scanned_entries"],
                progress_message=f"预览完成：{summary['count']:,} 个待移动文件，跳过 {summary['skipped_directory_count']:,} 个目录",
            )
        except BaseException:
            for path in (items_file, skipped_file, summary_file, items_index, skipped_index):
                path.unlink(missing_ok=True)
            raise


@register_handler
class MediaSortPlanHandler(TaskHandler):
    job_type = GENERATE_KIND
    supports_cancel = True
    supports_retry = False
    supports_pause = False
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        state = json.loads(job.state_json or "{}")
        preview_job_id = int(state["preview_job_id"])
        with context.SessionLocal() as session:
            preview_job = session.get(WorkJob, preview_job_id)
            if preview_job is None or preview_job.kind != PREVIEW_KIND or preview_job.status != "completed":
                raise ValueError("The selected media preview is no longer available")
        items_file, _, summary_file = _paths(settings, preview_job_id)
        with summary_file.open("r", encoding="utf-8") as stream:
            summary = json.load(stream)
        count = int(summary["count"])
        if not 0 < count <= MAX_PLAN_ITEMS or summary["conflict_count"] != 0:
            raise ValueError("Media sort preview is empty, conflicting or oversized")

        context.checkpoint(
            progress_current=0,
            progress_message=f"正在以安全事务批量生成 {count:,} 项 Move Plan（源文件不变）",
        )
        from app.batch.media_sort_bulk_plan import create_media_sort_bulk_plan

        # Stream and validate every row inside one atomic SQLite transaction.
        # No 300k-element Python/ORM list, no partially published draft Plan.
        plan = create_media_sort_bulk_plan(
            context.SessionLocal, settings,
            items_file=items_file, summary=summary, preview_job_id=preview_job_id,
        )
        with context.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            tracked = session.get(WorkJob, int(job.id))
            current = json.loads(tracked.state_json or "{}")
            current["plan_id"] = int(plan.id)
            tracked.state_json = json.dumps(current)
            session.commit()
        context.checkpoint(progress_current=count, progress_total=count,
                           progress_message=f"已创建移动计划 #{plan.id}，等待 Freeze → Validate → Execute")


@register_handler
class MediaSortPlanStageHandler(TaskHandler):
    job_type = STAGE_KIND
    supports_cancel = True
    supports_retry = False
    supports_pause = False
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        state = json.loads(job.state_json or "{}")
        plan_id = int(state["plan_id"])
        stage = state["stage"]
        if stage not in {"freeze", "validate"}:
            raise ValueError("Unknown media sort stage")
        service = _worker_plan_service(settings, context)
        with context.SessionLocal() as session:
            plan = session.get(BatchPlan, plan_id)
            if plan is None or plan.kind != "media-sort":
                raise ValueError("Media sort plan was removed or changed")
            count = session.scalar(select(func.count(BatchPlanItem.id)).where(
                BatchPlanItem.plan_id == plan_id
            )) or 0
        verb = "冻结" if stage == "freeze" else "校验"
        context.checkpoint(progress_current=0, progress_total=count,
                           progress_message=f"开始{verb} {count:,} 个文件")
        last_check_at = time.monotonic()
        last_checked_item = 0

        def _progress(current: int, total: int) -> None:
            nonlocal last_check_at, last_checked_item
            # A DB commit for every 25 files is expensive on NAS metadata
            # storage. Maintain a bounded cancellation/heartbeat interval:
            # check at most 250 items or ~0.75 seconds apart.
            now = time.monotonic()
            if (current == 1 or current == total
                    or current - last_checked_item >= 250
                    or now - last_check_at >= 0.75):
                # The service reports *before* examining this item. Don't
                # display 100% until the last item and DB commit both succeed.
                processed = max(0, current - 1)
                context.checkpoint(
                    progress_current=processed, progress_total=total,
                    progress_message=f"正在{verb}文件 {current:,}/{total:,}",
                )
                last_check_at = now
                last_checked_item = current

        if stage == "freeze":
            service.freeze_plan(plan_id, progress_callback=_progress)
        else:
            service.validate_plan(plan_id, progress_callback=_progress)
        context.checkpoint(progress_current=count, progress_total=count,
                           progress_message=f"{verb}结束，查看 Plan 状态")
