from __future__ import annotations

import contextlib
from dataclasses import dataclass
import errno
import hashlib
import os
from pathlib import Path
import re
import stat
from typing import Iterable

from app.fs_ops import rename_noreplace_at


@dataclass(frozen=True)
class EmptyDirRelocationResult:
    state: str
    reason: str
    quarantine_path: Path | None = None
    observed_device: int | None = None
    observed_inode: int | None = None


def build_e4_quarantine_name(
    plan_id: str,
    sequence: int,
    source_path: Path | str,
) -> str:
    clean_plan_id = re.sub(r"[^A-Za-z0-9._-]+", "_", str(plan_id)) or "plan"
    digest16 = hashlib.sha256(os.fsencode(str(source_path))).hexdigest()[:16]
    return f".nfc-e4-p{clean_plan_id}-s{sequence}-{digest16}"


def _containing_root(path: Path, roots: Iterable[Path | str]) -> tuple[int, Path] | None:
    resolved_roots = [Path(r).expanduser().resolve(strict=False) for r in roots]
    matches = [(i, r) for i, r in enumerate(resolved_roots) if path == r or path.is_relative_to(r)]
    if not matches:
        return None
    return max(matches, key=lambda pair: len(pair[1].parts))


def _handle_rollback_or_preserve(
    q_root_fd: int,
    q_name: str,
    source_parent_fd: int,
    leaf_name: str,
    target_quarantine_path: Path,
    *,
    reason: str,
    observed_dev: int | None,
    observed_ino: int | None,
) -> EmptyDirRelocationResult:
    try:
        rename_noreplace_at(
            q_root_fd,
            q_name,
            source_parent_fd,
            leaf_name,
        )
        return EmptyDirRelocationResult(
            state="failed",
            reason=f"conflict detected, safely rolled back: {reason}",
            quarantine_path=None,
            observed_device=observed_dev,
            observed_inode=observed_ino,
        )
    except (FileExistsError, OSError) as exc:
        return EmptyDirRelocationResult(
            state="failed",
            reason=f"conflict detected, preserved in quarantine (rollback failed: {exc}): {reason}",
            quarantine_path=target_quarantine_path,
            observed_device=observed_dev,
            observed_inode=observed_ino,
        )


def relocate_empty_dir_to_quarantine(
    source: Path,
    *,
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str,
    plan_id: str,
    sequence: int,
    expected_device: int | None = None,
    expected_inode: int | None = None,
) -> EmptyDirRelocationResult:
    """
    Atomically and safely moves an authorized empty directory into reserved quarantine storage.
    Guarantees:
    - Zero os.rmdir, zero os.unlink, zero shutil.rmtree.
    - Post-relocation identity & emptiness check.
    - If mismatch or non-empty, attempts atomic rollback with RENAME_NOREPLACE.
    - If rollback blocked, preserves object in quarantine without destroying it.
    """
    q_root = Path(quarantine_root).expanduser().resolve()
    if not q_root.exists() or not q_root.is_dir() or q_root.is_symlink():
        return EmptyDirRelocationResult("failed", f"Quarantine root is invalid: {quarantine_root}")

    match = _containing_root(source, allowed_roots)
    if match is None:
        return EmptyDirRelocationResult("skipped", "source is outside configured roots")
    _, base_root = match
    rel_to_root = source.relative_to(base_root)
    if len(rel_to_root.parts) == 0:
        return EmptyDirRelocationResult("skipped", "cannot remove allowed root directory")

    leaf_name = rel_to_root.parts[-1]
    parent_parts = rel_to_root.parts[:-1]
    q_name = build_e4_quarantine_name(plan_id, sequence, source)
    target_quarantine_path = q_root / q_name

    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    with contextlib.ExitStack() as stack:
        try:
            q_root_fd = os.open(str(q_root), flags)
            stack.callback(os.close, q_root_fd)
        except OSError as exc:
            return EmptyDirRelocationResult("failed", f"Failed to open quarantine root: {exc}")

        # Check if deterministic quarantine target already exists
        try:
            os.stat(q_name, dir_fd=q_root_fd, follow_symlinks=False)
            return EmptyDirRelocationResult(
                "failed",
                f"Quarantine target already exists: {q_name}",
                quarantine_path=target_quarantine_path,
            )
        except FileNotFoundError:
            pass
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                return EmptyDirRelocationResult("failed", f"Failed to check quarantine target: {exc}")

        # Open source parent chain with O_DIRECTORY | O_NOFOLLOW
        try:
            curr_fd = os.open(str(base_root), flags)
            stack.callback(os.close, curr_fd)
            for comp in parent_parts:
                next_fd = os.open(comp, flags, dir_fd=curr_fd)
                stack.callback(os.close, next_fd)
                curr_fd = next_fd
        except OSError as exc:
            return EmptyDirRelocationResult("skipped", f"Failed to safely access directory path: {exc}")

        source_parent_fd = curr_fd

        # Pre-mutation check of leaf in source parent
        try:
            st_pre = os.stat(leaf_name, dir_fd=source_parent_fd, follow_symlinks=False)
        except OSError as exc:
            return EmptyDirRelocationResult("skipped", f"stat failed: {exc}")

        if stat.S_ISLNK(st_pre.st_mode) or not stat.S_ISDIR(st_pre.st_mode):
            return EmptyDirRelocationResult("skipped", "source is not a directory")

        if (expected_device and st_pre.st_dev != expected_device) or (
            expected_inode and st_pre.st_ino != expected_inode
        ):
            return EmptyDirRelocationResult(
                "skipped",
                "source identity changed",
                observed_device=st_pre.st_dev,
                observed_inode=st_pre.st_ino,
            )

        # Atomic namespace relocation into quarantine
        try:
            rename_noreplace_at(
                source_parent_fd,
                leaf_name,
                q_root_fd,
                q_name,
            )
        except FileExistsError:
            return EmptyDirRelocationResult(
                "failed",
                f"Quarantine target collision: {q_name}",
                quarantine_path=target_quarantine_path,
            )
        except OSError as exc:
            if exc.errno == errno.EXDEV:
                return EmptyDirRelocationResult("failed", "cross-filesystem quarantine relocation is not supported")
            return EmptyDirRelocationResult("failed", str(exc))

        # Post-relocation verification on the moved object
        try:
            moved_fd = os.open(q_name, flags, dir_fd=q_root_fd)
            stack.callback(os.close, moved_fd)
            st_moved = os.fstat(moved_fd)
            is_dir = stat.S_ISDIR(st_moved.st_mode)
            is_symlink = stat.S_ISLNK(st_moved.st_mode)
            identity_ok = (
                (expected_device is None or st_moved.st_dev == expected_device)
                and (expected_inode is None or st_moved.st_ino == expected_inode)
            )
            entries = os.listdir(moved_fd)
            is_empty = len(entries) == 0
        except Exception as exc:
            return _handle_rollback_or_preserve(
                q_root_fd,
                q_name,
                source_parent_fd,
                leaf_name,
                target_quarantine_path,
                reason=f"post-relocation verification error: {exc}",
                observed_dev=None,
                observed_ino=None,
            )

        # Outcome A: expected identity + empty
        if is_dir and not is_symlink and identity_ok and is_empty:
            return EmptyDirRelocationResult(
                state="completed",
                reason="empty directory logically removed to quarantine",
                quarantine_path=target_quarantine_path,
                observed_device=st_moved.st_dev,
                observed_inode=st_moved.st_ino,
            )

        # Outcome B: Identity mismatch or not a directory
        if not is_dir or is_symlink or not identity_ok:
            return _handle_rollback_or_preserve(
                q_root_fd,
                q_name,
                source_parent_fd,
                leaf_name,
                target_quarantine_path,
                reason=f"moved object identity mismatch (expected {expected_device}:{expected_inode}, got {st_moved.st_dev}:{st_moved.st_ino})",
                observed_dev=st_moved.st_dev,
                observed_ino=st_moved.st_ino,
            )

        # Outcome C: Identity matches, but non-empty
        return _handle_rollback_or_preserve(
            q_root_fd,
            q_name,
            source_parent_fd,
            leaf_name,
            target_quarantine_path,
            reason=f"moved directory is non-empty ({len(entries)} items found)",
            observed_dev=st_moved.st_dev,
            observed_ino=st_moved.st_ino,
        )
