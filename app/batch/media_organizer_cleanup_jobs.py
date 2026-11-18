"""A separate, confirmed WorkJob for FINAL V1.6 cleanup (#400).

Important: this is wired but permanently fail-closed in production until
the externally reviewed NAS namespace-custody issuer exists. No API request
unlinks data; only the dedicated non-root Worker invokes the resumable
finalizer after frozen evidence, a second confirmation and a lease fence.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select, text

from app.batch import media_organizer_custody as namespace_custody
from app.batch.media_organizer_cleanup_plan import (
    cleanup_plan_path, _read_existing,
)
from app.batch.media_organizer_execute_jobs import (
    EXECUTE_KIND, ACTIVE, _require_enabled, _require_nonroot_mutation_worker,
    _literal_unit, _manifest_file, get_media_organizer_cleanup_plan,
)
from app.batch.media_organizer_finalize import (
    cleanup_confirmation, finish_deferred_cleanup,
)
from app.batch.media_organizer_manifest import load_frozen_preview_manifest
from app.batch.media_package_report_lifecycle import next_media_package_job_id
from app.config import Settings
from app.models import WorkJob
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler

CLEANUP_KIND = "media-organizer-cleanup"


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
    execution_job_id: int, confirmation: str,
) -> dict:
    """Queue exactly one separately approved cleanup job, without media writes."""
    _require_enabled(settings)
    if not isinstance(confirmation, str) or not confirmation:
        raise ValueError("exact separate cleanup approval required")

    # Read-only *full* frozen inventory audit and trusted original WorkJob.
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
    proof = namespace_custody.verified_namespace_custody(settings, unit)
    namespace_custody.assert_exclusive_custody(
        proof, _cleanup_scope(manifest),
    )

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        prior = session.get(WorkJob, execution_job_id)
        if prior is None or prior.kind != EXECUTE_KIND:
            raise KeyError(execution_job_id)
        phase = json.loads(prior.checkpoint_json or "{}").get("phase")
        if prior.status != "completed" or phase != "manual_cleanup_required":
            raise ValueError("cleanup is not ready for separate confirmation")
        matches = session.scalars(select(WorkJob).where(
            WorkJob.kind == CLEANUP_KIND,
            func.json_extract(WorkJob.state_json, "$.execution_job_id") == execution_job_id,
        ).order_by(WorkJob.id.desc())).all()
        if matches:
            existing = matches[0]
            if existing.status in (*ACTIVE, "completed"):
                return {"job_id": int(existing.id), "status": existing.status,
                        "execution_job_id": execution_job_id}
            raise ValueError("failed cleanup requires explicit journal recovery review")
        if session.scalar(select(WorkJob.id).where(
            WorkJob.kind.in_((CLEANUP_KIND, EXECUTE_KIND)),
            WorkJob.status.in_(ACTIVE),
        ).limit(1)) is not None:
            raise ValueError("another V1.6 mutation WorkJob is active")

        job = WorkJob(
            id=next_media_package_job_id(session, settings),
            kind=CLEANUP_KIND, status="queued", progress_current=0,
            progress_total=2,
            progress_message="等待专用 Worker 验证清理授权和独占目录权限",
            state_json=json.dumps({
                "execution_job_id": execution_job_id,
                "frozen_job_id": frozen_id,
                "unit": str(unit),
                "plan_sha256": review["plan_sha256"],
                "confirmation": confirmation,
            }, ensure_ascii=False),
        )
        session.add(job)
        session.commit()
        return {"job_id": int(job.id), "status": job.status,
                "execution_job_id": execution_job_id}


@register_handler
class MediaOrganizerCleanupHandler(TaskHandler):
    job_type = CLEANUP_KIND
    supports_cancel = False
    supports_retry = False
    supports_pause = False
    supports_resume = False  # Immutable journal may need a NEW explicit recovery Job.

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        _require_enabled(settings)
        if not context.worker_id:
            raise PermissionError("exclusive Worker lease required for cleanup")
        _require_nonroot_mutation_worker()
        state = json.loads(job.state_json or "{}")
        execution_id = state.get("execution_job_id")
        frozen_id = state.get("frozen_job_id")
        unit = _literal_unit(state.get("unit"), settings)
        if (not isinstance(execution_id, int) or execution_id <= 0
                or not isinstance(frozen_id, int) or frozen_id <= 0):
            raise ValueError("invalid frozen cleanup WorkJob identity")
        with context.SessionLocal() as session:
            original = session.get(WorkJob, execution_id)
            if original is None or original.kind != EXECUTE_KIND:
                raise ValueError("original approved publication is missing")
            original_state = json.loads(original.state_json or "{}")
            original_checkpoint = json.loads(original.checkpoint_json or "{}")
            if (original.status != "completed"
                    or original_checkpoint.get("phase") != "manual_cleanup_required"
                    or original_checkpoint.get("frozen_job_id") != frozen_id
                    or original_state.get("unit") != str(unit)):
                raise ValueError("original cleanup approval is stale or unrelated")
        frozen = _manifest_file(settings, frozen_id)
        manifest = load_frozen_preview_manifest(
            frozen, job_id=frozen_id, unit=unit,
        )
        plan = _read_existing(cleanup_plan_path(frozen))
        if (state.get("plan_sha256") != plan.get("plan_sha256")
                or state.get("confirmation") != cleanup_confirmation(
                    frozen_id, str(unit), plan["plan_sha256"],
                )):
            raise ValueError("cleanup WorkJob confirmation differs from frozen plan")
        proof = namespace_custody.verified_namespace_custody(settings, unit)
        namespace_custody.assert_exclusive_custody(
            proof, _cleanup_scope(manifest),
        )

        # Revalidate the Worker lease and scoped custody at EACH cleanup step,
        # not merely when the API queues the WorkJob.
        class FencedCustody:
            def assert_exclusive(self, folder: Path) -> None:
                from app.tasks.recovery import renew_and_assert_worker_lease
                renew_and_assert_worker_lease(context.SessionLocal, context.worker_id)
                namespace_custody.assert_exclusive_custody(proof, (folder,))

        context.checkpoint(
            progress_current=0, progress_total=2,
            progress_message="冻结清单与独占目录凭证已复核，开始可恢复清理",
            checkpoint_data={"schema_version": 1, "phase": "cleanup-verified",
                             "execution_job_id": execution_id, "frozen_job_id": frozen_id},
        )
        result = finish_deferred_cleanup(
            manifest, frozen_manifest_path=frozen,
            allowed_roots=settings.allowed_roots,
            quarantine_root=settings.quarantine_root,
            confirmation=state["confirmation"], custody=FencedCustody(),
        )
        if (not result["finalized"] or result["needed_moves"] != 0
                or result["renamed_count"] != 0):
            raise ValueError("finalization did not prove zero-change second scan")
        context.checkpoint(
            progress_current=1, progress_total=2,
            progress_message="原路径与暂存清理完成；二次扫描已确认零变更",
            checkpoint_data={"schema_version": 1, "phase": "cleanup-scanned-zero",
                             "execution_job_id": execution_id, "frozen_job_id": frozen_id},
        )
        # Durability ordering: update the original job's finalized status ONLY
        # after the resumable file-system journal has a committed final marker.
        with context.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            original = session.get(WorkJob, execution_id)
            if original is None or original.kind != EXECUTE_KIND:
                raise ValueError("original WorkJob changed during cleanup")
            current = json.loads(original.checkpoint_json or "{}")
            if (original.status != "completed"
                    or current.get("frozen_job_id") != frozen_id
                    or current.get("phase") != "manual_cleanup_required"):
                raise ValueError("original WorkJob finalization authority changed")
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
            checkpoint_data={"schema_version": 1, "phase": "completed",
                             "execution_job_id": execution_id, "frozen_job_id": frozen_id},
        )
