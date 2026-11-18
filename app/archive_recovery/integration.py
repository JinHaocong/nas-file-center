"""Integrate archive salvage with the single NAS File Center Worker authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import re
import time

from sqlalchemy import text

from app.archive_recovery.core import (
    RecoveryError, recover_archive, clean_interrupted_parts, reconcile_failed_archive_items,
)
from app.config import Settings
from app.config_sharing import shared_config_gid, ensure_shared_report_directory
from app.models import WorkJob
from app.tasks.context import JobContext
from app.tasks.handlers_base import TaskHandler, register_handler
from app.tasks.state_machine import JobCancelRequested, JobLeaseLost

SECRET_DIR = Path('/run/nfc-recovery-secrets')


def tmpfs_available() -> bool:
    """Require an explicit tmpfs mount shared by API and Worker, not /config."""
    try:
        root = str(SECRET_DIR.resolve(strict=True))
        with open('/proc/self/mountinfo', encoding='utf-8') as handle:
            return any(line.split(' - ', 1)[1].split()[0] == 'tmpfs'
                       and line.split(' - ', 1)[0].split()[4] == root
                       for line in handle if ' - ' in line)
    except (OSError, IndexError):
        return False


def read_one_time_password(token: str | None) -> str | None:
    """Read and immediately unlink an API-supplied password in tmpfs."""
    if not token:
        return None
    if len(token) != 32 or any(c not in '0123456789abcdef' for c in token) or not tmpfs_available():
        raise RecoveryError('PASSWORD_CHANNEL_UNAVAILABLE')
    path = SECRET_DIR / token
    file_fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        st = os.fstat(file_fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > 4096 or st.st_mode & 0o077:
            raise RecoveryError('PASSWORD_CHANNEL_INVALID')
        data = os.read(file_fd, 4097)
        if len(data) > 4096:
            raise RecoveryError('PASSWORD_TOO_LONG')
        return data.decode('utf-8')
    finally:
        os.close(file_fd)
        os.unlink(path)


def report_path(settings: Settings, job_id: int) -> Path:
    """Only numeric, task-derived report basenames can be accessed."""
    return settings.config_dir / 'archive-recovery-reports' / f'{job_id}.json'


def write_report(settings: Settings, job_id: int, report: dict) -> None:
    """Publish report metadata atomically under config; no password is stored."""
    directory = settings.config_dir / 'archive-recovery-reports'
    gid = shared_config_gid()
    if gid is None:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    else:
        ensure_shared_report_directory(directory, gid)
    candidate = directory / f'.{job_id}-{os.urandom(12).hex()}.json'
    fd = os.open(
        candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o640 if gid is not None else 0o600,
    )
    try:
        if gid is not None:
            created = os.fstat(fd)
            if created.st_gid != gid or not stat.S_ISREG(created.st_mode):
                raise PermissionError('SHARED_CONFIG: report file owner/group mismatch')
            # Group can read the result; no world access, and no host-file repair.
            os.fchmod(fd, 0o640)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(candidate, report_path(settings, job_id))
    finally:
        candidate.unlink(missing_ok=True)


def _create_worker_output_directory(
    source: Path,
    output: Path,
    state: dict,
    settings: Settings,
    context: JobContext,
) -> list[str]:
    """Create the result directory exclusively under the frozen source-parent inode."""
    from app.path_safety import require_allowed_path, require_unreserved_path
    from app.tasks.recovery import renew_and_assert_worker_lease

    if not context.worker_id:
        raise PermissionError("Archive output creation requires active Worker authority")
    if output.parent != source.parent or source.is_symlink():
        raise RecoveryError("OUTPUT_PARENT_INVALID")
    allowed = require_unreserved_path(
        require_allowed_path(source, settings.allowed_roots), settings.quarantine_root
    )
    if allowed != source:
        raise RecoveryError("SOURCE_INVALID")
    prefix = source.name[:60] + "_恢复结果_"
    suffix = output.name[len(prefix):] if output.name.startswith(prefix) else ""
    if not re.fullmatch(r"[0-9a-f]{8}", suffix):
        raise RecoveryError("OUTPUT_NAME_INVALID")

    expected_parent = state.get("parent_identity")
    expected_source = state.get("identity")
    if (
        not isinstance(expected_parent, list) or len(expected_parent) != 2
        or not isinstance(expected_source, list) or len(expected_source) != 4
    ):
        raise RecoveryError("OUTPUT_AUTHORITY_SNAPSHOT_MISSING")

    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    parent_fd = os.open(source.parent, directory_flags)
    try:
        parent_stat = os.fstat(parent_fd)
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or [str(parent_stat.st_dev), str(parent_stat.st_ino)] != expected_parent
        ):
            raise RecoveryError("OUTPUT_PARENT_CHANGED")

        source_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        source_fd = os.open(source.name, source_flags, dir_fd=parent_fd)
        try:
            source_stat = os.fstat(source_fd)
            observed_source = [
                str(source_stat.st_dev), str(source_stat.st_ino),
                str(source_stat.st_size), str(source_stat.st_mtime_ns),
            ]
            if not stat.S_ISREG(source_stat.st_mode) or observed_source != expected_source:
                raise RecoveryError("SOURCE_CHANGED")
        finally:
            os.close(source_fd)

        # Refresh the lease immediately before the filesystem mutation.
        renew_and_assert_worker_lease(context.SessionLocal, context.worker_id)
        try:
            os.mkdir(output.name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError as exc:
            raise RecoveryError("OUTPUT_CONFLICT") from exc

        output_fd = os.open(output.name, directory_flags, dir_fd=parent_fd)
        try:
            output_stat = os.fstat(output_fd)
            if (
                not stat.S_ISDIR(output_stat.st_mode)
                or output_stat.st_dev != parent_stat.st_dev
                or output_stat.st_uid != os.geteuid()
                or stat.S_IMODE(output_stat.st_mode) != 0o700
            ):
                raise RecoveryError("OUTPUT_DIRECTORY_UNSAFE")
            return [str(output_stat.st_dev), str(output_stat.st_ino)]
        finally:
            os.close(output_fd)
    finally:
        os.close(parent_fd)


def _persist_worker_output_identity(
    context: JobContext,
    job: WorkJob,
    state: dict,
    output_identity: list[str],
) -> None:
    """Persist the created directory's inode before any archive entry is published."""
    from app.tasks.recovery import assert_active_worker_lease

    if not context.worker_id or not callable(getattr(context, "SessionLocal", None)):
        raise PermissionError("Archive output identity requires active Worker authority")
    with context.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, context.worker_id)
        current = session.get(WorkJob, int(job.id))
        if current is None:
            raise KeyError(f"Archive recovery job #{job.id} disappeared")
        persisted = json.loads(current.state_json or "{}")
        for key in ("source", "output", "identity", "parent_identity", "deep", "secret_token"):
            if persisted.get(key) != state.get(key):
                raise RecoveryError("ARCHIVE_JOB_AUTHORITY_CHANGED")
        previous = persisted.get("output_identity")
        if previous is not None and previous != output_identity:
            raise RecoveryError("OUTPUT_IDENTITY_ALREADY_BOUND")
        persisted["output_identity"] = output_identity
        current.state_json = json.dumps(persisted, ensure_ascii=False, sort_keys=True)
        session.commit()
    state["output_identity"] = output_identity
    job.state_json = json.dumps(state, ensure_ascii=False, sort_keys=True)


def _validate_existing_worker_output(
    source: Path,
    output: Path,
    state: dict,
    settings: Settings,
) -> None:
    """Validate an already-created output directory for legacy queued jobs."""
    from app.path_safety import require_allowed_path, require_unreserved_path

    if output.parent != source.parent or output.is_symlink() or not output.is_dir():
        raise RecoveryError("OUTPUT_INVALID")
    allowed = require_unreserved_path(
        require_allowed_path(source, settings.allowed_roots), settings.quarantine_root
    )
    if allowed != source:
        raise RecoveryError("SOURCE_INVALID")
    expected_parent = state.get("parent_identity")
    if expected_parent is not None:
        parent_stat = os.stat(source.parent, follow_symlinks=False)
        if [str(parent_stat.st_dev), str(parent_stat.st_ino)] != expected_parent:
            raise RecoveryError("OUTPUT_PARENT_CHANGED")
    output_stat = os.stat(output, follow_symlinks=False)
    if [str(output_stat.st_dev), str(output_stat.st_ino)] != state.get("output_identity"):
        raise RecoveryError("OUTPUT_REPLACED")
    if (
        not stat.S_ISDIR(output_stat.st_mode)
        or output_stat.st_uid != os.geteuid()
        or stat.S_IMODE(output_stat.st_mode) != 0o700
    ):
        raise RecoveryError("OUTPUT_DIRECTORY_UNSAFE")


@register_handler
class ArchiveRecoveryHandler(TaskHandler):
    """Recover in place with fail-closed lease/cancel checkpoints."""

    job_type = 'archive-recovery'
    supports_pause = False
    supports_cancel = True
    supports_retry = False  # Fresh output directory and new secret token required.
    supports_resume = False

    def run(self, job: WorkJob, context: JobContext, settings: Settings) -> None:
        state = json.loads(job.state_json or '{}')
        source = Path(state['source'])
        output = Path(state['output'])
        token = state.get('secret_token')
        items: list[dict] = []
        status = 'failed'
        error: str | None = None
        report: dict | None = None
        password = None
        initial_source_stat = None
        last_check = 0.0

        def checkpoint() -> None:
            nonlocal last_check
            now = time.monotonic()
            if now - last_check >= 0.5:
                context.checkpoint(progress_message=f'正在恢复与验证；已处理 {len(items)} 个条目')
                last_check = now

        try:
            if not settings.allow_mutation:
                raise RecoveryError('MUTATION_DISABLED')
            from app.path_safety import require_allowed_path, require_unreserved_path
            allowed = require_unreserved_path(
                require_allowed_path(source, settings.allowed_roots), settings.quarantine_root)
            if allowed != source or source.is_symlink() or not source.is_file():
                raise RecoveryError('SOURCE_INVALID')
            st = source.stat()
            if ([str(st.st_dev), str(st.st_ino), str(st.st_size), str(st.st_mtime_ns)]
                    != state['identity']):
                raise RecoveryError('SOURCE_CHANGED')
            initial_source_stat = st
            if state.get("output_identity") is None:
                output_identity = _create_worker_output_directory(
                    source, output, state, settings, context
                )
                # Record locally first so finally can clean only this exact inode
                # even if the SQLite persistence step fails.
                state["output_identity"] = output_identity
                _persist_worker_output_identity(context, job, state, output_identity)
            else:
                _validate_existing_worker_output(source, output, state, settings)
            checkpoint()
            password = read_one_time_password(token)
            report = recover_archive(source, output, password=password, check=checkpoint,
                                     deep=state.get('deep', True), items=items)
            if not any(r['status'] in {'integrity_passed', 'format_validated', 'unverified', 'incomplete'}
                       for r in items):
                raise RecoveryError('NO_FILES_RECOVERED')
            after = source.stat()
            if (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
                report['warnings'].append('Original archive changed during recovery; evidence may be stale.')
                status = 'partial'
            else:
                status = 'partial' if any(r['status'] in {'incomplete', 'unrecovered'} for r in items) else 'completed'
            report['recovery_status'] = status
            context.log('archive_recovery_done', 'Archive recovery ended',
                        context={'result': status, 'files': len(items)})
            write_report(settings, job.id, report)
        except (JobCancelRequested, JobLeaseLost):
            status = 'cancelled'
            raise
        except (RecoveryError, OSError, ValueError) as exc:
            error = str(exc) if isinstance(exc, RecoveryError) else type(exc).__name__
            raise RecoveryError(error) from None
        finally:
            # All intermediate file descriptors close in core. Remove only
            # worker-owned temporary names under the same frozen parent/output inodes.
            if token and tmpfs_available():
                (SECRET_DIR / token).unlink(missing_ok=True)
            output_bound = False
            try:
                parent_stat = os.stat(source.parent, follow_symlinks=False)
                expected_parent = state.get("parent_identity")
                parent_matches = (
                    expected_parent is None
                    or [str(parent_stat.st_dev), str(parent_stat.st_ino)] == expected_parent
                )
                output_stat = os.stat(output, follow_symlinks=False)
                output_bound = (
                    parent_matches
                    and stat.S_ISDIR(output_stat.st_mode)
                    and [str(output_stat.st_dev), str(output_stat.st_ino)]
                    == state.get("output_identity")
                )
            except OSError:
                output_bound = False
            if output_bound:
                clean_interrupted_parts(output, state.get('output_identity', []))
                try:
                    (output / '_incomplete').rmdir()
                except OSError:
                    pass
            if status != 'completed' and status != 'partial':
                # A task stopped by RESOURCE_LIMIT / TIME_LIMIT may already
                # have recovered files. If the source is still the original
                # regular file, enumerate its verified header read-only to
                # make unvisited names visible in the terminal error report.
                failure_inventory = {}
                if status == 'failed' and initial_source_stat is not None and report is None:
                    try:
                        current = source.stat(follow_symlinks=False)
                        if (stat.S_ISREG(current.st_mode) and (
                            current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns
                        ) == (
                            initial_source_stat.st_dev, initial_source_stat.st_ino,
                            initial_source_stat.st_size, initial_source_stat.st_mtime_ns,
                        )):
                            failure_inventory = reconcile_failed_archive_items(source, items, password)
                    except (RecoveryError, OSError, ValueError):
                        # Inventory is evidence, not a precondition for safe
                        # cleanup; preserve any per-entry records already made.
                        pass
                write_report(settings, job.id, {
                    'source': str(source), 'output': str(output),
                    'recovery_status': status, 'error_code': error,
                    'items': items,
                    'stats': {s: sum(r['status'] == s for r in items)
                              for s in ('integrity_passed','format_validated','unverified','incomplete','unrecovered')},
                    'known_total': report.get('known_total') if report is not None else
                                   failure_inventory.get('known_total'),
                    **failure_inventory,
                    # Preserve bounded, non-secret decoder diagnostics on
                    # NO_FILES_RECOVERED. A fatal WorkJob must not erase the
                    # reason the fallback rejected an unsupported 7z layout.
                    **({key: report[key] for key in (
                        'format', 'deep_capability', 'aes_lzma2_deep', 'warnings',
                        'inventory', 'file_outcomes', 'missing_files',
                    ) if key in report} if report is not None else {}),
                })
                # Never retain empty failed-job output directories.
                try:
                    if output_bound and output.is_dir() and not output.is_symlink():
                        output.rmdir()
                except OSError:
                    pass


def cleanup_recovery_after_worker_restart(settings: Settings, session_factory, worker_id: str) -> None:
    """Retire only job-owned temp names after the existing Worker lease takeover."""
    from sqlalchemy import select
    from app.tasks.recovery import assert_active_worker_lease

    with session_factory() as session:
        assert_active_worker_lease(session, worker_id)
        jobs = list(session.scalars(
            select(WorkJob).where(WorkJob.kind == 'archive-recovery',
                                  WorkJob.status == 'failed',
                                  WorkJob.error_code == 'WORKER_INTERRUPTED')
        ))
    for job in jobs:
        try:
            state = json.loads(job.state_json or '{}')
            output = Path(state['output'])
            source = Path(state['source'])
            from app.path_safety import require_allowed_path
            if output.parent != source.parent or (
                require_allowed_path(source, settings.allowed_roots) != source
            ):
                continue
            expected_parent = state.get("parent_identity")
            if expected_parent is not None:
                parent_stat = os.stat(source.parent, follow_symlinks=False)
                if [str(parent_stat.st_dev), str(parent_stat.st_ino)] != expected_parent:
                    continue
            output_stat = os.stat(output, follow_symlinks=False)
            if (
                not stat.S_ISDIR(output_stat.st_mode)
                or [str(output_stat.st_dev), str(output_stat.st_ino)] != state.get("output_identity")
            ):
                continue
            clean_interrupted_parts(output, state.get('output_identity', []))
            token = state.get('secret_token')
            if token and len(token) == 32 and tmpfs_available():
                (SECRET_DIR / token).unlink(missing_ok=True)
        except (KeyError, OSError, ValueError):
            # No cleanup authority can be derived from malformed/stale job state.
            continue


def cleanup_cancelled_queued_recovery(state_json: str) -> None:
    """Remove one-time RAM secret and only a task-owned EMPTY output dir."""
    try:
        state = json.loads(state_json or '{}')
        token = state.get('secret_token')
        if token and len(token) == 32 and all(c in '0123456789abcdef' for c in token) and tmpfs_available():
            (SECRET_DIR / token).unlink(missing_ok=True)
        output = Path(state['output'])
        source = Path(state['source'])
        if output.parent != source.parent or output.is_symlink() or not output.is_dir():
            return
        st = output.stat()
        if [str(st.st_dev), str(st.st_ino)] != state.get('output_identity'):
            return
        output.rmdir()
    except (KeyError, ValueError, OSError):
        # Existing user files, foreign directories and ambiguous identities survive.
        pass