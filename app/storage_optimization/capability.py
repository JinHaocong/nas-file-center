from __future__ import annotations

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

    @property
    def supported(self) -> bool:
        return self.capability is StorageOptimizationCapability.SUPPORTED

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "capability": self.capability.value,
            "operation": self.operation,
            "reason": self.reason,
            "supported": self.supported,
            "parent_device": self.parent_device,
            "parent_inode": self.parent_inode,
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


def _probe_file(parent_fd: int, name: str, payload: bytes) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    try:
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


def probe_hardlink_capability(
    directory: Path | str,
    allowed_roots: Iterable[Path | str],
) -> CapabilityProbeResult:
    token = os.urandom(10).hex()
    source_name = f".__nfc_hardlink_probe_{token}.src"
    link_name = f".__nfc_hardlink_probe_{token}.dst"
    payload = b"nas-file-center-hardlink-probe"

    try:
        with _safe_parent(directory, allowed_roots) as (parent_fd, _):
            parent_st = os.fstat(parent_fd)
            source_fd = -1
            try:
                source_fd = _probe_file(parent_fd, source_name, payload)
                try:
                    os.link(
                        source_name,
                        link_name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
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
                    state = (
                        StorageOptimizationCapability.UNSUPPORTED
                        if exc.errno in unsupported
                        else StorageOptimizationCapability.UNKNOWN
                    )
                    reason = f"hardlink_probe_failed:{exc.errno}:{exc.strerror or exc}"
                    cleanup_ok = _cleanup_probe_name(parent_fd, link_name)
                    cleanup_ok = _cleanup_probe_name(parent_fd, source_name) and cleanup_ok
                    if not cleanup_ok:
                        state = StorageOptimizationCapability.UNKNOWN
                        reason = f"{reason};probe_cleanup_failed"
                    return CapabilityProbeResult(
                        state,
                        "hardlink",
                        reason,
                        int(parent_st.st_dev),
                        int(parent_st.st_ino),
                    )

                src_st = os.stat(source_name, dir_fd=parent_fd, follow_symlinks=False)
                dst_st = os.stat(link_name, dir_fd=parent_fd, follow_symlinks=False)
                if (
                    not stat.S_ISREG(src_st.st_mode)
                    or not stat.S_ISREG(dst_st.st_mode)
                    or (int(src_st.st_dev), int(src_st.st_ino))
                    != (int(dst_st.st_dev), int(dst_st.st_ino))
                ):
                    result = CapabilityProbeResult(
                        StorageOptimizationCapability.UNKNOWN,
                        "hardlink",
                        "hardlink_probe_identity_mismatch",
                        int(parent_st.st_dev),
                        int(parent_st.st_ino),
                    )
                else:
                    link_fd = os.open(link_name, os.O_RDONLY, dir_fd=parent_fd)
                    try:
                        if _read_all(source_fd) != payload or _read_all(link_fd) != payload:
                            result = CapabilityProbeResult(
                                StorageOptimizationCapability.UNKNOWN,
                                "hardlink",
                                "hardlink_probe_content_mismatch",
                                int(parent_st.st_dev),
                                int(parent_st.st_ino),
                            )
                        else:
                            result = CapabilityProbeResult(
                                StorageOptimizationCapability.SUPPORTED,
                                "hardlink",
                                "hardlink_probe_pass",
                                int(parent_st.st_dev),
                                int(parent_st.st_ino),
                            )
                    finally:
                        os.close(link_fd)

                cleanup_ok = _cleanup_probe_name(parent_fd, link_name)
                cleanup_ok = _cleanup_probe_name(parent_fd, source_name) and cleanup_ok
                if not cleanup_ok:
                    return CapabilityProbeResult(
                        StorageOptimizationCapability.UNKNOWN,
                        "hardlink",
                        "hardlink_probe_cleanup_failed",
                        int(parent_st.st_dev),
                        int(parent_st.st_ino),
                    )
                return result
            finally:
                if source_fd >= 0:
                    os.close(source_fd)
    except (OSError, ValueError) as exc:
        return CapabilityProbeResult(
            StorageOptimizationCapability.UNKNOWN,
            "hardlink",
            f"hardlink_parent_probe_failed:{exc}",
        )


def probe_reflink_capability(
    directory: Path | str,
    allowed_roots: Iterable[Path | str],
) -> CapabilityProbeResult:
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

    try:
        with _safe_parent(directory, allowed_roots) as (parent_fd, _):
            parent_st = os.fstat(parent_fd)
            source_fd = -1
            clone_fd = -1
            try:
                source_fd = _probe_file(parent_fd, source_name, payload)
                clone_fd = _probe_file(parent_fd, clone_name, b"")
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
                    state = (
                        StorageOptimizationCapability.UNSUPPORTED
                        if exc.errno in unsupported
                        else StorageOptimizationCapability.UNKNOWN
                    )
                    reason = f"reflink_probe_failed:{exc.errno}:{exc.strerror or exc}"
                    cleanup_ok = _cleanup_probe_name(parent_fd, clone_name)
                    cleanup_ok = _cleanup_probe_name(parent_fd, source_name) and cleanup_ok
                    if not cleanup_ok:
                        state = StorageOptimizationCapability.UNKNOWN
                        reason = f"{reason};probe_cleanup_failed"
                    return CapabilityProbeResult(
                        state,
                        "reflink",
                        reason,
                        int(parent_st.st_dev),
                        int(parent_st.st_ino),
                    )

                src_st = os.stat(source_name, dir_fd=parent_fd, follow_symlinks=False)
                clone_st = os.stat(clone_name, dir_fd=parent_fd, follow_symlinks=False)
                if (
                    not stat.S_ISREG(src_st.st_mode)
                    or not stat.S_ISREG(clone_st.st_mode)
                    or (int(src_st.st_dev), int(src_st.st_ino))
                    == (int(clone_st.st_dev), int(clone_st.st_ino))
                    or _read_all(source_fd) != payload
                    or _read_all(clone_fd) != payload
                ):
                    result = CapabilityProbeResult(
                        StorageOptimizationCapability.UNKNOWN,
                        "reflink",
                        "reflink_probe_identity_or_content_mismatch",
                        int(parent_st.st_dev),
                        int(parent_st.st_ino),
                    )
                else:
                    os.lseek(clone_fd, 0, os.SEEK_SET)
                    os.write(clone_fd, b"X")
                    os.fsync(clone_fd)
                    source_after = _read_all(source_fd)
                    clone_after = _read_all(clone_fd)
                    if source_after != payload or clone_after == payload:
                        result = CapabilityProbeResult(
                            StorageOptimizationCapability.UNKNOWN,
                            "reflink",
                            "reflink_probe_cow_independence_failed",
                            int(parent_st.st_dev),
                            int(parent_st.st_ino),
                        )
                    else:
                        result = CapabilityProbeResult(
                            StorageOptimizationCapability.SUPPORTED,
                            "reflink",
                            "reflink_probe_pass",
                            int(parent_st.st_dev),
                            int(parent_st.st_ino),
                        )

                cleanup_ok = _cleanup_probe_name(parent_fd, clone_name)
                cleanup_ok = _cleanup_probe_name(parent_fd, source_name) and cleanup_ok
                if not cleanup_ok:
                    return CapabilityProbeResult(
                        StorageOptimizationCapability.UNKNOWN,
                        "reflink",
                        "reflink_probe_cleanup_failed",
                        int(parent_st.st_dev),
                        int(parent_st.st_ino),
                    )
                return result
            finally:
                if clone_fd >= 0:
                    os.close(clone_fd)
                if source_fd >= 0:
                    os.close(source_fd)
    except (OSError, ValueError) as exc:
        return CapabilityProbeResult(
            StorageOptimizationCapability.UNKNOWN,
            "reflink",
            f"reflink_parent_probe_failed:{exc}",
        )


def probe_storage_optimization_capabilities(
    directory: Path | str,
    allowed_roots: Iterable[Path | str],
) -> dict[str, dict[str, str | int | bool | None]]:
    return {
        "hardlink": probe_hardlink_capability(directory, allowed_roots).to_dict(),
        "reflink": probe_reflink_capability(directory, allowed_roots).to_dict(),
    }
