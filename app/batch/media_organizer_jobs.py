"""Recursive organizer previews and a resumable, one-confirmation Worker batch."""
from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import closing
from itertools import islice
from pathlib import Path

from sqlalchemy import func, select, text

from app.batch.media_organizer_link_intent import LinkIntent
from app.batch.media_organizer_planner import is_reserved_workspace
from app.batch.media_package_report_lifecycle import next_media_package_job_id
from app.config import Settings
from app.models import TaskEvent, WorkJob, utcnow
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler
from app.tasks.logging import log_task_event

PREVIEW_KIND = "media-organizer-preview"
BATCH_KIND = "media-organizer-batch"
FLOW = "recursive-batch-v1"
RESULT_EVENT = "media_organizer_unit_result"
ACTIVE = ("queued", "running", "paused", "cancel_requested")
PREVIEW_STATUSES = ("ready", "blocked", "already_organized", "skipped")
RESULT_STATUSES = ("success", "skipped", "conflict", "failed")


def _selection(value: str, settings: Settings) -> Path:
    chosen = Path(value)
    if (not chosen.is_absolute() or "\0" in value or os.path.normpath(value) != value
            or not any(chosen.is_relative_to(root) for root in settings.allowed_roots)
            or chosen.is_relative_to(settings.quarantine_root) or is_reserved_workspace(chosen)):
        raise ValueError("请选择允许访问的目录")
    return chosen


def _job(session, kind: str, job_id: int) -> tuple[WorkJob, dict]:
    job = session.get(WorkJob, job_id)
    if job is None or job.kind != kind:
        raise KeyError(job_id)
    state = json.loads(job.state_json or "{}")
    if state.get("organizer_flow") != FLOW:
        raise KeyError(job_id)
    return job, state


def _batch_for_preview(session, preview_id: int) -> WorkJob | None:
    return session.scalar(select(WorkJob).where(
        WorkJob.kind == BATCH_KIND,
        func.json_extract(WorkJob.state_json, "$.organizer_flow") == FLOW,
        func.json_extract(WorkJob.state_json, "$.preview_job_id") == preview_id,
    ).order_by(WorkJob.id).limit(1))


def _new_job(session, settings: Settings, kind: str, state: dict, *, units: int = 0) -> WorkJob:
    job = WorkJob(
        id=next_media_package_job_id(session, settings), kind=kind,
        status="queued", progress_current=0, progress_total=units,
        progress_message="等待扫描" if kind == PREVIEW_KIND else "等待整理",
        state_json=json.dumps({"organizer_flow": FLOW, **state}, ensure_ascii=False),
        checkpoint_json=json.dumps({"schema_version": 1}),
    )
    session.add(job)
    session.commit()
    return job


def _receipt(job: WorkJob) -> dict:
    return {"job_id": str(job.id), "status": job.status}


def _progress(job: WorkJob) -> dict:
    return {"current": job.progress_current, "total": job.progress_total,
            "message": job.progress_message}


def _report_dir(settings: Settings, job_id: int) -> Path:
    return settings.reports_dir / "organizer-v1-previews" / str(job_id)


def _plan_summary(report: Path) -> dict:
    with closing(_rows(report / "summary.json")) as source:
        summary = next(source, None)
        if not isinstance(summary, dict):
            raise ValueError("目录预览报告不完整")
        return summary


def _rows(path: Path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "r", encoding="utf-8") as source:
        for line in source:
            yield json.loads(line)


def _report_file(path: Path):
    # API and Worker may use different UIDs with the same primary group.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    try:
        os.fchmod(fd, 0o640)
        return os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise


def _write_json(stream, data: dict) -> None:
    stream.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def _persist(stream) -> None:
    stream.flush()
    os.fsync(stream.fileno())


def enqueue_preview(session_factory, settings: Settings, selection: str) -> dict:
    chosen = _selection(selection, settings)
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        active = session.scalar(select(func.count(WorkJob.id)).where(
            WorkJob.kind == PREVIEW_KIND, WorkJob.status.in_(ACTIVE),
            func.json_extract(WorkJob.state_json, "$.organizer_flow") == FLOW,
        ))
        if active >= 3:
            raise ValueError("当前扫描任务较多，请稍后重试")
        return _receipt(_new_job(session, settings, PREVIEW_KIND, {"selection": str(chosen)}))


def get_preview(session_factory, settings: Settings, job_id: int, *,
                page: int, page_size: int, status_filter: str) -> dict:
    if status_filter not in ("all", *PREVIEW_STATUSES):
        raise ValueError("无效的预览状态")
    with session_factory() as session:
        job, state = _job(session, PREVIEW_KIND, job_id)
        batch = _batch_for_preview(session, job_id)
        result = {
            **_receipt(job), "selection": state["selection"], "error": job.error_text,
            "progress": _progress(job), "batch_job_id": str(batch.id) if batch else None,
            "execution_enabled": settings.allow_mutation and settings.allow_delete,
            "summary": None, "units": [], "filtered_total": 0, "read_only": True,
            "page": page, "page_size": page_size,
        }
    if result["status"] == "completed":
        report = _report_dir(settings, job_id)
        result["summary"] = _plan_summary(report)
        offset = (page - 1) * page_size
        for unit in _rows(report / "units.jsonl"):
            if status_filter != "all" and unit["status"] != status_filter:
                continue
            if offset <= result["filtered_total"] < offset + page_size:
                result["units"].append(unit)
            result["filtered_total"] += 1
    return result


def get_mapping(session_factory, settings: Settings, job_id: int, mapping_id: str, *,
                page: int, page_size: int) -> dict:
    if len(mapping_id) != 64 or any(c not in "0123456789abcdef" for c in mapping_id):
        raise KeyError(mapping_id)
    with session_factory() as session:
        job, _ = _job(session, PREVIEW_KIND, job_id)
        if job.status != "completed":
            raise ValueError("预览尚未完成")
    report = _report_dir(settings, job_id)
    path = report / f"{mapping_id}.jsonl"
    unit = next((row for row in _rows(report / "units.jsonl")
                 if row.get("mapping_id") == mapping_id), None)
    if unit is None:
        raise KeyError(mapping_id)
    offset = (page - 1) * page_size
    return {
        "job_id": str(job_id), "mapping_id": mapping_id, "page": page, "page_size": page_size,
        "total_moves": unit["total_proposals"], "read_only": True,
        "moves": list(islice(_rows(path), offset, offset + page_size)),
    }


def enqueue_batch(session_factory, settings: Settings, preview_id: int) -> dict:
    if not (settings.allow_mutation and settings.allow_delete):
        raise PermissionError("当前环境未开启整理权限")
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        preview, state = _job(session, PREVIEW_KIND, preview_id)
        existing = _batch_for_preview(session, preview_id)
        if existing is not None:
            return _receipt(existing)
        if preview.status != "completed":
            raise ValueError("请等待目录扫描完成")
        summary = _plan_summary(_report_dir(settings, preview_id))
        if summary["ready_count"] == 0:
            raise ValueError("没有可以整理的单元")
        return _receipt(_new_job(session, settings, BATCH_KIND, {
            "selection": state["selection"], "preview_job_id": preview_id,
        }, units=summary["unit_count"]))


def get_batch(session_factory, job_id: int, *, page: int, page_size: int) -> dict:
    with session_factory() as session:
        job, state = _job(session, BATCH_KIND, job_id)
        where = (TaskEvent.job_id == job_id, TaskEvent.event_type == RESULT_EVENT)
        status = func.json_extract(TaskEvent.context_json, "$.status")
        counts = dict(session.execute(select(status, func.count()).where(*where).group_by(status)).all())
        events = session.scalars(select(TaskEvent.context_json).where(*where).order_by(
            TaskEvent.id,
        ).offset((page - 1) * page_size).limit(page_size))
        return {
            **_receipt(job), "selection": state["selection"], "error": job.error_text,
            "preview_job_id": str(state["preview_job_id"]), "progress": _progress(job),
            "summary": {f"{name}_count": counts.get(name, 0) for name in RESULT_STATUSES},
            "items": [json.loads(event) for event in events], "filtered_total": sum(counts.values()),
            "page": page, "page_size": page_size,
        }


def _preview_row(record: dict, report: Path) -> dict:
    mapping = record.get("_mapping_items", []) if record["status"] == "ready" else []
    mapping_id = hashlib.sha256(record["unit"].encode()).hexdigest() if mapping else None
    if mapping_id is not None:
        with _report_file(report / f"{mapping_id}.jsonl") as stream:
            for move in mapping:
                _write_json(stream, {key: move[key] for key in ("source", "target", "target_name", "kind", "bytes")})
            _persist(stream)
    totals = record.get("totals", {})
    return {
        "unit": record["unit"], "status": record["status"], "reason": record.get("reason"),
        "operation": record.get("operation"), "organizer_mode": record.get("organizer_mode"),
        "totals": totals, "total_files": sum(totals.values()),
        "total_bytes": record.get("total_bytes", 0), "groups": record.get("groups", []),
        "needed_moves": record.get("actual_moves", 0),
        "renamed_count": record.get("renamed_count", 0),
        "wrapper_cleanup_count": len(record.get("wrapper_cleanup", [])),
        "total_proposals": len(mapping), "mapping_id": mapping_id,
        "sample_moves": mapping[:10], "truncated": len(mapping) > 10,
        "input_fingerprint": record.get("input_fingerprint"),
        "conflicts": record.get("conflicts", []), "read_only": True,
    }


@register_handler
class MediaOrganizerPreviewHandler(TaskHandler):
    job_type = PREVIEW_KIND
    supports_retry = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        from app.batch.media_organizer_planner import iter_organizing_previews

        state = json.loads(job.state_json)
        if state.get("organizer_flow") != FLOW:
            raise ValueError("历史预览需重新扫描")
        selection = _selection(state["selection"], settings)
        report = _report_dir(settings, job.id)
        report.parent.mkdir(mode=0o750, exist_ok=True)
        report.mkdir(mode=0o750)
        summary = dict.fromkeys([f"{status}_count" for status in PREVIEW_STATUSES], 0)
        summary.update(unit_count=0, file_count=0, needed_moves=0, renamed_count=0,
                       total_bytes=0, wrapper_cleanup_count=0, read_only=True,
                       totals={"P": 0, "V": 0, "Other": 0})
        last_check = time.monotonic()

        def check_cancelled() -> None:
            nonlocal last_check
            now = time.monotonic()
            if now - last_check >= 0.8:
                context.checkpoint()
                last_check = now

        with _report_file(report / "units.jsonl") as stream:
            for record in iter_organizing_previews(
                selection, allowed_roots=settings.allowed_roots, quarantine_root=settings.quarantine_root,
                media_package_root=settings.media_package_root, check_cancelled=check_cancelled,
                include_mapping=True,
            ):
                row = _preview_row(record, report)
                _write_json(stream, row)
                summary[f"{row['status']}_count"] += 1
                summary["unit_count"] += 1
                summary["file_count"] += row["total_files"]
                for key in ("needed_moves", "renamed_count", "total_bytes", "wrapper_cleanup_count"):
                    summary[key] += row[key]
                for kind in summary["totals"]:
                    summary["totals"][kind] += row["totals"].get(kind, 0)
                if summary["unit_count"] % 25 == 0:
                    context.checkpoint(progress_current=summary["unit_count"])
            _persist(stream)
        with _report_file(report / "summary.json") as stream:
            _write_json(stream, summary)
            _persist(stream)
        context.checkpoint(progress_current=summary["unit_count"], progress_total=summary["unit_count"],
                           progress_message="目录预览完成")


def _record_result(context: JobContext, ordinal: int, total: int, result: dict) -> None:
    from app.tasks.recovery import assert_active_worker_lease

    with context.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        now = utcnow()
        assert_active_worker_lease(session, context.worker_id, now=now)
        job = session.get(WorkJob, context.job_id)
        if job.status != "running" or job.progress_current != ordinal:
            raise ValueError("批量整理进度已经变化")
        job.progress_current = ordinal + 1
        job.progress_message = f"已处理 {ordinal + 1}/{total} 个整理单元"
        job.heartbeat_at = now
        log_task_event(session, job_id=job.id, event_type=RESULT_EVENT, message=job.progress_message,
                       context=result, timestamp=now)
        session.commit()


def _finish_unit(unit: dict, settings: Settings, path: Path, job_id: int, fence) -> tuple[str, str | None]:
    from app.batch.media_organizer_planner import preview_organizing_unit
    from app.batch.media_package_execution import (
        MediaPackageExecutionConflict, execute_frozen_manifest, load_frozen_manifest,
        prepare_organizer_manifest, save_frozen_manifest,
    )

    if unit["status"] == "blocked":
        return "conflict", unit["reason"] or "预览发现目标或目录冲突"
    if unit["status"] != "ready":
        return "skipped", unit["reason"]
    try:
        chosen = _selection(unit["unit"], settings)
        options = {
            "mode": unit["organizer_mode"], "allowed_roots": settings.allowed_roots,
            "media_package_root": settings.media_package_root, "quarantine_root": settings.quarantine_root,
        }
        if os.path.lexists(path):
            manifest = load_frozen_manifest(path, job_id=job_id, package=chosen)
            package_root = settings.media_package_root
            if (manifest.get("organizer_mode") != options["mode"]
                    or manifest.get("input_fingerprint") != unit["input_fingerprint"]
                    or manifest.get("media_package_root") != (str(package_root) if package_root else None)
                    or manifest.get("quarantine_root") != (str(settings.quarantine_root)
                                                           if settings.quarantine_root else None)):
                raise MediaPackageExecutionConflict("当前目录设置或冻结记录已变化")
        else:
            manifest = prepare_organizer_manifest(chosen, preview_record=unit, job_id=job_id, **options)
            fence()
            save_frozen_manifest(path, manifest)
        execute_frozen_manifest(
            manifest, lease_fence=fence, allow_fuse_compat=settings.media_package_fuse_compat_enabled,
            link_intent=LinkIntent(path.with_suffix(".link.json")),
        )
        fresh = preview_organizing_unit(chosen, include_items=True, **options)
        if fresh["status"] != "already_organized":
            raise MediaPackageExecutionConflict("整理后重新扫描时仍发现变更")
        expected = {row["final"]: row["identity"] for row in manifest["moves"]}
        live = {row["path"]: [row[key] for key in ("dev", "ino", "bytes", "mtime_ns")]
                for row in fresh["_snapshot_items"]}
        if live != expected:
            raise MediaPackageExecutionConflict("整理后文件与确认的预览记录不一致")
        return "success", None
    except (MediaPackageExecutionConflict, ValueError) as exc:
        return "conflict", str(exc)
    except OSError as exc:
        return "failed", str(exc)


@register_handler
class MediaOrganizerBatchHandler(TaskHandler):
    job_type = BATCH_KIND
    supports_cancel = False
    supports_retry = False
    supports_resume = True

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        from app.tasks.recovery import renew_and_assert_worker_lease

        if not (context.worker_id and settings.allow_mutation and settings.allow_delete):
            raise PermissionError("整理需要已授权的 Worker")
        state = json.loads(job.state_json)
        if state.get("organizer_flow") != FLOW:
            raise ValueError("未知的批量整理任务")
        selection = _selection(state["selection"], settings)
        with context.SessionLocal() as session:
            preview, bound = _job(session, PREVIEW_KIND, state["preview_job_id"])
            if preview.status != "completed" or bound["selection"] != str(selection):
                raise ValueError("目录预览与批量整理范围不一致")
        report = _report_dir(settings, state["preview_job_id"])
        folder = settings.reports_dir / "organizer-v1-executions" / str(job.id)

        def fence() -> None:
            renew_and_assert_worker_lease(context.SessionLocal, context.worker_id)

        for ordinal, unit in enumerate(_rows(report / "units.jsonl")):
            if ordinal < job.progress_current:
                continue
            if ordinal >= job.progress_total or not Path(unit["unit"]).is_relative_to(selection):
                raise ValueError("预览单元超出原确认范围")
            status, reason = _finish_unit(
                unit, settings, folder / f"{ordinal}.json", job.id, fence,
            )
            _record_result(context, ordinal, job.progress_total, {
                "unit": unit["unit"], "status": status, "reason": reason,
            })
        # A truncated/unpublished report must never look like a complete batch.
        with context.SessionLocal() as session:
            if session.get(WorkJob, job.id).progress_current != job.progress_total:
                raise ValueError("目录预览报告不完整")
