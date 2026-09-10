import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from app.batch_utilities.errors import (
    BatchUtilityInvalidConfigError,
    BatchUtilityLimitExceededError,
    BatchUtilitySymlinkBlockedError,
    BatchUtilityScopeNotFoundError,
)


class FdPath(int):
    """An integer file descriptor subclass that preserves its original string path.
    Enables passing file descriptors to os.scandir() on POSIX while preserving
    string representations for path logging, error reporting, and test mocks.
    """
    def __new__(cls, fd: int, path: str):
        obj = super().__new__(cls, fd)
        obj.path = str(path)
        return obj

    def __str__(self) -> str:
        return self.path

    def __fspath__(self) -> str:
        return self.path


@dataclass
class FlattenCandidate:
    wrapper_path: str
    source_path: str
    target_path: str
    object_type: str
    size: int
    mtime_ns: int
    device: int
    inode: int
    is_dir: bool


@dataclass
class FlattenError:
    source_path: str
    conflict_type: str
    reason: str
    wrapper_path: str | None = None
    object_type: str = "file"


def discover_flatten_one_level(
    wrapper_paths: Sequence[str],
) -> tuple[list[FlattenCandidate], list[FlattenError]]:
    candidates = []
    errors = []

    for w_path in wrapper_paths:
        clean_path = str(w_path).rstrip("/") or "/"

        flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        try:
            fd = os.open(clean_path, flags)
        except (NotADirectoryError, OSError) as e:
            try:
                st = os.lstat(clean_path)
                if stat.S_ISLNK(st.st_mode):
                    raise BatchUtilitySymlinkBlockedError(
                        f"Wrapper path '{w_path}' is a symlink",
                        details={"wrapper_path": str(w_path), "stage": "DISCOVERY"},
                    )
                if not stat.S_ISDIR(st.st_mode):
                    raise BatchUtilityInvalidConfigError(
                        f"Wrapper path '{w_path}' is not a directory",
                        details={"wrapper_path": str(w_path), "stage": "DISCOVERY"},
                    )
            except BatchUtilitySymlinkBlockedError:
                raise
            except BatchUtilityInvalidConfigError:
                raise
            except OSError:
                pass

            raise BatchUtilityInvalidConfigError(
                f"Failed to scan wrapper directory '{w_path}': {e}",
                details={
                    "wrapper_path": str(w_path),
                    "errno": getattr(e, "errno", None),
                    "stage": "DISCOVERY",
                },
            )

        try:
            target_parent = Path(clean_path).parent
            dir_handle = FdPath(fd, clean_path)
            with os.scandir(dir_handle) as it:
                for entry in it:
                    child_source = os.path.join(clean_path, entry.name)
                    child_target = str(target_parent / entry.name)

                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError as e:
                        errors.append(
                            FlattenError(
                                source_path=child_source,
                                conflict_type="STAT_FAILED",
                                reason=f"Failed to stat wrapper child: {e}",
                                wrapper_path=w_path,
                                object_type="file",
                            )
                        )
                        continue

                    if stat.S_ISLNK(st.st_mode):
                        errors.append(
                            FlattenError(
                                source_path=child_source,
                                conflict_type="WRAPPER_CHILD_SYMLINK",
                                reason="Wrapper child is a symlink",
                                wrapper_path=w_path,
                                object_type="symlink",
                            )
                        )
                        continue

                    if not stat.S_ISREG(st.st_mode) and not stat.S_ISDIR(st.st_mode):
                        errors.append(
                            FlattenError(
                                source_path=child_source,
                                conflict_type="UNSUPPORTED_OBJECT",
                                reason="Wrapper child is an unsupported object type",
                                wrapper_path=w_path,
                                object_type="unsupported",
                            )
                        )
                        continue

                    is_dir = stat.S_ISDIR(st.st_mode)
                    candidates.append(
                        FlattenCandidate(
                            wrapper_path=w_path,
                            source_path=child_source,
                            target_path=child_target,
                            object_type="directory" if is_dir else "file",
                            size=st.st_size if not is_dir else 0,
                            mtime_ns=st.st_mtime_ns,
                            device=st.st_dev,
                            inode=st.st_ino,
                            is_dir=is_dir,
                        )
                    )
                    if len(candidates) + len(errors) > 50000:
                        raise BatchUtilityLimitExceededError("Flatten utility supports maximum 50,000 candidates")
        except OSError as e:
            raise BatchUtilityInvalidConfigError(
                f"Failed to scan wrapper directory '{w_path}': {e}",
                details={
                    "wrapper_path": str(w_path),
                    "errno": getattr(e, "errno", None),
                    "stage": "DISCOVERY",
                },
            )
        finally:
            os.close(fd)

    return candidates, errors
