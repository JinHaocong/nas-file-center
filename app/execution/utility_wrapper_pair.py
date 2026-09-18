from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import stat
from typing import Iterable, Iterator

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.path_safety import is_reserved_quarantine_path, require_allowed_path


@dataclass(frozen=True)
class UtilityWrapperCleanupResult:
    state: str
    reason: str


class UtilityWrapperLiveBindingError(OSError):
    pass


class UtilityWrapperLiveGuard:
    def __init__(
        self,
        *,
        parent_fd: int,
        wrapper_fd: int,
        leaf_name: str,
        wrapper_path: Path,
        child_name: str,
    ) -> None:
        self.parent_fd = parent_fd
        self.wrapper_fd = wrapper_fd
        self.leaf_name = leaf_name
        self.wrapper_path = wrapper_path
        self.child_name = child_name

    def remove_if_empty(self) -> UtilityWrapperCleanupResult:
        try:
            names = os.listdir(self.wrapper_fd)
        except OSError as exc:
            return UtilityWrapperCleanupResult(
                "failed",
                f"failed to inspect live wrapper directory: {exc}",
            )

        if names:
            return UtilityWrapperCleanupResult(
                "failed",
                "live wrapper directory is not empty after paired MOVE",
            )

        try:
            st_open = os.fstat(self.wrapper_fd)
            st_path = os.stat(
                self.leaf_name,
                dir_fd=self.parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return UtilityWrapperCleanupResult(
                "failed",
                "live wrapper pathname disappeared before structural cleanup",
            )
        except OSError as exc:
            return UtilityWrapperCleanupResult(
                "failed",
                f"failed to revalidate live wrapper binding: {exc}",
            )

        if (
            stat.S_ISLNK(st_path.st_mode)
            or not stat.S_ISDIR(st_path.st_mode)
            or not stat.S_ISDIR(st_open.st_mode)
        ):
            return UtilityWrapperCleanupResult(
                "failed",
                "live wrapper binding is no longer a directory",
            )

        # Compare the pathname binding to the still-open descriptor at the same
        # instant. This deliberately does not compare against the frozen inode:
        # some zfuse implementations expose unstable directory inode identity
        # after namespace mutations, while the open-FD/path pair still lets us
        # detect replacement/ABA immediately before rmdir.
        if (
            int(st_path.st_dev) != int(st_open.st_dev)
            or int(st_path.st_ino) != int(st_open.st_ino)
        ):
            return UtilityWrapperCleanupResult(
                "failed",
                "live wrapper pathname no longer matches the opened directory",
            )

        try:
            os.rmdir(self.leaf_name, dir_fd=self.parent_fd)
        except OSError as exc:
            if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
                return UtilityWrapperCleanupResult(
                    "failed",
                    "live wrapper directory became non-empty before rmdir",
                )
            return UtilityWrapperCleanupResult(
                "failed",
                f"failed to remove live wrapper directory: {exc}",
            )

        return UtilityWrapperCleanupResult(
            "completed",
            "empty wrapper structurally removed under live descriptor authority",
        )


@contextmanager
def open_utility_wrapper_live_guard(
    *,
    wrapper_path: Path | str,
    child_path: Path | str,
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str | None,
) -> Iterator[UtilityWrapperLiveGuard]:
    wrapper = Path(wrapper_path)
    child = Path(child_path)

    if child.parent != wrapper:
        raise UtilityWrapperLiveBindingError(
            errno.EINVAL,
            "Utility child is not a direct child of the wrapper",
            os.fspath(child),
        )

    require_allowed_path(wrapper, allowed_roots)
    require_allowed_path(child, allowed_roots)

    if quarantine_root is not None:
        if (
            is_reserved_quarantine_path(wrapper, quarantine_root)
            or is_reserved_quarantine_path(child, quarantine_root)
        ):
            raise UtilityWrapperLiveBindingError(
                errno.EPERM,
                "Utility wrapper binding cannot use reserved quarantine storage",
                os.fspath(wrapper),
            )

    if not hasattr(os, "O_NOFOLLOW"):
        raise UtilityWrapperLiveBindingError(
            errno.EOPNOTSUPP,
            "safe live wrapper binding requires O_NOFOLLOW",
            os.fspath(wrapper),
        )

    with safe_open_parent_fd(wrapper, allowed_roots) as (parent_fd, leaf_name):
        st_leaf = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISLNK(st_leaf.st_mode) or not stat.S_ISDIR(st_leaf.st_mode):
            raise UtilityWrapperLiveBindingError(
                errno.ENOTDIR,
                "Utility wrapper is not a real directory",
                os.fspath(wrapper),
            )

        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        wrapper_fd = os.open(leaf_name, flags, dir_fd=parent_fd)
        try:
            names = os.listdir(wrapper_fd)
            if names != [child.name] and sorted(names) != [child.name]:
                raise UtilityWrapperLiveBindingError(
                    errno.ENOTEMPTY,
                    "Utility wrapper no longer contains exactly the frozen child",
                    os.fspath(wrapper),
                )

            child_fd_stat = os.stat(
                child.name,
                dir_fd=wrapper_fd,
                follow_symlinks=False,
            )
            child_path_stat = os.lstat(child)
            if (
                int(child_fd_stat.st_dev) != int(child_path_stat.st_dev)
                or int(child_fd_stat.st_ino) != int(child_path_stat.st_ino)
                or stat.S_IFMT(child_fd_stat.st_mode) != stat.S_IFMT(child_path_stat.st_mode)
            ):
                raise UtilityWrapperLiveBindingError(
                    getattr(errno, "ESTALE", errno.EIO),
                    "Utility child pathname is not bound to the opened wrapper",
                    os.fspath(child),
                )

            yield UtilityWrapperLiveGuard(
                parent_fd=parent_fd,
                wrapper_fd=wrapper_fd,
                leaf_name=leaf_name,
                wrapper_path=wrapper,
                child_name=child.name,
            )
        finally:
            os.close(wrapper_fd)
