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
from .models import DownloadVerificationRun, DownloadVerificationItem, DownloadVerificationSource
from .sources import AListAPIClient, source_secret_path
from .webdav import WebDAVClient, WebDAVError, relative_parts


def build_client(settings):
    return WebDAVClient(
        base_url=settings.download_verify_webdav_base_url,
        username=settings.download_verify_webdav_user,
        password_file=str(settings.download_verify_webdav_password_file or ""),
        allow_http=settings.download_verify_allow_http,
    )


def source_client(source: DownloadVerificationSource, settings, *, mode: str):
    secret = (str(source_secret_path(settings.config_dir, source.secret_file))
              if source.secret_file else None)
    if mode == "metadata":
        return AListAPIClient(base_url=source.base_url, username=source.username,
                              password_file=secret)
    if mode == "strict_sha256":
        return WebDAVClient(base_url=source.base_url + "/dav/",
                            username=source.username, password_file=secret or "",
                            allow_http=source.base_url.startswith("http://"))
    raise VerificationError("INVALID_VERIFY_MODE")


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
            mode = run.mode or "strict_sha256"
            source_id, source_revision = run.source_id, run.source_revision
            source = session.get(DownloadVerificationSource, source_id) if source_id else None
            if source_id and (source is None or not source.active or source.revision != source_revision):
                raise VerificationError("SOURCE_CHANGED")
        remote_parts = relative_parts(remote_root)
        local = qualified_local_root(local_root, settings)
        # A paused/recovered task replays the entire run. JobContext progress is
        # monotone, so clear the old progress under the current Worker lease.
        with context.SessionLocal() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            from app.tasks.recovery import assert_active_worker_lease
            if context.worker_id is not None:
                assert_active_worker_lease(session, context.worker_id)
            current = session.get(WorkJob, job.id)
            current.progress_current = 0
            current.progress_total = 0
            current.progress_message = "重新开始完整校验"
            session.commit()

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
            client = source_client(source, settings, mode=mode) if source_id else build_client(settings)
            context.checkpoint(progress_message="读取 WebDAV 云端目录",
                checkpoint_data={"schema_version": 1, "phase": "remote_manifest", "run_id": run_id})
            # Resume is a fresh verification, never reuse old successful item rows.
            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                from app.tasks.recovery import assert_active_worker_lease
                if context.worker_id is not None:
                    assert_active_worker_lease(session, context.worker_id)
                session.query(DownloadVerificationItem).filter(
                    DownloadVerificationItem.run_id == run_id).delete(synchronize_session=False)
                run = session.get(DownloadVerificationRun, run_id)
                run.result = "INCOMPLETE"
                run.finished_at = None
                run.checked = 0
                run.bytes_checked = 0
                run.error_code = None
                session.commit()
            remote = client.manifest(remote_parts, lambda: context.checkpoint(
                progress_message="枚举 WebDAV 目录",
                checkpoint_data={"schema_version": 1, "phase": "remote_manifest", "run_id": run_id}))
            context.checkpoint(progress_message="读取 NAS 本地目录",
                checkpoint_data={"schema_version": 1, "phase": "local_manifest", "run_id": run_id})
            local_rows = local_manifest(local, quarantine_root=settings.quarantine_root)
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
                if status == "PENDING_SHA256" and mode == "metadata":
                    status = "METADATA_MATCH"
                elif status == "PENDING_SHA256":
                    rel = row["relative_path"]
                    # The remote endpoint must return original full 200-byte content.
                    remote_sha = client.sha256(remote_parts + tuple(rel.split("/")), row["remote_size"], tick)
                    local_sha = hash_local_file(local, rel, row["local_size"], tick)
                    status = "VERIFIED_MATCH" if remote_sha == local_sha else "HASH_MISMATCH"
                    bytes_done += row["remote_size"]
                if status not in ("VERIFIED_MATCH", "METADATA_MATCH", "DIRECTORY_MATCH"):
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
            if remote_fingerprint(remote) != remote_fingerprint(client.manifest(
                    remote_parts, lambda: context.checkpoint(
                        progress_message="再次枚举 WebDAV 目录",
                        checkpoint_data={"schema_version": 1, "phase": "revalidate", "run_id": run_id}))):
                raise VerificationError("REMOTE_CHANGED")
            if local_fingerprint(local_rows) != local_fingerprint(local_manifest(
                    local, quarantine_root=settings.quarantine_root)):
                raise VerificationError("LOCAL_CHANGED")
            # Source edits during a scan require a fresh comparison.
            if source_id:
                with context.SessionLocal() as session:
                    current_source = session.get(DownloadVerificationSource, source_id)
                    if (current_source is None or not current_source.active or
                            current_source.revision != source_revision):
                        raise VerificationError("SOURCE_CHANGED")
            # Final cancellation/lease checkpoint BEFORE publishing the verdict.
            context.checkpoint(
                progress_current=total, progress_total=total,
                progress_message="内容有差异" if differences else ("路径及大小清单一致（未校验内容）" if mode == "metadata" else "双端 SHA256 校验一致"),
                checkpoint_data={"schema_version": 1, "phase": "finalizing", "run_id": run_id})
            with context.SessionLocal() as session:
                session.execute(text("BEGIN IMMEDIATE"))
                from app.tasks.recovery import assert_active_worker_lease
                if context.worker_id is not None:
                    assert_active_worker_lease(session, context.worker_id)
                run = session.get(DownloadVerificationRun, run_id)
                run.result = "DIFFERENT" if differences else ("METADATA_IDENTICAL" if mode == "metadata" else "VERIFIED_IDENTICAL")
                run.checked = completed
                run.bytes_checked = bytes_done
                run.finished_at = utcnow()
                session.commit()
            # WorkJob transitions to completed later, under the same Worker lease.
            # API suppresses a successful verdict until that transition is durable.
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
                        "REMOTE_CHANGED", "LOCAL_CHANGED", "SOURCE_CHANGED") else "INCOMPLETE"
                    current.error_code = str(exc) if isinstance(exc, (WebDAVError, VerificationError)) else "VERIFICATION_FAILED"
                    current.checked = completed
                    current.bytes_checked = bytes_done
                    current.finished_at = utcnow()
                session.commit()
            raise
