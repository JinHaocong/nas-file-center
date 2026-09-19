from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import Any

from app.planning.dedupe_preview import (
    _directory_binding_matches,
    _open_absolute_directory_nofollow,
    _recursive_directory_open_flags,
    _relative_reserved_quarantine_path,
    _snapshot_real_regular_files_recursive,
)


@dataclass(frozen=True)
class RecursiveProtectionSnapshot:
    """Public sampled snapshot contract for Recursive Last-File Protection.

    Architecture Amendment A intentionally does not treat the finite descriptor-
    bound verification passes underneath this API as an atomic snapshot against
    arbitrary external writers. They are defense in depth; callers must still
    perform the frozen Validate/Execute live protection checks.
    """

    count: int
    stable: bool
    device: int | None
    inode: int | None
    tree_identity_digest: str | None

    def digest_payload(self) -> dict[str, Any]:
        return {
            "stable": self.stable,
            "device": self.device,
            "inode": self.inode,
            "tree_identity_digest": self.tree_identity_digest,
        }


def snapshot_recursive_regular_files(
    directory: str | Path,
    *,
    quarantine_root: str | Path | None = None,
) -> RecursiveProtectionSnapshot:
    """Read one descriptor-bound, no-follow sampled recursive file snapshot."""

    snapshot = _snapshot_real_regular_files_recursive(
        directory,
        quarantine_root=quarantine_root,
    )
    return RecursiveProtectionSnapshot(
        count=snapshot.count,
        stable=snapshot.stable,
        device=snapshot.device,
        inode=snapshot.inode,
        tree_identity_digest=snapshot.tree_identity_digest,
    )


@dataclass(frozen=True)
class RecursiveProtectionLiveCount:
    """Execute-time exact recursive count without Preview tree-digest materialization.

    This reader keeps Amendment A's descriptor-bound/no-follow and fail-closed
    semantics, but it intentionally does not build deterministic identity rows or
    rebind every row because Execute only needs the current regular-file count and
    protected-directory identity. It performs two fresh descriptor-bound count
    passes and a final protected-root rebind. External writers still cannot be
    atomically excluded from the final syscall gap, as documented by Amendment A.
    """

    count: int
    stable: bool
    device: int | None
    inode: int | None


def _unstable_live_count(
    *,
    device: int | None = None,
    inode: int | None = None,
) -> RecursiveProtectionLiveCount:
    return RecursiveProtectionLiveCount(
        count=0,
        stable=False,
        device=device,
        inode=inode,
    )


def _count_live_regular_files_pass(
    root_fd: int,
    *,
    excluded_relative_path: str | None,
) -> int | None:
    """Consume root_fd and return one exact descriptor-bound regular-file count."""

    dir_flags = _recursive_directory_open_flags()
    if dir_flags is None:
        try:
            os.close(root_fd)
        except OSError:
            pass
        return None

    regular_flags = os.O_RDONLY | os.O_NOFOLLOW
    count = 0
    stable = True
    stack: list[tuple[int, str]] = [(root_fd, ".")]

    while stack and stable:
        current_fd, relative_dir = stack.pop()
        try:
            try:
                iterator = os.scandir(current_fd)
            except OSError:
                stable = False
                continue

            try:
                for entry in iterator:
                    relative_path = (
                        entry.name
                        if relative_dir == "."
                        else f"{relative_dir}/{entry.name}"
                    )
                    if (
                        excluded_relative_path is not None
                        and relative_path == excluded_relative_path
                    ):
                        continue

                    try:
                        entry_st = entry.stat(follow_symlinks=False)
                    except OSError:
                        stable = False
                        break

                    if stat.S_ISLNK(entry_st.st_mode):
                        continue

                    if stat.S_ISREG(entry_st.st_mode):
                        try:
                            file_fd = os.open(
                                entry.name,
                                regular_flags,
                                dir_fd=current_fd,
                            )
                        except OSError:
                            stable = False
                            break
                        try:
                            opened_file_st = os.fstat(file_fd)
                        finally:
                            os.close(file_fd)
                        if (
                            not stat.S_ISREG(opened_file_st.st_mode)
                            or int(opened_file_st.st_dev) != int(entry_st.st_dev)
                            or int(opened_file_st.st_ino) != int(entry_st.st_ino)
                        ):
                            stable = False
                            break
                        count += 1
                        continue

                    if stat.S_ISDIR(entry_st.st_mode):
                        try:
                            child_fd = os.open(
                                entry.name,
                                dir_flags,
                                dir_fd=current_fd,
                            )
                        except OSError:
                            stable = False
                            break
                        child_st = os.fstat(child_fd)
                        if (
                            not stat.S_ISDIR(child_st.st_mode)
                            or int(child_st.st_dev) != int(entry_st.st_dev)
                            or int(child_st.st_ino) != int(entry_st.st_ino)
                        ):
                            os.close(child_fd)
                            stable = False
                            break
                        stack.append((child_fd, relative_path))
            finally:
                iterator.close()
        finally:
            try:
                os.close(current_fd)
            except OSError:
                pass

    if not stable:
        for fd, _relative_dir in stack:
            try:
                os.close(fd)
            except OSError:
                pass
        return None

    return count


def live_count_recursive_regular_files(
    directory: str | Path,
    *,
    quarantine_root: str | Path | None = None,
) -> RecursiveProtectionLiveCount:
    """Return a trustworthy current exact count for Execute Last-File preflight.

    Preview/Freeze/Validate continue to use the stronger sampled snapshot reader
    with deterministic tree identity. Execute does not consume that digest; doing
    its O(number-of-tree-rows * depth) final row rebind for every Quarantine item
    is therefore redundant work. Two independently reacquired descriptor-bound
    count passes plus a final protected-root binding check preserve the Execute
    authority actually required by Amendment A.
    """

    excluded_relative_path = _relative_reserved_quarantine_path(
        directory,
        quarantine_root,
    )
    if excluded_relative_path == ".":
        return _unstable_live_count()

    first_opened = _open_absolute_directory_nofollow(directory)
    if first_opened is None:
        return _unstable_live_count()
    first_fd, first_st = first_opened
    root_device = int(first_st.st_dev)
    root_inode = int(first_st.st_ino)

    first_count = _count_live_regular_files_pass(
        first_fd,
        excluded_relative_path=excluded_relative_path,
    )
    if first_count is None:
        return _unstable_live_count(device=root_device, inode=root_inode)

    second_opened = _open_absolute_directory_nofollow(directory)
    if second_opened is None:
        return _unstable_live_count(device=root_device, inode=root_inode)
    second_fd, second_st = second_opened
    if (
        int(second_st.st_dev) != root_device
        or int(second_st.st_ino) != root_inode
    ):
        os.close(second_fd)
        return _unstable_live_count(device=root_device, inode=root_inode)

    second_count = _count_live_regular_files_pass(
        second_fd,
        excluded_relative_path=excluded_relative_path,
    )
    if second_count is None or second_count != first_count:
        return _unstable_live_count(device=root_device, inode=root_inode)

    if not _directory_binding_matches(directory, root_device, root_inode):
        return _unstable_live_count(device=root_device, inode=root_inode)

    return RecursiveProtectionLiveCount(
        count=second_count,
        stable=True,
        device=root_device,
        inode=root_inode,
    )
