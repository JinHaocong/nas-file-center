"""WorkJob-backed, read-only semantic media preview with private reports."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from sqlalchemy import func, select, text

from app.batch.media_package_report_lifecycle import next_media_package_job_id
from app.batch.media_organizer_planner import _check_scope, _normalized_excluded_dir_names
from app.batch.media_organizer_reports import (
    mapping_identifier, read_preview_mapping, read_preview_page,
)
from app.fs_ops import rename_noreplace_at
from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_organizer_scan import write_semantic_preview
from app.config import Settings
from app.models import WorkJob
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler

PREVIEW_KIND = "media-organizer-preview"
ACTIVE_STATUSES = ("queued", "running", "paused", "cancel_requested")
MAX_ACTIVE_PREVIEWS = 3


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
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root / f"{job_id}.semantic.jsonl", root / f"{job_id}.semantic.summary.json"


def _new_private(path: Path):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, 'O_NOFOLLOW', 0), 0o600)
    return os.fdopen(fd, 'w', encoding='utf-8')


def mapping_report_root(settings: Settings, job_id: int) -> Path:
    data, _ = report_files(settings, job_id)
    return data.parent / f"{job_id}.semantic-maps"


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
        "job_id": job_id, "mapping_id": mapping_id,
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
            state_json=json.dumps({'selection': str(chosen)}, ensure_ascii=False),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return {'job_id': int(job.id), 'status': job.status}


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
        if not data.is_file() or not final.is_file():
            raise ValueError('completed preview report is incomplete')
        with final.open('r', encoding='utf-8') as stream:
            summary = json.load(stream)
        units, total = read_preview_page(data, page=page, page_size=page_size,
                                         status_filter=status_filter)
    execution_enabled = bool(
        getattr(settings, 'media_organizer_execution_enabled', False)
        and getattr(settings, 'media_organizer_namespace_quiescence_ack', False)
        and settings.allow_mutation and settings.allow_delete
    )
    confirmation_tokens = {}
    if (execution_enabled and status == 'completed' and summary
            and summary.get('blocked_count') == 0
            and 1 <= summary.get('unit_count', 0) <= 5000):
        # Admin-only endpoint: provide the exact unit-bound confirmation
        # for visible ready rows, not for skipped/blocked/foreign units.
        from app.batch.media_organizer_execute_jobs import approval_token
        confirmation_tokens = {
            row['unit']: approval_token(job_id, row['unit'])
            for row in units if row.get('status') == 'ready' and not row.get('groups')
        }
    return {'job_id': job_id, 'status': status, 'error': error,
            'selection': state.get('selection', ''), 'progress': progress,
            'summary': summary, 'units': units, 'page': page,
            'page_size': page_size, 'filtered_total': total, 'read_only': True,
            'execution_enabled': execution_enabled,
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
        selection = state.get('selection')
        if not isinstance(selection, str):
            raise ValueError('preview requires literal selection')
        chosen = _validate_selection(selection, settings)
        data, summary_path = report_files(settings, int(job.id))
        stage_data = data.with_name(data.name + '.staging')
        stage_summary = summary_path.with_name(summary_path.name + '.staging')
        final_mappings = mapping_report_root(settings, int(job.id))
        stage_mappings = final_mappings.with_name(final_mappings.name + '.staging')
        for path in (data, summary_path, stage_data, stage_summary,
                     final_mappings, stage_mappings):
            if os.path.lexists(path):
                raise ValueError('preview report already exists; preserve evidence for review')
        stage_mappings.mkdir(mode=0o700)
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
                               checkpoint_data={'schema_version': 1, 'units_scanned': n})

        with _new_private(stage_data) as out:
            final_stats = write_semantic_preview(
                chosen, allowed_roots=[Path(x) for x in settings.allowed_roots],
                quarantine_root=settings.quarantine_root,
                exclude_roots=_excluded(settings),
                exclude_dir_names=_excluded_names(settings), out=out,
                mapping_root=stage_mappings, max_items=10,
                check_cancelled=check_cancelled, on_progress=progress,
            )
            out.flush()
            os.fsync(out.fileno())
        with _new_private(stage_summary) as out:
            json.dump(final_stats, out, ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        # Publish the complete mapping directory without replacing any
        # existing evidence. The summary remains the final report marker.
        report_fd = _open_directory_nofollow(data.parent)
        try:
            rename_noreplace_at(
                report_fd, stage_mappings.name, report_fd, final_mappings.name,
            )
            os.fsync(report_fd)
        finally:
            os.close(report_fd)
        # Summary is the final durable publication marker. No overwrite even
        # if a competing process creates a destination after preflight.
        for staged, final in ((stage_data, data), (stage_summary, summary_path)):
            os.link(staged, final, follow_symlinks=False)
            os.unlink(staged)
        context.checkpoint(progress_current=final_stats['unit_count'],
                           progress_message='只读整理预览完成',
                           checkpoint_data={'schema_version': 1, 'finished': True,
                                            'units_scanned': final_stats['unit_count']})
