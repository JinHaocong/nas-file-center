"""Existing Worker-owned read-only WebDAV verification, with persisted row outcomes."""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import select, text

from app.models import WorkJob, utcnow
from app.tasks.handlers_base import TaskHandler, register_handler
from .engine import (
    VerificationError, diff_inventory, hash_local_file, local_fingerprint,
    local_manifest, qualified_local_root, remote_fingerprint,
)
from .models import DownloadVerificationRun, DownloadVerificationItem
from .webdav import WebDAVClient, WebDAVError, relative_parts


def build_client(settings):
    return WebDAVClient(
        base_url=settings.download_verify_webdav_base_url,
        username=settings.download_verify_webdav_user,
        password_file=str(settings.download_verify_webdav_password_file or ""),
        allow_http=settings.download_verify_allow_http,
    )


@register_handler
class DownloadVerificationHandler(TaskHandler):
    job_type = "download-verify-webdav"
    supports_pause = True
    supports_cancel = True
    supports_retry = False  # A fresh run is required for every new attempt.
    supports_resume = True

    def run(self, job: WorkJob, context, settings) -> None:
        state = json.loads(job.state_json or "{}")
        run_id = state.get("run_id")
        with context.SessionLocal() as session:
            run = session.get(DownloadVerificationRun, run_id)
            if run is None or run.work_job_id != job.id:
                raise VerificationError("VERIFY_JOB_AUTHORITY_MISMATCH")
            remote_root, local_root = run.remote_root, run.local_root
        remote_parts = relative_parts(remote_root)
        local = qualified_local_root(local_root, settings)

        def commit_row(row: dict, *, remote_sha=None, local_sha=None, status=None):
            # No payload content or credentials are ever persisted.
            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                from app.tasks.recovery import assert_active_worker_lease
                if context.worker_id is not None:
                    assert_active_worker_lease(session, context.worker_id)
                item = session.scalar(select(DownloadVerificationItem).where(
                    DownloadVerificationItem.run_id == run_id,
                    DownloadVerificationItem.relative_path == row["relative_path"]))
                if item is None:
                    item = DownloadVerificationItem(
                        run_id=run_id, relative_path=row["relative_path"], kind=row["kind"],
                        remote_size=row["remote_size"], local_size=row["local_size"],
                        status=status or row["status"],
                        remote_sha256=remote_sha, local_sha256=local_sha)
                    session.add(item)
                else:
                    item.status = status or row["status"]
                    item.remote_sha256 = remote_sha
                    item.local_sha256 = local_sha
                session.commit()

        completed = 0
        bytes_done = 0
        total = 0
        try:
            client = build_client(settings)
            context.checkpoint(progress_message="读取 WebDAV 云端目录",
                checkpoint_data={"schema_version": 1, "phase": "remote_manifest", "run_id": run_id})
            remote = client.manifest(remote_parts)
            context.checkpoint(progress_message="读取 NAS 本地目录",
                checkpoint_data={"schema_version": 1, "phase": "local_manifest", "run_id": run_id})
            local_rows = local_manifest(local)
            rows = diff_inventory(remote, local_rows)
            total = len(rows)
            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                from app.tasks.recovery import assert_active_worker_lease
                if context.worker_id is not None:
                    assert_active_worker_lease(session, context.worker_id)
                run = session.get(DownloadVerificationRun, run_id)
                run.total = total
                session.commit()
            # For cancellation and lease fencing during large streaming files.
            chunks = 0
            def tick():
                nonlocal chunks
                chunks += 1
                if chunks % 16 == 0:
                    context.checkpoint(
                        progress_current=completed, progress_total=total,
                        progress_message="流式 SHA256 校验中",
                        checkpoint_data={"schema_version": 1, "phase": "hashing", "run_id": run_id,
                                         "checked": completed})

            differences = False
            for row in rows:
                status = row["status"]
                remote_sha = local_sha = None
                if status == "PENDING_SHA256":
                    rel = row["relative_path"]
                    # The remote endpoint must return original full 200-byte content.
                    remote_sha = client.sha256(remote_parts + tuple(rel.split("/")), row["remote_size"], tick)
                    local_sha = hash_local_file(local, rel, row["local_size"], tick)
                    status = "VERIFIED_MATCH" if remote_sha == local_sha else "HASH_MISMATCH"
                    bytes_done += row["remote_size"]
                if status not in ("VERIFIED_MATCH", "DIRECTORY_MATCH"):
                    differences = True
                commit_row(row, remote_sha=remote_sha, local_sha=local_sha, status=status)
                completed += 1
                context.checkpoint(
                    progress_current=completed, progress_total=total,
                    progress_message=f"已核验 {completed}/{total} 个目录及文件条目",
                    checkpoint_data={"schema_version": 1, "phase": "hashing",
                                     "run_id": run_id, "checked": completed})
            context.checkpoint(progress_message="再次枚举 WebDAV 与 NAS，检查目录变化",
                checkpoint_data={"schema_version": 1, "phase": "revalidate", "run_id": run_id})
            # No 'identical' if either tree changed during the scan.
            if remote_fingerprint(remote) != remote_fingerprint(client.manifest(remote_parts)):
                raise VerificationError("REMOTE_CHANGED")
            if local_fingerprint(local_rows) != local_fingerprint(local_manifest(local)):
                raise VerificationError("LOCAL_CHANGED")
            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                from app.tasks.recovery import assert_active_worker_lease
                if context.worker_id is not None:
                    assert_active_worker_lease(session, context.worker_id)
                run = session.get(DownloadVerificationRun, run_id)
                run.result = "DIFFERENT" if differences else "VERIFIED_IDENTICAL"
                run.checked = completed
                run.bytes_checked = bytes_done
                run.finished_at = utcnow()
                session.commit()
            context.checkpoint(
                progress_current=total, progress_total=total,
                progress_message="内容有差异" if differences else "双端 SHA256 校验一致",
                checkpoint_data={"schema_version": 1, "phase": "completed", "run_id": run_id})
        except Exception as exc:
            # A failed/paused/unavailable scan must never publish VERIFIED_IDENTICAL.
            # Preserve the original worker control exception (cancel/lease loss).
            from app.tasks.state_machine import JobLeaseLost, JobPauseRequested, JobCancelRequested
            if isinstance(exc, (JobLeaseLost, JobPauseRequested, JobCancelRequested)):
                raise
            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                from app.tasks.recovery import assert_active_worker_lease
                if context.worker_id is not None:
                    assert_active_worker_lease(session, context.worker_id)
                current = session.get(DownloadVerificationRun, run_id)
                if current is not None:
                    current.result = "STALE" if isinstance(exc, VerificationError) and str(exc) in (
                        "REMOTE_CHANGED", "LOCAL_CHANGED") else "INCOMPLETE"
                    current.error_code = str(exc) if isinstance(exc, (WebDAVError, VerificationError)) else "VERIFICATION_FAILED"
                    current.checked = completed
                    current.bytes_checked = bytes_done
                    current.finished_at = utcnow()
                session.commit()
            raise
