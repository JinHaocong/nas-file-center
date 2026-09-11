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


def _execute_safe_noreplace_fallback(source: Path | str, target: Path | str) -> None:
    src_path = Path(source)
    dst_path = Path(target)

    try:
        st_src = os.lstat(src_path)
    except FileNotFoundError:
        raise FileNotFoundError(errno.ENOENT, f"No such file or directory: {source}")
    except OSError:
        raise

    if stat.S_ISDIR(st_src.st_mode):
        raise OSError(
            errno.EOPNOTSUPP,
            f"Directory rename without replace not supported on this filesystem: {source}",
        )

    if not (stat.S_ISREG(st_src.st_mode) or stat.S_ISLNK(st_src.st_mode)):
        raise OSError(
            errno.EOPNOTSUPP,
            f"Special inode rename without replace not supported on this filesystem: {source}",
        )

    if stat.S_ISREG(st_src.st_mode):
        # 1. Exclusive destination publication via kernel link
        os.link(src_path, dst_path, follow_symlinks=False)

        # 2. Verify destination ownership before source retirement (Blocker B)
        try:
            st_dst = os.lstat(dst_path)
            if st_dst.st_ino != st_src.st_ino or st_dst.st_dev != st_src.st_dev:
                raise OSError(
                    errno.ESTALE,
                    f"Destination path replaced concurrently before source retirement: {target}",
                )
        except OSError as stat_err:
            if stat_err.errno == errno.ESTALE:
                raise
            raise OSError(
                errno.ESTALE,
                f"Destination path replaced or missing concurrently before source retirement: {target}",
            ) from stat_err

        # 3. Retire source. Do NOT delete destination on failure (Blocker A)
        os.unlink(src_path)
        return

    if stat.S_ISLNK(st_src.st_mode):
        created_via_link = False
        target_val = None
        try:
            os.link(src_path, dst_path, follow_symlinks=False)
            created_via_link = True
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

        # Verify destination ownership before source retirement
        try:
            if created_via_link:
                st_dst = os.lstat(dst_path)
                if st_dst.st_ino != st_src.st_ino or st_dst.st_dev != st_src.st_dev:
                    raise OSError(
                        errno.ESTALE,
                        f"Destination symlink replaced concurrently before source retirement: {target}",
                    )
            else:
                if not os.path.islink(dst_path) or os.readlink(dst_path) != target_val:
                    raise OSError(
                        errno.ESTALE,
                        f"Destination symlink modified or replaced concurrently: {target}",
                    )
        except OSError as stat_err:
            if stat_err.errno == errno.ESTALE:
                raise
            raise OSError(
                errno.ESTALE,
                f"Destination symlink replaced or missing concurrently before source retirement: {target}",
            ) from stat_err

        # Retire source symlink. Do NOT delete destination on failure (Blocker A)
        os.unlink(src_path)
        return


def _execute_safe_noreplace_at_fallback(
    source_dir_fd: int,
    source_name: str,
    target_dir_fd: int,
    target_name: str,
) -> None:
    sfd = _normalize_dir_fd(source_dir_fd)
    dfd = _normalize_dir_fd(target_dir_fd)

    try:
        st_src = os.lstat(source_name, dir_fd=sfd)
    except FileNotFoundError:
        raise FileNotFoundError(errno.ENOENT, f"No such file or directory: {source_name}")
    except OSError:
        raise

    if stat.S_ISDIR(st_src.st_mode):
        raise OSError(
            errno.EOPNOTSUPP,
            f"Directory rename without replace not supported on this filesystem: {source_name}",
        )

    if not (stat.S_ISREG(st_src.st_mode) or stat.S_ISLNK(st_src.st_mode)):
        raise OSError(
            errno.EOPNOTSUPP,
            f"Special inode rename without replace not supported on this filesystem: {source_name}",
        )

    if stat.S_ISREG(st_src.st_mode):
        os.link(source_name, target_name, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)

        try:
            st_dst = os.lstat(target_name, dir_fd=dfd)
            if st_dst.st_ino != st_src.st_ino or st_dst.st_dev != st_src.st_dev:
                raise OSError(
                    errno.ESTALE,
                    f"Destination path replaced concurrently before source retirement: {target_name}",
                )
        except OSError as stat_err:
            if stat_err.errno == errno.ESTALE:
                raise
            raise OSError(
                errno.ESTALE,
                f"Destination path replaced or missing concurrently before source retirement: {target_name}",
            ) from stat_err

        os.unlink(source_name, dir_fd=sfd)
        return

    if stat.S_ISLNK(st_src.st_mode):
        created_via_link = False
        target_val = None
        try:
            os.link(source_name, target_name, src_dir_fd=sfd, dst_dir_fd=dfd, follow_symlinks=False)
            created_via_link = True
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
            if created_via_link:
                st_dst = os.lstat(target_name, dir_fd=dfd)
                if st_dst.st_ino != st_src.st_ino or st_dst.st_dev != st_src.st_dev:
                    raise OSError(
                        errno.ESTALE,
                        f"Destination symlink replaced concurrently before source retirement: {target_name}",
                    )
            else:
                try:
                    rlink = os.readlink(target_name, dir_fd=dfd)
                    if rlink != target_val:
                        raise OSError(
                            errno.ESTALE,
                            f"Destination symlink modified concurrently: {target_name}",
                        )
                except OSError as rlink_err:
                    raise OSError(
                        errno.ESTALE,
                        f"Destination symlink replaced or missing concurrently: {target_name}",
                    ) from rlink_err
        except OSError as stat_err:
            if stat_err.errno == errno.ESTALE:
                raise
            raise OSError(
                errno.ESTALE,
                f"Destination symlink replaced or missing concurrently before source retirement: {target_name}",
            ) from stat_err

        os.unlink(source_name, dir_fd=sfd)
        return


def rename_noreplace(source: Path | str, target: Path | str) -> None:
    """
    Renames `source` to `target` with strict NO-REPLACE semantics.

    Execution paths:
    1. Native Path (Kernel Atomic):
       Uses kernel-level atomic `renameat2(..., RENAME_NOREPLACE)` on Linux or
       `renameatx_np(..., RENAME_EXCL)` on macOS Darwin. Guarantees single-syscall
       atomic rename with strict no-replace exclusion.

    2. Compatibility Path (Unix link+unlink):
       When the underlying filesystem rejects `RENAME_NOREPLACE` (e.g. `zfuse.zfsv3` on Linux
       FUSE returning EINVAL/ENOSYS/EOPNOTSUPP), executes strict no-replace semantics via:
       a. Capability probe (`_probe_rename_noreplace_supported`) using a disposable temporary file.
       b. Exclusive destination creation via `os.link()` (or `os.symlink()` for symlinks).
          If target already exists, the kernel atomically raises FileExistsError; target is never overwritten.
       c. Pre-retirement destination ownership verification: confirms target still references the
          exact same inode/device (or symlink target) before removing source. If target was replaced
          concurrently, raises OSError(errno.ESTALE) and preserves source data intact.
       d. Source retirement via `os.unlink()`. If unlinking source fails, source data is preserved and
          target is NOT deleted, preventing accidental deletion of unrelated/replaced destination data.
       e. Object types: Regular files and symlinks are supported. Directories and special inodes
          (FIFO, socket, character/block devices) strictly fail closed with OSError(errno.EOPNOTSUPP).
       f. Cross-device (EXDEV): Raises OSError(errno.EXDEV) and never falls back to cross-device copying.
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
    `target_dir_fd` with strict NO-REPLACE semantics.

    Execution paths:
    1. Native Path (Kernel Atomic):
       Uses kernel-level atomic `renameat2(..., RENAME_NOREPLACE)` on Linux or
       `renameatx_np(..., RENAME_EXCL)` on macOS Darwin. Guarantees single-syscall
       atomic rename with strict no-replace exclusion.

    2. Compatibility Path (Unix link+unlink):
       When the underlying filesystem rejects `RENAME_NOREPLACE` (e.g. `zfuse.zfsv3` on Linux
       FUSE returning EINVAL/ENOSYS/EOPNOTSUPP), executes strict no-replace semantics via:
       a. Capability probe (`_probe_rename_noreplace_supported`) using a disposable temporary file.
       b. Exclusive destination creation via `os.link()` (or `os.symlink()` for symlinks).
          If target already exists, the kernel atomically raises FileExistsError; target is never overwritten.
       c. Pre-retirement destination ownership verification: confirms target still references the
          exact same inode/device (or symlink target) before removing source. If target was replaced
          concurrently, raises OSError(errno.ESTALE) and preserves source data intact.
       d. Source retirement via `os.unlink()`. If unlinking source fails, source data is preserved and
          target is NOT deleted, preventing accidental deletion of unrelated/replaced destination data.
       e. Object types: Regular files and symlinks are supported. Directories and special inodes
          (FIFO, socket, character/block devices) strictly fail closed with OSError(errno.EOPNOTSUPP).
       f. Cross-device (EXDEV): Raises OSError(errno.EXDEV) and never falls back to cross-device copying.
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
