"""Explicitly confirmed, default-disabled one-unit semantic execution.

Only a Worker holding the exclusive lease may mutate media. The HTTP API
queues one reviewed unit; a frozen checksum manifest is written before any
file operation. Failed jobs never auto-retry: assisted continuation requires
a separate explicit request and uses the SAME original job's custody proof.

This feature stays off unless MEDIA_ORGANIZER_EXECUTION_ENABLED is explicitly
enabled alongside ALLOW_MUTATION and ALLOW_DELETE.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import func, select, text

from app.batch.media_package_report_lifecycle import next_media_package_job_id
from app.batch.media_organizer_jobs import (
    PREVIEW_KIND, _validate_selection, _excluded_names, report_files,
)
from app.batch.media_organizer_manifest import (
    build_frozen_preview_manifest, load_frozen_preview_manifest,
    save_frozen_preview_manifest,
)
from app.batch.media_organizer_stage import stage_frozen_sources
from app.batch.media_organizer_publish import publish_frozen_stage
from app.batch.media_organizer_retire import retire_published_stage
from app.config import Settings
from app.models import WorkJob
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler

EXECUTE_KIND = "media-organizer-execute"
ACTIVE = ("queued", "running", "paused", "cancel_requested")
MAX_REPORT_UNITS_FOR_EXECUTION = 5000


def approval_token(preview_job_id: int, unit: str) -> str:
    if not isinstance(preview_job_id, int) or preview_job_id <= 0:
        raise ValueError("invalid preview job identity")
    if not isinstance(unit, str) or not unit or not Path(unit).is_absolute():
        raise ValueError("absolute organizing unit required")
    digest = hashlib.sha256(unit.encode("utf-8")).hexdigest()[:16].upper()
    return f"EXECUTE_MEDIA_ORGANIZER_PREVIEW_{preview_job_id}_UNIT_{digest}"


def recovery_token(job_id: int) -> str:
    if not isinstance(job_id, int) or job_id <= 0:
        raise ValueError("invalid execution job identity")
    return f"RECOVER_MEDIA_ORGANIZER_EXECUTION_{job_id}"


def _require_enabled(settings: Settings) -> None:
    if not (getattr(settings, "media_organizer_execution_enabled", False)
            and settings.allow_mutation and settings.allow_delete):
        raise ValueError(
            "Execution requires MEDIA_ORGANIZER_EXECUTION_ENABLED, "
            "ALLOW_MUTATION and ALLOW_DELETE"
        )
    # A file-identity check followed by name-based directory rename/rmdir
    # cannot exclude an uncooperative concurrent writer. An independently
    # reviewed/exclusively quiescent namespace is an additional REQUIREMENT.
    # This acknowledgement is deliberately false in every default deploy.
    if not getattr(settings, "media_organizer_namespace_quiescence_ack", False):
        raise ValueError(
            "Execution blocked: MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK "
            "requires verified exclusive namespace custody"
        )


def _literal_unit(value: str, settings: Settings) -> Path:
    if (not isinstance(value, str) or not value or
            not Path(value).is_absolute() or os.path.normpath(value) != value):
        raise ValueError("canonical absolute organizing unit required")
    selected = _validate_selection(value, settings)
    if str(selected) != value:
        raise ValueError("organizing unit must match its canonical path")
    return selected


def _execution_folder(settings: Settings, job_id: int) -> Path:
    if not isinstance(job_id, int) or job_id <= 0:
        raise ValueError("invalid execution job identity")
    root = settings.reports_dir / "media_organizer-executions"
    if root.is_symlink():
        raise ValueError("unsafe execution report root")
    return root / str(job_id)


def _manifest_file(settings: Settings, job_id: int) -> Path:
    return _execution_folder(settings, job_id) / "manifest.json"


def _completed_preview(session, settings: Settings, preview_job_id: int) -> tuple[dict, dict]:
    preview = session.get(WorkJob, preview_job_id)
    if preview is None or preview.kind != PREVIEW_KIND:
        raise KeyError(preview_job_id)
    if preview.status != "completed":
        raise ValueError("read-only preview must finish before confirmation")
    data, summary_path = report_files(settings, preview_job_id)
    if (not data.is_file() or not summary_path.is_file()
            or data.is_symlink() or summary_path.is_symlink()):
        raise ValueError("completed preview evidence is missing or unsafe")
    with summary_path.open("r", encoding="utf-8") as stream:
        summary = json.load(stream)
    if (not isinstance(summary, dict)
            or not isinstance(summary.get("unit_count"), int)
            or not 1 <= summary["unit_count"] <= MAX_REPORT_UNITS_FOR_EXECUTION
            or not isinstance(summary.get("ready_count"), int)
            or summary["ready_count"] <= 0
            or summary.get("blocked_count") != 0
            or summary.get("read_only") is not True):
        raise ValueError("preview is empty, over limit, or has unresolved blockers")
    return json.loads(preview.state_json or "{}"), summary


def _ready_unit_record(settings: Settings, preview_job_id: int, unit: str,
                       expected_summary: dict) -> dict:
    data, summary_path = report_files(settings, preview_job_id)
    if data.is_symlink() or summary_path.is_symlink():
        raise ValueError("unsafe preview report")
    found = None
    seen = 0
    ready_count = blocked_count = 0
    with data.open("r", encoding="utf-8") as rows:
        for line in rows:
            seen += 1
            if seen > MAX_REPORT_UNITS_FOR_EXECUTION:
                raise ValueError("preview exceeds execution unit limit")
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("invalid preview record")
            ready_count += record.get("status") == "ready"
            blocked_count += record.get("status") == "blocked"
            if record.get("unit") == unit:
                if found is not None:
                    raise ValueError("ambiguous duplicate organizing unit in preview")
                found = record
    if (seen != expected_summary.get("unit_count")
            or ready_count != expected_summary.get("ready_count")
            or blocked_count != expected_summary.get("blocked_count")):
        raise ValueError("preview summary changed since completion")
    if found is None or found.get("status") != "ready":
        raise ValueError("unit was not ready in the approved preview")
    if (not isinstance(found.get("input_fingerprint"), str)
            or len(found["input_fingerprint"]) != 64):
        raise ValueError("approved preview is missing source fingerprint")
    return found


def enqueue_media_organizer_execution(
    session_factory, settings: Settings, *, preview_job_id: int,
    unit: str, confirmation: str,
) -> dict:
    """Queue exactly one reviewed unit, never mutate files in the API request."""
    _require_enabled(settings)
    _literal_unit(unit, settings)
    if confirmation != approval_token(preview_job_id, unit):
        raise ValueError("exact unit-bound preview confirmation required")
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        preview_state, summary = _completed_preview(session, settings, preview_job_id)
        selection = _literal_unit(preview_state.get("selection"), settings)
        if not Path(unit).is_relative_to(selection):
            raise ValueError("unit must remain within the original preview selection")
        _ready_unit_record(settings, preview_job_id, unit, summary)
        matches = session.scalars(select(WorkJob).where(
            WorkJob.kind == EXECUTE_KIND,
            func.json_extract(WorkJob.state_json, "$.preview_job_id") == preview_job_id,
            func.json_extract(WorkJob.state_json, "$.unit") == unit,
        ).order_by(WorkJob.id.desc())).all()
        originals = [job for job in matches
                     if "recovery_of_job_id" not in json.loads(job.state_json or "{}")]
        if originals:
            old = originals[0]
            if old.status in (*ACTIVE, "completed"):
                return {"job_id": int(old.id), "status": old.status}
            raise ValueError("prior execution failed; explicit recovery is required")
        active = session.scalar(select(WorkJob.id).where(
            WorkJob.kind == EXECUTE_KIND,
            WorkJob.status.in_(ACTIVE),
        ).limit(1))
        if active is not None:
            raise ValueError("another semantic execution is active")
        job = WorkJob(
            id=next_media_package_job_id(session, settings),
            kind=EXECUTE_KIND, status="queued", progress_current=0,
            progress_total=4,
            progress_message="等待专用 Worker 冻结并校验选定作品",
            state_json=json.dumps({
                "preview_job_id": preview_job_id,
                "selection": str(selection), "unit": unit,
            }, ensure_ascii=False),
        )
        session.add(job)
        session.commit()
        return {"job_id": int(job.id), "status": job.status}


def get_media_organizer_execution(session_factory, job_id: int) -> dict:
    with session_factory() as session:
        job = session.get(WorkJob, job_id)
        if job is None or job.kind != EXECUTE_KIND:
            raise KeyError(job_id)
        state = json.loads(job.state_json or "{}")
        checkpoint = json.loads(job.checkpoint_json or "{}")
        return {
            "job_id": int(job.id), "status": job.status,
            "error": job.error_text,
            "preview_job_id": state.get("preview_job_id"),
            "unit": state.get("unit"),
            "recovery_of_job_id": state.get("recovery_of_job_id"),
            "progress": {
                "current": int(job.progress_current or 0),
                "total": int(job.progress_total or 0),
                "message": job.progress_message,
                "phase": checkpoint.get("phase"),
            },
        }


def enqueue_media_organizer_recovery(
    session_factory, settings: Settings, *, failed_job_id: int,
    confirmation: str,
) -> dict:
    """Create a distinct explicit recovery job tied to original frozen custody."""
    _require_enabled(settings)
    if confirmation != recovery_token(failed_job_id):
        raise ValueError("exact original execution recovery confirmation required")
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        original = session.get(WorkJob, failed_job_id)
        if original is None or original.kind != EXECUTE_KIND:
            raise KeyError(failed_job_id)
        if original.status != "failed":
            raise ValueError("only a failed original execution can be recovered")
        state = json.loads(original.state_json or "{}")
        if state.get("recovery_of_job_id") is not None:
            raise ValueError("nested recovery is forbidden; manual review required")
        phase = json.loads(original.checkpoint_json or "{}").get("phase")
        if phase not in ("frozen", "staged", "published"):
            raise ValueError("no recoverable frozen phase recorded")
        unit = str(_literal_unit(state.get("unit"), settings))
        original_preview_id = state.get("preview_job_id")
        if not isinstance(original_preview_id, int) or original_preview_id <= 0:
            raise ValueError("recovery preview identity missing")
        # Idempotent retransmission of an already-authorized recovery must
        # not demand a staging directory that successful cleanup has removed.
        existing = session.scalar(select(WorkJob).where(
            WorkJob.kind == EXECUTE_KIND,
            func.json_extract(WorkJob.state_json, "$.recovery_of_job_id") == failed_job_id,
        ).order_by(WorkJob.id.desc()).limit(1))
        if existing is not None:
            if existing.status in (*ACTIVE, "completed"):
                return {"job_id": int(existing.id), "status": existing.status,
                        "recovery_of_job_id": failed_job_id}
            raise ValueError("prior recovery failed; manual review required")
        manifest_path = _manifest_file(settings, failed_job_id)
        manifest = load_frozen_preview_manifest(
            manifest_path, job_id=failed_job_id, unit=Path(unit),
        )
        if manifest.get("job_id") != failed_job_id:
            raise ValueError("frozen job identity changed")
        stage = Path(unit) / manifest["stage_directory"]
        if not stage.is_dir() or stage.is_symlink():
            raise ValueError("trusted staged custody is absent; manual review required")
        # New recovery authorization proves the original stage witness.
        # A PUBLISHED task may also have entered the last-marker/rmdir gap:
        # in that special case ONLY a completely empty, inode-bound stage
        # plus the independently durable private receipt is acceptable.
        from app.batch.file_rename import _open_directory_nofollow
        from app.batch.media_organizer_stage import _read_marker, _authority
        from app.batch.media_organizer_retire import (
            _read_retirement_receipt, _retirement_receipt_path,
        )
        fd = _open_directory_nofollow(stage)
        try:
            owner_present = _read_marker(fd, ".nfc-stage-authority", _authority(manifest))
            if not owner_present:
                if phase != "published":
                    raise ValueError("original staged ownership witness is missing")
                with os.scandir(fd) as entries:
                    if next(entries, None) is not None:
                        raise ValueError("unwitnessed stage is not empty; manual recovery required")
                _read_retirement_receipt(
                    _retirement_receipt_path(manifest_path),
                    manifest, os.fstat(fd),
                )
        finally:
            os.close(fd)
        active = session.scalar(select(WorkJob.id).where(
            WorkJob.kind == EXECUTE_KIND, WorkJob.status.in_(ACTIVE),
        ).limit(1))
        if active is not None:
            raise ValueError("another semantic execution is active")
        job = WorkJob(
            id=next_media_package_job_id(session, settings),
            kind=EXECUTE_KIND, status="queued", progress_current=0,
            progress_total=4,
            progress_message="等待 Worker 使用原冻结清单安全恢复",
            state_json=json.dumps({
                "preview_job_id": original_preview_id, "unit": unit,
                "selection": state.get("selection"),
                "recovery_of_job_id": failed_job_id,
            }, ensure_ascii=False),
            retry_of=failed_job_id,
        )
        session.add(job)
        session.commit()
        return {"job_id": int(job.id), "status": job.status,
                "recovery_of_job_id": failed_job_id}


@register_handler
class MediaOrganizerExecuteHandler(TaskHandler):
    job_type = EXECUTE_KIND
    supports_cancel = False
    supports_retry = False
    supports_pause = False
    supports_resume = False  # Only explicit new recovery WorkJob is supported.

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        _require_enabled(settings)
        if not context.worker_id:
            raise PermissionError("exclusive Worker lease required for media mutation")
        state = json.loads(job.state_json or "{}")
        original_id = state.get("recovery_of_job_id")
        preview_id = state.get("preview_job_id")
        unit = _literal_unit(state.get("unit"), settings)
        if not isinstance(preview_id, int) or preview_id < 1:
            raise ValueError("missing original preview job id")

        def fence() -> None:
            from app.tasks.recovery import renew_and_assert_worker_lease
            renew_and_assert_worker_lease(context.SessionLocal, context.worker_id)

        frozen_job_id = int(job.id) if original_id is None else original_id
        phase = "new"
        if original_id is not None:
            with context.SessionLocal() as session:
                original = session.get(WorkJob, original_id)
                if (original is None or original.kind != EXECUTE_KIND
                        or original.status != "failed"):
                    raise ValueError("original failed job no longer provides recovery authority")
                original_state = json.loads(original.state_json or "{}")
                if (original_state.get("unit") != str(unit)
                        or original_state.get("preview_job_id") != preview_id):
                    raise ValueError("recovery binding differs from original approval")
                phase = json.loads(original.checkpoint_json or "{}").get("phase")
                if phase not in ("frozen", "staged", "published"):
                    raise ValueError("unsupported original recovery phase")
        folder = _execution_folder(settings, frozen_job_id)
        manifest_path = _manifest_file(settings, frozen_job_id)

        def checkpoint(n: int, mode: str, message: str) -> None:
            context.checkpoint(
                progress_current=n, progress_total=4, progress_message=message,
                checkpoint_data={
                    "schema_version": 1, "phase": mode, "preview_job_id": preview_id,
                    "frozen_job_id": frozen_job_id, "unit": str(unit),
                },
            )

        fence()
        if original_id is None:
            with context.SessionLocal() as session:
                state_preview, summary = _completed_preview(session, settings, preview_id)
                selection = _literal_unit(state_preview.get("selection"), settings)
                if not unit.is_relative_to(selection):
                    raise ValueError("unit moved outside approved preview scope")
            record = _ready_unit_record(settings, preview_id, str(unit), summary)
            if manifest_path.exists() or manifest_path.is_symlink():
                raise ValueError("untrusted frozen manifest file already exists")
            manifest = build_frozen_preview_manifest(
                unit, preview_record=record, allowed_roots=settings.allowed_roots,
                quarantine_root=settings.quarantine_root, job_id=frozen_job_id,
                exclude_dir_names=_excluded_names(settings),
            )
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            fence()
            save_frozen_preview_manifest(manifest_path, manifest)
        else:
            manifest = load_frozen_preview_manifest(
                manifest_path, job_id=frozen_job_id, unit=unit,
            )
        checkpoint(1, "frozen", "冻结清单已经验证")
        if phase != "published":
            # An interruption in staging or publication retains all private
            # source links, so retry those phases only with the original
            # checksum-validated manifest and owner witness.
            fence()
            stage_frozen_sources(
                manifest, frozen_manifest_path=manifest_path,
                allowed_roots=settings.allowed_roots,
                quarantine_root=settings.quarantine_root, lease_fence=fence,
                resume=original_id is not None,
            )
            checkpoint(2, "staged", "全部已暂存，开始核验与无覆盖发布")
            fence()
            publish_frozen_stage(
                manifest, frozen_manifest_path=manifest_path,
                allowed_roots=settings.allowed_roots,
                quarantine_root=settings.quarantine_root, lease_fence=fence,
                resume=original_id is not None,
            )
        # Retirement may have already removed one or more staged hardlinks.
        # Its durable marker, not the source layout, governs continuation:
        # never attempt restaging after the original job reached published.
        checkpoint(3, "published", "已验证发布阶段，准备核验并移除暂存链接")
        fence()
        retire_published_stage(
            manifest, frozen_manifest_path=manifest_path,
            allowed_roots=settings.allowed_roots,
            quarantine_root=settings.quarantine_root, lease_fence=fence,
            resume=original_id is not None,
        )
        checkpoint(4, "completed", "已完成执行并核对目标结构")
