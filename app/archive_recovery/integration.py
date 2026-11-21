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
_CANCELLED_OUTPUT_PENDING = "cancelled_output_cleanup_pending"

# A real tmpfs-backed *shared* Docker volume is required. Separate per-service
# Docker tmpfs mounts do NOT share data across two container UIDs.
def _secret_authority() -> tuple[int, int] | None:
    raw_uid = os.environ.get("NFC_SECRET_OWNER_UID")
    raw_gid = os.environ.get("NFC_SECRET_GROUP_GID")
    if raw_uid is None and raw_gid is None:
        # Explicit legacy configuration for a single-UID private tmpfs mount.
        return None
    if (
        not raw_uid or not raw_gid
        or not raw_uid.isascii() or not raw_uid.isdecimal()
        or not raw_gid.isascii() or not raw_gid.isdecimal()
    ):
        raise RecoveryError("PASSWORD_CHANNEL_UNAVAILABLE")
    uid, gid = int(raw_uid), int(raw_gid)
    if uid <= 0 or gid <= 0 or gid != os.getegid():
        raise RecoveryError("PASSWORD_CHANNEL_UNAVAILABLE")
    return uid, gid


def _assert_secret_token(token: str) -> None:
    if (
        type(token) is not str or len(token) != 32
        or any(char not in "0123456789abcdef" for char in token)
    ):
        raise RecoveryError("PASSWORD_CHANNEL_INVALID")


def _secret_file_valid(info: os.stat_result, authority: tuple[int, int] | None) -> bool:
    if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
        return False
    if authority is None:
        return info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600
    owner_uid, shared_gid = authority
    return (
        info.st_uid == owner_uid
        and info.st_gid == shared_gid
        and stat.S_IMODE(info.st_mode) == 0o640
    )


def tmpfs_available() -> bool:
    """Strict local mount/owner preflight; identical-mount proof is a Docker test."""
    try:
        authority = _secret_authority()
        info = os.lstat(SECRET_DIR)
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            return False
        mode = stat.S_IMODE(info.st_mode)
        if authority is None:
            if mode != 0o700 or info.st_uid != os.geteuid():
                return False
        else:
            if (info.st_uid, info.st_gid, mode) != (authority[0], authority[1], 0o2770):
                return False
        path = str(SECRET_DIR)
        # A fake directory placed under /run or /config is not a secret store.
        with open("/proc/self/mountinfo", encoding="utf-8") as handle:
            for line in handle:
                if " - " not in line:
                    continue
                left, right = line.split(" - ", 1)
                columns = left.split()
                if len(columns) >= 5 and columns[4] == path and right.split()[0] == "tmpfs":
                    return True
        return False
    except (OSError, IndexError, RecoveryError):
        return False


def discard_one_time_password(token: str | None) -> bool:
    """Delete only an authenticated, inode-matching token in the private RAM root.

    Callers can treat False as a safe hold; this never chmods/chowns or scans
    arbitrary files. The shared group must contain only trusted API/Worker UIDs.
    """
    if not token:
        return False
    try:
        _assert_secret_token(token)
        if not tmpfs_available():
            return False
        authority = _secret_authority()
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        root_flags = flags | getattr(os, "O_DIRECTORY", 0)
        root_fd = os.open(SECRET_DIR, root_flags)
        try:
            fd = os.open(token, flags, dir_fd=root_fd)
            try:
                info = os.fstat(fd)
                if not _secret_file_valid(info, authority):
                    return False
                current = os.stat(token, dir_fd=root_fd, follow_symlinks=False)
                if not _secret_file_valid(current, authority):
                    return False
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                    return False
                os.unlink(token, dir_fd=root_fd)
                return True
            finally:
                os.close(fd)
        finally:
            os.close(root_fd)
    except (OSError, RecoveryError):
        return False


def store_one_time_password(token: str, password: str) -> None:
    """Create a bounded, exclusive one-time RAM token; never store it in SQLite."""
    _assert_secret_token(token)
    if not isinstance(password, str):
        raise RecoveryError("PASSWORD_CHANNEL_INVALID")
    payload = password.encode("utf-8")
    if len(payload) > 4096:
        raise RecoveryError("PASSWORD_TOO_LONG")
    if not tmpfs_available():
        raise RecoveryError("PASSWORD_CHANNEL_UNAVAILABLE")
    authority = _secret_authority()
    if authority is not None and os.geteuid() != authority[0]:
        raise RecoveryError("PASSWORD_CHANNEL_UNAVAILABLE")
    mode = 0o640 if authority is not None else 0o600
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(SECRET_DIR / token, flags, mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            if not _secret_file_valid(os.fstat(handle.fileno()), authority):
                raise RecoveryError("PASSWORD_CHANNEL_INVALID")
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        discard_one_time_password(token)
        raise


def read_one_time_password(token: str | None) -> str | None:
    """Worker consumes only a verified API-owned, group-readable RAM secret."""
    if not token:
        return None
    _assert_secret_token(token)
    if not tmpfs_available():
        raise RecoveryError("PASSWORD_CHANNEL_UNAVAILABLE")
    authority = _secret_authority()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(SECRET_DIR / token, flags)
    except OSError as exc:
        raise RecoveryError("PASSWORD_CHANNEL_UNAVAILABLE") from exc
    with os.fdopen(fd, "rb") as handle:
        if not _secret_file_valid(os.fstat(handle.fileno()), authority):
            raise RecoveryError("PASSWORD_CHANNEL_INVALID")
        payload = handle.read(4097)
        if len(payload) > 4096:
            raise RecoveryError("PASSWORD_TOO_LONG")
        try:
            password = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RecoveryError("PASSWORD_CHANNEL_INVALID") from exc
        if not discard_one_time_password(token):
            raise RecoveryError("PASSWORD_CHANNEL_INVALID")
        return password


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
            discard_one_time_password(token)
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


def cleanup_recovery_after_worker_restart(
    settings: Settings, session_factory, worker_id: str, *, cancelled_only: bool = False,
) -> None:
    """Retire inode-bound output and temporary names with Worker authority."""
    from sqlalchemy import and_, or_, select
    from app.tasks.media_mutation_lock import assert_media_mutation_lock
    from app.tasks.recovery import assert_active_worker_lease, renew_and_assert_worker_lease

    assert_media_mutation_lock(settings)
    cancelled = and_(
        WorkJob.status == "cancelled",
        WorkJob.state_json.contains(f'"{_CANCELLED_OUTPUT_PENDING}"', autoescape=True),
    )
    interrupted = and_(
        WorkJob.status == "failed", WorkJob.error_code == "WORKER_INTERRUPTED",
    )

    with session_factory() as session:
        assert_active_worker_lease(session, worker_id)
        jobs = list(session.scalars(
            select(WorkJob).where(
                WorkJob.kind == "archive-recovery",
                cancelled if cancelled_only else or_(cancelled, interrupted),
            )
        ))
    for job in jobs:
        try:
            if job.status == "cancelled":
                state = _consume_cancelled_output_cleanup(session_factory, worker_id, job)
                if state is None:
                    continue
            else:
                state = json.loads(job.state_json or "{}")
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
            assert_media_mutation_lock(settings)
            renew_and_assert_worker_lease(session_factory, worker_id)
            if job.status == "cancelled":
                _remove_empty_cancelled_output(output, output_stat)
            else:
                clean_interrupted_parts(output, state.get('output_identity', []))
            token = state.get('secret_token')
            discard_one_time_password(token)
        except (KeyError, OSError, ValueError):
            # No cleanup authority can be derived from malformed/stale job state.
            continue


def record_cancelled_output_cleanup(job: WorkJob) -> None:
    """Register a single attempt while the queued cancellation is committed."""
    try:
        state = json.loads(job.state_json or "{}")
    except (TypeError, ValueError):
        return
    if not isinstance(state, dict):
        return
    identity = state.get("output_identity")
    if isinstance(identity, list) and len(identity) == 2 and all(type(part) is str for part in identity):
        state[_CANCELLED_OUTPUT_PENDING] = True
        job.state_json = json.dumps(state, ensure_ascii=False)


def _consume_cancelled_output_cleanup(session_factory, worker_id: str, job: WorkJob) -> dict | None:
    from app.tasks.recovery import assert_active_worker_lease

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        current = session.get(WorkJob, job.id)
        if (
            current is None or current.kind != "archive-recovery" or current.status != "cancelled"
            or current.state_json != job.state_json
        ):
            return None
        state = json.loads(current.state_json or "{}")
        if not isinstance(state, dict) or state.pop(_CANCELLED_OUTPUT_PENDING, None) is not True:
            return None
        # Disarm before even observing the pathname. A crash, missing path or
        # stale inode must never authorize a second attempt against a later name.
        current.state_json = json.dumps(state, ensure_ascii=False)
        session.commit()
        return state


def _remove_empty_cancelled_output(output: Path, observed: os.stat_result) -> None:
    parent_fd = os.open(
        output.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    try:
        current = os.stat(output.name, dir_fd=parent_fd, follow_symlinks=False)
        if (current.st_dev, current.st_ino) == (observed.st_dev, observed.st_ino):
            os.rmdir(output.name, dir_fd=parent_fd)
    finally:
        os.close(parent_fd)


def discard_cancelled_recovery_password(state_json: str) -> None:
    """Retire the one-time RAM secret without accessing the media namespace."""
    try:
        state = json.loads(state_json or "{}")
        if isinstance(state, dict):
            discard_one_time_password(state.get("secret_token"))
    except (TypeError, ValueError):
        pass
