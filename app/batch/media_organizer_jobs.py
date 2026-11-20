"""WorkJob-backed, read-only semantic media preview with private reports."""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

from sqlalchemy import func, select, text

from app.batch.media_package_report_lifecycle import next_media_package_job_id
from app.batch.media_organizer_planner import _check_scope, _normalized_excluded_dir_names
from app.batch.media_organizer_reports import (
    mapping_identifier, read_preview_mapping, read_preview_page,
)
from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_scan import write_semantic_preview
from app.config import Settings
from app.batch.media_organizer_authority import execution_mode, check_api_eligibility
from app.config_sharing import (
    shared_config_gid, require_shared_file, require_shared_directory,
    ensure_shared_report_directory,
)
from app.models import WorkJob
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler

PREVIEW_KIND = "media-organizer-preview"
ACTIVE_STATUSES = ("queued", "running", "paused", "cancel_requested")
MAX_ACTIVE_PREVIEWS = 3


def mode_fields(mode: str) -> dict:
    if mode not in ("strict", "maintenance_window"):
        raise ValueError("invalid execution mode in job evidence")
    return {"execution_mode": mode, "assurance_level": mode,
            "requires_maintenance_window": mode == "maintenance_window",
            "namespace_exclusive_custody_proven": False}


def require_mode(settings, *records: dict) -> str:
    mode = execution_mode(settings)
    if any(record.get("execution_mode", "strict") != mode for record in records):
        raise ValueError("execution mode differs from the original approval or frozen evidence")
    return mode


def _excluded(settings: Settings) -> list[Path]:
    configured = getattr(settings, 'media_package_root', None)
    return [Path(configured)] if configured is not None else []


def _excluded_names(settings: Settings) -> list[str]:
    raw = getattr(settings, "media_organizer_excluded_dir_names_raw", "")
    if not isinstance(raw, str):
        raise ValueError("excluded directory names setting must be comma-separated text")
    values = [name.strip() for name in raw.split(",") if name.strip()]
    return sorted(_normalized_excluded_dir_names(values))


def _validate_selection(selection: str, settings: Settings) -> Path:
    chosen = Path(selection).expanduser()
    _check_scope(chosen, [Path(x) for x in settings.allowed_roots],
                 Path(settings.quarantine_root) if settings.quarantine_root is not None else None)
    excluded_names = set(_excluded_names(settings))
    if any(part.casefold() in excluded_names for part in chosen.parts):
        raise ValueError("selected unit is inside an excluded protected directory")
    raw = os.path.abspath(chosen)
    for root in _excluded(settings):
        excluded = os.path.abspath(root)
        if os.path.commonpath((raw, excluded)) == excluded:
            raise ValueError("Selection is inside a configured excluded root")
    return chosen


def report_files(settings: Settings, job_id: int) -> tuple[Path, Path]:
    if not isinstance(job_id, int) or job_id < 1:
        raise ValueError("invalid preview job id")
    # Share the existing media preview namespace with the audited global ID
    # allocator so task-history cleanup cannot silently recycle report IDs.
    root = settings.reports_dir / "media_package-previews"
    if root.is_symlink():
        raise ValueError("unsafe preview report directory")
    shared_gid = shared_config_gid()
    if shared_gid is None:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    else:
        # A shared API may only read from a preprovisioned trusted group root.
        # Existing private host directories cannot be chmod/chowned in place.
        require_shared_directory(settings.reports_dir, shared_gid)
        ensure_shared_report_directory(root, shared_gid)
    return root / f"{job_id}.semantic.jsonl", root / f"{job_id}.semantic.summary.json"


def _new_private(path: Path):
    gid = shared_config_gid()
    if gid is not None:
        require_shared_directory(path.parent, gid)
    mode = 0o640 if gid is not None else 0o600
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, mode)
    try:
        if gid is not None:
            created = os.fstat(fd)
            if (not os.path.isfile(path) or created.st_uid != os.geteuid()
                    or created.st_gid != gid):
                raise PermissionError("SHARED_CONFIG: preview evidence group mismatch")
            # Only a newly created file descriptor may be fchmod'd.
            os.fchmod(fd, mode)
        return os.fdopen(fd, 'w', encoding='utf-8')
    except BaseException:
        os.close(fd)
        raise


def mapping_report_root(settings: Settings, job_id: int) -> Path:
    data, _ = report_files(settings, job_id)
    return data.parent / f"{job_id}.semantic-maps"


def _create_mapping_report_directory(directory: Path, shared_gid: int | None) -> None:
    """Exclusively create the final mapping directory without directory rename.

    The directory name is job-ID scoped and is created with mkdirat/O_EXCL
    semantics before any mapping rows are written. The completed WorkJob plus
    the summary file linked last is the publication marker. If a Worker stops
    midway, the incomplete directory is preserved but cannot be read through
    the API because the job is not completed and no summary marker exists.
    """
    if shared_gid is not None:
        require_shared_directory(directory.parent, shared_gid)
    parent_fd = _open_directory_nofollow(directory.parent)
    mapping_fd = None
    try:
        parent_info = os.fstat(parent_fd)
        parent_named = os.stat(directory.parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or not stat.S_ISDIR(parent_named.st_mode)
            or (parent_info.st_dev, parent_info.st_ino)
            != (parent_named.st_dev, parent_named.st_ino)
        ):
            raise PermissionError("preview mapping parent identity changed")

        mode = 0o2770 if shared_gid is not None else 0o700
        # mkdirat is the atomic no-replace primitive needed here. Unlike
        # renameat2(RENAME_NOREPLACE), ZFuse supports exclusive directory
        # creation; an existing or raced destination is never adopted.
        os.mkdir(directory.name, mode=mode, dir_fd=parent_fd)
        mapping_fd = os.open(
            directory.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        created = os.fstat(mapping_fd)
        if (
            not stat.S_ISDIR(created.st_mode)
            or created.st_uid != os.geteuid()
            or (shared_gid is not None and created.st_gid != shared_gid)
        ):
            raise PermissionError("new preview mapping directory owner/group mismatch")
        # fchmod is limited to the inode created by the exclusive mkdir above.
        os.fchmod(mapping_fd, mode)
        created = os.fstat(mapping_fd)
        named = os.stat(directory.name, dir_fd=parent_fd, follow_symlinks=False)
        parent_after = os.stat(directory.parent, follow_symlinks=False)
        if (
            not stat.S_ISDIR(named.st_mode)
            or (created.st_dev, created.st_ino) != (named.st_dev, named.st_ino)
            or stat.S_IMODE(created.st_mode) != mode
            or (parent_info.st_dev, parent_info.st_ino)
            != (parent_after.st_dev, parent_after.st_ino)
        ):
            raise PermissionError("new preview mapping directory binding or mode changed")
        os.fsync(mapping_fd)
        os.fsync(parent_fd)
    finally:
        if mapping_fd is not None:
            os.close(mapping_fd)
        os.close(parent_fd)


def get_media_organizer_mapping(
    session_factory, settings: Settings, job_id: int, mapping_id: str, *,
    page: int = 1, page_size: int = 50,
) -> dict:
    """Return a bounded page of the exact full map for one completed preview unit."""
    if not isinstance(mapping_id, str) or len(mapping_id) != 64:
        raise ValueError("invalid mapping identity")
    with session_factory() as session:
        job = session.get(WorkJob, job_id)
        if job is None or job.kind != PREVIEW_KIND:
            raise KeyError(job_id)
        if job.status != "completed":
            raise ValueError("full mapping is available only after preview completion")
    data, summary = report_files(settings, job_id)
    if (data.is_symlink() or summary.is_symlink()
            or not data.is_file() or not summary.is_file()):
        raise ValueError("completed preview report is incomplete")
    shared_gid = shared_config_gid()
    if shared_gid is not None:
        require_shared_file(data, shared_gid, 0o640)
        require_shared_file(summary, shared_gid, 0o640)
    with summary.open("r", encoding="utf-8") as stream:
        mode = json.load(stream).get("execution_mode", "strict")
    found = False
    with data.open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("mapping_id") == mapping_id and row.get("status") == "ready":
                if mapping_identifier(row.get("unit", "")) != mapping_id:
                    raise ValueError("mapping identity does not match preview unit")
                found = True
                break
    if not found:
        raise KeyError(mapping_id)
    moves, total = read_preview_mapping(
        mapping_report_root(settings, job_id), mapping_id,
        page=page, page_size=page_size,
    )
    return {
        **mode_fields(mode), "job_id": job_id, "mapping_id": mapping_id,
        "page": page, "page_size": page_size, "total_moves": total,
        "moves": moves, "read_only": True,
    }


def enqueue_media_organizer_preview(session_factory, settings: Settings, *, selection: str) -> dict:
    chosen = _validate_selection(selection, settings)
    with session_factory() as session:
        session.execute(text('BEGIN IMMEDIATE'))
        active = session.scalar(select(func.count(WorkJob.id)).where(
            WorkJob.kind == PREVIEW_KIND, WorkJob.status.in_(ACTIVE_STATUSES))) or 0
        if active >= MAX_ACTIVE_PREVIEWS:
            raise ValueError('too many active media organizer previews')
        job = WorkJob(
            id=next_media_package_job_id(session, settings),
            kind=PREVIEW_KIND, status='queued', progress_current=0,
            progress_total=0, progress_message='等待 Worker 只读分析目录',
            state_json=json.dumps({'selection': str(chosen), 'execution_mode': execution_mode(settings),
                                   'maintenance_window_confirmed': False}, ensure_ascii=False),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return {'job_id': int(job.id), 'status': job.status, **mode_fields(execution_mode(settings))}


def get_media_organizer_preview(session_factory, settings: Settings, job_id: int, *,
                                page: int = 1, page_size: int = 25,
                                status_filter: str = 'all') -> dict:
    # Check pagination/filter even before the job completes.
    if not isinstance(page, int) or page < 1 or not 1 <= page_size <= 100:
        raise ValueError('invalid preview pagination')
    if status_filter not in ('all', 'ready', 'blocked', 'already_organized', 'skipped'):
        raise ValueError('invalid preview status filter')
    with session_factory() as session:
        job = session.get(WorkJob, job_id)
        if job is None or job.kind != PREVIEW_KIND:
            raise KeyError(job_id)
        state = json.loads(job.state_json or '{}')
        status, error = job.status, job.error_text
        progress = {'current': int(job.progress_current or 0),
                    'total': int(job.progress_total or 0),
                    'message': job.progress_message}
    summary = None
    units = []
    total = 0
    if status == 'completed':
        data, final = report_files(settings, job_id)
        if (data.is_symlink() or final.is_symlink()
                or not data.is_file() or not final.is_file()):
            raise ValueError('completed preview report is incomplete')
        shared_gid = shared_config_gid()
        if shared_gid is not None:
            require_shared_file(data, shared_gid, 0o640)
            require_shared_file(final, shared_gid, 0o640)
        with final.open('r', encoding='utf-8') as stream:
            summary = json.load(stream)
        units, total = read_preview_page(data, page=page, page_size=page_size,
                                         status_filter=status_filter)
    mode = state.get("execution_mode", "strict")
    execution_enabled = bool(
        mode == execution_mode(settings)
        and (summary is None or summary.get("execution_mode", "strict") == mode)
        and getattr(settings, 'media_organizer_execution_enabled', False)
        and (mode == 'maintenance_window' or getattr(settings, 'media_organizer_namespace_quiescence_ack', False))
        and settings.allow_mutation and settings.allow_delete
    )
    confirmation_tokens = {}
    if (execution_enabled and status == 'completed' and summary
            and summary.get('blocked_count') == 0
            and 1 <= summary.get('unit_count', 0) <= 5000):
        # Admin-only endpoint: provide the exact unit-bound confirmation
        # for visible ready rows, not for skipped/blocked/foreign units.
        from app.batch.media_organizer_execute_jobs import approval_token
        for row in units:
            if row.get('status') != 'ready':
                continue
            if mode == "maintenance_window" or row.get("groups"):
                try:
                    unit = Path(row["unit"])
                    check_api_eligibility(settings, unit, (unit,))
                except (ValueError, OSError, PermissionError):
                    continue
            confirmation_tokens[row['unit']] = approval_token(job_id, row['unit'])
    return {'job_id': job_id, 'status': status, 'error': error,
            'selection': state.get('selection', ''), 'progress': progress,
            'summary': summary, 'units': units, 'page': page,
            'page_size': page_size, 'filtered_total': total, 'read_only': True,
            'execution_enabled': execution_enabled, **mode_fields(mode),
            'confirmation_tokens': confirmation_tokens}


@register_handler
class MediaOrganizerPreviewHandler(TaskHandler):
    job_type = PREVIEW_KIND
    supports_cancel = True
    supports_pause = False
    supports_retry = False
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        state = json.loads(job.state_json or '{}')
        mode = require_mode(settings, state)
        selection = state.get('selection')
        if not isinstance(selection, str):
            raise ValueError('preview requires literal selection')
        chosen = _validate_selection(selection, settings)
        data, summary_path = report_files(settings, int(job.id))
        stage_data = data.with_name(data.name + '.staging')
        stage_summary = summary_path.with_name(summary_path.name + '.staging')
        final_mappings = mapping_report_root(settings, int(job.id))
        for path in (data, summary_path, stage_data, stage_summary, final_mappings):
            if os.path.lexists(path):
                raise ValueError('preview report already exists; preserve evidence for review')
        shared_gid = shared_config_gid()
        _create_mapping_report_directory(final_mappings, shared_gid)
        last_tick = 0.0

        def check_cancelled():
            nonlocal last_tick
            now = time.monotonic()
            if now - last_tick >= 0.8:
                context.checkpoint()
                last_tick = now

        def progress(n: int, _stats: dict):
            context.checkpoint(progress_current=n,
                               progress_message=f'已只读预览 {n:,} 个目录单元',
                               checkpoint_data={'schema_version': 1, 'execution_mode': mode, 'units_scanned': n})

        with _new_private(stage_data) as out:
            final_stats = write_semantic_preview(
                chosen, allowed_roots=[Path(x) for x in settings.allowed_roots],
                quarantine_root=settings.quarantine_root,
                exclude_roots=_excluded(settings),
                exclude_dir_names=_excluded_names(settings), out=out,
                mapping_root=final_mappings, max_items=10,
                check_cancelled=check_cancelled, on_progress=progress,
            )
            out.flush()
            os.fsync(out.fileno())
        final_stats["execution_mode"] = mode
        with _new_private(stage_summary) as out:
            json.dump(final_stats, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        # Mapping files were written directly beneath the exclusively-created
        # job-scoped final directory and fsynced there. Do not rename a directory:
        # the target ZFuse filesystem returns EOPNOTSUPP for renameat2(RENAME_NOREPLACE).
        # Revalidate the final directory binding and fsync it before publishing
        # the summary marker. API readers require a completed WorkJob and this
        # summary marker, so a partial directory from an interrupted preview
        # remains inaccessible and is preserved for diagnosis.
        report_fd = _open_directory_nofollow(data.parent)
        mapping_fd = _open_directory_nofollow(final_mappings)
        try:
            mapping_info = os.fstat(mapping_fd)
            mapping_named = os.stat(
                final_mappings.name, dir_fd=report_fd, follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(mapping_info.st_mode)
                or not stat.S_ISDIR(mapping_named.st_mode)
                or (mapping_info.st_dev, mapping_info.st_ino)
                != (mapping_named.st_dev, mapping_named.st_ino)
                or (shared_gid is not None and (
                    mapping_info.st_gid != shared_gid
                    or stat.S_IMODE(mapping_info.st_mode) != 0o2770
                ))
                or (shared_gid is None and (
                    mapping_info.st_uid != os.geteuid()
                    or stat.S_IMODE(mapping_info.st_mode) != 0o700
                ))
            ):
                raise PermissionError("preview mapping directory binding or permissions changed")
            os.fsync(mapping_fd)
            os.fsync(report_fd)
        finally:
            os.close(mapping_fd)
            os.close(report_fd)
        # Summary is the final durable publication marker. No overwrite even
        # if a competing process creates a destination after preflight.
        for staged, final in ((stage_data, data), (stage_summary, summary_path)):
            os.link(staged, final, follow_symlinks=False)
            os.unlink(staged)
        # Persist both no-replace report links, including the final summary marker.
        report_fd = _open_directory_nofollow(data.parent)
        try:
            os.fsync(report_fd)
        finally:
            os.close(report_fd)
        context.checkpoint(progress_current=final_stats['unit_count'],
                           progress_message='只读整理预览完成',
                           checkpoint_data={'schema_version': 1, 'execution_mode': mode, 'finished': True,
                                            'units_scanned': final_stats['unit_count']})
