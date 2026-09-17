from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import stat
from typing import Iterable

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd


UTILITY_EMPTY_WRAPPER_STRUCTURAL_CLEANUP_REASON = "empty wrapper structurally removed"


@dataclass(frozen=True)
class UtilityStructuralCleanupResult:
    state: str
    reason: str


def remove_authorized_empty_wrapper(
    source: Path,
    *,
    allowed_roots: Iterable[Path | str],
    expected_device: int | None,
    expected_inode: int | None,
) -> UtilityStructuralCleanupResult:
    """Remove exactly one already-authorized empty wrapper directory.

    This primitive is intentionally quarantine-independent. Authorization is
    resolved by the frozen Utility MOVE -> rmdir pair before this function is
    reached. Here we only re-open the bound wrapper through no-follow directory
    descriptors, re-check its frozen identity and physical emptiness, and issue
    one non-recursive rmdir against the already-open parent directory.
    """
    if not hasattr(os, "O_NOFOLLOW"):
        return UtilityStructuralCleanupResult(
            "failed",
            "safe structural cleanup requires O_NOFOLLOW",
        )

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    try:
        with safe_open_parent_fd(source, allowed_roots) as (parent_fd, leaf_name):
            try:
                st_leaf = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return UtilityStructuralCleanupResult("skipped", "source does not exist")

            if stat.S_ISLNK(st_leaf.st_mode) or not stat.S_ISDIR(st_leaf.st_mode):
                return UtilityStructuralCleanupResult("skipped", "source is not a directory")
            if (expected_device and st_leaf.st_dev != expected_device) or (
                expected_inode and st_leaf.st_ino != expected_inode
            ):
                return UtilityStructuralCleanupResult("skipped", "source identity changed")

            try:
                wrapper_fd = os.open(leaf_name, flags, dir_fd=parent_fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    return UtilityStructuralCleanupResult("skipped", "source is not a directory")
                return UtilityStructuralCleanupResult("failed", f"failed to open wrapper directory: {exc}")

            try:
                st_open = os.fstat(wrapper_fd)
                if not stat.S_ISDIR(st_open.st_mode) or stat.S_ISLNK(st_open.st_mode):
                    return UtilityStructuralCleanupResult("skipped", "source is not a directory")
                if (expected_device and st_open.st_dev != expected_device) or (
                    expected_inode and st_open.st_ino != expected_inode
                ):
                    return UtilityStructuralCleanupResult("skipped", "source identity changed")
                if os.listdir(wrapper_fd):
                    return UtilityStructuralCleanupResult("skipped", "source directory is not empty")

                # Re-check the pathname binding immediately before rmdir so an
                # ABA replacement cannot substitute a different empty directory.
                try:
                    st_final = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    return UtilityStructuralCleanupResult("skipped", "source does not exist")
                if (
                    stat.S_ISLNK(st_final.st_mode)
                    or not stat.S_ISDIR(st_final.st_mode)
                    or st_final.st_dev != st_open.st_dev
                    or st_final.st_ino != st_open.st_ino
                ):
                    return UtilityStructuralCleanupResult("skipped", "source identity changed")

                try:
                    os.rmdir(leaf_name, dir_fd=parent_fd)
                except OSError as exc:
                    if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
                        return UtilityStructuralCleanupResult("skipped", "source directory is not empty")
                    if exc.errno == errno.ENOENT:
                        return UtilityStructuralCleanupResult("skipped", "source does not exist")
                    return UtilityStructuralCleanupResult("failed", str(exc))
            finally:
                os.close(wrapper_fd)
    except (OSError, ValueError) as exc:
        return UtilityStructuralCleanupResult("failed", str(exc))

    return UtilityStructuralCleanupResult(
        "completed",
        UTILITY_EMPTY_WRAPPER_STRUCTURAL_CLEANUP_REASON,
    )
