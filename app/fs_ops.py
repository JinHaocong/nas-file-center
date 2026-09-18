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

__all__ = [
    "NoreplaceProbeCleanupError",
    "probe_existing_noreplace_capability_at",
    "probe_plain_directory_rename_noclobber_at",
    "rename_directory_noreplace_compat",
    "rename_noreplace",
    "rename_noreplace_at",
]

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_RENAME_EXCL = 0x00000004


class NoreplaceProbeCleanupError(RuntimeError):
    """Raised when a disposable NOREPLACE capability probe cannot be fully cleaned up."""



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


def _cleanup_probe_name(path: str, *, dir_fd: int | None = None) -> bool:
    try:
        os.unlink(path, dir_fd=dir_fd)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _raise_probe_cleanup_error() -> None:
    raise NoreplaceProbeCleanupError("RENAME_NOREPLACE probe cleanup failed")


def _cleanup_probe_entry(path: str, *, dir_fd: int | None = None) -> bool:
    """Remove one disposable probe pathname without following symlinks."""
    try:
        st = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False

    try:
        if stat.S_ISDIR(st.st_mode):
            os.rmdir(path, dir_fd=dir_fd)
        else:
            os.unlink(path, dir_fd=dir_fd)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _probe_mkdir_at(dir_fd: int | None, name: str) -> os.stat_result:
    os.mkdir(name, 0o700, dir_fd=dir_fd)
    return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)


def _probe_file_at(dir_fd: int | None, name: str) -> os.stat_result:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dir_fd)
    try:
        os.write(fd, b"nfc-probe")
    finally:
        os.close(fd)
    return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)


def _probe_symlink_at(dir_fd: int | None, name: str, token: str) -> os.stat_result:
    os.symlink(f".__nfc_probe_nonexistent_{token}", name, dir_fd=dir_fd)
    return os.stat(name, dir_fd=dir_fd, follow_symlinks=False)


def _probe_identity(st: os.stat_result) -> tuple[int, int, int]:
    return (int(st.st_dev), int(st.st_ino), int(stat.S_IFMT(st.st_mode)))


def probe_plain_directory_rename_noclobber_at(
    source_parent_fd: int,
    target_parent_fd: int,
) -> bool | None:
    """Positive-probe whether plain directory rename is itself strict no-clobber.

    Some NAS/FUSE implementations reject native RENAME_NOREPLACE while their
    ordinary directory rename operation still refuses every existing target.
    This function grants compatibility authority only after disposable runtime
    probes prove that exact behavior on the actual source/target parents.

    Required proof:
      1. directory -> existing empty directory is refused and preserves both;
      2. directory -> existing regular file is refused and preserves both;
      3. directory -> existing symlink is refused and preserves both;
      4. directory -> absent target succeeds and preserves source identity.

    Any namespace mutation on a collision probe, unexpected errno, identity
    mismatch, or unresolved probe cleanup fails closed.  A False result means
    the filesystem definitely does not provide the required behavior; None
    means authority could not be established safely.
    """
    src_fd = _normalize_dir_fd(source_parent_fd)
    dst_fd = _normalize_dir_fd(target_parent_fd)
    token = os.urandom(10).hex()

    acceptable_collision_errnos = {
        errno.EEXIST,
        errno.ENOTEMPTY,
        errno.EISDIR,
        errno.ENOTDIR,
    }
    unsupported_errnos = {
        errno.EXDEV,
        errno.ENOSYS,
        errno.EOPNOTSUPP,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
    }

    def cleanup(names: list[tuple[str, int | None]]) -> None:
        if not all(_cleanup_probe_entry(name, dir_fd=dfd) for name, dfd in names):
            _raise_probe_cleanup_error()

    collision_specs = ("directory", "file", "symlink")
    for index, target_kind in enumerate(collision_specs):
        src_name = f".__probe_plain_move_src_{token}_{index}"
        dst_name = f".__probe_plain_move_dst_{token}_{index}"
        owned = [(src_name, src_fd), (dst_name, dst_fd)]
        try:
            src_before = _probe_mkdir_at(src_fd, src_name)
            if target_kind == "directory":
                dst_before = _probe_mkdir_at(dst_fd, dst_name)
            elif target_kind == "file":
                dst_before = _probe_file_at(dst_fd, dst_name)
            else:
                dst_before = _probe_symlink_at(dst_fd, dst_name, token)

            try:
                os.rename(
                    src_name,
                    dst_name,
                    src_dir_fd=src_fd,
                    dst_dir_fd=dst_fd,
                )
            except OSError as exc:
                if exc.errno in unsupported_errnos:
                    cleanup(owned)
                    return False
                if exc.errno not in acceptable_collision_errnos:
                    cleanup(owned)
                    return None

                try:
                    src_after = os.stat(src_name, dir_fd=src_fd, follow_symlinks=False)
                    dst_after = os.stat(dst_name, dir_fd=dst_fd, follow_symlinks=False)
                except OSError:
                    cleanup(owned)
                    return None

                if _probe_identity(src_after) != _probe_identity(src_before):
                    cleanup(owned)
                    return None
                if _probe_identity(dst_after) != _probe_identity(dst_before):
                    cleanup(owned)
                    return None
            else:
                # Plain POSIX rename may replace an empty directory. Any
                # successful collision mutation proves no-clobber is absent.
                cleanup(owned)
                return False
        except NoreplaceProbeCleanupError:
            raise
        except Exception:
            cleanup(owned)
            return None
        cleanup(owned)

    src_name = f".__probe_plain_move_src_{token}_success"
    dst_name = f".__probe_plain_move_dst_{token}_success"
    owned = [(src_name, src_fd), (dst_name, dst_fd)]
    try:
        src_before = _probe_mkdir_at(src_fd, src_name)
        try:
            os.rename(
                src_name,
                dst_name,
                src_dir_fd=src_fd,
                dst_dir_fd=dst_fd,
            )
        except OSError as exc:
            cleanup(owned)
            if exc.errno in unsupported_errnos:
                return False
            return None

        try:
            os.stat(src_name, dir_fd=src_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError:
            cleanup(owned)
            return None
        else:
            cleanup(owned)
            return None

        try:
            dst_after = os.stat(dst_name, dir_fd=dst_fd, follow_symlinks=False)
        except OSError:
            cleanup(owned)
            return None

        if _probe_identity(dst_after) != _probe_identity(src_before):
            cleanup(owned)
            return None
    except NoreplaceProbeCleanupError:
        raise
    except Exception:
        cleanup(owned)
        return None

    cleanup(owned)
    return True


def _open_probe_parent(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags)


def rename_directory_noreplace_compat(source: Path | str, target: Path | str) -> None:
    """Move one directory with no-clobber semantics on positively-probed COMPAT filesystems.

    This is deliberately *not* an exists()+rename fallback. The ordinary rename
    call is authorized only when a runtime disposable probe on the same source
    and target parents proves that this filesystem's plain directory rename
    refuses existing targets. Unknown/ambiguous capability fails closed.
    """
    src = Path(source)
    dst = Path(target)

    try:
        source_before = os.lstat(src)
    except OSError:
        raise
    if not stat.S_ISDIR(source_before.st_mode) or stat.S_ISLNK(source_before.st_mode):
        raise OSError(
            errno.EOPNOTSUPP,
            "COMPAT plain-rename no-replace supports directories only",
            os.fspath(src),
        )

    src_parent_fd = _open_probe_parent(src.parent)
    try:
        dst_parent_fd = _open_probe_parent(dst.parent)
    except Exception:
        os.close(src_parent_fd)
        raise

    try:
        capability = probe_plain_directory_rename_noclobber_at(
            src_parent_fd,
            dst_parent_fd,
        )
        if capability is not True:
            raise OSError(
                errno.EOPNOTSUPP,
                "Plain directory rename no-clobber semantics are not positively proven",
                os.fspath(src),
            )

        try:
            os.stat(dst.name, dir_fd=dst_parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(
                errno.EEXIST,
                f"Target path already exists: {dst}",
                os.fspath(dst),
            )

        current_source = os.stat(
            src.name,
            dir_fd=src_parent_fd,
            follow_symlinks=False,
        )
        if _probe_identity(current_source) != _probe_identity(source_before):
            raise OSError(
                errno.ESTALE if hasattr(errno, "ESTALE") else errno.EIO,
                "Source directory identity changed before COMPAT move",
                os.fspath(src),
            )

        try:
            os.rename(
                src.name,
                dst.name,
                src_dir_fd=src_parent_fd,
                dst_dir_fd=dst_parent_fd,
            )
        except OSError as exc:
            if exc.errno in {
                errno.EEXIST,
                errno.ENOTEMPTY,
                errno.EISDIR,
                errno.ENOTDIR,
            }:
                raise FileExistsError(
                    errno.EEXIST,
                    f"Target path already exists: {dst}",
                    os.fspath(dst),
                ) from exc
            raise

        try:
            moved = os.stat(dst.name, dir_fd=dst_parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise OSError(
                errno.EIO,
                f"COMPAT move postcondition failed: target unavailable: {exc}",
                os.fspath(dst),
            ) from exc

        if _probe_identity(moved) != _probe_identity(source_before):
            raise OSError(
                errno.EIO,
                "COMPAT move postcondition failed: target identity mismatch",
                os.fspath(dst),
            )
        try:
            os.stat(src.name, dir_fd=src_parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise OSError(
                errno.EIO,
                "COMPAT move postcondition failed: source binding still exists",
                os.fspath(src),
            )
    finally:
        os.close(dst_parent_fd)
        os.close(src_parent_fd)


def probe_existing_noreplace_capability_at(dir_fd: int, entry_name: str) -> bool | None:
    """Probe native NOREPLACE support without mutating the candidate binding.

    A same-entry call is used only as a non-destructive first signal. EEXIST,
    ENOTEMPTY, or an unchanged successful no-op are not sufficient proof of
    real cross-name MOVE support because COMPAT filesystems may special-case
    source == destination. Any such positive-looking result must therefore be
    confirmed by the isolated disposable cross-name probe before mutation
    authority is granted. Ambiguous results fail closed as None. A disposable
    probe cleanup failure raises NoreplaceProbeCleanupError because namespace
    residue is a safety failure, not ordinary capability ambiguity.
    """
    if _RENAME_AT_IMPL is None:
        return False

    try:
        before = os.stat(entry_name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return None

    ctypes.set_errno(0)
    result = _RENAME_AT_IMPL(
        dir_fd,
        os.fsencode(entry_name),
        dir_fd,
        os.fsencode(entry_name),
    )
    if result == 0:
        try:
            after = os.stat(entry_name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError:
            return None
        before_identity = (before.st_dev, before.st_ino, stat.S_IFMT(before.st_mode))
        after_identity = (after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode))
        if after_identity != before_identity:
            return None
        return _probe_rename_noreplace_supported(dir_fd=dir_fd)

    err = ctypes.get_errno()
    if err in (errno.EEXIST, errno.ENOTEMPTY):
        return _probe_rename_noreplace_supported(dir_fd=dir_fd)
    if err in (
        errno.ENOSYS,
        errno.EOPNOTSUPP,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
    ):
        return False
    return None


def _probe_rename_noreplace_supported(
    target: Path | str | None = None,
    *,
    dir_path: Path | str | None = None,
    dir_fd: int | None = None,
) -> bool | None:
    """
    Probes whether the filesystem at target directory or dir_fd supports atomic RENAME_NOREPLACE.
    Uses a valid, existing disposable temporary file to exercise the filesystem's handling
    of the RENAME_NOREPLACE flag. A positive result is granted only after both disposable
    probe names are confirmed cleaned up; unresolved cleanup raises a safety error.
    Returns:
      True:  Filesystem supports RENAME_NOREPLACE and probe cleanup completed.
      False: Filesystem rejects RENAME_NOREPLACE capability (e.g. returned EINVAL/ENOSYS/EOPNOTSUPP on existing source).
      None:  Capability could not otherwise be safely established (fails closed).
    Raises:
      NoreplaceProbeCleanupError: Disposable probe namespace cleanup could not be confirmed.
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
        except Exception:
            return None

        try:
            os.close(fd)
        except Exception:
            _cleanup_probe_name(probe_src_name, dir_fd=dfd_norm)
            _cleanup_probe_name(probe_dst_name, dir_fd=dfd_norm)
            _raise_probe_cleanup_error()

        capability: bool | None = None
        try:
            res = _RENAME_AT_IMPL(
                raw_fd,
                os.fsencode(probe_src_name),
                raw_fd,
                os.fsencode(probe_dst_name),
            )
            if res == 0:
                capability = True
            else:
                perr = ctypes.get_errno()
                if perr in (
                    errno.EINVAL,
                    errno.ENOSYS,
                    errno.EOPNOTSUPP,
                    getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
                ):
                    capability = False
        finally:
            src_clean = _cleanup_probe_name(probe_src_name, dir_fd=dfd_norm)
            dst_clean = _cleanup_probe_name(probe_dst_name, dir_fd=dfd_norm)

        if not (src_clean and dst_clean):
            _raise_probe_cleanup_error()
        return capability

    path = target if target is not None else dir_path
    if path is not None and _RENAME_IMPL is not None:
        try:
            parent = os.path.dirname(os.fspath(path)) or "."
            token = os.urandom(8).hex()
            probe_src = os.path.join(parent, f".__probe_noreplace_src_{token}")
            probe_dst = os.path.join(parent, f".__probe_noreplace_dst_{token}")

            try:
                fd = os.open(probe_src, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except Exception:
                return None

            try:
                os.close(fd)
            except Exception:
                _cleanup_probe_name(probe_src)
                _cleanup_probe_name(probe_dst)
                _raise_probe_cleanup_error()

            capability: bool | None = None
            try:
                res = _RENAME_IMPL(os.fsencode(probe_src), os.fsencode(probe_dst))
                if res == 0:
                    capability = True
                else:
                    perr = ctypes.get_errno()
                    if perr in (
                        errno.EINVAL,
                        errno.ENOSYS,
                        errno.EOPNOTSUPP,
                        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
                    ):
                        capability = False
            finally:
                src_clean = _cleanup_probe_name(probe_src)
                dst_clean = _cleanup_probe_name(probe_dst)

            if not (src_clean and dst_clean):
                _raise_probe_cleanup_error()
            return capability
        except NoreplaceProbeCleanupError:
            raise
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