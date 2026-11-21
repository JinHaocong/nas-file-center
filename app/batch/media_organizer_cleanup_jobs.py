"""A separate, confirmed WorkJob for FINAL V1.6 cleanup (#400).

Only the non-root Worker invokes the resumable finalizer under the approved
execution mode, after frozen evidence, a fresh confirmation and a lease fence.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select, text

from app.batch.media_organizer_authority import (
    check_api_eligibility, acquire_operation_authority, assert_operation_authorized,
    fence_operation_authority,
)
from app.batch.media_organizer_jobs import mode_fields, require_mode
from app.batch.media_organizer_cleanup_plan import (
    cleanup_plan_path, _read_existing,
)
from app.batch.media_organizer_execute_jobs import (
    EXECUTE_KIND, ACTIVE, _require_enabled, _require_nonroot_mutation_worker,
    _literal_unit, _manifest_file, get_media_organizer_cleanup_plan,
    _approval_fields, _validate_job_approval, _snapshot_review, _require_mutation_slot,
    _validate_publication_family,
)
from app.batch.media_organizer_finalize import (
    cleanup_confirmation, finish_deferred_cleanup, _operations,
)
from app.batch.media_organizer_manifest import _checksum, load_frozen_preview_manifest
from app.batch.media_package_report_lifecycle import next_media_package_job_id
from app.config import Settings
from app.models import WorkJob
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler

CLEANUP_KIND = "media-organizer-cleanup"


def cleanup_recovery_confirmation(cleanup_job_id: int, frozen_job_id: int,
                                  unit: str, plan_sha256: str) -> str:
    """A new approval for this failed attempt, never implicit cleanup retry."""
    if type(cleanup_job_id) is not int or cleanup_job_id <= 0:
        raise ValueError("invalid failed cleanup identity")
    return (f"RECOVER_CLEANUP_JOB_{cleanup_job_id}_"
            + cleanup_confirmation(frozen_job_id, unit, plan_sha256))


def _cleanup_checkpoint_binding(state: dict, cleanup_job_id: int) -> dict:
    fields = ("execution_job_id", "frozen_job_id", "unit", "plan_sha256", "manifest_checksum")
    return {"cleanup_job_id": cleanup_job_id, **{field: state.get(field) for field in fields}}


def _validated_state(job: WorkJob, settings: Settings) -> dict:
    state = json.loads(job.state_json or "{}")
    if not isinstance(state, dict) or job.kind != CLEANUP_KIND:
        raise ValueError("invalid cleanup WorkJob authority")
    _validate_job_approval(settings, job, state)
    checkpoint = json.loads(job.checkpoint_json or "{}")
    if checkpoint:
        mode = require_mode(settings, checkpoint)
        if mode == "maintenance_window" and any(
                checkpoint.get(key) != value for key, value in _cleanup_checkpoint_binding(state, job.id).items()):
            raise ValueError("cleanup checkpoint differs from the approved frozen evidence")
    for field in ("execution_job_id", "frozen_job_id"):
        if type(state.get(field)) is not int or state[field] <= 0:
            raise ValueError("invalid frozen cleanup WorkJob identity")
    unit = str(_literal_unit(state.get("unit"), settings))
    digest = state.get("plan_sha256")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("invalid immutable cleanup plan checksum")
    if (state.get("unit") != unit or state.get("confirmation") != cleanup_confirmation(
            state["frozen_job_id"], unit, digest)):
        raise ValueError("cleanup WorkJob confirmation differs from frozen plan")
    return state


def _cleanup_ancestry(session, job: WorkJob, state: dict,
                      settings: Settings) -> set[int]:
    """Validate every explicit failed predecessor; never adopt another unit."""
    ids: set[int] = set()
    fields = ("execution_job_id", "frozen_job_id", "unit", "plan_sha256", "confirmation")
    current = job
    while len(ids) < 128:
        current_state = _validated_state(current, settings)
        if any(current_state.get(key) != state[key] for key in fields):
            raise ValueError("cleanup recovery ancestry belongs to another frozen plan")
        if current.id in ids:
            raise ValueError("cyclic cleanup recovery ancestry")
        ids.add(int(current.id))
        parent_id = current_state.get("recovery_of_job_id")
        if parent_id is None:
            if current.retry_of is not None or "recovery_confirmation" in current_state:
                raise ValueError("unbound cleanup recovery ancestry")
            return ids
        if (type(parent_id) is not int or not 0 < parent_id < current.id
                or current.retry_of != parent_id
                or current_state.get("recovery_confirmation") != cleanup_recovery_confirmation(
                    parent_id, state["frozen_job_id"], state["unit"], state["plan_sha256"])):
            raise ValueError("cleanup recovery approval is not bound to its predecessor")
        parent = session.get(WorkJob, parent_id)
        if parent is None or parent.kind != CLEANUP_KIND or parent.status != "failed":
            raise ValueError("cleanup recovery predecessor is not failed")
        current = parent
    raise ValueError("cleanup recovery ancestry exceeds review limit")


def _original_for_cleanup(session, state: dict, finalizers: set[int], settings: Settings) -> WorkJob:
    original = session.get(WorkJob, state["execution_job_id"])
    if original is None or original.kind != EXECUTE_KIND:
        raise ValueError("original approved publication is missing")
    original_state = json.loads(original.state_json or "{}")
    checkpoint = json.loads(original.checkpoint_json or "{}")
    _validate_publication_family(session, settings, original, original_state, checkpoint)
    if state.get("execution_mode") == "maintenance_window" and (
            checkpoint.get("cleanup_plan_sha256") != state["plan_sha256"]
            or checkpoint.get("unit") != state["unit"]
            or checkpoint.get("manifest_checksum") != state.get("manifest_checksum")):
        raise ValueError("cleanup approval differs from the completed Worker handoff")
    if (original.status != "completed"
            or checkpoint.get("frozen_job_id") != state["frozen_job_id"]
            or original_state.get("unit") != state["unit"]):
        raise ValueError("original cleanup approval is stale or unrelated")
    phase = checkpoint.get("phase")
    if phase == "completed":
        finalized_by = checkpoint.get("finalized_by_cleanup_job_id")
        if type(finalized_by) is not int or finalized_by not in finalizers:
            raise ValueError("original finalization belongs to another cleanup")
    elif phase != "manual_cleanup_required":
        raise ValueError("original publication is not ready for cleanup")
    return original


def _frozen_cleanup_plan(settings: Settings, state: dict, original: WorkJob):
    frozen = _manifest_file(settings, state["frozen_job_id"])
    manifest = load_frozen_preview_manifest(
        frozen, job_id=state["frozen_job_id"], unit=Path(state["unit"]),
    )
    require_mode(settings, manifest)
    if state.get("execution_mode") == "maintenance_window":
        from app.batch.media_organizer_shared_handoff import read_shared_cleanup_handoff
        # The caller already checked the publication's phase and finalizer ancestry.
        handoff = read_shared_cleanup_handoff(
            manifest, frozen, json.loads(original.checkpoint_json), allow_finalized=True,
        )
        plan = handoff["plan"]
    else:
        plan = _read_existing(cleanup_plan_path(frozen))
        _operations(manifest, plan)
    if state["plan_sha256"] != plan.get("plan_sha256"):
        raise ValueError("cleanup WorkJob differs from immutable plan")
    # Pure frozen-plan validation: stage may already have been removed by
    # the failed Worker. Only that Worker's private journal authorizes replay.
    return frozen, manifest


def _receipt(job: WorkJob, state: dict) -> dict:
    result = {**mode_fields(state.get("execution_mode", "strict")),
              "job_id": int(job.id), "status": job.status,
              "execution_job_id": state["execution_job_id"]}
    if state.get("recovery_of_job_id") is not None:
        result["recovery_of_job_id"] = state["recovery_of_job_id"]
    return result


def _existing_cleanup(session, execution_job_id: int):
    return session.scalar(select(WorkJob).where(
        WorkJob.kind == CLEANUP_KIND,
        func.json_extract(WorkJob.state_json, "$.execution_job_id") == execution_job_id,
    ).order_by(WorkJob.id.desc()).limit(1))


def _approved_existing(session, job: WorkJob, confirmation: str, settings: Settings):
    state = _validated_state(job, settings)
    if confirmation != state["confirmation"]:
        raise ValueError("exact separate cleanup confirmation required")
    _original_for_cleanup(session, state, _cleanup_ancestry(session, job, state, settings), settings)
    if job.status not in (*ACTIVE, "completed"):
        raise ValueError("failed cleanup requires explicit journal recovery review")
    return _receipt(job, state)


def _cleanup_scope(manifest: dict) -> tuple[Path, ...]:
    unit = Path(manifest["unit"])
    parents = {unit}
    for row in manifest["moves"]:
        parents.update((
            Path(row["source"]).parent,
            Path(row["target"]).parent,
            Path(row["final"]).parent,
        ))
    for literal in manifest["wrapper_identities"]:
        parents.add(Path(literal).parent)
    return tuple(sorted(parents))


def enqueue_media_organizer_cleanup(
    session_factory, settings: Settings, *,
    execution_job_id: int, confirmation: str, maintenance_window_confirmed: bool = False,
) -> dict:
    """Queue exactly one separately approved cleanup job, without media writes."""
    _require_enabled(settings)
    approval = _approval_fields(settings, maintenance_window_confirmed)
    if not isinstance(confirmation, str) or not confirmation:
        raise ValueError("exact separate cleanup approval required")

    # A response lost after cleanup must not require already-deleted source
    # names. This path only returns the existing approved job; it cannot run it.
    with session_factory() as session:
        existing = _existing_cleanup(session, execution_job_id)
        if existing is not None:
            return _approved_existing(session, existing, confirmation, settings)

    # Explicit shared mode reads the completed Worker's bound snapshot;
    # legacy mode retains the live audit. The Worker always audits again.
    shared = _snapshot_review(settings)
    review = get_media_organizer_cleanup_plan(
        session_factory, settings, execution_job_id, page=1, page_size=1,
    )
    frozen_id = int(review["job_id"])
    unit = _literal_unit(review["unit"], settings)
    expected = cleanup_confirmation(
        frozen_id, str(unit), review["plan_sha256"],
    )
    if confirmation != expected:
        raise ValueError("exact separate cleanup confirmation required")
    manifest_path = _manifest_file(settings, frozen_id)
    manifest = load_frozen_preview_manifest(
        manifest_path, job_id=frozen_id, unit=unit,
    )
    if _checksum(manifest) != review["manifest_checksum"]:
        raise ValueError("frozen manifest changed after cleanup review")
    require_mode(settings, manifest)
    check_api_eligibility(settings, unit, _cleanup_scope(manifest))

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        prior = session.get(WorkJob, execution_job_id)
        if prior is None or prior.kind != EXECUTE_KIND:
            raise KeyError(execution_job_id)
        checkpoint = json.loads(prior.checkpoint_json or "{}")
        _validate_publication_family(session, settings, prior, json.loads(prior.state_json), checkpoint)
        phase = checkpoint.get("phase")
        if prior.status != "completed" or phase != "manual_cleanup_required":
            raise ValueError("cleanup is not ready for separate confirmation")
        if shared and (
                checkpoint.get("manifest_checksum") != review["manifest_checksum"]
                or checkpoint.get("cleanup_plan_sha256") != review["plan_sha256"]
                or checkpoint.get("frozen_job_id") != frozen_id
                or checkpoint.get("unit") != str(unit)):
            raise ValueError("completed Worker snapshot changed before cleanup queue")
        existing = _existing_cleanup(session, execution_job_id)
        if existing is not None:
            return _approved_existing(session, existing, confirmation, settings)
        _require_mutation_slot(session, family_id=frozen_id if maintenance_window_confirmed else None)

        approved_id = next_media_package_job_id(session, settings)
        job = WorkJob(
            id=approved_id,
            kind=CLEANUP_KIND, status="queued", progress_current=0,
            progress_total=2,
            progress_message=("等待专用 Worker 核验维护窗口清理授权和操作范围"
                              if maintenance_window_confirmed else "等待专用 Worker 验证清理授权和独占目录权限"),
            state_json=json.dumps({
                **approval, "approved_job_id": approved_id, "manifest_checksum": _checksum(manifest),
                "execution_job_id": execution_job_id,
                "frozen_job_id": frozen_id,
                "unit": str(unit),
                "plan_sha256": review["plan_sha256"],
                "confirmation": confirmation,
            }, ensure_ascii=False),
        )
        session.add(job)
        session.commit()
        return _receipt(job, json.loads(job.state_json))


def enqueue_media_organizer_cleanup_recovery(
    session_factory, settings: Settings, *, failed_job_id: int, confirmation: str,
    maintenance_window_confirmed: bool = False,
) -> dict:
    """Queue explicit recovery; private journal reconciliation stays in Worker."""
    _require_enabled(settings)
    approval = _approval_fields(settings, maintenance_window_confirmed)
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        failed = session.get(WorkJob, failed_job_id)
        if failed is None or failed.kind != CLEANUP_KIND:
            raise KeyError(failed_job_id)
        if failed.status != "failed":
            raise ValueError("only a failed cleanup can be explicitly recovered")
        state = _validated_state(failed, settings)
        expected = cleanup_recovery_confirmation(
            failed_job_id, state["frozen_job_id"], state["unit"], state["plan_sha256"],
        )
        if confirmation != expected:
            raise ValueError("exact failed-cleanup recovery confirmation required")
        ancestors = _cleanup_ancestry(session, failed, state, settings)
        existing = session.scalar(select(WorkJob).where(
            WorkJob.kind == CLEANUP_KIND,
            func.json_extract(WorkJob.state_json, "$.recovery_of_job_id") == failed_job_id,
        ).order_by(WorkJob.id.desc()).limit(1))
        if existing is not None:
            if existing.status not in (*ACTIVE, "completed"):
                raise ValueError("recover the latest failed cleanup attempt explicitly")
            existing_state = _validated_state(existing, settings)
            ancestry = _cleanup_ancestry(session, existing, existing_state, settings)
            _original_for_cleanup(session, existing_state, ancestry, settings)
            return _receipt(existing, existing_state)
        original = _original_for_cleanup(session, state, ancestors, settings)
        _, manifest = _frozen_cleanup_plan(settings, state, original)
        check_api_eligibility(settings, Path(state["unit"]), _cleanup_scope(manifest))
        _require_mutation_slot(session, family_id=state["frozen_job_id"] if maintenance_window_confirmed else None)
        recovery_state = {key: state[key] for key in (
            "execution_job_id", "frozen_job_id", "unit", "plan_sha256", "confirmation",
        )}
        approved_id = next_media_package_job_id(session, settings)
        recovery_state.update(approval, approved_job_id=approved_id, manifest_checksum=_checksum(manifest))
        recovery_state.update({"recovery_of_job_id": failed_job_id,
                               "recovery_confirmation": confirmation})
        job = WorkJob(
            id=approved_id, kind=CLEANUP_KIND,
            status="queued", progress_current=0, progress_total=2,
            progress_message="等待专用 Worker 核验原清理日志并恢复",
            state_json=json.dumps(recovery_state, ensure_ascii=False),
            retry_of=failed_job_id,
        )
        session.add(job)
        session.commit()
        return _receipt(job, recovery_state)


@register_handler
class MediaOrganizerCleanupHandler(TaskHandler):
    job_type = CLEANUP_KIND
    supports_cancel = False
    supports_retry = False
    supports_pause = False
    supports_resume = False  # Restart marks failed; a NEW confirmed job may recover.

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        _require_enabled(settings)
        if not context.worker_id:
            raise PermissionError("exclusive Worker lease required for cleanup")
        _require_nonroot_mutation_worker()
        state = _validated_state(job, settings)
        unit = Path(state["unit"])
        with context.SessionLocal() as session:
            original = _original_for_cleanup(
                session, state, _cleanup_ancestry(session, job, state, settings), settings,
            )
            frozen, manifest = _frozen_cleanup_plan(settings, state, original)
        with acquire_operation_authority(
            settings, unit, _cleanup_scope(manifest), manifest=manifest,
            maintenance_window_confirmed=state.get("maintenance_window_confirmed") is True,
        ) as proof:
            self._finalize(job, context, settings, state, frozen, manifest, proof)

    def _finalize(self, job, context, settings, state, frozen, manifest, proof) -> None:
        binding = {**mode_fields(state.get("execution_mode", "strict")), **_cleanup_checkpoint_binding(state, job.id)}

        def renew_lease():
            from app.tasks.recovery import renew_and_assert_worker_lease
            renew_and_assert_worker_lease(context.SessionLocal, context.worker_id)

        fenced = fence_operation_authority(proof, renew_lease)
        assert_operation_authorized(fenced, _cleanup_scope(manifest))
        context.checkpoint(
            progress_current=0, progress_total=2,
            progress_message=("冻结清单与维护窗口授权已复核，开始可恢复清理"
                              if binding["requires_maintenance_window"] else "冻结清单与独占目录凭证已复核，开始可恢复清理"),
            checkpoint_data={**binding, "schema_version": 1, "phase": "cleanup-verified"},
        )
        result = finish_deferred_cleanup(
            manifest, frozen_manifest_path=frozen,
            allowed_roots=settings.allowed_roots,
            quarantine_root=settings.quarantine_root,
            confirmation=state["confirmation"], custody=fenced,
        )
        if (not result["finalized"] or result["needed_moves"] != 0
                or result["renamed_count"] != 0):
            raise ValueError("finalization did not prove zero-change second scan")
        context.checkpoint(
            progress_current=1, progress_total=2,
            progress_message="原路径与暂存清理完成；二次扫描已确认零变更",
            checkpoint_data={**binding, "schema_version": 1, "phase": "cleanup-scanned-zero"},
        )
        # Durability ordering: update the original job's finalized status ONLY
        # after the resumable file-system journal has a committed final marker.
        with context.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            from app.tasks.recovery import assert_active_worker_lease
            assert_active_worker_lease(session, context.worker_id)
            assert_operation_authorized(proof, _cleanup_scope(manifest))
            current_job = session.get(WorkJob, int(job.id))
            if (current_job is None or current_job.status != "running"
                    or _validated_state(current_job, settings) != state):
                raise ValueError("cleanup WorkJob authority changed before finalization")
            original = _original_for_cleanup(session, state, _cleanup_ancestry(
                session, current_job, state, settings,
            ), settings)
            current = json.loads(original.checkpoint_json or "{}")
            current.update({
                "phase": "completed",
                "finalized_by_cleanup_job_id": int(job.id),
                "second_scan_needed_moves": 0,
                "second_scan_renamed_count": 0,
            })
            original.checkpoint_json = json.dumps(
                current, ensure_ascii=False, separators=(",", ":"),
            )
            original.progress_message = "全部文件已整理并安全清理；二次扫描零变更"
            session.commit()
        context.checkpoint(
            progress_current=2, progress_total=2,
            progress_message="已完成清理及零变更复扫",
            checkpoint_data={**binding, "schema_version": 1, "phase": "completed"},
        )
