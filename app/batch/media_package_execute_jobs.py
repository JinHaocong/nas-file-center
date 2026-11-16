"""MediaPackage guarded execution queue: preview -> freeze/check -> no-replace Worker.

Mutation is never triggered by a scan or ordinary GET. An administrator must
submit the exact preview-bound confirmation after completed read-only review.
The Worker refuses to run without the existing exclusive lease.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import func, select, text
from app.batch.media_package_jobs import PREVIEW_KIND, _files as _preview_files, _root
from app.batch.media_package_organizer import _package_path
from app.batch.media_package_execution import (
    MediaPackageExecutionConflict, execute_frozen_manifest, load_frozen_manifest,
    prepare_media_package_manifest, save_frozen_manifest,
)
from app.config import Settings
from app.models import WorkJob
from app.tasks.handlers_base import TaskHandler, register_handler
from app.tasks.context import JobContext

EXECUTE_KIND = "media_package-package-execute"
ACTIVE = ("queued", "running", "paused", "cancel_requested")


def _execution_folder(settings: Settings, job_id: int) -> Path:
    if job_id <= 0:
        raise ValueError("Invalid MediaPackage execution job ID")
    return settings.reports_dir / "media_package-executions" / str(job_id)


def enqueue_media_package_execution(session_factory, settings: Settings,
                             *, preview_job_id: int, confirmation: str) -> dict:
    """Only an exact user-confirmed, completed and conflict-free preview may execute."""
    if not settings.allow_mutation or not settings.allow_delete:
        raise ValueError("MediaPackage execution requires ALLOW_MUTATION and ALLOW_DELETE")
    expected = f"EXECUTE_MEDIA_PACKAGE_PREVIEW_{preview_job_id}"
    if not isinstance(confirmation, str) or confirmation != expected:
        raise ValueError("Exact MediaPackage preview execution confirmation is required")
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        preview = session.get(WorkJob, preview_job_id)
        if preview is None or preview.kind != PREVIEW_KIND:
            raise KeyError(preview_job_id)
        if preview.status != "completed":
            raise ValueError("MediaPackage preview must be completed before execution")
        data, index, summary_path = _preview_files(settings, preview_job_id)
        if not (data.is_file() and index.is_file() and summary_path.is_file()):
            raise ValueError("MediaPackage preview evidence is incomplete")
        with summary_path.open("r", encoding="utf-8") as file:
            summary = json.load(file)
        if (not isinstance(summary.get("package_count"), int)
                or summary["package_count"] <= 0 or
                not isinstance(summary.get("ready_count"), int)
                or summary["ready_count"] <= 0 or
                summary.get("blocked_count") != 0):
            raise ValueError("Preview has no ready packages or unresolved conflicts")
        existing = session.scalar(select(WorkJob).where(
            WorkJob.kind == EXECUTE_KIND,
            func.json_extract(WorkJob.state_json, "$.preview_job_id") == preview_job_id,
        ).order_by(WorkJob.id.desc()).limit(1))
        if existing is not None:
            if existing.status in (*ACTIVE, "completed"):
                return {"job_id": existing.id, "status": existing.status}
            # Fail-closed: never silently restart a partially mutated package
            # under a different job id/staging namespace.
            raise ValueError(
                "Previous execution failed or was cancelled; manual recovery is required"
            )
        active = session.scalar(select(WorkJob.id).where(
            WorkJob.kind == EXECUTE_KIND,
            WorkJob.status.in_(ACTIVE),
        ).limit(1))
        if active is not None:
            raise ValueError(f"Another MediaPackage execution task #{active} is running")
        job = WorkJob(
            kind=EXECUTE_KIND, status="queued", progress_current=0,
            progress_total=summary["package_count"],
            progress_message="等待 Worker 对资源包进行冻结、校验与安全移动",
            state_json=json.dumps({"preview_job_id": preview_job_id,
                                   "selection": json.loads(preview.state_json or "{}").get("selection", "")},
                                  ensure_ascii=False),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return {"job_id": int(job.id), "status": job.status}


def get_media_package_execution(session_factory, job_id: int) -> dict:
    with session_factory() as session:
        job = session.get(WorkJob, job_id)
        if job is None or job.kind != EXECUTE_KIND:
            raise KeyError(job_id)
        state = json.loads(job.state_json or "{}")
        checkpoint = json.loads(job.checkpoint_json or "{}")
        return {
            "job_id": int(job.id), "status": job.status,
            "error": job.error_text, "preview_job_id": state.get("preview_job_id"),
            "progress": {
                "current": int(job.progress_current or 0),
                "total": int(job.progress_total or 0),
                "message": job.progress_message,
                "package": checkpoint.get("package", ""),
                "package_file_progress": checkpoint.get("package_file_progress", 0),
            },
        }


@register_handler
class MediaPackageExecuteHandler(TaskHandler):
    job_type = EXECUTE_KIND
    supports_cancel = False
    supports_retry = False
    supports_pause = False
    supports_resume = True

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        if not settings.allow_mutation or not settings.allow_delete:
            raise PermissionError("MediaPackage execution mutation gates are disabled")
        if not context.worker_id:
            raise PermissionError("MediaPackage execution requires an exclusive Worker lease")
        state = json.loads(job.state_json or "{}")
        preview_job_id = state.get("preview_job_id")
        if not isinstance(preview_job_id, int) or preview_job_id <= 0:
            raise ValueError("Missing MediaPackage preview authority")
        with context.SessionLocal() as session:
            preview = session.get(WorkJob, preview_job_id)
            if preview is None or preview.kind != PREVIEW_KIND or preview.status != "completed":
                raise ValueError("Approved MediaPackage preview is no longer available")
        data, _index, summary_path = _preview_files(settings, preview_job_id)
        with summary_path.open("r", encoding="utf-8") as file:
            summary = json.load(file)
        total = summary["package_count"]
        if not isinstance(total, int) or not 1 <= total <= 60_000:
            raise ValueError("Unsafe execution package count")
        if summary.get("blocked_count") != 0:
            raise ValueError("MediaPackage execution is blocked by unresolved preview conflicts")

        # The resume checkpoint is committed BEFORE any filesystem operation.
        context.checkpoint(
            progress_total=total,
            progress_message="MediaPackage 开始逐资源包冻结、校验与执行",
            checkpoint_data={
                "schema_version": 1, "preview_job_id": preview_job_id,
                "mode": "frozen_manifest_reconcile",
            },
        )
        folder = _execution_folder(settings, int(job.id))
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)

        def fence() -> None:
            # Lazy import avoids recovery -> handler registry -> execute-job cycle.
            from app.tasks.recovery import renew_and_assert_worker_lease
            renew_and_assert_worker_lease(context.SessionLocal, context.worker_id)

        results = []
        with data.open("r", encoding="utf-8") as stream:
            for ordinal, line in enumerate(stream):
                if ordinal >= total:
                    raise ValueError("Preview contains more packages than its frozen summary")
                record = json.loads(line)
                package = Path(record["package"])
                checked = _package_path(
                    package, _root(settings), settings.allowed_roots, settings.quarantine_root,
                )
                if package != checked:
                    raise MediaPackageExecutionConflict("Preview package escaped the configured MediaPackage root")
                package_name = str(package)[-120:]
                manifest_path = folder / f"{ordinal:07d}.manifest.json"

                if record["status"] == "ready":
                    if manifest_path.is_file():
                        manifest = load_frozen_manifest(
                            manifest_path, job_id=int(job.id), package=package,
                        )
                        if manifest.get("media_package_root") != str(_root(settings)):
                            raise MediaPackageExecutionConflict("Frozen manifest root differs from configured MediaPackage root")
                    else:
                        # Newly frozen packages must match every file identity
                        # in the original preview. No stale preview may run.
                        manifest = prepare_media_package_manifest(
                            package, media_package_root=_root(settings),
                            allowed_roots=settings.allowed_roots,
                            quarantine_root=settings.quarantine_root,
                            preview_record=record, job_id=int(job.id),
                        )
                        save_frozen_manifest(manifest_path, manifest)

                    def file_progress(done: int, count: int) -> None:
                        context.checkpoint(
                            progress_current=ordinal, progress_total=total,
                            progress_message=f"资源包 {ordinal + 1}/{total}: {done}/{count} 文件",
                            checkpoint_data={
                                "schema_version": 1,
                                "preview_job_id": preview_job_id,
                                "mode": "frozen_manifest_reconcile",
                                "package": package_name, "package_file_progress": done,
                            },
                        )

                    result = execute_frozen_manifest(
                        manifest, lease_fence=fence, progress=file_progress,
                    )
                    results.append(result)
                elif record["status"] in ("skipped", "already_organized"):
                    results.append({"package": str(package), "skipped": True})
                else:
                    raise MediaPackageExecutionConflict(
                        "Preview contains blocked or unsupported packages; refusing execution"
                    )
                context.checkpoint(
                    progress_current=ordinal + 1, progress_total=total,
                    progress_message=f"已完成 {ordinal + 1}/{total} 个资源包",
                    checkpoint_data={
                        "schema_version": 1,
                        "preview_job_id": preview_job_id,
                        "mode": "frozen_manifest_reconcile",
                        "package": package_name,
                    },
                )
        if len(results) != total:
            raise ValueError("Preview package count changed during execution")
        # Private completed-report summary. Each manifest is retained for
        # auditing and safe Worker crash reconciliation.
        report = folder / "result.json"
        if not report.exists():
            tmp = folder / "result.json.tmp"
            fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump({
                    "preview_job_id": preview_job_id, "job_id": int(job.id),
                    "packages": len(results),
                    "files_moved": sum(r.get("files_moved", 0) for r in results),
                    "files_reconciled": sum(r.get("files_reconciled", 0) for r in results),
                    "empty_dirs_removed": sum(r.get("empty_dirs_removed", 0) for r in results),
                }, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            os.link(tmp, report, follow_symlinks=False)
            os.unlink(tmp)
