from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import Callable


_HASH_CHUNK_BYTES = 8 * 1024 * 1024
_HASH_CHECKPOINT_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class IntegrityCheckResult:
    status: str
    reason_code: str
    detail: str | None = None
    observed_sha256: str | None = None
    baseline_sha256: str | None = None
    baseline_device: int | None = None
    baseline_inode: int | None = None
    baseline_size: int | None = None
    baseline_mtime_ns: int | None = None


def _mtime_ns(st: os.stat_result) -> int:
    return int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))


def _identity_tuple(st: os.stat_result) -> tuple[int, int, int, int]:
    return (int(st.st_dev), int(st.st_ino), int(st.st_size), _mtime_ns(st))


def _is_regular(st: os.stat_result) -> bool:
    return stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode)


def _same_live_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return _is_regular(left) and _is_regular(right) and _identity_tuple(left) == _identity_tuple(right)


def _hash_bound_regular(
    path: Path,
    expected: os.stat_result,
    *,
    checkpoint: Callable[[], None] | None = None,
) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    digest = hashlib.sha256()
    checkpoint_budget = _HASH_CHECKPOINT_BYTES
    try:
        before = os.fstat(fd)
        if not _same_live_identity(expected, before):
            raise RuntimeError("source identity changed before integrity hash")

        processed = 0
        while True:
            chunk = os.read(fd, _HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            processed += len(chunk)
            if checkpoint is not None and processed >= checkpoint_budget:
                checkpoint()
                checkpoint_budget += _HASH_CHECKPOINT_BYTES

        after = os.fstat(fd)
        if not _same_live_identity(expected, after):
            raise RuntimeError("source identity changed during integrity hash")
    finally:
        os.close(fd)

    after_path = os.lstat(path)
    if not _same_live_identity(expected, after_path):
        raise RuntimeError("source pathname changed during integrity hash")
    return digest.hexdigest()


def verify_or_establish_integrity_baseline(
    path: Path | str,
    *,
    indexed_device: int,
    indexed_inode: int,
    indexed_size: int,
    indexed_mtime_ns: int,
    baseline_sha256: str | None,
    baseline_device: int | None,
    baseline_inode: int | None,
    baseline_size: int | None,
    baseline_mtime_ns: int | None,
    checkpoint: Callable[[], None] | None = None,
) -> IntegrityCheckResult:
    """Establish or verify a pathname-bound SHA256 baseline without mutation.

    A baseline may only be minted while the live regular-file identity still
    matches the indexed snapshot. Existing baselines are immutable: later
    identity drift is reported as changed, while same-identity payload drift is
    detected by recomputing SHA256.
    """

    source = Path(path)
    try:
        live = os.lstat(source)
    except FileNotFoundError:
        return IntegrityCheckResult("unknown", "SOURCE_UNAVAILABLE", "source path does not exist")
    except OSError as exc:
        return IntegrityCheckResult("unknown", "SOURCE_UNAVAILABLE", str(exc))

    if not _is_regular(live):
        return IntegrityCheckResult("unknown", "SOURCE_NOT_REGULAR", "source is not a regular file")

    live_identity = _identity_tuple(live)

    if baseline_sha256 is None:
        indexed_identity = (
            int(indexed_device),
            int(indexed_inode),
            int(indexed_size),
            int(indexed_mtime_ns),
        )
        if live_identity != indexed_identity:
            return IntegrityCheckResult(
                "unknown",
                "INDEX_IDENTITY_CHANGED",
                "live file identity no longer matches the indexed snapshot",
            )
        try:
            digest = _hash_bound_regular(source, live, checkpoint=checkpoint)
        except FileNotFoundError:
            return IntegrityCheckResult("unknown", "SOURCE_UNAVAILABLE", "source disappeared during hash")
        except OSError as exc:
            return IntegrityCheckResult("unknown", "HASH_READ_FAILED", str(exc))
        except RuntimeError as exc:
            return IntegrityCheckResult("unknown", "SOURCE_CHANGED_DURING_HASH", str(exc))
        return IntegrityCheckResult(
            "baseline",
            "BASELINE_ESTABLISHED",
            observed_sha256=digest,
            baseline_sha256=digest,
            baseline_device=live_identity[0],
            baseline_inode=live_identity[1],
            baseline_size=live_identity[2],
            baseline_mtime_ns=live_identity[3],
        )

    if (
        baseline_device is None
        or baseline_inode is None
        or baseline_size is None
        or baseline_mtime_ns is None
    ):
        return IntegrityCheckResult(
            "unknown",
            "BASELINE_IDENTITY_MISSING",
            "stored SHA256 baseline is missing its physical identity",
        )

    expected_identity = (
        int(baseline_device),
        int(baseline_inode),
        int(baseline_size),
        int(baseline_mtime_ns),
    )
    if live_identity != expected_identity:
        return IntegrityCheckResult(
            "changed",
            "IDENTITY_CHANGED",
            "live file identity differs from the stored SHA256 baseline",
        )

    try:
        digest = _hash_bound_regular(source, live, checkpoint=checkpoint)
    except FileNotFoundError:
        return IntegrityCheckResult("unknown", "SOURCE_UNAVAILABLE", "source disappeared during hash")
    except OSError as exc:
        return IntegrityCheckResult("unknown", "HASH_READ_FAILED", str(exc))
    except RuntimeError as exc:
        return IntegrityCheckResult("unknown", "SOURCE_CHANGED_DURING_HASH", str(exc))

    if digest != baseline_sha256:
        return IntegrityCheckResult(
            "changed",
            "SHA256_MISMATCH",
            "current SHA256 differs from the stored baseline",
            observed_sha256=digest,
        )

    return IntegrityCheckResult(
        "verified",
        "SHA256_MATCH",
        observed_sha256=digest,
    )
