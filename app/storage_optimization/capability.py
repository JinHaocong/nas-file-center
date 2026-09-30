from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from enum import Enum
import errno
import fcntl
import os
from pathlib import Path
import stat
from typing import Iterable

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd


# Linux fs.h: _IOW(0x94, 9, int)
FICLONE = 0x40049409


class StorageOptimizationCapability(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CapabilityProbeResult:
    capability: StorageOptimizationCapability
    operation: str
    reason: str
    parent_device: int | None = None
    parent_inode: int | None = None
    source_parent_device: int | None = None
    source_parent_inode: int | None = None

    @property
    def supported(self) -> bool:
        return self.capability is StorageOptimizationCapability.SUPPORTED

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "capability": self.capability.value,
            "operation": self.operation,
            "reason": self.reason,
            "supported": self.supported,
            # Backward-compatible aliases: parent_* describe the destination
            # parent where the optimized SOURCE pathname would live.
            "parent_device": self.parent_device,
            "parent_inode": self.parent_inode,
            "source_parent_device": self.source_parent_device,
            "source_parent_inode": self.source_parent_inode,
        }


def _safe_parent(directory: Path | str, allowed_roots: Iterable[Path | str]):
    directory = Path(directory).expanduser()
    return safe_open_parent_fd(directory / ".__nfc_storage_probe_anchor", allowed_roots)


def _cleanup_probe_name(parent_fd: int, name: str) -> bool:
    try:
        os.unlink(name, dir_fd=parent_fd)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _cleanup_pair(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> bool:
    destination_ok = _cleanup_probe_name(destination_parent_fd, destination_name)
    source_ok = _cleanup_probe_name(source_parent_fd, source_name)
    return destination_ok and source_ok


def _probe_file(parent_fd: int, name: str, payload: bytes) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    try:
        if payload:
            os.write(fd, payload)
        os.fsync(fd)
    except Exception:
        os.close(fd)
        raise
    return fd


def _read_all(fd: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 64 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _result(
    capability: StorageOptimizationCapability,
    operation: str,
    reason: str,
    source_parent_st: os.stat_result | None,
    destination_parent_st: os.stat_result | None,
) -> CapabilityProbeResult:
    return CapabilityProbeResult(
        capability=capability,
        operation=operation,
        reason=reason,
        parent_device=(
            int(destination_parent_st.st_dev)
            if destination_parent_st is not None
            else None
        ),
        parent_inode=(
            int(destination_parent_st.st_ino)
            if destination_parent_st is not None
            else None
        ),
        source_parent_device=(
            int(source_parent_st.st_dev)
            if source_parent_st is not None
            else None
        ),
        source_parent_inode=(
            int(source_parent_st.st_ino)
            if source_parent_st is not None
            else None
        ),
    )


def probe_hardlink_between(
    source_directory: Path | str,
    destination_directory: Path | str,
    allowed_roots: Iterable[Path | str],
) -> CapabilityProbeResult:
    """Positively prove hard-link support between two actual parent directories.

    The probe source lives in the KEEP-side parent and the link destination lives
    in the SOURCE-side parent. This intentionally does not trust st_dev equality:
    NAS/FUSE layouts can report equal device numbers while cross-area hard links
    still fail.
    """
    token = os.urandom(10).hex()
    source_name = f".__nfc_hardlink_probe_{token}.src"
    link_name = f".__nfc_hardlink_probe_{token}.dst"
    payload = b"nas-file-center-hardlink-probe"

    source_parent_st: os.stat_result | None = None
    destination_parent_st: os.stat_result | None = None
    try:
        with ExitStack() as stack:
            source_parent_fd, _ = stack.enter_context(
                _safe_parent(source_directory, allowed_roots)
            )
            destination_parent_fd, _ = stack.enter_context(
                _safe_parent(destination_directory, allowed_roots)
            )
            source_parent_st = os.fstat(source_parent_fd)
            destination_parent_st = os.fstat(destination_parent_fd)

            source_fd = -1
            try:
                source_fd = _probe_file(source_parent_fd, source_name, payload)
                try:
                    os.link(
                        source_name,
                        link_name,
                        src_dir_fd=source_parent_fd,
                        dst_dir_fd=destination_parent_fd,
                        follow_symlinks=False,
                    )
                except OSError as exc:
                    unsupported = {
                        errno.EXDEV,
                        errno.EOPNOTSUPP,
                        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
                        errno.EPERM,
                        errno.ENOSYS,
                    }
                    capability = (
                        StorageOptimizationCapability.UNSUPPORTED
                        if exc.errno in unsupported
                        else StorageOptimizationCapability.UNKNOWN
                    )
                    reason = f"hardlink_probe_failed:{exc.errno}:{exc.strerror or exc}"
                    if not _cleanup_pair(
                        source_parent_fd,
                        source_name,
                        destination_parent_fd,
                        link_name,
                    ):
                        capability = StorageOptimizationCapability.UNKNOWN
                        reason = f"{reason};probe_cleanup_failed"
                    return _result(
                        capability,
                        "hardlink",
                        reason,
                        source_parent_st,
                        destination_parent_st,
                    )

                src_st = os.stat(
                    source_name,
                    dir_fd=source_parent_fd,
                    follow_symlinks=False,
                )
                dst_st = os.stat(
                    link_name,
                    dir_fd=destination_parent_fd,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISREG(src_st.st_mode)
                    or not stat.S_ISREG(dst_st.st_mode)
                    or (int(src_st.st_dev), int(src_st.st_ino))
                    != (int(dst_st.st_dev), int(dst_st.st_ino))
                ):
                    result = _result(
                        StorageOptimizationCapability.UNKNOWN,
                        "hardlink",
                        "hardlink_probe_identity_mismatch",
                        source_parent_st,
                        destination_parent_st,
                    )
                else:
                    link_fd = os.open(
                        link_name,
                        os.O_RDONLY,
                        dir_fd=destination_parent_fd,
                    )
                    try:
                        if _read_all(source_fd) != payload or _read_all(link_fd) != payload:
                            result = _result(
                                StorageOptimizationCapability.UNKNOWN,
                                "hardlink",
                                "hardlink_probe_content_mismatch",
                                source_parent_st,
                                destination_parent_st,
                            )
                        else:
                            result = _result(
                                StorageOptimizationCapability.SUPPORTED,
                                "hardlink",
                                "hardlink_probe_pass",
                                source_parent_st,
                                destination_parent_st,
                            )
                    finally:
                        os.close(link_fd)

                if not _cleanup_pair(
                    source_parent_fd,
                    source_name,
                    destination_parent_fd,
                    link_name,
                ):
                    return _result(
                        StorageOptimizationCapability.UNKNOWN,
                        "hardlink",
                        "hardlink_probe_cleanup_failed",
                        source_parent_st,
                        destination_parent_st,
                    )
                return result
            finally:
                if source_fd >= 0:
                    os.close(source_fd)
    except (OSError, ValueError) as exc:
        return _result(
            StorageOptimizationCapability.UNKNOWN,
            "hardlink",
            f"hardlink_parent_probe_failed:{exc}",
            source_parent_st,
            destination_parent_st,
        )


def probe_hardlink_capability(
    directory: Path | str,
    allowed_roots: Iterable[Path | str],
) -> CapabilityProbeResult:
    return probe_hardlink_between(directory, directory, allowed_roots)


def probe_reflink_between(
    source_directory: Path | str,
    destination_directory: Path | str,
    allowed_roots: Iterable[Path | str],
) -> CapabilityProbeResult:
    """Positively prove FICLONE + copy-on-write independence between parents."""
    if not hasattr(fcntl, "ioctl"):
        return CapabilityProbeResult(
            StorageOptimizationCapability.UNSUPPORTED,
            "reflink",
            "ficlone_ioctl_unavailable",
        )

    token = os.urandom(10).hex()
    source_name = f".__nfc_reflink_probe_{token}.src"
    clone_name = f".__nfc_reflink_probe_{token}.dst"
    payload = b"nas-file-center-reflink-probe"

    source_parent_st: os.stat_result | None = None
    destination_parent_st: os.stat_result | None = None
    try:
        with ExitStack() as stack:
            source_parent_fd, _ = stack.enter_context(
                _safe_parent(source_directory, allowed_roots)
            )
            destination_parent_fd, _ = stack.enter_context(
                _safe_parent(destination_directory, allowed_roots)
            )
            source_parent_st = os.fstat(source_parent_fd)
            destination_parent_st = os.fstat(destination_parent_fd)

            source_fd = -1
            clone_fd = -1
            try:
                source_fd = _probe_file(source_parent_fd, source_name, payload)
                clone_fd = _probe_file(destination_parent_fd, clone_name, b"")
                try:
                    fcntl.ioctl(clone_fd, FICLONE, source_fd)
                    os.fsync(clone_fd)
                except OSError as exc:
                    unsupported = {
                        errno.EXDEV,
                        errno.EOPNOTSUPP,
                        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
                        errno.ENOTTY,
                        errno.EINVAL,
                        errno.ENOSYS,
                    }
                    capability = (
                        StorageOptimizationCapability.UNSUPPORTED
                        if exc.errno in unsupported
                        else StorageOptimizationCapability.UNKNOWN
                    )
                    reason = f"reflink_probe_failed:{exc.errno}:{exc.strerror or exc}"
                    if not _cleanup_pair(
                        source_parent_fd,
                        source_name,
                        destination_parent_fd,
                        clone_name,
                    ):
                        capability = StorageOptimizationCapability.UNKNOWN
                        reason = f"{reason};probe_cleanup_failed"
                    return _result(
                        capability,
                        "reflink",
                        reason,
                        source_parent_st,
                        destination_parent_st,
                    )

                src_st = os.stat(
                    source_name,
                    dir_fd=source_parent_fd,
                    follow_symlinks=False,
                )
                clone_st = os.stat(
                    clone_name,
                    dir_fd=destination_parent_fd,
                    follow_symlinks=False,
                )
                if (
                    not stat.S_ISREG(src_st.st_mode)
                    or not stat.S_ISREG(clone_st.st_mode)
                    or (int(src_st.st_dev), int(src_st.st_ino))
                    == (int(clone_st.st_dev), int(clone_st.st_ino))
                    or _read_all(source_fd) != payload
                    or _read_all(clone_fd) != payload
                ):
                    result = _result(
                        StorageOptimizationCapability.UNKNOWN,
                        "reflink",
                        "reflink_probe_identity_or_content_mismatch",
                        source_parent_st,
                        destination_parent_st,
                    )
                else:
                    os.lseek(clone_fd, 0, os.SEEK_SET)
                    os.write(clone_fd, b"X")
                    os.fsync(clone_fd)
                    source_after = _read_all(source_fd)
                    clone_after = _read_all(clone_fd)
                    if source_after != payload or clone_after == payload:
                        result = _result(
                            StorageOptimizationCapability.UNKNOWN,
                            "reflink",
                            "reflink_probe_cow_independence_failed",
                            source_parent_st,
                            destination_parent_st,
                        )
                    else:
                        result = _result(
                            StorageOptimizationCapability.SUPPORTED,
                            "reflink",
                            "reflink_probe_pass",
                            source_parent_st,
                            destination_parent_st,
                        )

                if not _cleanup_pair(
                    source_parent_fd,
                    source_name,
                    destination_parent_fd,
                    clone_name,
                ):
                    return _result(
                        StorageOptimizationCapability.UNKNOWN,
                        "reflink",
                        "reflink_probe_cleanup_failed",
                        source_parent_st,
                        destination_parent_st,
                    )
                return result
            finally:
                if clone_fd >= 0:
                    os.close(clone_fd)
                if source_fd >= 0:
                    os.close(source_fd)
    except (OSError, ValueError) as exc:
        return _result(
            StorageOptimizationCapability.UNKNOWN,
            "reflink",
            f"reflink_parent_probe_failed:{exc}",
            source_parent_st,
            destination_parent_st,
        )


def probe_reflink_capability(
    directory: Path | str,
    allowed_roots: Iterable[Path | str],
) -> CapabilityProbeResult:
    return probe_reflink_between(directory, directory, allowed_roots)


def probe_storage_optimization_capabilities(
    directory: Path | str,
    allowed_roots: Iterable[Path | str],
) -> dict[str, dict[str, str | int | bool | None]]:
    return {
        "hardlink": probe_hardlink_capability(directory, allowed_roots).to_dict(),
        "reflink": probe_reflink_capability(directory, allowed_roots).to_dict(),
    }


def probe_storage_optimization_between(
    source_directory: Path | str,
    destination_directory: Path | str,
    allowed_roots: Iterable[Path | str],
) -> dict[str, dict[str, str | int | bool | None]]:
    return {
        "hardlink": probe_hardlink_between(
            source_directory,
            destination_directory,
            allowed_roots,
        ).to_dict(),
        "reflink": probe_reflink_between(
            source_directory,
            destination_directory,
            allowed_roots,
        ).to_dict(),
    }
