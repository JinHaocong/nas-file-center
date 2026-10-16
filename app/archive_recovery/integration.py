"""Integrate archive salvage with the single NAS File Center Worker authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import time

from sqlalchemy import text

from app.archive_recovery.core import RecoveryError, recover_archive, clean_interrupted_parts
from app.config import Settings
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
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    candidate = directory / f'.{job_id}-{os.urandom(12).hex()}.json'
    fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(candidate, report_path(settings, job_id))
    finally:
        candidate.unlink(missing_ok=True)


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
            if output.parent != source.parent or output.is_symlink() or not output.is_dir():
                raise RecoveryError('OUTPUT_INVALID')
            out_stat = output.stat()
            if [str(out_stat.st_dev), str(out_stat.st_ino)] != state.get('output_identity'):
                raise RecoveryError('OUTPUT_REPLACED')
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
            # worker-owned temporary names; final published files survive.
            if token and tmpfs_available():
                (SECRET_DIR / token).unlink(missing_ok=True)
            clean_interrupted_parts(output, state.get('output_identity', []))
            try:
                (output / '_incomplete').rmdir()
            except OSError:
                pass
            if status != 'completed' and status != 'partial':
                write_report(settings, job.id, {
                    'source': str(source), 'output': str(output),
                    'recovery_status': status, 'error_code': error,
                    'items': items,
                    'stats': {s: sum(r['status'] == s for r in items)
                              for s in ('integrity_passed','format_validated','unverified','incomplete','unrecovered')},
                    'known_total': report.get('known_total') if report is not None else None,
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
                    if output.is_dir() and not output.is_symlink() and (
                        [str(output.stat().st_dev), str(output.stat().st_ino)] == state.get('output_identity')
                    ):
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