from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Sequence

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.exceptions import StateConflictError
from app.models import QuarantineEntry


_CROSS_STORAGE_MODE = "cross_storage_transactional"
_ALLOWED_RESTORED_PAYLOAD_NAMES = {
    "anchor",
    "captured_source",
    "captured_quarantine_view",
}


@dataclass(frozen=True)
class RestoredArtifact:
    path: Path
    device: int
    inode: int
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class RestoredCleanupPlan:
    entry_id: int
    target_path: Path
    tx_entry_root: Path
    artifacts: tuple[RestoredArtifact, ...]

    @property
    def reclaim_bytes(self) -> int:
        # Hard-link artifacts can report the same logical size more than once.
        # This is advisory only; actual filesystem block reclamation depends on
        # link count and filesystem allocation.
        return sum(item.size for item in self.artifacts)


def _mtime_ns(st: os.stat_result) -> int:
    return int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))


def _absolute(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_restored_target(
    entry: QuarantineEntry,
    *,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
) -> tuple[Path, int, int, int, int]:
    q_root = _absolute(quarantine_root)
    roots = [_absolute(root) for root in allowed_roots]

    if (
        entry.restore_target_path
        and entry.restore_device is not None
        and entry.restore_inode is not None
        and entry.restore_mtime_ns is not None
    ):
        target = _absolute(entry.restore_target_path)
        expected_device = int(entry.restore_device)
        expected_inode = int(entry.restore_inode)
        expected_mtime_ns = int(entry.restore_mtime_ns)
    else:
        # Historical same-storage restored entries predate persisted restore
        # destination authority. The original path is the only safe fallback,
        # and the restored hard-link must still bind to the original identity.
        target = _absolute(entry.original_path)
        expected_device = int(entry.device)
        expected_inode = int(entry.inode)
        expected_mtime_ns = int(entry.mtime_ns)

    if not any(target == root or _is_within(target, root) for root in roots):
        raise StateConflictError(
            f"RESTORED_CLEANUP_TARGET_OUTSIDE_ALLOWED_ROOTS: entry #{entry.id} target {target}"
        )
    if target == q_root or _is_within(target, q_root):
        raise StateConflictError(
            f"RESTORED_CLEANUP_TARGET_IN_QUARANTINE: entry #{entry.id} target {target}"
        )

    try:
        with safe_open_parent_fd(target, roots) as (parent_fd, leaf):
            fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=parent_fd)
            try:
                st = os.fstat(fd)
            finally:
                os.close(fd)
    except Exception as exc:
        raise StateConflictError(
            f"RESTORED_CLEANUP_TARGET_INVALID: cannot verify restored target for entry #{entry.id}: {exc}"
        ) from exc

    if (
        not stat.S_ISREG(st.st_mode)
        or int(st.st_dev) != expected_device
        or int(st.st_ino) != expected_inode
        or int(st.st_size) != int(entry.size)
        or _mtime_ns(st) != expected_mtime_ns
    ):
        raise StateConflictError(
            f"RESTORED_CLEANUP_TARGET_CHANGED: restored target identity changed for entry #{entry.id}"
        )

    return target, expected_device, expected_inode, int(entry.size), expected_mtime_ns


def build_restored_cleanup_plan(
    entry: QuarantineEntry,
    *,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
) -> RestoredCleanupPlan:
    if entry.state != "restored":
        raise StateConflictError(
            f"RESTORED_CLEANUP_STATE_INVALID: entry #{entry.id} state={entry.state}"
        )

    q_root = _absolute(quarantine_root)
    tx_root = q_root / ".tx"
    tx_entry_root = tx_root / f"entry-{int(entry.id)}"
    target, expected_device, expected_inode, expected_size, expected_mtime_ns = (
        _resolve_restored_target(
            entry,
            allowed_roots=allowed_roots,
            quarantine_root=q_root,
        )
    )

    # A restored record must no longer have a public quarantine payload.
    public_path = _absolute(entry.quarantine_path)
    try:
        os.lstat(public_path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise StateConflictError(
            f"RESTORED_CLEANUP_PUBLIC_VIEW_UNKNOWN: entry #{entry.id}: {exc}"
        ) from exc
    else:
        raise StateConflictError(
            f"RESTORED_CLEANUP_PUBLIC_VIEW_PRESENT: entry #{entry.id} still has a public quarantine payload"
        )

    try:
        root_stat = os.lstat(tx_entry_root)
    except FileNotFoundError:
        return RestoredCleanupPlan(
            entry_id=int(entry.id),
            target_path=target,
            tx_entry_root=tx_entry_root,
            artifacts=(),
        )
    except OSError as exc:
        raise StateConflictError(
            f"RESTORED_CLEANUP_TX_UNKNOWN: cannot inspect transaction namespace for entry #{entry.id}: {exc}"
        ) from exc

    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise StateConflictError(
            f"RESTORED_CLEANUP_TX_INVALID: transaction namespace is not a directory for entry #{entry.id}"
        )

    artifacts: list[RestoredArtifact] = []
    for dirpath, dirnames, filenames in os.walk(tx_entry_root, followlinks=False):
        dir_path = Path(dirpath)
        for dirname in dirnames:
            candidate = dir_path / dirname
            child_stat = os.lstat(candidate)
            if stat.S_ISLNK(child_stat.st_mode) or not stat.S_ISDIR(child_stat.st_mode):
                raise StateConflictError(
                    f"RESTORED_CLEANUP_TX_INVALID: non-directory transaction child for entry #{entry.id}: {candidate}"
                )

        for filename in filenames:
            candidate = dir_path / filename
            if filename not in _ALLOWED_RESTORED_PAYLOAD_NAMES:
                raise StateConflictError(
                    f"RESTORED_CLEANUP_UNKNOWN_ARTIFACT: entry #{entry.id}: {candidate}"
                )
            child_stat = os.lstat(candidate)
            if stat.S_ISLNK(child_stat.st_mode) or not stat.S_ISREG(child_stat.st_mode):
                raise StateConflictError(
                    f"RESTORED_CLEANUP_ARTIFACT_INVALID: entry #{entry.id}: {candidate}"
                )

            if entry.transaction_mode == _CROSS_STORAGE_MODE:
                # A completed cross-storage restore has already retired its
                # public quarantine payload and should leave only empty attempt
                # directories. Never guess authority for an unexpected payload.
                raise StateConflictError(
                    f"RESTORED_CLEANUP_CROSS_STORAGE_ARTIFACT_PRESENT: entry #{entry.id}: {candidate}"
                )

            if (
                int(child_stat.st_dev) != expected_device
                or int(child_stat.st_ino) != expected_inode
                or int(child_stat.st_size) != expected_size
                or _mtime_ns(child_stat) != expected_mtime_ns
            ):
                raise StateConflictError(
                    f"RESTORED_CLEANUP_ARTIFACT_CHANGED: private restore artifact identity changed for entry #{entry.id}: {candidate}"
                )

            artifacts.append(
                RestoredArtifact(
                    path=candidate,
                    device=int(child_stat.st_dev),
                    inode=int(child_stat.st_ino),
                    size=int(child_stat.st_size),
                    mtime_ns=_mtime_ns(child_stat),
                )
            )

    return RestoredCleanupPlan(
        entry_id=int(entry.id),
        target_path=target,
        tx_entry_root=tx_entry_root,
        artifacts=tuple(artifacts),
    )


def execute_restored_cleanup_plan(
    plan: RestoredCleanupPlan,
    *,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str,
) -> dict[str, int]:
    q_root = _absolute(quarantine_root)
    valid_roots = [_absolute(root) for root in allowed_roots]
    if q_root not in valid_roots:
        valid_roots.append(q_root)

    removed_count = 0
    removed_logical_bytes = 0

    for artifact in plan.artifacts:
        if not _is_within(_absolute(artifact.path), plan.tx_entry_root):
            raise StateConflictError(
                f"RESTORED_CLEANUP_SCOPE_INVALID: artifact escaped entry namespace: {artifact.path}"
            )

        try:
            with safe_open_parent_fd(artifact.path, valid_roots) as (parent_fd, leaf):
                immediate = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
                if (
                    not stat.S_ISREG(immediate.st_mode)
                    or int(immediate.st_dev) != artifact.device
                    or int(immediate.st_ino) != artifact.inode
                    or int(immediate.st_size) != artifact.size
                    or _mtime_ns(immediate) != artifact.mtime_ns
                ):
                    raise StateConflictError(
                        f"RESTORED_CLEANUP_ARTIFACT_CHANGED: private artifact changed before unlink: {artifact.path}"
                    )
                os.unlink(leaf, dir_fd=parent_fd)
                os.fsync(parent_fd)
        except FileNotFoundError:
            # Idempotent retry after a prior successful unlink.
            continue

        removed_count += 1
        removed_logical_bytes += artifact.size

    # Remove only directories that are now empty. A concurrently-created or
    # foreign object makes rmdir fail and therefore keeps the DB record for
    # inspection/retry instead of recursively deleting unknown content.
    if plan.tx_entry_root.exists():
        for dirpath, _dirnames, _filenames in os.walk(
            plan.tx_entry_root,
            topdown=False,
            followlinks=False,
        ):
            path = Path(dirpath)
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                raise StateConflictError(
                    f"RESTORED_CLEANUP_TX_CHANGED: transaction namespace changed for entry #{plan.entry_id}: {path}"
                )
            try:
                os.rmdir(path)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise StateConflictError(
                    f"RESTORED_CLEANUP_TX_NOT_EMPTY: transaction namespace still contains unknown artifacts for entry #{plan.entry_id}: {exc}"
                ) from exc

    return {
        "removed_artifact_count": removed_count,
        "removed_logical_bytes": removed_logical_bytes,
    }
