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
) -> bool:
    """
    Probes whether the filesystem at target directory or dir_fd supports atomic RENAME_NOREPLACE.
    Returns True if supported, False if unsupported (e.g. zfuse returning EINVAL/ENOSYS/EOPNOTSUPP).
    """
    if dir_fd is not None and _RENAME_AT_IMPL is not None:
        probe_name = os.fsencode(f".__probe_noreplace_{os.urandom(8).hex()}")
        res = _RENAME_AT_IMPL(dir_fd, probe_name, dir_fd, probe_name)
        if res != 0:
            perr = ctypes.get_errno()
            if perr == errno.ENOENT:
                return True
            if perr in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP)):
                return False
        return False

    path = target if target is not None else dir_path
    if path is not None and _RENAME_IMPL is not None:
        try:
            parent = os.path.dirname(os.fspath(path)) or "."
            probe_path = os.fsencode(os.path.join(parent, f".__probe_noreplace_{os.urandom(8).hex()}"))
            res = _RENAME_IMPL(probe_path, probe_path)
            if res != 0:
                perr = ctypes.get_errno()
                if perr == errno.ENOENT:
                    return True
                if perr in (errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP)):
                    return False
        except Exception:
            pass
        return False

    return False


def _execute_safe_noreplace_fallback(source: Path | str, target: Path | str) -> None:
    src_path = Path(source)
    dst_path = Path(target)

    try:
        st = os.lstat(src_path)
    except FileNotFoundError:
        raise FileNotFoundError(errno.ENOENT, f"No such file or directory: {source}")
    except OSError:
        raise

    if stat.S_ISDIR(st.st_mode):
        raise OSError(
            errno.EOPNOTSUPP,
            f"Directory rename without replace not supported on this filesystem: {source}",
        )

    if stat.S_ISLNK(st.st_mode):
        try:
            os.link(src_path, dst_path, follow_symlinks=False)
        except (PermissionError, OSError) as link_err:
            if link_err.errno in (
                errno.EPERM,
                errno.EACCES,
                errno.EOPNOTSUPP,
                getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
            ):
                target_val = os.readlink(src_path)
                os.symlink(target_val, dst_path)
            else:
                raise link_err

        try:
            os.unlink(src_path)
        except Exception as unlink_err:
            try:
                os.unlink(dst_path)
            except Exception:
                pass
            raise unlink_err
        return

    os.link(src_path, dst_path, follow_symlinks=False)
    try:
        os.unlink(src_path)
    except Exception as unlink_err:
        try:
            os.unlink(dst_path)
        except Exception:
            pass
        raise unlink_err


def _execute_safe_noreplace_at_fallback(
    source_dir_fd: int,
    source_name: str,
    target_dir_fd: int,
    target_name: str,
) -> None:
    sfd = _normalize_dir_fd(source_dir_fd)
    dfd = _normalize_dir_fd(target_dir_fd)

    try:
        st = os.lstat(source_name, dir_fd=sfd)
    except FileNotFoundError:
        raise FileNotFoundError(errno.ENOENT, f"No such file or directory: {source_name}")
    except OSError:
        raise

    if stat.S_ISDIR(st.st_mode):
        raise OSError(
            errno.EOPNOTSUPP,
            f"Directory rename without replace not supported on this filesystem: {source_name}",
        )

    if stat.S_ISLNK(st.st_mode):
        try:
            os.link(source_name, target_name, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)
        except (PermissionError, OSError) as link_err:
            if link_err.errno in (
                errno.EPERM,
                errno.EACCES,
                errno.EOPNOTSUPP,
                getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
            ):
                target_val = os.readlink(source_name, dir_fd=sfd)
                os.symlink(target_val, target_name, dir_fd=dfd)
            else:
                raise link_err

        try:
            os.unlink(source_name, dir_fd=sfd)
        except Exception as unlink_err:
            try:
                os.unlink(target_name, dir_fd=dfd)
            except Exception:
                pass
            raise unlink_err
        return

    os.link(source_name, target_name, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)
    try:
        os.unlink(source_name, dir_fd=sfd)
    except Exception as unlink_err:
        try:
            os.unlink(target_name, dir_fd=dfd)
        except Exception:
            pass
        raise unlink_err


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
        if err in (errno.ENOSYS, errno.EOPNOTSUPP, getattr(errno, "ENOTSUP", errno.EOPNOTSUPP)):
            _execute_safe_noreplace_fallback(source, target)
            return
        if err == errno.EINVAL:
            if not _probe_rename_noreplace_supported(target):
                _execute_safe_noreplace_fallback(source, target)
                return
        raise OSError(err, os.strerror(err), str(source))


def rename_noreplace_at(
    source_dir_fd: int,
    source_name: str,
    target_dir_fd: int,
    target_name: str,
) -> None:
    """
    Atomically renames `source_name` relative to `source_dir_fd` to `target_name`
    relative to `target_dir_fd` with strict NO-REPLACE semantics using renameat2.
    If `target_name` already exists, raises FileExistsError without overwriting target.
    If cross-device link (EXDEV), raises OSError with errno.EXDEV.
    If platform lacks atomic no-replace capability, fails closed with NotImplementedError.
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
            _execute_safe_noreplace_at_fallback(source_dir_fd, source_name, target_dir_fd, target_name)
            return
        if err == errno.EINVAL:
            if not _probe_rename_noreplace_supported(dir_fd=target_dir_fd):
                _execute_safe_noreplace_at_fallback(source_dir_fd, source_name, target_dir_fd, target_name)
                return
        raise OSError(err, os.strerror(err), str(source_name))
