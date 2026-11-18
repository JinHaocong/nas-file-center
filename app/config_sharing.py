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


def require_shared_directory(directory: Path, gid: int) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(directory, flags)
    except OSError as exc:
        raise PermissionError(f"{_ERROR}: unsafe or inaccessible directory {directory}") from exc
    try:
        st = os.fstat(fd)
        mode = stat.S_IMODE(st.st_mode)
        if (
            not stat.S_ISDIR(st.st_mode)
            or st.st_gid != gid
            or (mode & 0o070) != 0o070
            or not (mode & stat.S_ISGID)
            or mode & 0o007
        ):
            raise PermissionError(f"{_ERROR}: expected trusted setgid 2770 directory {directory}")
        # A swapped basename must not be accepted as the opened directory.
        bound = os.stat(directory, follow_symlinks=False)
        if (bound.st_dev, bound.st_ino) != (st.st_dev, st.st_ino):
            raise PermissionError(f"{_ERROR}: directory identity changed {directory}")
    finally:
        os.close(fd)


def require_shared_file(path: Path, gid: int, mode: int) -> None:
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise PermissionError(f"{_ERROR}: missing or inaccessible file {path}") from exc
    if not stat.S_ISREG(st.st_mode) or st.st_gid != gid or stat.S_IMODE(st.st_mode) != mode:
        raise PermissionError(f"{_ERROR}: invalid group/mode/identity for existing file {path}")


def _new_group_file(path: Path, gid: int, mode: int) -> None:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags, mode)
    except FileExistsError:
        pass
    else:
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_gid != gid or st.st_uid != os.geteuid():
                raise PermissionError(f"{_ERROR}: new file has unexpected owner/group")
            # fchmod ONLY the newly created inode, never an existing NAS file.
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
    require_shared_file(path, gid, mode)


def ensure_shared_database(db_path: Path, gid: int) -> None:
    require_shared_directory(db_path.parent, gid)
    _new_group_file(db_path, gid, 0o660)
    # SQLite's sidecars inherit the main DB's mode; pre-existing sidecars
    # must already have the required permissions. Never chmod them here.
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if os.path.lexists(sidecar):
            require_shared_file(sidecar, gid, 0o660)


def ensure_shared_init_lock(lock_path: Path, gid: int) -> None:
    require_shared_directory(lock_path.parent, gid)
    _new_group_file(lock_path, gid, 0o660)


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
