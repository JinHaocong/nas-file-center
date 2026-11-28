from __future__ import annotations

from dataclasses import dataclass
import errno
import os
from pathlib import Path
import stat
from typing import Callable, Iterable

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
    before_rmdir: Callable[[int, int], bool] | None = None,
) -> UtilityStructuralCleanupResult:
    """Remove exactly one already-authorized empty wrapper directory.

    The caller authorizes removal from its reviewed operation and completed
    file steps. This primitive re-opens the bound wrapper through no-follow
    directory descriptors, confirms its frozen identity and physical emptiness,
    and issues one non-recursive rmdir against the already-open parent.
    Callers may check a lease or mount boundary before the final identity check.
    """
    if not hasattr(os, "O_NOFOLLOW"):
        return UtilityStructuralCleanupResult(
            "failed",
            "safe structural cleanup requires O_NOFOLLOW",
        )
    if (
        not isinstance(expected_device, int)
        or isinstance(expected_device, bool)
        or expected_device <= 0
        or not isinstance(expected_inode, int)
        or isinstance(expected_inode, bool)
        or expected_inode <= 0
    ):
        return UtilityStructuralCleanupResult(
            "failed",
            "frozen wrapper identity is missing or invalid",
        )

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    removed = False

    try:
        with safe_open_parent_fd(source, allowed_roots) as (parent_fd, leaf_name):
            try:
                st_leaf = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return UtilityStructuralCleanupResult("skipped", "source does not exist")

            if stat.S_ISLNK(st_leaf.st_mode) or not stat.S_ISDIR(st_leaf.st_mode):
                return UtilityStructuralCleanupResult("skipped", "source is not a directory")
            if st_leaf.st_dev != expected_device or st_leaf.st_ino != expected_inode:
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
                if st_open.st_dev != expected_device or st_open.st_ino != expected_inode:
                    return UtilityStructuralCleanupResult("skipped", "source identity changed")
                if os.listdir(wrapper_fd):
                    return UtilityStructuralCleanupResult("skipped", "source directory is not empty")
                if before_rmdir is not None and not before_rmdir(parent_fd, wrapper_fd):
                    return UtilityStructuralCleanupResult("skipped", "source directory is outside the current cleanup boundary")

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
                    removed = True
                except OSError as exc:
                    if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
                        return UtilityStructuralCleanupResult("skipped", "source directory is not empty")
                    if exc.errno == errno.ENOENT:
                        return UtilityStructuralCleanupResult("skipped", "source does not exist")
                    return UtilityStructuralCleanupResult("failed", str(exc))
            finally:
                os.close(wrapper_fd)
    except (OSError, ValueError) as exc:
        if removed:
            return UtilityStructuralCleanupResult(
                "completed",
                f"{UTILITY_EMPTY_WRAPPER_STRUCTURAL_CLEANUP_REASON} (post-mutation descriptor close warning: {exc})",
            )
        return UtilityStructuralCleanupResult("failed", str(exc))

    return UtilityStructuralCleanupResult(
        "completed",
        UTILITY_EMPTY_WRAPPER_STRUCTURAL_CLEANUP_REASON,
    )
