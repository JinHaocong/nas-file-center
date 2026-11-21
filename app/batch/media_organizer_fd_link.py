"""Linux inode-bound, exclusive hardlink primitive for V1.6 retained originals.

The preferred linkat(AT_EMPTY_PATH) form requires CAP_DAC_READ_SEARCH. The
unprivileged equivalent follows this process' stable /proc/self/fd/<n> magic
link with AT_SYMLINK_FOLLOW. Both forms remain bound to the already-open inode;
there is deliberately no source-basename fallback.
"""
from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys

_AT_FDCWD = -100
_AT_EMPTY_PATH = 0x1000
_AT_SYMLINK_FOLLOW = 0x400


def _call_linkat(linkat, olddirfd: int, oldpath: bytes, newdirfd: int,
                 newpath: bytes, flags: int) -> None:
    ctypes.set_errno(0)
    result = linkat(olddirfd, oldpath, newdirfd, newpath, flags)
    if result != 0:
        code = ctypes.get_errno() or errno.EIO
        raise OSError(code, os.strerror(code), os.fsdecode(newpath))


def link_pinned_inode_noreplace(source_fd: int, destination_dir_fd: int,
                               destination_basename: str) -> None:
    """Create an exclusive hardlink from a pinned regular inode, never by source name.

    The caller opens the source with O_NOFOLLOW and verifies the frozen inode.
    AT_EMPTY_PATH is attempted first. ENOENT is the documented result when
    CAP_DAC_READ_SEARCH is absent; only then use /proc/self/fd/<fd> with
    AT_SYMLINK_FOLLOW. No pathname derived from the original source basename
    is ever used. linkat itself supplies destination no-replace semantics.
    """
    if not isinstance(destination_basename, str) or (
        destination_basename in ("", ".", "..")
        or "/" in destination_basename or "\x00" in destination_basename
    ):
        raise ValueError("unsafe destination basename for pinned hardlink")
    if not sys.platform.startswith("linux"):
        raise OSError(errno.EOPNOTSUPP, "pinned fd hardlinks require Linux")

    observed = os.fstat(source_fd)
    if not stat.S_ISREG(observed.st_mode):
        raise ValueError("pinned hardlink source is not a regular file")

    libc = ctypes.CDLL(None, use_errno=True)
    linkat = getattr(libc, "linkat", None)
    if linkat is None:
        raise OSError(errno.ENOSYS, "linkat unavailable; name fallback forbidden")
    linkat.argtypes = [ctypes.c_int, ctypes.c_char_p,
                       ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    linkat.restype = ctypes.c_int

    target = os.fsencode(destination_basename)
    try:
        _call_linkat(linkat, source_fd, b"", destination_dir_fd,
                     target, _AT_EMPTY_PATH)
    except OSError as exc:
        if exc.errno != errno.ENOENT:
            raise
        # Linux documents this procfs form as the unprivileged alternative
        # to AT_EMPTY_PATH. Verify the magic link resolves to the same open
        # inode before asking linkat to follow it.
        proc_path = f"/proc/self/fd/{source_fd}"
        try:
            proc_info = os.stat(proc_path, follow_symlinks=True)
        except OSError:
            raise exc
        if (not stat.S_ISREG(proc_info.st_mode)
                or (int(proc_info.st_dev), int(proc_info.st_ino)) !=
                (int(observed.st_dev), int(observed.st_ino))):
            raise OSError(errno.ESTALE, "proc fd link no longer identifies pinned source")
        _call_linkat(linkat, _AT_FDCWD, os.fsencode(proc_path),
                     destination_dir_fd, target, _AT_SYMLINK_FOLLOW)

    current_source = os.fstat(source_fd)
    if (not stat.S_ISREG(current_source.st_mode)
            or (int(current_source.st_dev), int(current_source.st_ino)) !=
            (int(observed.st_dev), int(observed.st_ino))):
        raise OSError(errno.ESTALE, "pinned source identity changed during hardlink")

    created = os.stat(destination_basename, dir_fd=destination_dir_fd,
                      follow_symlinks=False)
    if (not stat.S_ISREG(created.st_mode)
            or (int(created.st_dev), int(created.st_ino)) !=
            (int(observed.st_dev), int(observed.st_ino))):
        raise OSError(errno.ESTALE, "published hardlink does not match pinned source inode")
