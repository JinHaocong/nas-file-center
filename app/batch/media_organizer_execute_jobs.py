"""Explicitly confirmed, default-disabled one-unit semantic execution.

Only a non-root Worker holding the exclusive lease and the selected authority
contract may mutate media. The HTTP API queues one reviewed unit; a frozen
checksum manifest is written before any file operation. Failed jobs never
auto-retry: assisted continuation requires a separate explicit request and
uses the SAME original job's strict proof or maintenance-window agreement.

This feature stays off unless MEDIA_ORGANIZER_EXECUTION_ENABLED is explicitly
enabled alongside ALLOW_MUTATION and ALLOW_DELETE.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path

from sqlalchemy import func, select, text

from app.batch.file_rename import _open_directory_nofollow
from app.batch.media_package_report_lifecycle import next_media_package_job_id
from app.batch.media_organizer_jobs import (
    PREVIEW_KIND, _validate_selection, _excluded_names, report_files, mode_fields, require_mode,
)
from app.batch.media_organizer_manifest import (
    _checksum, build_frozen_preview_manifest, load_frozen_preview_manifest,
    save_frozen_preview_manifest,
)
from app.batch.media_organizer_stage import stage_frozen_sources
from app.batch.media_organizer_publish import publish_frozen_stage
from app.batch.media_organizer_deferred_cleanup import (
    validate_deferred_publication, record_deferred_cleanup_evidence,
    read_deferred_cleanup_review,
)
from app.config import Settings
from app.config_sharing import shared_config_gid, ensure_shared_report_directory
from app.batch.media_organizer_cleanup_audit import audit_deferred_cleanup_inventory
from app.batch.media_organizer_path_roles import POLICY, classify_path_roles, uses_path_roles
from app.batch.media_organizer_authority import (
    execution_mode, check_api_eligibility, acquire_operation_authority, assert_operation_authorized,
)
from app.batch.media_organizer_cleanup_plan import (
    cleanup_plan_path, read_cleanup_plan, save_cleanup_plan,
)
from app.models import WorkJob
from app.tasks.context import JobContext
from app.tasks.logging import log_task_event
from app.tasks.handlers_base import TaskHandler, register_handler

EXECUTE_KIND = "media-organizer-execute"
MUTATION_KINDS = (EXECUTE_KIND, "media-organizer-cleanup")
ACTIVE = ("queued", "running", "paused", "cancel_requested")
MAX_REPORT_UNITS_FOR_EXECUTION = 5000
RECOVERABLE_PHASES = ("frozen", "staged", "published", "manual_cleanup_required")


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
    # Strict mode requires a separately verified external namespace proof.
    # Maintenance-window mode instead requires a fresh literal operator
    # acknowledgement on every execute/recovery/cleanup WorkJob; it is an
    # operational promise, not an OS-enforced exclusion mechanism.
    if (execution_mode(settings) == "strict"
            and not getattr(settings, "media_organizer_namespace_quiescence_ack", False)):
        raise ValueError(
            "Strict execution blocked: MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK "
            "requires verified exclusive namespace custody"
        )


def _approval_fields(settings: Settings, confirmed: bool) -> dict:
    mode = execution_mode(settings)
    if type(confirmed) is not bool or (mode == "maintenance_window") != confirmed:
        raise ValueError("maintenance_window_confirmed must match the configured execution mode")
    return {"execution_mode": mode, "maintenance_window_confirmed": confirmed}


def _validate_job_approval(settings: Settings, job: WorkJob, state: dict) -> None:
    from app.tasks.recovery import organizer_recovery_predecessor

    mode = require_mode(settings, state)
    parent = organizer_recovery_predecessor(job.id, getattr(job, "retry_of", None), state)
    _approval_fields(settings, state.get("maintenance_window_confirmed", False))
    if mode == "maintenance_window" and (
            type(state.get("approved_job_id")) is not int or state["approved_job_id"] != job.id):
        raise ValueError("maintenance approval belongs to another WorkJob")
    if mode == "maintenance_window" and job.kind == EXECUTE_KIND:
        expected = (approval_token(state.get("preview_job_id"), state.get("unit"))
                    if parent is None else recovery_token(parent))
        if state.get("confirmation") != expected:
            raise ValueError("maintenance confirmation differs from the approved unit or job")


def _snapshot_review(settings: Settings) -> bool:
    return shared_config_gid() is not None or execution_mode(settings) == "maintenance_window"


def _require_mutation_slot(session, *, family_id: int | None = None) -> None:
    """Keep queued foreign work from blocking the sole reserved family's follow-up."""
    from app.tasks.recovery import reserved_maintenance_family_ids, work_job_allowed_by_maintenance_reservation

    reserved = reserved_maintenance_family_ids(session)
    if reserved and reserved != {family_id}:
        raise ValueError("another frozen maintenance window is active")
    active = session.scalars(select(WorkJob).where(
        WorkJob.kind.in_(MUTATION_KINDS), WorkJob.status.in_(ACTIVE),
    ))
    for job in active:
        if reserved and job.status == "queued" and not work_job_allowed_by_maintenance_reservation(session, job):
            continue
        raise ValueError("another V1.6 mutation WorkJob is active")


def _require_mutation_worker_identity(settings: Settings) -> None:
    """Require the ordinary non-root Worker or the explicit 0:10000 NAS profile."""
    from app.nas_compat_worker import is_nas_compat_root_worker

    if not hasattr(os, "geteuid"):
        raise PermissionError("V1.6 requires a POSIX Worker identity")
    if os.geteuid() == 0 and not is_nas_compat_root_worker(settings):
        raise PermissionError(
            "UID 0 is disabled; enable the explicit NAS compatibility Root Worker profile"
        )
    if os.geteuid() != 0 and getattr(settings, "nas_compat_root_worker_enabled", False):
        raise PermissionError("NAS compatibility Root Worker profile requires UID 0")


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
    state = json.loads(preview.state_json or "{}")
    require_mode(settings, state, summary)
    return state, summary


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
    unit: str, confirmation: str, maintenance_window_confirmed: bool = False,
) -> dict:
    """Queue exactly one reviewed unit, never mutate files in the API request."""
    _require_enabled(settings)
    approval = _approval_fields(settings, maintenance_window_confirmed)
    _literal_unit(unit, settings)
    if confirmation != approval_token(preview_job_id, unit):
        raise ValueError("exact unit-bound preview confirmation required")
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        preview_state, summary = _completed_preview(session, settings, preview_job_id)
        selection = _literal_unit(preview_state.get("selection"), settings)
        if not Path(unit).is_relative_to(selection):
            raise ValueError("unit must remain within the original preview selection")
        ready = _ready_unit_record(settings, preview_job_id, unit, summary)
        # Even a flat plan creates a private stage through mkdir/open.
        # Strict mode checks external custody here; maintenance mode validates
        # scope now and requires a literal operator acknowledgement at enqueue.
        check_api_eligibility(settings, Path(unit), (Path(unit),))
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
                _validate_job_approval(settings, old, json.loads(old.state_json))
                return {"job_id": int(old.id), "status": old.status, **mode_fields(approval["execution_mode"])}
            raise ValueError("prior execution failed; explicit recovery is required")
        _require_mutation_slot(session)
        approved_id = next_media_package_job_id(session, settings)
        job = WorkJob(
            id=approved_id,
            kind=EXECUTE_KIND, status="queued", progress_current=0,
            progress_total=4,
            progress_message="等待专用 Worker 冻结并校验选定作品",
            state_json=json.dumps({
                **approval, "approved_job_id": approved_id, "confirmation": confirmation,
                "input_fingerprint": ready["input_fingerprint"],
                "preview_job_id": preview_job_id,
                "selection": str(selection), "unit": unit,
            }, ensure_ascii=False),
        )
        session.add(job)
        session.commit()
        return {"job_id": int(job.id), "status": job.status, **mode_fields(approval["execution_mode"])}


def get_media_organizer_execution(
    session_factory, job_id: int, *, settings: Settings | None = None,
) -> dict:
    from app.batch.media_organizer_cleanup_jobs import (
        CLEANUP_KIND, cleanup_recovery_confirmation,
    )
    execution_enabled = False
    if settings is not None:
        try:
            _require_enabled(settings)
        except ValueError:
            pass
        else:
            execution_enabled = True
    with session_factory() as session:
        job = session.get(WorkJob, job_id)
        if job is None or job.kind != EXECUTE_KIND:
            raise KeyError(job_id)
        state = json.loads(job.state_json or "{}")
        checkpoint = json.loads(job.checkpoint_json or "{}")
        mode = state.get("execution_mode", "strict")
        execution_enabled = execution_enabled and mode == execution_mode(settings)
        # A pre-freeze failure, such as NAS #31's permission denial, has no
        # durable replay authority. Do not advertise a non-working recovery.
        failed_original = job.status == "failed" and state.get("recovery_of_job_id") is None
        recovery_available = (
            failed_original
            and checkpoint.get("phase") in RECOVERABLE_PHASES
            and checkpoint.get("execution_mode", "strict") == mode
            and (mode != "maintenance_window" or (
                isinstance(checkpoint.get("manifest_checksum"), str)
                and len(checkpoint["manifest_checksum"]) == 64
            ))
        )
        cleanup = session.scalar(select(WorkJob).where(
            WorkJob.kind == CLEANUP_KIND,
            func.json_extract(WorkJob.state_json, "$.execution_job_id") == job_id,
        ).order_by(WorkJob.id.desc()).limit(1))
        abandon_job = session.scalar(select(WorkJob).where(
            WorkJob.kind == EXECUTE_KIND,
            func.json_extract(WorkJob.state_json, "$.abandon_of_job_id") == job_id,
        ).order_by(WorkJob.id.desc()).limit(1))
        abandon_available = (
            execution_enabled and failed_original and mode == "maintenance_window"
            and checkpoint.get("phase") == "frozen"
            and isinstance(checkpoint.get("manifest_checksum"), str)
            and len(checkpoint["manifest_checksum"]) == 64
            and abandon_job is None
        )
        cleanup_status = None
        if cleanup is not None:
            cleanup_state = json.loads(cleanup.state_json or "{}")
            recovery_confirmation = None
            if (cleanup.status == "failed" and isinstance(cleanup_state, dict)
                    and cleanup_state.get("unit") == state.get("unit")
                    and type(cleanup_state.get("frozen_job_id")) is int
                    and cleanup_state["frozen_job_id"] == checkpoint.get("frozen_job_id")):
                recovery_confirmation = cleanup_recovery_confirmation(
                    int(cleanup.id), cleanup_state["frozen_job_id"],
                    cleanup_state["unit"], cleanup_state.get("plan_sha256"),
                )
            cleanup_status = {
                **mode_fields(cleanup_state.get("execution_mode", "strict")),
                "job_id": int(cleanup.id), "status": cleanup.status,
                "error": cleanup.error_text,
                "recovery_confirmation": recovery_confirmation,
            }
        return {
            "job_id": int(job.id), "status": job.status,
            **mode_fields(mode), "execution_enabled": execution_enabled,
            "error": job.error_text,
            "preview_job_id": state.get("preview_job_id"),
            "unit": state.get("unit"),
            "recovery_of_job_id": state.get("recovery_of_job_id"),
            "recovery_available": recovery_available,
            "abandon_available": abandon_available,
            "recovery_unavailable_reason": (
                "未形成可验证的冻结检查点，不能自动恢复。请保留现有文件与证据，核查后重新只读扫描。"
                if failed_original and not recovery_available else None
            ),
            "manual_cleanup_required": checkpoint.get("phase") == "manual_cleanup_required",
            "finalized": checkpoint.get("phase") == "completed",
            "publication_complete": (
                checkpoint.get("phase") == "completed" or
                checkpoint.get("phase") in ("published", "manual_cleanup_required")
                and checkpoint.get("deferred_publication_count", 0) == 0
            ),
            "deferred_publication_count": (
                0 if checkpoint.get("phase") == "completed" else
                checkpoint.get("deferred_publication_count", 0)
            ),
            "cleanup": cleanup_status,
            "progress": {
                "current": int(job.progress_current or 0),
                "total": int(job.progress_total or 0),
                "message": job.progress_message,
                "phase": checkpoint.get("phase"),
            },
        }


def _validate_publication_family(session, settings, job, state, checkpoint) -> None:
    """Recheck the failed root of a recovered publication before separate cleanup."""
    _validate_job_approval(settings, job, state)
    mode = require_mode(settings, checkpoint)
    if mode != "maintenance_window":
        return
    root_id = state.get("recovery_of_job_id", job.id)
    if (checkpoint.get("frozen_job_id") != root_id or checkpoint.get("unit") != state["unit"]
            or checkpoint.get("preview_job_id") != state["preview_job_id"]):
        raise ValueError("publication differs from the approved frozen unit")
    if root_id == job.id:
        return
    original = session.get(WorkJob, root_id)
    if original is None:
        raise ValueError("missing original frozen execution")
    original_state, original_checkpoint, _, _ = _original_recovery_authority(original, settings)
    digest = checkpoint.get("manifest_checksum")
    if not digest or digest != original_checkpoint.get("manifest_checksum"):
        raise ValueError("recovered publication differs from the original frozen manifest")
    _recovery_job_binding(job, original, original_state, original_checkpoint, digest)


def _cleanup_review_authority(session_factory, settings: Settings, job_id: int):
    """Bind review artifacts to a completed execution, without private reads."""
    if type(job_id) is not int or job_id <= 0:
        raise ValueError("invalid execution job")
    with session_factory() as session:
        job = session.get(WorkJob, job_id)
        if job is None or job.kind != EXECUTE_KIND:
            raise KeyError(job_id)
        state = json.loads(job.state_json or "{}")
        checkpoint = json.loads(job.checkpoint_json or "{}")
        if not isinstance(state, dict) or not isinstance(checkpoint, dict):
            raise ValueError("invalid completed execution checkpoint")
        if (job.status != "completed" or
                checkpoint.get("phase") != "manual_cleanup_required"):
            raise ValueError("completed publication evidence is not ready for review")
        unit = _literal_unit(state.get("unit"), settings)
        prior = state.get("recovery_of_job_id")
        frozen_id = int(job_id) if prior is None else prior
        if not isinstance(frozen_id, int) or frozen_id < 1:
            raise ValueError("invalid frozen execution identity")
        _validate_publication_family(session, settings, job, state, checkpoint)
        if checkpoint.get("frozen_job_id") != frozen_id:
            raise ValueError("cleanup review checkpoint is not bound to the frozen job")
    manifest_file = _manifest_file(settings, frozen_id)
    manifest = load_frozen_preview_manifest(
        manifest_file, job_id=frozen_id, unit=unit,
    )
    require_mode(settings, manifest)
    if manifest.get("cleanup_policy") != "deferred":
        raise ValueError("unsafe cleanup policy in frozen plan")
    return manifest, manifest_file, checkpoint


def get_media_organizer_cleanup_review(
    session_factory, settings: Settings, job_id: int, *,
    page: int = 1, page_size: int = 25,
) -> dict:
    """Review a shared Worker snapshot or the explicit legacy live reader."""
    if not (type(page) is int and page >= 1 and
            type(page_size) is int and 1 <= page_size <= 100):
        raise ValueError("invalid review page")
    shared = _snapshot_review(settings)
    manifest, manifest_file, checkpoint = _cleanup_review_authority(
        session_factory, settings, job_id,
    )
    if shared:
        from app.batch.media_organizer_shared_handoff import (
            read_shared_cleanup_handoff, shared_review_page,
        )
        read_shared_cleanup_handoff(manifest, manifest_file, checkpoint)
        result = shared_review_page(manifest, page=page, page_size=page_size)
    else:
        result = read_deferred_cleanup_review(
            manifest, frozen_manifest_path=manifest_file, page=page, page_size=page_size,
        )
        result.update(verification_scope="live_frozen_inventory",
                      live_inventory_verified=True, read_only=True)
    result.update(mode_fields(execution_mode(settings)), reviewed_execution_job_id=job_id)
    return result


def get_media_organizer_cleanup_audit(
    session_factory, settings: Settings, job_id: int,
) -> dict:
    """Admin-read entire frozen inventory; not a cleanup/finalize operation."""
    if _snapshot_review(settings):
        from app.batch.media_organizer_shared_handoff import (
            read_shared_cleanup_handoff, shared_audit_summary,
        )
        manifest, path, checkpoint = _cleanup_review_authority(session_factory, settings, job_id)
        read_shared_cleanup_handoff(manifest, path, checkpoint)
        result = shared_audit_summary(manifest)
        result.update(mode_fields(execution_mode(settings)), reviewed_execution_job_id=job_id)
        return result
    # This existing reader already checks completed WorkJob, phase, checksum,
    # read-only journal, the first frozen row and source→unit binding.
    review = get_media_organizer_cleanup_review(
        session_factory, settings, job_id, page=1, page_size=1,
    )
    frozen_id = int(review["job_id"])
    unit = Path(review["unit"])
    path = _manifest_file(settings, frozen_id)
    manifest = load_frozen_preview_manifest(
        path, job_id=frozen_id, unit=unit,
    )
    result = audit_deferred_cleanup_inventory(
        manifest, frozen_manifest_path=path,
        allowed_roots=settings.allowed_roots,
        quarantine_root=settings.quarantine_root,
    )
    result["reviewed_execution_job_id"] = job_id
    result.update(mode_fields(execution_mode(settings)), verification_scope="live_frozen_inventory", live_inventory_verified=True)
    return result


def get_media_organizer_cleanup_plan(
    session_factory, settings: Settings, job_id: int, *,
    page: int = 1, page_size: int = 25,
) -> dict:
    """Verified paginated planned cleanup *review*; no mutation authority."""
    if (not isinstance(page, int) or page < 1
            or not isinstance(page_size, int) or not 1 <= page_size <= 100):
        raise ValueError("invalid cleanup plan pagination")
    from app.batch.media_organizer_finalize import cleanup_confirmation
    shared = _snapshot_review(settings)
    if shared:
        from app.batch.media_organizer_shared_handoff import read_shared_cleanup_handoff
        manifest, path, checkpoint = _cleanup_review_authority(session_factory, settings, job_id)
        plan = read_shared_cleanup_handoff(manifest, path, checkpoint)["plan"]
        frozen_id = manifest["job_id"]
    else:
        audit = get_media_organizer_cleanup_audit(session_factory, settings, job_id)
        frozen_id = int(audit["job_id"])
        path = _manifest_file(settings, frozen_id)
        manifest = load_frozen_preview_manifest(path, job_id=frozen_id, unit=Path(audit["unit"]))
        plan = read_cleanup_plan(cleanup_plan_path(path), manifest)
    offset = (page - 1) * page_size
    return {
        **mode_fields(execution_mode(settings)), "job_id": frozen_id,
        "reviewed_execution_job_id": job_id,
        "unit": plan["unit"],
        "plan_sha256": plan["plan_sha256"],
        "confirmation": cleanup_confirmation(frozen_id, plan["unit"], plan["plan_sha256"]),
        "manifest_checksum": plan["manifest_checksum"],
        "plan_kind": "review_only",
        "page": page,
        "page_size": page_size,
        "total_original_links": len(plan["original_links"]),
        "total_staged_links": len(plan["staged_links"]),
        "original_links": plan["original_links"][offset:offset + page_size],
        "staged_links": plan["staged_links"][offset:offset + page_size],
        "wrapper_directories": plan["wrapper_directories"],
        "total_deferred_publications": len(plan.get("deferred_publications", [])),
        "deferred_publications": plan.get("deferred_publications", [])[offset:offset + page_size],
        "total_released_original_links": len(plan.get("released_original_links", [])),
        "released_original_links": plan.get("released_original_links", [])[offset:offset + page_size],
        "total_retained_original_links": len(plan.get("retained_original_links", [])),
        "retained_original_links": plan.get("retained_original_links", [])[offset:offset + page_size],
        "retained_wrapper_directories": plan.get("retained_wrapper_directories", []),
        "stage": plan["stage"],
        "cleanup_authorized": False,
        "finalized": False,
        "zero_change_rescan_verified": False,
        "namespace_exclusive_custody_proven": False,
        "read_only": True,
        "verification_scope": "worker_handoff_snapshot" if shared else "live_frozen_inventory",
        "live_inventory_verified": not shared,
    }


def _original_recovery_authority(original: WorkJob, settings: Settings):
    """Read the failed original's approval; never treat a recovery as original."""
    if original.kind != EXECUTE_KIND or original.status != "failed":
        raise ValueError("only a failed original execution can be recovered")
    state = json.loads(original.state_json or "{}")
    checkpoint = json.loads(original.checkpoint_json or "{}")
    if not isinstance(state, dict) or not isinstance(checkpoint, dict):
        raise ValueError("invalid original recovery authority")
    _validate_job_approval(settings, original, state)
    if not checkpoint.get("phase"):
        # Before the first checkpoint the Worker cannot have acquired replay
        # authority. Do not treat missing mode as strict, or backfill evidence.
        raise ValueError(
            "no verified frozen checkpoint; preserve evidence and start a new read-only preview"
        )
    require_mode(settings, checkpoint)
    if state.get("recovery_of_job_id") is not None:
        raise ValueError("nested recovery is forbidden; manual review required")
    phase = checkpoint.get("phase")
    if phase not in RECOVERABLE_PHASES:
        raise ValueError("no recoverable frozen phase recorded")
    unit = _literal_unit(state.get("unit"), settings)
    if type(state.get("preview_job_id")) is not int or state["preview_job_id"] <= 0:
        raise ValueError("recovery preview identity missing")
    # Earlier legacy phases retain their private-read authorization path.
    # The newly supported terminal gap always requires frozen digest binding.
    bound = _snapshot_review(settings) or phase == "manual_cleanup_required"
    if bound:
        selection = _literal_unit(state.get("selection"), settings)
        if original.retry_of is not None or not unit.is_relative_to(selection):
            raise ValueError("original recovery approval is not bound to its selection")
    return state, checkpoint, unit, bound


def _recovery_manifest_authority(manifest: dict, checkpoint: dict, *,
                                 frozen_id: int, preview_id: int, unit: Path,
                                 phases=RECOVERABLE_PHASES) -> str:
    """Bind a readable immutable manifest to an existing Worker checkpoint."""
    if (type(checkpoint.get("schema_version")) is not int
            or checkpoint["schema_version"] != 1
            or checkpoint.get("phase") not in phases
            or type(checkpoint.get("frozen_job_id")) is not int
            or checkpoint["frozen_job_id"] != frozen_id
            or type(checkpoint.get("preview_job_id")) is not int
            or checkpoint["preview_job_id"] != preview_id
            or checkpoint.get("unit") != str(unit)
            or checkpoint.get("execution_mode", "strict") != manifest.get("execution_mode", "strict")
            or manifest.get("cleanup_policy") != "deferred"
            or type(manifest.get("job_id")) is not int
            or manifest["job_id"] != frozen_id
            or manifest.get("unit") != str(unit)):
        raise ValueError("recovery checkpoint differs from original frozen authority")
    digest = checkpoint.get("manifest_checksum")
    if not isinstance(digest, str) or digest != _checksum(manifest):
        raise ValueError("recovery requires the original Worker-issued manifest checksum")
    return digest


def _recovery_job_binding(recovery: WorkJob, original: WorkJob,
                          original_state: dict, checkpoint: dict, digest: str) -> None:
    """A queued or repeated request must name the same immutable approval."""
    state = json.loads(recovery.state_json or "{}")
    if (not isinstance(state, dict) or recovery.kind != EXECUTE_KIND
            or int(recovery.id) <= int(original.id)
            or recovery.retry_of != original.id
            or type(state.get("recovery_of_job_id")) is not int
            or state["recovery_of_job_id"] != original.id
            or type(state.get("preview_job_id")) is not int
            or state["preview_job_id"] != original_state["preview_job_id"]
            or state.get("unit") != original_state["unit"]
            or state.get("selection") != original_state.get("selection")
            or state.get("execution_mode", "strict") != original_state.get("execution_mode", "strict")
            or state.get("recovery_manifest_checksum") != digest
            or state.get("recovery_phase") != checkpoint["phase"]):
        raise ValueError("recovery WorkJob differs from its original frozen approval")


def enqueue_media_organizer_abandon(
    session_factory, settings: Settings, *, failed_job_id: int,
) -> dict:
    """Queue a Worker-only closeout for a failed, pre-publication frozen job."""
    _require_enabled(settings)
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        original = session.get(WorkJob, failed_job_id)
        if original is None or original.kind != EXECUTE_KIND:
            raise KeyError(failed_job_id)
        original_state, checkpoint, unit, bound = _original_recovery_authority(original, settings)
        if execution_mode(settings) != "maintenance_window" or checkpoint.get("phase") != "frozen":
            raise ValueError("only a failed frozen task before publication can be ended")
        if not bound:
            raise ValueError("original frozen approval is not bound for closeout")
        manifest_path = _manifest_file(settings, failed_job_id)
        manifest = load_frozen_preview_manifest(
            manifest_path, job_id=failed_job_id, unit=unit,
        )
        digest = _recovery_manifest_authority(
            manifest, checkpoint, frozen_id=failed_job_id,
            preview_id=original_state["preview_job_id"], unit=unit,
            phases=("frozen",),
        )
        existing = session.scalar(select(WorkJob).where(
            WorkJob.kind == EXECUTE_KIND,
            func.json_extract(WorkJob.state_json, "$.abandon_of_job_id") == failed_job_id,
        ).order_by(WorkJob.id.desc()).limit(1))
        if existing is not None:
            if existing.status in (*ACTIVE, "completed"):
                return {"job_id": int(existing.id), "status": existing.status,
                        "abandon_of_job_id": failed_job_id}
            raise ValueError("previous closeout task failed; inspect its error before retry")
        _require_mutation_slot(session, family_id=failed_job_id)
        approved_id = next_media_package_job_id(session, settings)
        job = WorkJob(
            id=approved_id,
            kind=EXECUTE_KIND, status="queued", progress_current=0,
            progress_total=1,
            progress_message="等待 Worker 确认暂存目录已不存在并结束失败任务",
            state_json=json.dumps({
                **_approval_fields(settings, True),
                "approved_job_id": approved_id,
                "confirmation": recovery_token(failed_job_id),
                "preview_job_id": original_state["preview_job_id"],
                "unit": str(unit),
                "selection": original_state.get("selection"),
                "recovery_of_job_id": failed_job_id,
                "recovery_manifest_checksum": digest,
                "recovery_phase": "frozen",
                "abandon_frozen_before_publish": True,
                "abandon_of_job_id": failed_job_id,
            }, ensure_ascii=False),
            retry_of=failed_job_id,
        )
        session.add(job)
        session.commit()
        return {"job_id": int(job.id), "status": job.status,
                "abandon_of_job_id": failed_job_id}


def _abandon_frozen_before_publish(
    job: WorkJob, context: JobContext, settings: Settings, state: dict,
) -> None:
    """End a failed frozen job only when its stage and report residue are absent."""
    original_id = state.get("abandon_of_job_id")
    if type(original_id) is not int or original_id <= 0:
        raise ValueError("invalid failed execution closeout identity")
    with context.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        original = session.get(WorkJob, original_id)
        if original is None or original.kind != EXECUTE_KIND or original.status != "failed":
            raise ValueError("original execution is no longer a failed task")
        original_state, checkpoint, original_unit, bound = _original_recovery_authority(original, settings)
        if (not bound or original_unit != Path(state.get("unit", ""))
                or checkpoint.get("phase") != "frozen"
                or checkpoint.get("execution_mode") != "maintenance_window"):
            raise ValueError("original task is no longer in the pre-publication frozen phase")
        manifest_path = _manifest_file(settings, original_id)
        manifest = load_frozen_preview_manifest(
            manifest_path, job_id=original_id, unit=Path(original_state["unit"]),
        )
        digest = _recovery_manifest_authority(
            manifest, checkpoint, frozen_id=original_id,
            preview_id=original_state["preview_job_id"],
            unit=Path(original_state["unit"]), phases=("frozen",),
        )
        _recovery_job_binding(job, original, original_state, checkpoint, digest)
        if state.get("recovery_manifest_checksum") != digest:
            raise ValueError("closeout approval differs from the original frozen manifest")
        unit_fd = _open_directory_nofollow(Path(manifest["unit"]))
        try:
            try:
                os.stat(manifest["stage_directory"], dir_fd=unit_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("staging directory still exists; the failed task cannot be ended yet")
        finally:
            os.close(unit_fd)
        report_fd = _open_directory_nofollow(manifest_path.parent)
        try:
            with os.scandir(report_fd) as entries:
                names = {entry.name for entry in entries}
            if names != {manifest_path.name}:
                raise ValueError("unexpected frozen-task report residue; preserve it for review")
        finally:
            os.close(report_fd)
        checkpoint["phase"] = "abandoned_before_publish"
        checkpoint["operator_abandoned"] = True
        checkpoint["abandoned_by_job_id"] = int(job.id)
        original.checkpoint_json = json.dumps(checkpoint, ensure_ascii=False, separators=(",", ":"))
        log_task_event(
            session, job_id=original_id,
            event_type="abandoned_before_publish",
            message="管理员结束了发布前失败的整理任务；没有修改媒体文件。",
            context={"abandon_job_id": int(job.id), "stage_absent": True},
        )
        session.commit()
    context.checkpoint(
        progress_current=1, progress_total=1,
        progress_message="失败任务已结束；媒体文件未修改",
        checkpoint_data={
            "schema_version": 1, "phase": "completed",
            "abandoned_job_id": original_id,
        },
    )


def _validate_private_recovery_stage(manifest: dict, manifest_path: Path, phase: str) -> None:
    """Worker live check, also retained by the no-shared-GID legacy API."""
    stage = Path(manifest["unit"]) / manifest["stage_directory"]
    if not stage.is_dir() or stage.is_symlink():
        raise ValueError("trusted staged custody is absent; manual review required")
    from app.batch.media_organizer_stage import (
        _read_marker, _authority, _assert_private_stage_fd,
    )
    from app.batch.media_organizer_retire import (
        _read_retirement_receipt, _retirement_receipt_path,
    )
    fd = _open_directory_nofollow(stage)
    try:
        _assert_private_stage_fd(fd)
        owner_present = _read_marker(fd, ".nfc-stage-authority", _authority(manifest))
        if not owner_present:
            if phase != "published":
                raise ValueError("original staged ownership witness is missing")
            # Retain the legacy published last-marker/rmdir-gap check. The
            # deferred Worker still verifies all stage/source/final inventory.
            with os.scandir(fd) as entries:
                if next(entries, None) is not None:
                    raise ValueError("unwitnessed stage is not empty; manual recovery required")
            _read_retirement_receipt(
                _retirement_receipt_path(manifest_path), manifest, os.fstat(fd),
            )
    finally:
        os.close(fd)


def _resume_frozen_stage(manifest: dict, manifest_path: Path, phase: str) -> bool:
    """Distinguish interruption before the first mkdir from a witnessed partial stage."""
    if manifest.get("execution_mode") == "maintenance_window" and phase == "frozen":
        unit_fd = _open_directory_nofollow(Path(manifest["unit"]))
        try:
            os.stat(manifest["stage_directory"], dir_fd=unit_fd, follow_symlinks=False)
        except FileNotFoundError:
            stage_absent = True
        else:
            stage_absent = False
        finally:
            os.close(unit_fd)
        if stage_absent:
            # Before the first media write the job has only its frozen manifest.
            # Fresh staging rechecks the complete inventory and uses exclusive mkdir.
            report_fd = _open_directory_nofollow(manifest_path.parent)
            try:
                with os.scandir(report_fd) as entries:
                    if {entry.name for entry in entries} != {manifest_path.name}:
                        raise ValueError("unexpected job evidence before initial staging")
            finally:
                os.close(report_fd)
            return False
    _validate_private_recovery_stage(manifest, manifest_path, phase)
    return True


def _frozen_custody_scope(manifest: dict) -> tuple[Path, ...]:
    parents = {Path(manifest["unit"])}
    if manifest.get("execution_mode") == "maintenance_window":
        parents.update(Path(literal) for literal in manifest["wrapper_identities"])
    for row in manifest["moves"]:
        parents.update(Path(row[key]).parent for key in ("source", "target", "final"))
    return tuple(sorted(parents))


def enqueue_media_organizer_recovery(
    session_factory, settings: Settings, *, failed_job_id: int,
    confirmation: str, maintenance_window_confirmed: bool = False,
) -> dict:
    """Create a distinct explicit recovery job tied to original frozen custody."""
    _require_enabled(settings)
    approval = _approval_fields(settings, maintenance_window_confirmed)
    if confirmation != recovery_token(failed_job_id):
        raise ValueError("exact original execution recovery confirmation required")
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        original = session.get(WorkJob, failed_job_id)
        if original is None or original.kind != EXECUTE_KIND:
            raise KeyError(failed_job_id)
        state, checkpoint, selected, bound = _original_recovery_authority(original, settings)
        phase = checkpoint["phase"]
        unit = str(selected)
        original_preview_id = state["preview_job_id"]
        shared = _snapshot_review(settings)
        manifest_path = _manifest_file(settings, failed_job_id)
        manifest = None
        digest = None
        if bound:
            # An explicit shared-GID API may read only shared frozen evidence.
            # It cannot inspect Worker 0700/0600 custody. No error fallback and
            # no digest backfill can turn old/unbound artifacts into authority.
            manifest = load_frozen_preview_manifest(
                manifest_path, job_id=failed_job_id, unit=selected,
            )
            digest = _recovery_manifest_authority(
                manifest, checkpoint, frozen_id=failed_job_id,
                preview_id=original_preview_id, unit=selected,
            )
            if shared and phase == "manual_cleanup_required":
                from app.batch.media_organizer_shared_handoff import read_shared_cleanup_handoff
                read_shared_cleanup_handoff(manifest, manifest_path, checkpoint)
        # Idempotent retransmission of an already-authorized recovery must
        # not demand a staging directory that successful cleanup has removed.
        existing = session.scalar(select(WorkJob).where(
            WorkJob.kind == EXECUTE_KIND,
            func.json_extract(WorkJob.state_json, "$.recovery_of_job_id") == failed_job_id,
        ).order_by(WorkJob.id.desc()).limit(1))
        if existing is not None:
            if existing.status in (*ACTIVE, "completed"):
                _validate_job_approval(settings, existing, json.loads(existing.state_json))
                if bound:
                    _recovery_job_binding(existing, original, state, checkpoint, digest)
                    if existing.status == "completed":
                        completed = json.loads(existing.checkpoint_json or "{}")
                        if not isinstance(completed, dict):
                            raise ValueError("invalid completed recovery checkpoint")
                        _recovery_manifest_authority(
                            manifest, completed, frozen_id=failed_job_id,
                            preview_id=original_preview_id, unit=selected,
                            phases=("manual_cleanup_required", "completed"),
                        )
                return {"job_id": int(existing.id), "status": existing.status,
                        "recovery_of_job_id": failed_job_id, **mode_fields(approval["execution_mode"])}
            raise ValueError("prior recovery failed; manual review required")
        if manifest is None:
            manifest = load_frozen_preview_manifest(
                manifest_path, job_id=failed_job_id, unit=selected,
            )
        require_mode(settings, manifest)
        if manifest.get("job_id") != failed_job_id:
            raise ValueError("frozen job identity changed")
        if not shared:
            _validate_private_recovery_stage(manifest, manifest_path, phase)
        # A known missing/revoked scope must not consume the one assisted
        # recovery attempt, including a flat stage. The Worker independently
        # reacquires custody before any mutation.
        check_api_eligibility(settings, selected, _frozen_custody_scope(manifest))
        _require_mutation_slot(session, family_id=failed_job_id if maintenance_window_confirmed else None)
        approved_id = next_media_package_job_id(session, settings)
        job = WorkJob(
            id=approved_id,
            kind=EXECUTE_KIND, status="queued", progress_current=0,
            progress_total=4,
            progress_message="等待 Worker 使用原冻结清单安全恢复",
            state_json=json.dumps({
                **approval, "approved_job_id": approved_id, "confirmation": confirmation,
                "preview_job_id": original_preview_id, "unit": unit,
                "selection": state.get("selection"),
                "recovery_of_job_id": failed_job_id,
                **({"recovery_manifest_checksum": digest, "recovery_phase": phase}
                   if bound else {}),
            }, ensure_ascii=False),
            retry_of=failed_job_id,
        )
        session.add(job)
        session.commit()
        return {"job_id": int(job.id), "status": job.status,
                "recovery_of_job_id": failed_job_id, **mode_fields(approval["execution_mode"])}


@register_handler
class MediaOrganizerExecuteHandler(TaskHandler):
    job_type = EXECUTE_KIND
    supports_cancel = False
    supports_retry = False
    supports_pause = False
    supports_resume = False  # Only explicit new recovery WorkJob is supported.

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        with ExitStack() as resources:
            self._run(job, context, settings, resources)

    def _run(self, job: WorkJob, context: JobContext, settings: Settings, resources: ExitStack) -> None:
        _require_enabled(settings)
        if not context.worker_id:
            raise PermissionError("exclusive Worker lease required for media mutation")
        _require_mutation_worker_identity(settings)
        state = json.loads(job.state_json or "{}")
        if not isinstance(state, dict):
            raise ValueError("invalid execution WorkJob approval")
        _validate_job_approval(settings, job, state)
        if state.get("abandon_frozen_before_publish") is True:
            _abandon_frozen_before_publish(job, context, settings, state)
            return
        mode = execution_mode(settings)
        original_id = state.get("recovery_of_job_id")
        preview_id = state.get("preview_job_id")
        unit = _literal_unit(state.get("unit"), settings)
        if not isinstance(preview_id, int) or preview_id < 1:
            raise ValueError("missing original preview job id")

        custody = None
        custody_parents: tuple[Path, ...] = ()

        def fence() -> None:
            from app.tasks.recovery import renew_and_assert_worker_lease
            renew_and_assert_worker_lease(context.SessionLocal, context.worker_id)
            if custody is not None:
                assert_operation_authorized(custody, custody_parents)

        def bind_authority(manifest: dict) -> None:
            nonlocal custody, custody_parents
            require_mode(settings, manifest)
            custody_parents = _frozen_custody_scope(manifest)
            custody = resources.enter_context(acquire_operation_authority(
                settings, unit, custody_parents, manifest=manifest,
                maintenance_window_confirmed=state.get("maintenance_window_confirmed") is True,
            ))
            assert_operation_authorized(custody, custody_parents)

        frozen_job_id = int(job.id) if original_id is None else original_id
        phase = "new"
        resume_stage = False
        if original_id is not None:
            if type(original_id) is not int or original_id <= 0:
                raise ValueError("invalid original failed execution identity")
            with context.SessionLocal() as session:
                original = session.get(WorkJob, original_id)
                if original is None:
                    raise ValueError("original failed job no longer provides recovery authority")
                original_state, original_checkpoint, original_unit, bound = (
                    _original_recovery_authority(original, settings)
                )
                if (original_unit != unit
                        or original_state["preview_job_id"] != preview_id):
                    raise ValueError("recovery binding differs from original approval")
                phase = original_checkpoint["phase"]
        folder = _execution_folder(settings, frozen_job_id)
        manifest_path = _manifest_file(settings, frozen_job_id)
        handoff_checkpoint = {}

        def checkpoint(n: int, phase_name: str, message: str) -> None:
            pending_count = (len(classify_path_roles(manifest)["deferred_rows"])
                             if uses_path_roles(manifest) else 0)
            context.checkpoint(
                progress_current=n, progress_total=4, progress_message=message,
                checkpoint_data={
                    "schema_version": 1, "phase": phase_name, "preview_job_id": preview_id,
                    "frozen_job_id": frozen_job_id, "unit": str(unit),
                    "deferred_publication_count": pending_count, **mode_fields(mode),
                    **handoff_checkpoint,
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
            if mode == "maintenance_window" and (
                    state.get("selection") != str(selection)
                    or state.get("input_fingerprint") != record["input_fingerprint"]):
                raise ValueError("approved unit differs from the reviewed preview evidence")
            if manifest_path.exists() or manifest_path.is_symlink():
                raise ValueError("untrusted frozen manifest file already exists")
            manifest = build_frozen_preview_manifest(
                unit, preview_record=record, allowed_roots=settings.allowed_roots,
                quarantine_root=settings.quarantine_root, job_id=frozen_job_id,
                exclude_dir_names=_excluded_names(settings),
            )
            manifest["execution_mode"] = mode
            manifest["cleanup_policy"] = "deferred"
            roles = classify_path_roles(manifest)
            if roles["retained_sources"] or roles["retained_groups"] or roles["deferred_rows"]:
                manifest["path_role_policy"] = POLICY
            bind_authority(manifest)
            # Only newly frozen, explicitly versioned plans can retain final
            # roles or defer occupied final names to separately approved cleanup.
            validate_deferred_publication(manifest, namespace_custody=custody)
            shared_gid = shared_config_gid()
            if shared_gid is None:
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                # Newly created job evidence is readable by the trusted API
                # group; incompatible legacy private dirs must fail closed.
                ensure_shared_report_directory(folder.parent, shared_gid)
                ensure_shared_report_directory(folder, shared_gid)
            fence()
            save_frozen_preview_manifest(manifest_path, manifest)
        else:
            manifest = load_frozen_preview_manifest(
                manifest_path, job_id=frozen_job_id, unit=unit,
            )
            if bound:
                digest = _recovery_manifest_authority(
                    manifest, original_checkpoint, frozen_id=frozen_job_id,
                    preview_id=preview_id, unit=unit,
                )
                _recovery_job_binding(job, original, original_state, original_checkpoint, digest)
                if (_snapshot_review(settings)
                        and phase == "manual_cleanup_required"):
                    from app.batch.media_organizer_shared_handoff import read_shared_cleanup_handoff
                    read_shared_cleanup_handoff(manifest, manifest_path, original_checkpoint)
            bind_authority(manifest)
            # Shared API authorization was a frozen-artifact snapshot only.
            # Every recovery still proves private custody in the Worker,
            # followed by the complete phase-specific live inventory checks.
            resume_stage = _resume_frozen_stage(manifest, manifest_path, phase)
        validate_deferred_publication(manifest, namespace_custody=custody)
        # The Worker records this immutable authority before staging. All new
        # phases retain it, including interruption before the completed commit.
        # Existing checkpoints are never repaired/backfilled by the API.
        handoff_checkpoint = {"manifest_checksum": _checksum(manifest)}
        checkpoint(1, "frozen", "冻结清单已经验证")
        if phase not in ("published", "manual_cleanup_required"):
            # An interruption in staging or publication retains all private
            # source links, so retry those phases only with the original
            # checksum-validated manifest and owner witness.
            fence()
            stage_frozen_sources(
                manifest, frozen_manifest_path=manifest_path,
                allowed_roots=settings.allowed_roots,
                quarantine_root=settings.quarantine_root, lease_fence=fence,
                resume=resume_stage,
            )
            checkpoint(2, "staged", "全部已暂存，开始核验与无覆盖发布")
            fence()
            publish_frozen_stage(
                manifest, frozen_manifest_path=manifest_path,
                allowed_roots=settings.allowed_roots,
                quarantine_root=settings.quarantine_root, lease_fence=fence,
                resume=resume_stage,
                defer_directory_cleanup=True, namespace_custody=custody,
            )
        # The safe execution path never removes original classification
        # wrappers, private staged hardlinks or recovery witnesses.
        # Its durable marker, not the source layout, governs continuation:
        # never attempt restaging after the original job reached published.
        deferred_count = (len(classify_path_roles(manifest)["deferred_rows"])
                          if uses_path_roles(manifest) else 0)
        checkpoint(3, "published", (
            "暂存和可用目标已验证，正在准备需单独确认的最终重排清单"
            if deferred_count else "已发布文件，正在核验人工清理凭证"
        ))
        fence()
        record_deferred_cleanup_evidence(
            manifest, frozen_manifest_path=manifest_path,
            allowed_roots=settings.allowed_roots,
            quarantine_root=settings.quarantine_root, lease_fence=fence,
            namespace_custody=custody,
        )
        # Commit durable, immutable per-link review authority BEFORE the
        # publication is marked completed. This performs no media cleanup.
        fence()
        audit_deferred_cleanup_inventory(
            manifest, frozen_manifest_path=manifest_path,
            allowed_roots=settings.allowed_roots,
            quarantine_root=settings.quarantine_root,
        )
        save_cleanup_plan(cleanup_plan_path(manifest_path), manifest)
        if _snapshot_review(settings):
            from app.batch.media_organizer_shared_handoff import shared_handoff_checkpoint
            handoff_checkpoint = shared_handoff_checkpoint(manifest, manifest_path)
        checkpoint(
            4, "manual_cleanup_required",
            ("全部原文件与暂存副本已保留；目标重排及清理等待单独确认"
             if deferred_count else
             "媒体文件已发布；旧分类目录和暂存文件已保留，等待人工核查清理"),
        )
