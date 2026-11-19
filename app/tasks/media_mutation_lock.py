"""Cooperative media exclusion for processes sharing one trusted CONFIG_DIR.

The config mount must be the same local filesystem and inode namespace for all
participants, with working Linux flock and access limited to trusted principals.
Separate mounts/replicas, processes bypassing this guard, config replacement by
an operator, and external media writers are outside this coordination boundary.
The database Worker lease is a separate fence and cannot release this lock.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import stat
import threading
from typing import Iterator

from app.config import Settings
from app.config_sharing import shared_config_gid

_LOCK_NAME = ".media-mutation.lock"
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class MediaMutationLockUnavailable(PermissionError):
    """The cooperative lock is inaccessible or its binding is unsafe."""


class MediaMutationLockBusy(MediaMutationLockUnavailable):
    """Another cooperative operation already holds the lock."""


@dataclass(frozen=True)
class _Lock:
    directory_fd: int
    file_fd: int
    gid: int | None


_local = threading.local()
_fd_guard = threading.Lock()
_open_fds: set[int] = set()
_bindings: dict[Path, tuple[tuple[int, int], tuple[int, int]]] = {}


def _after_fork_child() -> None:
    global _local
    # A child must not retain the parent's open file description. Closing the
    # inherited references leaves the parent's flock intact; LOCK_UN would not.
    for fd in _open_fds:
        os.close(fd)
    _open_fds.clear()
    _local = threading.local()
    _fd_guard.release()


os.register_at_fork(
    before=_fd_guard.acquire,
    after_in_parent=_fd_guard.release,
    after_in_child=_after_fork_child,
)


def _config_path(settings: Settings) -> Path:
    if ".." in settings.config_dir.parts:
        # Lexical normalization of a symlink followed by ".." could otherwise
        # lock a different directory than the one opening the database uses.
        raise MediaMutationLockUnavailable("Media mutation lock requires a canonical CONFIG_DIR")
    return Path(os.path.abspath(settings.config_dir))


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _open_directory(path: Path) -> int:
    """Open every component without following symlinks."""
    fd = os.open(path.anchor, _DIRECTORY_FLAGS)
    try:
        for name in path.parts[1:]:
            next_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    except BaseException:
        os.close(fd)
        raise
    return fd


def _check_directory(info: os.stat_result, gid: int | None) -> None:
    mode = stat.S_IMODE(info.st_mode)
    if gid is None:
        valid = info.st_uid == os.geteuid() and mode & 0o700 == 0o700 and not mode & 0o022
    else:
        valid = info.st_gid == gid and mode & 0o2070 == 0o2070 and not mode & 0o007
    if not stat.S_ISDIR(info.st_mode) or not valid:
        raise MediaMutationLockUnavailable("Media mutation lock directory permissions are unsafe")


def _check_file(info: os.stat_result, gid: int | None) -> None:
    if gid is None:
        valid = info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600
    else:
        valid = info.st_uid != 0 and info.st_gid == gid and stat.S_IMODE(info.st_mode) == 0o660
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not valid:
        raise MediaMutationLockUnavailable("Media mutation lock file permissions or type are unsafe")


def _validate(path: Path, lock: _Lock) -> None:
    try:
        with _fd_guard:
            named_directory_fd = _open_directory(path)
            try:
                directory = os.fstat(lock.directory_fd)
                named_directory = os.fstat(named_directory_fd)
                file = os.fstat(lock.file_fd)
                named_file = os.stat(_LOCK_NAME, dir_fd=named_directory_fd, follow_symlinks=False)
                _check_directory(directory, lock.gid)
                _check_file(file, lock.gid)
                _check_file(named_file, lock.gid)
                binding = (_identity(directory), _identity(file))
                if (
                    binding != (_identity(named_directory), _identity(named_file))
                    or _bindings.get(path, binding) != binding
                ):
                    raise MediaMutationLockUnavailable("Media mutation lock binding changed")
                _bindings[path] = binding
            finally:
                os.close(named_directory_fd)
    except MediaMutationLockUnavailable:
        raise
    except OSError as exc:
        raise MediaMutationLockUnavailable("Cannot revalidate the media mutation lock") from exc


def _acquire_flock(fd: int, *, blocking: bool) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise MediaMutationLockBusy("Media mutation lock is busy") from exc


def _close_fd(fd: int) -> None:
    with _fd_guard:
        _open_fds.remove(fd)
        os.close(fd)


def _held_locks() -> dict[Path, _Lock]:
    if not hasattr(_local, "locks"):
        _local.locks = {}
    return _local.locks


def assert_media_mutation_lock(settings: Settings) -> None:
    """Assert current-thread ownership and revalidate the held inode binding."""
    path = _config_path(settings)
    lock = _held_locks().get(path)
    if lock is None:
        raise MediaMutationLockUnavailable("Media mutation lock is required on the current thread")
    _validate(path, lock)


@contextmanager
def media_mutation_lock(settings: Settings, *, blocking: bool = True) -> Iterator[None]:
    """Hold exclusive media mutation access for the current thread and process."""
    path = _config_path(settings)
    locks = _held_locks()
    if path in locks:
        _validate(path, locks[path])
        yield
        _validate(path, locks[path])
        return

    process_id = os.getpid()
    directory_fd = None
    file_fd = None
    try:
        try:
            gid = shared_config_gid()
            with _fd_guard:
                directory_fd = _open_directory(path)
                _open_fds.add(directory_fd)
            _check_directory(os.fstat(directory_fd), gid)
            # A second flock on the pinned directory prevents accepting a
            # replacement lock-file inode while another holder is unwinding.
            _acquire_flock(directory_fd, blocking=blocking)
            with _fd_guard:
                try:
                    file_fd = os.open(_LOCK_NAME, _FILE_FLAGS, dir_fd=directory_fd)
                except FileNotFoundError:
                    if path in _bindings:
                        raise MediaMutationLockUnavailable("Media mutation lock file disappeared")
                    mode = 0o600 if gid is None else 0o660
                    file_fd = os.open(
                        _LOCK_NAME, _FILE_FLAGS | os.O_CREAT | os.O_EXCL, mode, dir_fd=directory_fd,
                    )
                    _open_fds.add(file_fd)
                    os.fchmod(file_fd, mode)
                else:
                    _open_fds.add(file_fd)
            lock = _Lock(directory_fd, file_fd, gid)
            _validate(path, lock)
            _acquire_flock(file_fd, blocking=blocking)
            _validate(path, lock)
        except MediaMutationLockUnavailable:
            raise
        except OSError as exc:
            raise MediaMutationLockUnavailable("Cannot acquire the media mutation lock") from exc

        locks[path] = lock
        try:
            yield
            _validate(path, lock)
        finally:
            locks.pop(path)
    finally:
        # The at-fork child hook already closed these FDs in a forked child.
        if os.getpid() == process_id:
            if file_fd is not None:
                _close_fd(file_fd)
            if directory_fd is not None:
                _close_fd(directory_fd)
