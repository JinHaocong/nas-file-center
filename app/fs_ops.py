from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import sys

__all__ = ["rename_noreplace"]

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 0x00000004


def _get_linux_rename_func():
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except Exception:
        return None

    if hasattr(libc, "renameat2"):
        func = libc.renameat2
        func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        func.restype = ctypes.c_int

        def _linux_rename(src: bytes, dst: bytes) -> int:
            return func(_AT_FDCWD, src, _AT_FDCWD, dst, _RENAME_NOREPLACE)

        return _linux_rename

    # Fallback to syscall if renameat2 not in libc symbol table
    if hasattr(libc, "syscall"):
        # Syscall numbers for renameat2
        # x86_64: 316, aarch64: 276
        import platform
        machine = platform.machine().lower()
        if machine in ("x86_64", "amd64"):
            nr_renameat2 = 316
        elif machine in ("aarch64", "arm64"):
            nr_renameat2 = 276
        else:
            return None

        syscall = libc.syscall
        syscall.argtypes = [ctypes.c_long, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        syscall.restype = ctypes.c_int

        def _linux_syscall_rename(src: bytes, dst: bytes) -> int:
            return syscall(nr_renameat2, _AT_FDCWD, src, _AT_FDCWD, dst, _RENAME_NOREPLACE)

        return _linux_syscall_rename

    return None


def _get_darwin_rename_func():
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except Exception:
        return None

    if hasattr(libc, "renamex_np"):
        func = libc.renamex_np
        func.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        func.restype = ctypes.c_int

        def _darwin_rename(src: bytes, dst: bytes) -> int:
            return func(src, dst, _RENAME_EXCL)

        return _darwin_rename

    return None


_RENAME_IMPL = None
if sys.platform.startswith("linux"):
    _RENAME_IMPL = _get_linux_rename_func()
elif sys.platform == "darwin":
    _RENAME_IMPL = _get_darwin_rename_func()


def rename_noreplace(source: Path | str, target: Path | str) -> None:
    """
    Atomically renames `source` to `target` with strict NO-REPLACE semantics.
    If `target` already exists, raises FileExistsError without overwriting `target`.
    If cross-device link (EXDEV), raises OSError with errno.EXDEV.
    If platform lacks atomic no-replace capability, fails closed with NotImplementedError.
    """
    if _RENAME_IMPL is None:
        raise NotImplementedError("Atomic no-replace rename is not available on this platform; failing closed.")

    src_bytes = os.fsencode(str(source))
    dst_bytes = os.fsencode(str(target))

    res = _RENAME_IMPL(src_bytes, dst_bytes)
    if res != 0:
        err = ctypes.get_errno()
        if err in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(errno.EEXIST, f"Target path already exists: {target}")
        if err == errno.EXDEV:
            raise OSError(errno.EXDEV, f"Cross-device rename not permitted: {source} -> {target}")
        if err == errno.ENOENT:
            raise FileNotFoundError(errno.ENOENT, f"No such file or directory: {source}")
        raise OSError(err, os.strerror(err), str(source))
