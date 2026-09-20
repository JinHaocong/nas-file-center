from __future__ import annotations

import contextlib
import errno
import hashlib
import os
from pathlib import Path
import stat
import uuid
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.batch_utilities.empty_dir_quarantine import (
    acquire_safe_quarantine_root_fd,
    safe_open_parent_fd,
)
from app.exceptions import StateConflictError
from app.fs_ops import rename_noreplace_at
from app.models import QuarantineEntry, utcnow
from app.quarantine.tx_allocator import allocate_and_create_attempt_dir
from app.tasks.recovery import assert_active_worker_lease, renew_and_assert_worker_lease


CROSS_STORAGE_MODE = "cross_storage_transactional"
_STAGING_NAME = "cross-storage-staging"
_COPY_CHUNK_SIZE = 8 * 1024 * 1024


def _mtime_ns(st: os.stat_result) -> int:
    return int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))


def _hash_fd(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, _COPY_CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError(errno.EIO, "short write while copying cross-storage quarantine payload")
        view = view[written:]


def _source_authority(
    entry: QuarantineEntry,
    *,
    expected_device: int | None,
    expected_inode: int | None,
    expected_size: int | None,
    expected_mtime_ns: int | None,
    expected_hash: str | None,
) -> tuple[int, int, int, int, str]:
    device = int(entry.device or expected_device or 0)
    inode = int(entry.inode or expected_inode or 0)
    size = int(entry.size if entry.size is not None else (expected_size or 0))
    mtime = int(entry.mtime_ns or expected_mtime_ns or 0)
    content_hash = str(entry.content_hash or expected_hash or "").lower()

    if device <= 0 or inode <= 0:
        raise StateConflictError("CROSS_STORAGE_FROZEN_IDENTITY_MISSING: source device/inode authority is required")
    if size < 0:
        raise StateConflictError("CROSS_STORAGE_FROZEN_IDENTITY_MISSING: source size authority is invalid")
    if mtime <= 0:
        raise StateConflictError("CROSS_STORAGE_FROZEN_IDENTITY_MISSING: source mtime authority is required")
    if len(content_hash) != 64 or any(ch not in "0123456789abcdef" for ch in content_hash):
        raise StateConflictError("CROSS_STORAGE_FROZEN_IDENTITY_MISSING: SHA256 authority is required")
    return device, inode, size, mtime, content_hash


def _assert_fd_source_identity(
    fd: int,
    *,
    device: int,
    inode: int,
    size: int,
    mtime_ns: int,
    failure_prefix: str,
) -> os.stat_result:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise StateConflictError(f"{failure_prefix}: source is not a regular file")
    if (
        int(st.st_dev) != device
        or int(st.st_ino) != inode
        or int(st.st_size) != size
        or _mtime_ns(st) != mtime_ns
    ):
        raise StateConflictError(f"{failure_prefix}: source identity changed")
    return st


def _qualify_fd_payload(
    fd: int,
    *,
    size: int,
    expected_hash: str,
    expected_device: int | None = None,
    expected_inode: int | None = None,
    expected_mtime_ns: int | None = None,
    failure_prefix: str,
) -> os.stat_result:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise StateConflictError(f"{failure_prefix}: payload is not a regular file")
    if int(before.st_size) != size:
        raise StateConflictError(f"{failure_prefix}: payload size changed")
    if expected_device is not None and int(before.st_dev) != int(expected_device):
        raise StateConflictError(f"{failure_prefix}: payload device changed")
    if expected_inode is not None and int(before.st_ino) != int(expected_inode):
        raise StateConflictError(f"{failure_prefix}: payload inode changed")
    if expected_mtime_ns is not None and _mtime_ns(before) != int(expected_mtime_ns):
        raise StateConflictError(f"{failure_prefix}: payload mtime changed")

    digest = _hash_fd(fd)
    if digest.lower() != expected_hash.lower():
        raise StateConflictError(f"{failure_prefix}: payload SHA256 mismatch")

    after = os.fstat(fd)
    if (
        int(after.st_dev) != int(before.st_dev)
        or int(after.st_ino) != int(before.st_ino)
        or int(after.st_size) != int(before.st_size)
        or _mtime_ns(after) != _mtime_ns(before)
    ):
        raise StateConflictError(f"{failure_prefix}: payload changed during qualification")
    return after


def ensure_safe_quarantine_parent(quarantine_root: Path | str, target: Path | str) -> None:
    q_root_abs = Path(quarantine_root).expanduser().absolute()
    target_abs = Path(target).expanduser().absolute()
    try:
        rel = target_abs.relative_to(q_root_abs)
    except ValueError as exc:
        raise StateConflictError("CROSS_STORAGE_TARGET_OUTSIDE_QUARANTINE_ROOT") from exc
    if len(rel.parts) < 1:
        raise StateConflictError("CROSS_STORAGE_TARGET_INVALID")

    q_fd, _raw_q, _ = acquire_safe_quarantine_root_fd(q_root_abs)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with contextlib.ExitStack() as stack:
        stack.callback(os.close, q_fd)
        curr_fd = q_fd
        for component in rel.parts[:-1]:
            if component in {"", ".", ".."}:
                raise StateConflictError("CROSS_STORAGE_TARGET_INVALID")
            try:
                os.mkdir(component, mode=0o700, dir_fd=curr_fd)
            except FileExistsError:
                pass
            next_fd = os.open(component, flags, dir_fd=curr_fd)
            stack.callback(os.close, next_fd)
            curr_fd = next_fd


def _fsync_parent(path: Path, valid_roots: Sequence[Path | str]) -> None:
    with safe_open_parent_fd(path, valid_roots) as (parent_fd, _leaf):
        os.fsync(parent_fd)


def _mark_conflict(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str | None,
    message: str,
) -> None:
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        if worker_id:
            assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            session.rollback()
            return
        entry.state = "conflict"
        entry.tx_phase = "conflict"
        entry.last_error = message
        entry.updated_at = utcnow()
        session.commit()


def _persist_phase(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str,
    phase: str,
    *,
    q_stat: os.stat_result | None = None,
) -> None:
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"QuarantineEntry {entry_id} not found")
        entry.transaction_mode = CROSS_STORAGE_MODE
        entry.tx_phase = phase
        entry.updated_at = utcnow()
        if q_stat is not None:
            entry.quarantine_device = int(q_stat.st_dev)
            entry.quarantine_inode = int(q_stat.st_ino)
            entry.quarantine_mtime_ns = _mtime_ns(q_stat)
        session.commit()


def _finalize_active(session_factory: sessionmaker, entry_id: int, worker_id: str) -> None:
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"QuarantineEntry {entry_id} not found")
        now = utcnow()
        entry.transaction_mode = CROSS_STORAGE_MODE
        entry.state = "active"
        entry.tx_phase = "active"
        entry.quarantined_at = entry.quarantined_at or now
        entry.updated_at = now
        entry.last_error = None
        session.commit()


def _verify_public_quarantine(
    path: Path,
    valid_roots: Sequence[Path | str],
    *,
    size: int,
    content_hash: str,
    q_device: int,
    q_inode: int,
    q_mtime_ns: int,
) -> None:
    with safe_open_parent_fd(path, valid_roots) as (parent_fd, leaf):
        fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            _qualify_fd_payload(
                fd,
                size=size,
                expected_hash=content_hash,
                expected_device=q_device,
                expected_inode=q_inode,
                expected_mtime_ns=q_mtime_ns,
                failure_prefix="CROSS_STORAGE_QUARANTINE_AUTHORITY_CHANGED",
            )
        finally:
            os.close(fd)


def _verify_and_unlink_source(
    source_path: Path,
    valid_roots: Sequence[Path | str],
    *,
    session_factory: sessionmaker,
    worker_id: str,
    device: int,
    inode: int,
    size: int,
    mtime_ns: int,
    content_hash: str,
) -> None:
    with safe_open_parent_fd(source_path, valid_roots) as (parent_fd, leaf):
        fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
        try:
            _assert_fd_source_identity(
                fd,
                device=device,
                inode=inode,
                size=size,
                mtime_ns=mtime_ns,
                failure_prefix="CROSS_STORAGE_SOURCE_CHANGED",
            )
            digest = _hash_fd(fd)
            if digest.lower() != content_hash.lower():
                raise StateConflictError("CROSS_STORAGE_SOURCE_CHANGED: source SHA256 changed")
            _assert_fd_source_identity(
                fd,
                device=device,
                inode=inode,
                size=size,
                mtime_ns=mtime_ns,
                failure_prefix="CROSS_STORAGE_SOURCE_CHANGED",
            )

            renew_and_assert_worker_lease(session_factory, worker_id)
            immediate = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(immediate.st_mode)
                or int(immediate.st_dev) != device
                or int(immediate.st_ino) != inode
                or int(immediate.st_size) != size
                or _mtime_ns(immediate) != mtime_ns
            ):
                raise StateConflictError("CROSS_STORAGE_SOURCE_CHANGED: source pathname binding changed before unlink")
            os.unlink(leaf, dir_fd=parent_fd)
            os.fsync(parent_fd)
        finally:
            os.close(fd)


def execute_cross_storage_quarantine(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str,
    *,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
    expected_device: int | None = None,
    expected_inode: int | None = None,
    expected_size: int | None = None,
    expected_mtime_ns: int | None = None,
    expected_hash: str | None = None,
) -> None:
    """Gate6-C transactional regular-file quarantine across filesystem devices.

    The source pathname is never unlinked until an independently-created
    quarantine payload has been copied, fsync'd, read-back SHA256 qualified,
    atomically published with NOREPLACE, re-qualified from the public path, and
    the durable source-unlink authority phase has been committed.
    """

    if not worker_id or not str(worker_id).strip():
        raise PermissionError("Cross-storage quarantine requires valid worker authority / lease")

    q_root = Path(quarantine_root).expanduser().absolute()
    valid_roots = list(allowed_roots)
    if q_root not in [Path(r).expanduser().absolute() for r in valid_roots]:
        valid_roots.append(q_root)

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"QuarantineEntry {entry_id} not found")

        if entry.transaction_mode == CROSS_STORAGE_MODE and entry.tx_phase not in (None, "preparing", "active"):
            session.rollback()
            reconcile_cross_storage_quarantine(
                session_factory,
                entry_id,
                worker_id,
                allowed_roots=allowed_roots,
                quarantine_root=q_root,
            )
            return

        source_path = Path(entry.original_path)
        quarantine_path = Path(entry.quarantine_path)
        device, inode, size, mtime_ns, content_hash = _source_authority(
            entry,
            expected_device=expected_device,
            expected_inode=expected_inode,
            expected_size=expected_size,
            expected_mtime_ns=expected_mtime_ns,
            expected_hash=expected_hash,
        )

        # Persist any caller-supplied frozen authority before the first filesystem write.
        entry.device = device
        entry.inode = inode
        entry.size = size
        entry.mtime_ns = mtime_ns
        entry.content_hash = content_hash
        entry.transaction_mode = CROSS_STORAGE_MODE
        entry.tx_token = entry.tx_token or uuid.uuid4().hex
        entry.state = "preparing"
        entry.tx_phase = "cross_copying"
        entry.last_error = None
        entry.updated_at = utcnow()
        session.commit()

    ensure_safe_quarantine_parent(q_root, quarantine_path)
    generation, attempt_dir = allocate_and_create_attempt_dir(
        session_factory,
        entry_id,
        worker_id,
        quarantine_root=q_root,
    )
    staging_path = attempt_dir / _STAGING_NAME

    try:
        with safe_open_parent_fd(source_path, valid_roots) as (src_parent_fd, src_leaf):
            src_fd = os.open(src_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=src_parent_fd)
            try:
                pre = _assert_fd_source_identity(
                    src_fd,
                    device=device,
                    inode=inode,
                    size=size,
                    mtime_ns=mtime_ns,
                    failure_prefix="CROSS_STORAGE_SOURCE_CHANGED",
                )

                with safe_open_parent_fd(staging_path, valid_roots) as (dst_parent_fd, dst_leaf):
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                    dst_fd = os.open(dst_leaf, flags, 0o600, dir_fd=dst_parent_fd)
                    digest = hashlib.sha256()
                    copied = 0
                    try:
                        while True:
                            chunk = os.read(src_fd, _COPY_CHUNK_SIZE)
                            if not chunk:
                                break
                            _write_all(dst_fd, chunk)
                            digest.update(chunk)
                            copied += len(chunk)
                        os.fsync(dst_fd)
                    finally:
                        os.close(dst_fd)

                if copied != size or digest.hexdigest().lower() != content_hash:
                    raise StateConflictError("CROSS_STORAGE_COPY_VERIFY_FAILED: streamed payload authority mismatch")

                post = _assert_fd_source_identity(
                    src_fd,
                    device=device,
                    inode=inode,
                    size=size,
                    mtime_ns=mtime_ns,
                    failure_prefix="CROSS_STORAGE_SOURCE_CHANGED",
                )
                if (
                    int(post.st_dev) != int(pre.st_dev)
                    or int(post.st_ino) != int(pre.st_ino)
                    or int(post.st_size) != int(pre.st_size)
                    or _mtime_ns(post) != _mtime_ns(pre)
                ):
                    raise StateConflictError("CROSS_STORAGE_SOURCE_CHANGED: source changed during copy")
            finally:
                os.close(src_fd)

        with safe_open_parent_fd(staging_path, valid_roots) as (st_parent_fd, st_leaf):
            verify_fd = os.open(st_leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=st_parent_fd)
            try:
                q_stat = _qualify_fd_payload(
                    verify_fd,
                    size=size,
                    expected_hash=content_hash,
                    failure_prefix="CROSS_STORAGE_COPY_VERIFY_FAILED",
                )
            finally:
                os.close(verify_fd)

        if int(q_stat.st_dev) == device:
            raise StateConflictError("CROSS_STORAGE_TOPOLOGY_CHANGED: quarantine payload is not on a different filesystem")

        _persist_phase(
            session_factory,
            entry_id,
            worker_id,
            "cross_staging_verified",
            q_stat=q_stat,
        )

        with safe_open_parent_fd(staging_path, valid_roots) as (src_parent_fd, src_leaf):
            with safe_open_parent_fd(quarantine_path, valid_roots) as (dst_parent_fd, dst_leaf):
                renew_and_assert_worker_lease(session_factory, worker_id)
                rename_noreplace_at(src_parent_fd, src_leaf, dst_parent_fd, dst_leaf)
                os.fsync(dst_parent_fd)

        _persist_phase(session_factory, entry_id, worker_id, "cross_public_published")

        _verify_public_quarantine(
            quarantine_path,
            valid_roots,
            size=size,
            content_hash=content_hash,
            q_device=int(q_stat.st_dev),
            q_inode=int(q_stat.st_ino),
            q_mtime_ns=_mtime_ns(q_stat),
        )

        _persist_phase(session_factory, entry_id, worker_id, "cross_source_unlink_authorized")

        _verify_and_unlink_source(
            source_path,
            valid_roots,
            session_factory=session_factory,
            worker_id=worker_id,
            device=device,
            inode=inode,
            size=size,
            mtime_ns=mtime_ns,
            content_hash=content_hash,
        )

        _finalize_active(session_factory, entry_id, worker_id)
    except Exception as exc:
        # Preserve every ambiguous object and never widen cleanup authority.
        # Recovery knows how to classify the private staging/public view by the
        # durable entry generation and destination identity.
        try:
            with session_factory() as session:
                current = session.get(QuarantineEntry, entry_id)
                already_conflict = bool(
                    current is not None
                    and (current.state == "conflict" or current.tx_phase == "conflict")
                )
            if not already_conflict and not isinstance(exc, FileExistsError):
                with session_factory() as session:
                    session.execute(text("BEGIN IMMEDIATE"))
                    assert_active_worker_lease(session, worker_id)
                    current = session.get(QuarantineEntry, entry_id)
                    if current is not None:
                        current.last_error = str(exc)
                        current.updated_at = utcnow()
                        session.commit()
            elif isinstance(exc, FileExistsError):
                _mark_conflict(
                    session_factory,
                    entry_id,
                    worker_id,
                    f"CROSS_STORAGE_TARGET_COLLISION: {exc}",
                )
        except Exception:
            pass
        raise


def reconcile_cross_storage_quarantine(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str,
    *,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
) -> None:
    """Converge an interrupted Gate6-C quarantine without deleting replacements."""

    q_root = Path(quarantine_root).expanduser().absolute()
    valid_roots = list(allowed_roots)
    if q_root not in [Path(r).expanduser().absolute() for r in valid_roots]:
        valid_roots.append(q_root)

    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"QuarantineEntry {entry_id} not found")
        if entry.transaction_mode != CROSS_STORAGE_MODE:
            raise StateConflictError("CROSS_STORAGE_RECOVERY_MODE_MISMATCH")
        if entry.tx_phase == "active" and entry.state == "active":
            return

        source_path = Path(entry.original_path)
        quarantine_path = Path(entry.quarantine_path)
        generation = int(entry.active_attempt_generation or 0)
        staging_path = q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{generation}" / _STAGING_NAME
        device, inode, size, mtime_ns, content_hash = _source_authority(
            entry,
            expected_device=None,
            expected_inode=None,
            expected_size=None,
            expected_mtime_ns=None,
            expected_hash=None,
        )
        phase = entry.tx_phase
        q_device = entry.quarantine_device
        q_inode = entry.quarantine_inode
        q_mtime = entry.quarantine_mtime_ns

    if phase in {"cross_copying", "preparing", None}:
        # A private staging file in this phase was never granted publication or
        # source-unlink authority. It is safe to retire only when it is the exact
        # current-generation private regular-file slot.
        if os.path.lexists(staging_path):
            try:
                with safe_open_parent_fd(staging_path, valid_roots) as (parent_fd, leaf):
                    st = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                    if not stat.S_ISREG(st.st_mode):
                        raise StateConflictError("CROSS_STORAGE_RECOVERY_AMBIGUOUS_STAGING")
                    renew_and_assert_worker_lease(session_factory, worker_id)
                    os.unlink(leaf, dir_fd=parent_fd)
                    os.fsync(parent_fd)
            except Exception as exc:
                _mark_conflict(session_factory, entry_id, worker_id, str(exc))
                raise
        if os.path.lexists(quarantine_path):
            _mark_conflict(
                session_factory,
                entry_id,
                worker_id,
                "CROSS_STORAGE_RECOVERY_AMBIGUOUS_PUBLIC_VIEW",
            )
            raise StateConflictError("CROSS_STORAGE_RECOVERY_AMBIGUOUS_PUBLIC_VIEW")

        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            assert_active_worker_lease(session, worker_id)
            entry = session.get(QuarantineEntry, entry_id)
            entry.tx_phase = "preparing"
            entry.updated_at = utcnow()
            session.commit()
        execute_cross_storage_quarantine(
            session_factory,
            entry_id,
            worker_id,
            allowed_roots=allowed_roots,
            quarantine_root=q_root,
        )
        return

    if q_device is None or q_inode is None or q_mtime is None:
        _mark_conflict(
            session_factory,
            entry_id,
            worker_id,
            "CROSS_STORAGE_RECOVERY_AUTHORITY_MISSING: destination identity missing",
        )
        raise StateConflictError("CROSS_STORAGE_RECOVERY_AUTHORITY_MISSING")

    q_device_i = int(q_device)
    q_inode_i = int(q_inode)
    q_mtime_i = int(q_mtime)

    if phase == "cross_staging_verified":
        staging_exists = os.path.lexists(staging_path)
        public_exists = os.path.lexists(quarantine_path)

        if staging_exists and public_exists:
            _mark_conflict(session_factory, entry_id, worker_id, "CROSS_STORAGE_RECOVERY_AMBIGUOUS_PUBLICATION")
            raise StateConflictError("CROSS_STORAGE_RECOVERY_AMBIGUOUS_PUBLICATION")
        if staging_exists:
            with safe_open_parent_fd(staging_path, valid_roots) as (parent_fd, leaf):
                fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
                try:
                    _qualify_fd_payload(
                        fd,
                        size=size,
                        expected_hash=content_hash,
                        expected_device=q_device_i,
                        expected_inode=q_inode_i,
                        expected_mtime_ns=q_mtime_i,
                        failure_prefix="CROSS_STORAGE_RECOVERY_STAGING_CHANGED",
                    )
                finally:
                    os.close(fd)
            ensure_safe_quarantine_parent(q_root, quarantine_path)
            with safe_open_parent_fd(staging_path, valid_roots) as (src_parent_fd, src_leaf):
                with safe_open_parent_fd(quarantine_path, valid_roots) as (dst_parent_fd, dst_leaf):
                    renew_and_assert_worker_lease(session_factory, worker_id)
                    rename_noreplace_at(src_parent_fd, src_leaf, dst_parent_fd, dst_leaf)
                    os.fsync(dst_parent_fd)
        elif public_exists:
            _verify_public_quarantine(
                quarantine_path,
                valid_roots,
                size=size,
                content_hash=content_hash,
                q_device=q_device_i,
                q_inode=q_inode_i,
                q_mtime_ns=q_mtime_i,
            )
        else:
            _mark_conflict(session_factory, entry_id, worker_id, "CROSS_STORAGE_RECOVERY_DESTINATION_MISSING")
            raise StateConflictError("CROSS_STORAGE_RECOVERY_DESTINATION_MISSING")

        _persist_phase(session_factory, entry_id, worker_id, "cross_public_published")
        phase = "cross_public_published"

    if phase in {"cross_public_published", "cross_source_unlink_authorized"}:
        _verify_public_quarantine(
            quarantine_path,
            valid_roots,
            size=size,
            content_hash=content_hash,
            q_device=q_device_i,
            q_inode=q_inode_i,
            q_mtime_ns=q_mtime_i,
        )

        try:
            with safe_open_parent_fd(source_path, valid_roots) as (parent_fd, leaf):
                src_stat = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            source_exists = True
        except FileNotFoundError:
            source_exists = False
            src_stat = None

        if not source_exists:
            _finalize_active(session_factory, entry_id, worker_id)
            return

        assert src_stat is not None
        if (
            not stat.S_ISREG(src_stat.st_mode)
            or int(src_stat.st_dev) != device
            or int(src_stat.st_ino) != inode
            or int(src_stat.st_size) != size
            or _mtime_ns(src_stat) != mtime_ns
        ):
            _mark_conflict(
                session_factory,
                entry_id,
                worker_id,
                "CROSS_STORAGE_SOURCE_REPLACEMENT_DETECTED: replacement preserved",
            )
            raise StateConflictError("CROSS_STORAGE_SOURCE_REPLACEMENT_DETECTED")

        if phase != "cross_source_unlink_authorized":
            _persist_phase(session_factory, entry_id, worker_id, "cross_source_unlink_authorized")

        _verify_and_unlink_source(
            source_path,
            valid_roots,
            session_factory=session_factory,
            worker_id=worker_id,
            device=device,
            inode=inode,
            size=size,
            mtime_ns=mtime_ns,
            content_hash=content_hash,
        )
        _finalize_active(session_factory, entry_id, worker_id)
        return

    raise StateConflictError(f"CROSS_STORAGE_RECOVERY_UNKNOWN_PHASE: {phase}")
