"""Recursive organizer previews and a resumable, one-confirmation Worker batch."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from contextlib import closing, nullcontext
from itertools import islice
from pathlib import Path
from unicodedata import normalize
from uuid import uuid4

from sqlalchemy import func, select, text

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_link_intent import LinkIntent
from app.batch.media_organizer_planner import is_reserved_workspace
from app.batch.media_package_organizer import APPEND_VIDEO_OPERATIONS, _validate_scope
from app.batch.media_package_report_lifecycle import next_media_package_job_id
from app.config import Settings
from app.execution.luolcy_assignment import LUOLCY_ASSIGNMENT_KIND
from app.models import TaskEvent, WorkJob, utcnow
from app.path_safety import validate_mutation_destination
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler
from app.tasks.logging import log_task_event

PREVIEW_KIND = "media-organizer-preview"
BATCH_KIND = "media-organizer-batch"
FLOW = "recursive-batch-v1"
RESULT_EVENT = "media_organizer_unit_result"
ACTIVE = ("queued", "running", "paused", "cancel_requested")
PREVIEW_STATUSES = ("ready", "blocked", "already_organized", "skipped", "needs_assignment")
RESULT_STATUSES = ("success", "skipped", "conflict", "failed")
RESULT_COMMIT_SIZE = 100
RESULT_COMMIT_INTERVAL = 0.8


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


def _loose_report(session_factory, settings: Settings, job_id: int, loose_id: str) -> tuple[dict, Path, Path]:
    """Bind a loose-file report ID to a completed preview and its original selection."""
    if len(loose_id) != 64 or any(c not in "0123456789abcdef" for c in loose_id):
        raise KeyError(loose_id)
    with session_factory() as session:
        job, state = _job(session, PREVIEW_KIND, job_id)
        if job.status != "completed":
            raise ValueError("预览尚未完成")
    report = _report_dir(settings, job_id)
    with closing(_rows(report / "units.jsonl")) as rows:
        unit = next((row for row in rows if row.get("loose_id") == loose_id), None)
    if unit is None or unit["status"] != "needs_assignment":
        raise KeyError(loose_id)
    return unit, report / f"loose-{loose_id}.jsonl", Path(state["selection"])


def get_loose_files(session_factory, settings: Settings, job_id: int, loose_id: str, *,
                    page: int, page_size: int) -> dict:
    """Read one page of real sources without exposing the filesystem identity fields."""
    unit, path, _ = _loose_report(session_factory, settings, job_id, loose_id)
    start = (page - 1) * page_size
    with closing(_rows(path)) as rows:
        header = next(rows, None)
        if not isinstance(header, dict):
            raise ValueError("散件预览报告不完整")
        files = []
        if start < unit["total_files"]:
            files = [{key: row[key] for key in ("source", "kind", "bytes")}
                     for row in islice(rows, start, start + page_size)]
    return {
        "job_id": str(job_id), "loose_id": loose_id, "author": unit["unit"],
        "page": page, "page_size": page_size, "total_files": unit["total_files"],
        "packages": list(header["packages"]), "files": files, "read_only": True,
    }


def _name_key(name: str) -> str:
    return normalize("NFC", name).casefold()


def _assignment_package(author: Path, author_fd: int, header: dict, name: str, *,
                        new_package: bool, settings: Settings) -> tuple[Path, list[int] | None]:
    if (not name or name in {".", ".."} or "/" in name or "\0" in name
            or (new_package and (name != name.strip() or "\\" in name or any(ord(char) < 32 for char in name)))):
        raise ValueError("请输入合法的资源包目录名")
    package = _selection(str(author / name), settings)
    target = validate_mutation_destination(package, settings.allowed_roots, settings.quarantine_root)
    if target != package:
        raise ValueError("目标资源包超出作者目录")
    if new_package:
        with os.scandir(author_fd) as entries:
            if any(_name_key(entry.name) == _name_key(name) for entry in entries):
                raise ValueError("新资源包名称已存在，请更换名称或选择现有资源包")
        return package, None
    expected = header["packages"].get(name)
    if expected is None:
        raise ValueError("请选择扫描时存在的同作者资源包")
    info = os.stat(name, dir_fd=author_fd, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode) or [info.st_dev, info.st_ino] != expected:
        raise ValueError("目标资源包已经变化，请重新扫描")
    return package, expected


def _assignment_moves(author: Path, author_fd: int, package: Path, package_fd: int | None,
                      rows: dict[str, dict], settings: Settings) -> list[dict]:
    """Recheck source identity and build only same-name, no-overwrite MOVE items."""
    with os.scandir(package_fd) if package_fd is not None else nullcontext(()) as entries:
        occupied = {_name_key(entry.name) for entry in entries}
    moves = []
    for path, snapshot in rows.items():
        source = _selection(path, settings)
        if source.parent != author:
            raise ValueError("只可归属作者目录的直属文件")
        info = os.stat(source.name, dir_fd=author_fd, follow_symlinks=False)
        identity = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
        if (not stat.S_ISREG(info.st_mode) or identity !=
                [snapshot[key] for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns")]):
            raise ValueError(f"源文件已经变化，请重新扫描：{source.name}")
        if _name_key(source.name) in occupied:
            raise ValueError(f"目标已存在同名文件：{source.name}")
        occupied.add(_name_key(source.name))
        target = _selection(str(package / source.name), settings)
        if target != validate_mutation_destination(target, settings.allowed_roots, settings.quarantine_root):
            raise ValueError("目标文件超出资源包目录")
        moves.append({
            "operation": "move", "source": path, "target": str(target),
            "expected_device": info.st_dev, "expected_inode": info.st_ino,
            "expected_size": info.st_size, "expected_mtime_ns": info.st_mtime_ns,
        })
    return moves


def create_assignment_draft(service, job_id: int, loose_id: str, *, sources: list[str],
                            package_name: str, new_package: bool) -> dict:
    """Create a MOVE draft from explicitly selected files in one Luolcy author report."""
    settings = service.settings
    unit, report, selection = _loose_report(service.SessionLocal, settings, job_id, loose_id)
    media_package_root = settings.media_package_root
    author = _selection(unit["unit"], settings)
    if media_package_root is None or not author.is_relative_to(selection):
        raise ValueError("作者目录超出原扫描范围")
    _, depth = _validate_scope(author, media_package_root=media_package_root,
                               allowed_roots=settings.allowed_roots, quarantine_root=settings.quarantine_root)
    if depth != 3:
        raise ValueError("只能从 Luolcy 的作者层生成归属草稿")
    selected = set(sources)
    if not selected or len(selected) != len(sources):
        raise ValueError("请选择不同的待归属文件")
    with closing(_rows(report)) as rows:
        header = next(rows, None)
        if not isinstance(header, dict):
            raise ValueError("散件预览报告不完整")
        matching = {row["source"]: row for row in rows if row["source"] in selected}
    if matching.keys() != selected:
        raise ValueError("所选文件不在此预览的待归属清单中")
    author_fd = _open_directory_nofollow(author)
    try:
        info = os.fstat(author_fd)
        if [info.st_dev, info.st_ino] != header["author_identity"]:
            raise ValueError("作者目录已经变化，请重新扫描")
        package, package_identity = _assignment_package(
            author, author_fd, header, package_name, new_package=new_package, settings=settings,
        )
        package_fd = None
        try:
            if package_identity is not None:
                package_fd = os.open(package.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=author_fd)
                info = os.fstat(package_fd)
                if [info.st_dev, info.st_ino] != package_identity:
                    raise ValueError("目标资源包已经变化，请重新扫描")
            moves = _assignment_moves(author, author_fd, package, package_fd, matching, settings)
        finally:
            if package_fd is not None:
                os.close(package_fd)
    finally:
        os.close(author_fd)
    plan = service.create_plan(
        name=f"散件归属 · {author.name} / {package.name}", kind=LUOLCY_ASSIGNMENT_KIND, items=moves,
        metadata={"luolcy_assignment": {
            "assignment_id": uuid4().hex, "preview_job_id": str(job_id),
            "author": str(author), "package": str(package),
            "author_identity": header["author_identity"], "package_identity": package_identity,
            "sources": [[row["source"], [row[key] for key in ("expected_device", "expected_inode",
                                                               "expected_size", "expected_mtime_ns")]] for row in moves],
        }},
    )
    return {"plan_id": str(plan.id), "status": plan.status, "expected_changes": plan.expected_changes}


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
    if record.get("operation") in APPEND_VIDEO_OPERATIONS:
        mapping = [move for move in mapping if move["source"] != move["target"]]
    mapping_id = hashlib.sha256(record["unit"].encode()).hexdigest() if mapping else None
    if mapping_id is not None:
        with _report_file(report / f"{mapping_id}.jsonl") as stream:
            for move in mapping:
                _write_json(stream, {key: move[key] for key in ("source", "target", "target_name", "kind", "bytes")})
            _persist(stream)
    loose_files = record.get("_loose_files", [])
    loose_id = hashlib.sha256(record["unit"].encode()).hexdigest() if loose_files else None
    if loose_id is not None:
        with _report_file(report / f"loose-{loose_id}.jsonl") as stream:
            _write_json(stream, {"packages": record["_packages"], "author_identity": record["_author_identity"]})
            for loose_file in loose_files:
                _write_json(stream, loose_file)
            _persist(stream)
    totals = record.get("totals", {})
    return {
        "unit": record["unit"], "status": record["status"], "reason": record.get("reason"),
        "operation": record.get("operation"), "organizer_mode": record.get("organizer_mode"),
        **({"local_media_kinds": record["local_media_kinds"]} if record.get("local_media_kinds") else {}),
        **({"whole_author": True} if record.get("whole_author") else {}),
        **({"luolcy_author_siblings": record["luolcy_author_siblings"]}
           if record.get("luolcy_author_siblings") else {}),
        "totals": totals, "total_files": sum(totals.values()),
        "total_bytes": record.get("total_bytes", 0), "groups": record.get("groups", []),
        "needed_moves": record.get("actual_moves", 0),
        "renamed_count": record.get("renamed_count", 0),
        "wrapper_cleanup_count": len(record.get("wrapper_cleanup", [])),
        "total_proposals": len(mapping), "mapping_id": mapping_id,
        **({"loose_id": loose_id} if loose_id is not None else {}),
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


def _record_results(context: JobContext, ordinal: int, total: int, results: list[dict]) -> None:
    """Commit a contiguous run of results and advance its durable resume position."""
    from app.tasks.recovery import assert_active_worker_lease

    end = ordinal + len(results)
    with context.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        now = utcnow()
        assert_active_worker_lease(session, context.worker_id, now=now)
        job = session.get(WorkJob, context.job_id)
        if (job is None or job.status != "running" or job.progress_current != ordinal
                or job.progress_total != total or end > total):
            raise ValueError("批量整理进度已经变化")
        job.progress_current = end
        job.progress_message = f"已处理 {end}/{total} 个整理单元"
        job.heartbeat_at = now
        for index, result in enumerate(results, start=ordinal + 1):
            log_task_event(session, job_id=job.id, event_type=RESULT_EVENT,
                           message=f"已处理 {index}/{total} 个整理单元", context=result, timestamp=now)
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
        local_media_kinds = tuple(unit.get("local_media_kinds", ()))
        whole_author = unit.get("whole_author", False)
        options = {
            "mode": unit["organizer_mode"], "allowed_roots": settings.allowed_roots,
            "media_package_root": settings.media_package_root, "quarantine_root": settings.quarantine_root,
        }
        if os.path.lexists(path):
            manifest = load_frozen_manifest(path, job_id=job_id, package=chosen)
            package_root = settings.media_package_root
            if (manifest.get("organizer_mode") != options["mode"]
                    or tuple(manifest.get("local_media_kinds", ())) != local_media_kinds
                    or manifest.get("whole_author", False) != whole_author
                    or manifest.get("luolcy_author_siblings", {}) != unit.get("luolcy_author_siblings", {})
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
        if options["mode"] == "luolcy" and whole_author:
            # The executor verified the exact frozen files and buckets at the author root.
            return "success", None
        fresh = preview_organizing_unit(
            chosen, include_items=True, local_media_kinds=local_media_kinds, whole_author=whole_author, **options,
        )
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
        total = job.progress_total
        next_ordinal = job.progress_current
        if not 0 <= next_ordinal <= total:
            raise ValueError("批量整理进度已经变化")
        pending: list[dict] = []
        last_commit = time.monotonic()

        def fence() -> None:
            renew_and_assert_worker_lease(context.SessionLocal, context.worker_id)

        def commit_pending() -> None:
            nonlocal next_ordinal, last_commit
            if pending:
                _record_results(context, next_ordinal, total, pending)
                next_ordinal += len(pending)
                pending.clear()
                last_commit = time.monotonic()

        count = 0
        with closing(_rows(report / "units.jsonl")) as units:
            for count, unit in enumerate(units, start=1):
                ordinal = count - 1
                if ordinal < next_ordinal:
                    continue
                if ordinal >= total or not Path(unit["unit"]).is_relative_to(selection):
                    commit_pending()
                    raise ValueError("预览单元超出原确认范围")
                ready = unit["status"] == "ready"
                if ready:
                    # Checkpoint the prefix before starting a frozen filesystem operation.
                    commit_pending()
                status, reason = _finish_unit(unit, settings, folder / f"{ordinal}.json", job.id, fence)
                pending.append({"unit": unit["unit"], "status": status, "reason": reason})
                if (ready or len(pending) >= RESULT_COMMIT_SIZE
                        or time.monotonic() - last_commit >= RESULT_COMMIT_INTERVAL):
                    commit_pending()
        commit_pending()
        # A truncated/unpublished report must never look like a complete batch.
        with context.SessionLocal() as session:
            saved = session.get(WorkJob, job.id)
            if count != total or saved is None or saved.progress_current != total or saved.progress_total != total:
                raise ValueError("目录预览报告不完整")
