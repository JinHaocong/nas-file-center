"""Fail-closed shared API/Worker config-file permission gate.

Only enabled when NFC_SHARED_CONFIG_GID is explicitly configured.  No
existing host directory, database or evidence file is chmod/chowned here.
The two-UID configuration requires a trusted, pre-provisioned setgid root;
this is *not* a POSIX/NAS ACL or exclusive media namespace proof.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat


_ERROR = "SHARED_CONFIG"


def shared_config_gid() -> int | None:
    raw = os.environ.get("NFC_SHARED_CONFIG_GID", "").strip()
    if not raw:
        return None
    if not raw.isascii() or not raw.isdecimal():
        raise PermissionError(f"{_ERROR}: invalid numeric group ID")
    gid = int(raw)
    if gid <= 0 or gid != os.getegid():
        raise PermissionError(f"{_ERROR}: configured group must match non-root effective GID")
    return gid


def _validate_shared_directory_fd(directory_fd: int, directory: Path, gid: int) -> None:
    st = os.fstat(directory_fd)
    mode = stat.S_IMODE(st.st_mode)
    if (
        not stat.S_ISDIR(st.st_mode)
        or st.st_gid != gid
        or (mode & 0o070) != 0o070
        or not (mode & stat.S_ISGID)
        or mode & 0o007
    ):
        raise PermissionError(f"{_ERROR}: expected trusted setgid 2770 directory {directory}")
    # The FD must still identify the exact configured directory, not a
    # replacement reached through its pathname.
    try:
        bound = os.stat(directory, follow_symlinks=False)
    except OSError as exc:
        raise PermissionError(f"{_ERROR}: directory binding is unavailable {directory}") from exc
    if not stat.S_ISDIR(bound.st_mode) or (bound.st_dev, bound.st_ino) != (st.st_dev, st.st_ino):
        raise PermissionError(f"{_ERROR}: directory identity changed {directory}")


def _open_shared_directory(directory: Path, gid: int) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(directory, flags)
    except OSError as exc:
        raise PermissionError(f"{_ERROR}: unsafe or inaccessible directory {directory}") from exc
    try:
        _validate_shared_directory_fd(fd, directory, gid)
        return fd
    except BaseException:
        os.close(fd)
        raise


def require_shared_directory(directory: Path, gid: int) -> None:
    fd = _open_shared_directory(directory, gid)
    os.close(fd)


def pinned_directory_entry_path(directory_fd: int, name: str) -> str:
    """Return a proc-fd path to one entry below a verified, already-open directory.

    Some NAS FUSE implementations support stat(dir_fd=...) but return ENOENT
    for openat on existing files or O_CREAT against an absolute mount-root
    path. Resolving /proc/self/fd/<fd>/<name> keeps the directory inode pinned
    while using ordinary path lookup. Callers must compare the opened or newly
    created descriptor with a no-follow stat of the named entry before use.
    """
    if (
        not isinstance(name, str)
        or not name
        or name in {".", ".."}
        or os.path.basename(name) != name
        or chr(0) in name
    ):
        raise PermissionError(f"{_ERROR}: invalid pinned directory entry name")
    opened_directory = os.fstat(directory_fd)
    proc_directory = f"/proc/self/fd/{directory_fd}"
    try:
        named_directory = os.stat(proc_directory)
    except OSError as exc:
        raise PermissionError(f"{_ERROR}: pinned directory FD is not addressable through procfs") from exc
    if (
        not stat.S_ISDIR(opened_directory.st_mode)
        or not stat.S_ISDIR(named_directory.st_mode)
        or (opened_directory.st_dev, opened_directory.st_ino)
        != (named_directory.st_dev, named_directory.st_ino)
    ):
        raise PermissionError(f"{_ERROR}: pinned directory FD identity mismatch")
    return f"{proc_directory}/{name}"


def require_shared_file(path: Path, gid: int, mode: int) -> None:
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise PermissionError(f"{_ERROR}: missing or inaccessible file {path}") from exc
    if not stat.S_ISREG(st.st_mode) or st.st_gid != gid or stat.S_IMODE(st.st_mode) != mode:
        raise PermissionError(f"{_ERROR}: invalid group/mode/identity for existing file {path}")


def _require_shared_file_at(directory_fd: int, name: str, gid: int, mode: int):
    try:
        st = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError as exc:
        raise PermissionError(f"{_ERROR}: missing or inaccessible file {name}") from exc
    if not stat.S_ISREG(st.st_mode) or st.st_gid != gid or stat.S_IMODE(st.st_mode) != mode:
        raise PermissionError(f"{_ERROR}: invalid group/mode/identity for existing file {name}")
    return st


def _new_group_file(path: Path, gid: int, mode: int, *, directory_fd: int) -> None:
    # Create through the pinned directory FD's procfs handle. The NAS ZFuse
    # mount can return ENOENT for O_CREAT against an ordinary absolute path
    # at the shared config root, even though the directory is present and
    # writable. O_EXCL remains the atomic no-replace guard: an existing entry,
    # including a symlink, is never followed or overwritten.
    name = path.name
    if not name or name in {".", ".."} or os.path.basename(name) != name:
        raise PermissionError(f"{_ERROR}: invalid shared config filename")
    entry_path = pinned_directory_entry_path(directory_fd, name)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    created_identity = None
    try:
        fd = os.open(entry_path, flags, mode)
    except FileExistsError:
        pass
    else:
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_gid != gid or st.st_uid != os.geteuid():
                raise PermissionError(f"{_ERROR}: new file has unexpected owner/group")
            # fchmod ONLY the newly created inode, never an existing NAS file.
            os.fchmod(fd, mode)
            st = os.fstat(fd)
            if st.st_nlink != 1:
                raise PermissionError(f"{_ERROR}: new shared config file has unexpected link count")
            created_identity = (st.st_dev, st.st_ino)
        finally:
            os.close(fd)
    named = _require_shared_file_at(directory_fd, name, gid, mode)
    if created_identity is not None and (named.st_dev, named.st_ino) != created_identity:
        raise PermissionError(f"{_ERROR}: newly created file binding changed {name}")


def ensure_shared_database(db_path: Path, gid: int) -> None:
    directory_fd = _open_shared_directory(db_path.parent, gid)
    try:
        _new_group_file(db_path, gid, 0o660, directory_fd=directory_fd)
        # SQLite's sidecars inherit the main DB's mode; pre-existing sidecars
        # must already have the required permissions. Never chmod them here.
        for suffix in ("-wal", "-shm"):
            name = db_path.name + suffix
            try:
                sidecar = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise PermissionError(f"{_ERROR}: inaccessible SQLite sidecar {name}") from exc
            if (
                not stat.S_ISREG(sidecar.st_mode)
                or sidecar.st_gid != gid
                or stat.S_IMODE(sidecar.st_mode) != 0o660
            ):
                raise PermissionError(f"{_ERROR}: invalid group/mode/identity for SQLite sidecar {name}")
    finally:
        os.close(directory_fd)


def ensure_shared_init_lock(
    lock_path: Path, gid: int, *, directory_fd: int | None = None,
) -> None:
    owns_directory_fd = directory_fd is None
    if directory_fd is None:
        directory_fd = _open_shared_directory(lock_path.parent, gid)
    else:
        _validate_shared_directory_fd(directory_fd, lock_path.parent, gid)
    try:
        _new_group_file(lock_path, gid, 0o660, directory_fd=directory_fd)
    finally:
        if owns_directory_fd:
            os.close(directory_fd)


def ensure_shared_report_directory(directory: Path, gid: int) -> None:
    require_shared_directory(directory.parent, gid)
    created = False
    try:
        os.mkdir(directory, 0o2770)
        created = True
    except FileExistsError:
        pass
    if created:
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(directory, flags)
        try:
            st = os.fstat(fd)
            if st.st_uid != os.geteuid() or st.st_gid != gid:
                raise PermissionError(f"{_ERROR}: report directory owner/group mismatch")
            # Only change the newly created directory by FD; never repair existing.
            os.fchmod(fd, 0o2770)
        finally:
            os.close(fd)
    require_shared_directory(directory, gid)
