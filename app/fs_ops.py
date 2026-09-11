"""
Native Atomic Filesystem Primitives.

This module provides atomic filesystem primitives only (`renameat2(..., RENAME_NOREPLACE)`
on Linux and `renameatx_np(..., RENAME_EXCL)` on macOS Darwin).
The transactional quarantine engine (app.quarantine.engine and app.quarantine.restore) is
the sole source of atomic/isolated mutations on COMPAT filesystems where native no-replace
rename primitives are unsupported.
"""
from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import stat
import sys

__all__ = ["rename_noreplace", "rename_noreplace_at"]

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


def _get_linux_rename_at_func():
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except Exception:
        return None

    if hasattr(libc, "renameat2"):
        func = libc.renameat2
        func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        func.restype = ctypes.c_int

        def _linux_rename_at(sfd: int, src: bytes, dfd: int, dst: bytes) -> int:
            return func(sfd, src, dfd, dst, _RENAME_NOREPLACE)

        return _linux_rename_at

    if hasattr(libc, "syscall"):
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

        def _linux_syscall_rename_at(sfd: int, src: bytes, dfd: int, dst: bytes) -> int:
            return syscall(nr_renameat2, sfd, src, dfd, dst, _RENAME_NOREPLACE)

        return _linux_syscall_rename_at

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


def _get_darwin_rename_at_func():
    try:
        libc = ctypes.CDLL(None, use_errno=True)
    except Exception:
        return None

    if hasattr(libc, "renameatx_np"):
        func = libc.renameatx_np
        func.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        func.restype = ctypes.c_int

        def _darwin_rename_at(sfd: int, src: bytes, dfd: int, dst: bytes) -> int:
            return func(sfd, src, dfd, dst, _RENAME_EXCL)

        return _darwin_rename_at

    return None


_RENAME_IMPL = None
_RENAME_AT_IMPL = None
if sys.platform.startswith("linux"):
    _RENAME_IMPL = _get_linux_rename_func()
    _RENAME_AT_IMPL = _get_linux_rename_at_func()
elif sys.platform == "darwin":
    _RENAME_IMPL = _get_darwin_rename_func()
    _RENAME_AT_IMPL = _get_darwin_rename_at_func()


def _normalize_dir_fd(dfd: int | None) -> int | None:
    if dfd is None or dfd in (_AT_FDCWD, -2):
        return None
    return dfd


def _probe_rename_noreplace_supported(
    target: Path | str | None = None,
    *,
    dir_path: Path | str | None = None,
    dir_fd: int | None = None,
) -> bool | None:
    """
    Probes whether the filesystem at target directory or dir_fd supports atomic RENAME_NOREPLACE.
    Uses a valid, existing disposable temporary file to exercise the filesystem's handling
    of the RENAME_NOREPLACE flag.
    Returns:
      True:  Filesystem supports RENAME_NOREPLACE (e.g. probe rename returned 0).
      False: Filesystem rejects RENAME_NOREPLACE capability (e.g. returned EINVAL/ENOSYS/EOPNOTSUPP on existing source).
      None:  Capability could not be safely established (fails closed).
    """
    if dir_fd is not None and _RENAME_AT_IMPL is not None:
        dfd_norm = _normalize_dir_fd(dir_fd)
        raw_fd = _AT_FDCWD if dfd_norm is None else dfd_norm
        token = os.urandom(8).hex()
        probe_src_name = f".__probe_noreplace_src_{token}"
        probe_dst_name = f".__probe_noreplace_dst_{token}"

        try:
            fd = os.open(
                probe_src_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dfd_norm,
            )
            os.close(fd)
        except Exception:
            return None

        try:
            res = _RENAME_AT_IMPL(
                raw_fd,
                os.fsencode(probe_src_name),
                raw_fd,
                os.fsencode(probe_dst_name),
            )
            if res == 0:
                return True
            perr = ctypes.get_errno()
            if perr in (
                errno.EINVAL,
                errno.ENOSYS,
                errno.EOPNOTSUPP,
                getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
            ):
                return False
            return None
        finally:
            try:
                os.unlink(probe_src_name, dir_fd=dfd_norm)
            except OSError:
                pass
            try:
                os.unlink(probe_dst_name, dir_fd=dfd_norm)
            except OSError:
                pass

    path = target if target is not None else dir_path
    if path is not None and _RENAME_IMPL is not None:
        try:
            parent = os.path.dirname(os.fspath(path)) or "."
            token = os.urandom(8).hex()
            probe_src = os.path.join(parent, f".__probe_noreplace_src_{token}")
            probe_dst = os.path.join(parent, f".__probe_noreplace_dst_{token}")

            try:
                fd = os.open(probe_src, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(fd)
            except Exception:
                return None

            try:
                res = _RENAME_IMPL(os.fsencode(probe_src), os.fsencode(probe_dst))
                if res == 0:
                    return True
                perr = ctypes.get_errno()
                if perr in (
                    errno.EINVAL,
                    errno.ENOSYS,
                    errno.EOPNOTSUPP,
                    getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
                ):
                    return False
                return None
            finally:
                try:
                    os.unlink(probe_src)
                except OSError:
                    pass
                try:
                    os.unlink(probe_dst)
                except OSError:
                    pass
        except Exception:
            return None

    return None


def rename_noreplace(source: Path | str, target: Path | str) -> None:
    """
    Renames `source` to `target` with strict NO-REPLACE semantics using native kernel primitives.

    Execution paths:
    1. Native Path (Kernel Atomic):
       Uses kernel-level atomic `renameat2(..., RENAME_NOREPLACE)` on Linux or
       `renameatx_np(..., RENAME_EXCL)` on macOS Darwin. Guarantees single-syscall
       atomic rename with strict no-replace exclusion.
    2. Unsupported / Non-native:
       If the underlying filesystem rejects `RENAME_NOREPLACE` (e.g. `zfuse.zfsv3` returning
       EINVAL/ENOSYS/EOPNOTSUPP), raises OSError(errno.EOPNOTSUPP).
       Compatibility mutations on such filesystems are handled solely by the transactional
       quarantine engine (app.quarantine.engine and app.quarantine.restore).
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
        if err in (errno.ENOSYS, errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP)):
            raise OSError(errno.EOPNOTSUPP, "Atomic no-replace rename not supported by filesystem", str(source))
        if err == errno.EINVAL:
            if _probe_rename_noreplace_supported(target) is False:
                raise OSError(errno.EOPNOTSUPP, "Atomic no-replace rename not supported by filesystem", str(source))
        raise OSError(err, os.strerror(err), str(source))


def rename_noreplace_at(
    source_dir_fd: int,
    source_name: str,
    target_dir_fd: int,
    target_name: str,
) -> None:
    """
    Renames `source_name` relative to `source_dir_fd` to `target_name` relative to
    `target_dir_fd` with strict NO-REPLACE semantics using native kernel primitives.

    Execution paths:
    1. Native Path (Kernel Atomic):
       Uses kernel-level atomic `renameat2(..., RENAME_NOREPLACE)` on Linux or
       `renameatx_np(..., RENAME_EXCL)` on macOS Darwin. Guarantees single-syscall
       atomic rename with strict no-replace exclusion.
    2. Unsupported / Non-native:
       If the underlying filesystem rejects `RENAME_NOREPLACE` (e.g. `zfuse.zfsv3` returning
       EINVAL/ENOSYS/EOPNOTSUPP), raises OSError(errno.EOPNOTSUPP).
       Compatibility mutations on such filesystems are handled solely by the transactional
       quarantine engine (app.quarantine.engine and app.quarantine.restore).
    """
    if _RENAME_AT_IMPL is None:
        raise NotImplementedError("Atomic no-replace renameat2 is not available on this platform; failing closed.")

    src_bytes = os.fsencode(str(source_name))
    dst_bytes = os.fsencode(str(target_name))

    res = _RENAME_AT_IMPL(source_dir_fd, src_bytes, target_dir_fd, dst_bytes)
    if res != 0:
        err = ctypes.get_errno()
        if err in (errno.EEXIST, errno.ENOTEMPTY):
            raise FileExistsError(errno.EEXIST, f"Target path already exists: {target_name}")
        if err == errno.EXDEV:
            raise OSError(errno.EXDEV, f"Cross-device rename not permitted: {source_name} -> {target_name}")
        if err == errno.ENOENT:
            raise FileNotFoundError(errno.ENOENT, f"No such file or directory: {source_name}")
        if err in (errno.ENOSYS, errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP)):
            raise OSError(errno.EOPNOTSUPP, "Atomic no-replace renameat2 not supported by filesystem", str(source_name))
        if err == errno.EINVAL:
            if _probe_rename_noreplace_supported(dir_fd=target_dir_fd) is False:
                raise OSError(errno.EOPNOTSUPP, "Atomic no-replace renameat2 not supported by filesystem", str(source_name))
        raise OSError(err, os.strerror(err), str(source_name))
