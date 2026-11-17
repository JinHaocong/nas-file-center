"""Background read-only MediaPackage package previews and bounded pagination.

The job performs *no* mutation under DATA_MOUNT. Only 0600 report artifacts
under CONFIG_DIR are created. No Move Plan is exposed by these endpoints.
"""
from __future__ import annotations

import itertools
import json
import os
import time
from pathlib import Path

from sqlalchemy import func, select, text
from app.batch.media_package_report_lifecycle import next_media_package_job_id
from app.batch.media_package_organizer import (
    _validate_scope, iter_media_package_packages, preview_media_package_package,
)
from app.config import Settings
from app.models import WorkJob
from app.tasks.handlers_base import TaskHandler, register_handler
from app.tasks.context import JobContext

PREVIEW_KIND = "media_package-package-preview"
ACTIVE_STATUSES = ("queued", "running", "paused", "cancel_requested")
PAGE_INDEX_STRIDE = 128
MAX_QUEUED_PREVIEWS = 3


def _root(settings: Settings) -> Path:
    # Scope is supplied privately at deployment time and cannot be widened
    # or inferred from a user-selected path.
    configured = settings.media_package_root
    if configured is None:
        raise ValueError("MEDIA_PACKAGE_ROOT is not configured")
    raw = Path(configured).expanduser()
    if not raw.is_absolute():
        raise ValueError("MEDIA_PACKAGE_ROOT must be an absolute path")
    from app.path_safety import require_allowed_path, require_unreserved_path
    return require_unreserved_path(
        require_allowed_path(raw, settings.allowed_roots),
        settings.quarantine_root,
    )


def _files(settings: Settings, job_id: int) -> tuple[Path, Path, Path]:
    if not isinstance(job_id, int) or job_id < 1:
        raise ValueError("Invalid MediaPackage preview job id")
    root = settings.reports_dir / "media_package-previews"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return (
        root / f"{job_id}.packages.jsonl",
        root / f"{job_id}.packages.idx",
        root / f"{job_id}.summary.json",
    )


def _create_private(path: Path):
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    return os.fdopen(fd, "w", encoding="utf-8")


def _read_page(data: Path, index: Path, *, page: int, size: int) -> list[dict]:
    offset = (page - 1) * size
    base = 0
    byte_position = 0
    if index.is_file():
        with index.open("r", encoding="utf-8") as hints:
            for line in hints:
                row, pos = (int(part) for part in line.rstrip("\n").split("\t", 1))
                if row > offset:
                    break
                if row < base or pos < byte_position:
                    raise ValueError("MediaPackage preview index is corrupt")
                base, byte_position = row, pos
    with data.open("r", encoding="utf-8") as stream:
        stream.seek(byte_position)
        return [json.loads(line) for line in
                itertools.islice(stream, offset - base, offset - base + size)]


def _read_filtered_page(data: Path, *, page: int, size: int, status: str) -> tuple[list[dict], int]:
    """Filter the complete frozen report before applying pagination."""
    offset = (page - 1) * size
    rows: list[dict] = []
    matched = 0
    with data.open("r", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record.get("status") != status:
                continue
            if offset <= matched < offset + size:
                rows.append(record)
            matched += 1
    return rows, matched


def enqueue_media_package_preview(session_factory, settings: Settings, *, selection: str) -> dict:
    chosen, _ = _validate_scope(
        selection, media_package_root=_root(settings),
        allowed_roots=settings.allowed_roots,
        quarantine_root=settings.quarantine_root,
    )
    with session_factory() as session:
        # Serialize ID allocation with all other SQLite task inserts.
        session.execute(text("BEGIN IMMEDIATE"))
        active = session.scalar(select(func.count(WorkJob.id)).where(
            WorkJob.kind == PREVIEW_KIND, WorkJob.status.in_(ACTIVE_STATUSES),
        )) or 0
        if active >= MAX_QUEUED_PREVIEWS:
            raise ValueError("Too many MediaPackage previews are active; cancel or finish one first")
        job = WorkJob(
            id=next_media_package_job_id(session, settings),
            kind=PREVIEW_KIND, status="queued",
            progress_current=0, progress_total=0,
            progress_message="等待 Worker 扫描 MediaPackage 资源包",
            state_json=json.dumps({"selection": str(chosen)}, ensure_ascii=False),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return {"job_id": int(job.id), "status": job.status}


def get_media_package_preview(session_factory, settings: Settings, job_id: int, *,
                       page: int = 1, page_size: int = 25, status_filter: str = "all") -> dict:
    if status_filter not in {"all", "ready", "blocked", "already_organized", "skipped"}:
        raise ValueError("Invalid MediaPackage preview status filter")
    if not 1 <= page or not 1 <= page_size <= 100:
        raise ValueError("Invalid MediaPackage preview pagination")
    with session_factory() as session:
        job = session.get(WorkJob, job_id)
        if job is None or job.kind != PREVIEW_KIND:
            raise KeyError(job_id)
        status, error = job.status, job.error_text
        state = json.loads(job.state_json or "{}")
        checkpoint = json.loads(job.checkpoint_json or "{}")
        progress = {
            "current": int(job.progress_current or 0),
            "total": int(job.progress_total or 0),
            "message": job.progress_message,
            "current_package": checkpoint.get("current_package", ""),
        }

    summary = None
    packages = []
    if status == "completed":
        data, index, summary_path = _files(settings, job_id)
        if not all(path.is_file() for path in (data, index, summary_path)):
            raise ValueError("Completed MediaPackage preview artifacts are incomplete; scan again")
        with summary_path.open("r", encoding="utf-8") as stream:
            summary = json.load(stream)
        if status_filter == "all":
            packages = _read_page(data, index, page=page, size=page_size)
            filtered_total = summary["package_count"]
        else:
            packages, filtered_total = _read_filtered_page(
                data, page=page, size=page_size, status=status_filter,
            )
    return {
        "job_id": job_id, "status": status, "error": error,
        "selection": state.get("selection", ""),
        "progress": progress, "summary": summary,
        "packages": packages, "page": page, "page_size": page_size,
        "filtered_total": filtered_total if status == "completed" else 0,
        "read_only": True,
    }


@register_handler
class MediaPackagePreviewHandler(TaskHandler):
    job_type = PREVIEW_KIND
    supports_cancel = True
    supports_retry = False
    supports_pause = False
    # Restart uses a fresh scan. Do not assert safe resume until a durable,
    # consistency-checked per-package checkpoint protocol is implemented.
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        state = json.loads(job.state_json or "{}")
        selection = state.get("selection")
        if not isinstance(selection, str):
            raise ValueError("MediaPackage preview requires a literal selection path")
        _validate_scope(
            selection, media_package_root=_root(settings),
            allowed_roots=settings.allowed_roots,
            quarantine_root=settings.quarantine_root,
        )

        data, index, summary = _files(settings, int(job.id))
        staged = [path.with_name(path.name + ".staging") for path in (data, index, summary)]
        # A reused/stale report path is evidence, not disposable scratch.
        # Never erase it merely because a new preview uses the same task ID.
        for path in (*staged, data, index, summary):
            if os.path.lexists(path):
                raise ValueError(
                    f"MediaPackage preview report already exists; preserve for review: {path}"
                )
        seen = ready = blocked = skipped = already_organized = files_seen = changes = 0
        renamed = automatically_resolved = 0
        start = last_checkpoint = time.monotonic()
        try:
            with _create_private(staged[0]) as out, _create_private(staged[1]) as offsets:
                for package in iter_media_package_packages(
                    selection, media_package_root=_root(settings),
                    allowed_roots=settings.allowed_roots,
                    quarantine_root=settings.quarantine_root,
                ):
                    # Invalid, changing or unreadable packages are presented as
                    # blocked. An unsafe discovery scope instead fails closed.
                    try:
                        record = preview_media_package_package(
                            package, media_package_root=_root(settings),
                            allowed_roots=settings.allowed_roots,
                            quarantine_root=settings.quarantine_root,
                            max_rows=10,
                        )
                    except (ValueError, OSError) as exc:
                        record = {
                            "package": str(package), "status": "blocked",
                            "reason": "scan_error", "total_files": 0,
                            "totals": {"P": 0, "V": 0, "Other": 0},
                            "groups": [], "sample_moves": [],
                            "conflicts": [{"reason": "scan_error", "detail": str(exc)[:500]}],
                            "total_proposals": 0, "needed_moves": 0,
                            "truncated": False, "read_only": True,
                        }
                    if seen % PAGE_INDEX_STRIDE == 0:
                        offsets.write(f"{seen}\t{out.tell()}\n")
                    out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                    seen += 1
                    status = record["status"]
                    ready += status == "ready"
                    blocked += status == "blocked"
                    skipped += status == "skipped"
                    already_organized += status == "already_organized"
                    files_seen += int(record.get("total_files", 0))
                    changes += int(record.get("needed_moves", 0))
                    renamed += int(record.get("renamed_count", 0))
                    automatically_resolved += int(record.get("resolved_collision_count", 0))
                    now = time.monotonic()
                    if seen == 1 or seen % 25 == 0 or now - last_checkpoint >= 0.8:
                        context.checkpoint(
                            progress_current=seen,
                            progress_message=f"已预览 {seen:,} 个资源包；当前 {str(package)[-140:]}",
                            checkpoint_data={
                                "schema_version": 1, "current_package": str(package)[-500:],
                                "packages_scanned": seen, "file_count": files_seen,
                            },
                        )
                        last_checkpoint = now
                for stream in (out, offsets):
                    stream.flush()
                    os.fsync(stream.fileno())

            finished = {
                "package_count": seen, "ready_count": ready, "blocked_count": blocked,
                "skipped_count": skipped, "already_organized_count": already_organized,
                "file_count": files_seen, "needed_moves": changes,
                "renamed_count": renamed,
                "resolved_collision_count": automatically_resolved,
                "elapsed_seconds": round(time.monotonic() - start, 3),
            }
            with _create_private(staged[2]) as output:
                json.dump(finished, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            # Publish without overwriting another report that appeared after
            # the initial preflight. The summary remains the final commit marker.
            for staged_path, final_path in zip(staged, (data, index, summary)):
                os.link(staged_path, final_path, follow_symlinks=False)
                os.unlink(staged_path)
            context.checkpoint(
                progress_current=seen,
                progress_message=f"MediaPackage 预览完成：{seen:,} 包，待整理 {ready:,}，冲突 {blocked:,}",
                checkpoint_data={"schema_version": 1, "packages_scanned": seen, "finished": True},
            )
        except BaseException:
            # Preserve failed-preview evidence for diagnosis. A new task uses
            # another reserved ID; it must never erase these report artifacts.
            raise
