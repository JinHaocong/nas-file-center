from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from enum import Enum
import errno
import fcntl
import os
from pathlib import Path
import stat
from typing import Callable, Iterable

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.batch.media_organizer_custody import (
    NamespaceCustodyUnavailable, ScopedNamespaceCustody, assert_exclusive_custody,
)


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


def verified_probe_namespace_custody(
    identities: dict[Path, tuple[int, int]],
) -> ScopedNamespaceCustody:
    """No live issuer exists for scratch names in externally writable parents.

    A future reviewed issuer must hold exclusion for these exact directory
    inodes until release. A Worker lease, random filename or pre-unlink stat
    cannot establish ownership at the final name-based syscall.
    """
    raise NamespaceCustodyUnavailable(
        "storage probe external namespace custody is not proven"
    )


def _hold_probe_custody(stack, parents, mutation_fence):
    _fence(mutation_fence)
    identities = {}
    for directory, observed in parents:
        path = Path(directory).expanduser()
        identity = (int(observed.st_dev), int(observed.st_ino))
        if path in identities and identities[path] != identity:
            raise NamespaceCustodyUnavailable("storage probe parent identity changed")
        identities[path] = identity
    proof = verified_probe_namespace_custody(identities)
    release = getattr(proof, "close", None) or getattr(proof, "release", None)
    if callable(release):
        stack.callback(release)
    assert_exclusive_custody(proof, identities)

    def fence():
        if mutation_fence is not None:
            mutation_fence()
        assert_exclusive_custody(proof, identities)

    return fence


class _MutationFenceFailure(Exception):
    """Carry authority failures past filesystem capability error handling."""

    def __init__(self, error: Exception):
        super().__init__("storage probe mutation authority lost")
        self.error = error


def _fence(mutation_fence: Callable[[], None] | None) -> None:
    if mutation_fence is not None:
        try:
            mutation_fence()
        except Exception as exc:
            # PermissionError/ValueError from an authority check must not be
            # mistaken for an unsupported filesystem or authorize cleanup.
            raise _MutationFenceFailure(exc) from exc


def _cleanup_probe_name(
    parent_fd: int, name: str, probe_fd: int, *,
    mutation_fence: Callable[[], None] | None = None,
) -> bool:
    _fence(mutation_fence)
    try:
        observed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        owned = os.fstat(probe_fd)
        if not stat.S_ISREG(observed.st_mode) or (
            observed.st_dev, observed.st_ino
        ) != (owned.st_dev, owned.st_ino):
            return False
        # Identity checks are defense in depth beneath held namespace custody;
        # they cannot themselves make unlink conditional on an inode.
        _fence(mutation_fence)
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
    *,
    source_probe_fd: int,
    destination_probe_fd: int | None,
    mutation_fence: Callable[[], None] | None = None,
) -> bool:
    # EEXIST never creates an owned destination. Do not even attempt to clean it.
    destination_ok = destination_probe_fd is None or _cleanup_probe_name(
        destination_parent_fd, destination_name, destination_probe_fd,
        mutation_fence=mutation_fence,
    )
    source_ok = _cleanup_probe_name(
        source_parent_fd, source_name, source_probe_fd, mutation_fence=mutation_fence,
    )
    return destination_ok and source_ok


def _probe_file(
    parent_fd: int, name: str, payload: bytes, *,
    mutation_fence: Callable[[], None] | None = None,
) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    _fence(mutation_fence)
    fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
    try:
        if payload:
            _fence(mutation_fence)
            os.write(fd, payload)
        _fence(mutation_fence)
        os.fsync(fd)
    except Exception:
        os.close(fd)
        raise
    return fd


def _read_all(fd: int, expected_size: int) -> bytes:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    remaining = expected_size + 1
    while remaining:
        chunk = os.read(fd, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
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


def _matches_parent_identity(
    observed: os.stat_result,
    expected: tuple[int, int] | None,
) -> bool:
    return expected is None or (
        int(observed.st_dev), int(observed.st_ino)
    ) == (int(expected[0]), int(expected[1]))


def probe_hardlink_between(
    source_directory: Path | str,
    destination_directory: Path | str,
    allowed_roots: Iterable[Path | str],
    *,
    expected_source_parent_identity: tuple[int, int] | None = None,
    expected_destination_parent_identity: tuple[int, int] | None = None,
    mutation_fence: Callable[[], None] | None = None,
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
            if (
                not _matches_parent_identity(source_parent_st, expected_source_parent_identity)
                or not _matches_parent_identity(destination_parent_st, expected_destination_parent_identity)
            ):
                return _result(
                    StorageOptimizationCapability.UNKNOWN,
                    "hardlink",
                    "hardlink_probe_parent_identity_changed",
                    source_parent_st,
                    destination_parent_st,
                )

            mutation_fence = _hold_probe_custody(stack, (
                (source_directory, source_parent_st),
                (destination_directory, destination_parent_st),
            ), mutation_fence)
            source_fd = -1
            link_fd = -1
            try:
                source_fd = _probe_file(
                    source_parent_fd, source_name, payload, mutation_fence=mutation_fence,
                )
                try:
                    _fence(mutation_fence)
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
                        source_probe_fd=source_fd,
                        destination_probe_fd=None,
                        mutation_fence=mutation_fence,
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

                _fence(mutation_fence)
                link_fd = os.open(
                    link_name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                    dir_fd=destination_parent_fd,
                )
                src_st = os.fstat(source_fd)
                dst_st = os.fstat(link_fd)
                if (
                    not stat.S_ISREG(src_st.st_mode)
                    or not stat.S_ISREG(dst_st.st_mode)
                    or (int(src_st.st_dev), int(src_st.st_ino))
                    != (int(dst_st.st_dev), int(dst_st.st_ino))
                ):
                    # Never read or clean a replaced destination. Preserve the
                    # source evidence for explicit review of the custody loss.
                    return _result(
                        StorageOptimizationCapability.UNKNOWN,
                        "hardlink",
                        "hardlink_probe_identity_mismatch",
                        source_parent_st,
                        destination_parent_st,
                    )
                else:
                    if (
                        src_st.st_size != len(payload) or dst_st.st_size != len(payload)
                        or _read_all(source_fd, len(payload)) != payload
                        or _read_all(link_fd, len(payload)) != payload
                    ):
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

                if not _cleanup_pair(
                    source_parent_fd,
                    source_name,
                    destination_parent_fd,
                    link_name,
                    source_probe_fd=source_fd,
                    destination_probe_fd=link_fd,
                    mutation_fence=mutation_fence,
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
                if link_fd >= 0:
                    os.close(link_fd)
                if source_fd >= 0:
                    os.close(source_fd)
    except _MutationFenceFailure as exc:
        raise exc.error from None
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
    *,
    expected_parent_identity: tuple[int, int] | None = None,
    mutation_fence: Callable[[], None] | None = None,
) -> CapabilityProbeResult:
    return probe_hardlink_between(
        directory,
        directory,
        allowed_roots,
        expected_source_parent_identity=expected_parent_identity,
        expected_destination_parent_identity=expected_parent_identity,
        mutation_fence=mutation_fence,
    )


def probe_reflink_between(
    source_directory: Path | str,
    destination_directory: Path | str,
    allowed_roots: Iterable[Path | str],
    *,
    expected_source_parent_identity: tuple[int, int] | None = None,
    expected_destination_parent_identity: tuple[int, int] | None = None,
    mutation_fence: Callable[[], None] | None = None,
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
            if (
                not _matches_parent_identity(source_parent_st, expected_source_parent_identity)
                or not _matches_parent_identity(destination_parent_st, expected_destination_parent_identity)
            ):
                return _result(
                    StorageOptimizationCapability.UNKNOWN,
                    "reflink",
                    "reflink_probe_parent_identity_changed",
                    source_parent_st,
                    destination_parent_st,
                )

            mutation_fence = _hold_probe_custody(stack, (
                (source_directory, source_parent_st),
                (destination_directory, destination_parent_st),
            ), mutation_fence)
            source_fd = -1
            clone_fd = -1
            try:
                source_fd = _probe_file(
                    source_parent_fd, source_name, payload, mutation_fence=mutation_fence,
                )
                clone_fd = _probe_file(
                    destination_parent_fd, clone_name, b"", mutation_fence=mutation_fence,
                )
                try:
                    _fence(mutation_fence)
                    fcntl.ioctl(clone_fd, FICLONE, source_fd)
                    _fence(mutation_fence)
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
                        source_probe_fd=source_fd,
                        destination_probe_fd=clone_fd,
                        mutation_fence=mutation_fence,
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
                    or src_st.st_size != len(payload) or clone_st.st_size != len(payload)
                    or _read_all(source_fd, len(payload)) != payload
                    or _read_all(clone_fd, len(payload)) != payload
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
                    _fence(mutation_fence)
                    os.write(clone_fd, b"X")
                    _fence(mutation_fence)
                    os.fsync(clone_fd)
                    source_after = _read_all(source_fd, len(payload))
                    clone_after = _read_all(clone_fd, len(payload))
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
                    source_probe_fd=source_fd,
                    destination_probe_fd=clone_fd,
                    mutation_fence=mutation_fence,
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
    except _MutationFenceFailure as exc:
        raise exc.error from None
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
    *,
    expected_parent_identity: tuple[int, int] | None = None,
    mutation_fence: Callable[[], None] | None = None,
) -> CapabilityProbeResult:
    return probe_reflink_between(
        directory,
        directory,
        allowed_roots,
        expected_source_parent_identity=expected_parent_identity,
        expected_destination_parent_identity=expected_parent_identity,
        mutation_fence=mutation_fence,
    )


def probe_storage_optimization_capabilities(
    directory: Path | str,
    allowed_roots: Iterable[Path | str],
    *,
    expected_parent_identity: tuple[int, int] | None = None,
    mutation_fence: Callable[[], None] | None = None,
) -> dict[str, dict[str, str | int | bool | None]]:
    return {
        "hardlink": probe_hardlink_capability(
            directory, allowed_roots, expected_parent_identity=expected_parent_identity,
            mutation_fence=mutation_fence,
        ).to_dict(),
        "reflink": probe_reflink_capability(
            directory, allowed_roots, expected_parent_identity=expected_parent_identity,
            mutation_fence=mutation_fence,
        ).to_dict(),
    }


def probe_storage_optimization_between(
    source_directory: Path | str,
    destination_directory: Path | str,
    allowed_roots: Iterable[Path | str],
    *,
    expected_source_parent_identity: tuple[int, int] | None = None,
    expected_destination_parent_identity: tuple[int, int] | None = None,
    mutation_fence: Callable[[], None] | None = None,
) -> dict[str, dict[str, str | int | bool | None]]:
    return {
        "hardlink": probe_hardlink_between(
            source_directory,
            destination_directory,
            allowed_roots,
            expected_source_parent_identity=expected_source_parent_identity,
            expected_destination_parent_identity=expected_destination_parent_identity,
            mutation_fence=mutation_fence,
        ).to_dict(),
        "reflink": probe_reflink_between(
            source_directory,
            destination_directory,
            allowed_roots,
            expected_source_parent_identity=expected_source_parent_identity,
            expected_destination_parent_identity=expected_destination_parent_identity,
            mutation_fence=mutation_fence,
        ).to_dict(),
    }
