from contextlib import contextmanager
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
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


@contextmanager
def acquire_wrapper_dir(
    path: str,
    expected_device: int | None = None,
    expected_inode: int | None = None,
    stage: str = "DISCOVERY",
):
    """Acquires an opened file descriptor to a wrapper directory with strict no-follow semantics,
    and validates its physical filesystem identity (st_dev, st_ino) before yielding.
    If the opened descriptor does not match expected_device / expected_inode, closes fd and fails closed immediately
    with WRAPPER_IDENTITY_CHANGED without enumerating any children.
    """
    clean_path = str(path).rstrip("/") or "/"

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
                    f"Wrapper path '{path}' is a symlink",
                    details={"wrapper_path": str(path), "stage": stage},
                )
            if not stat.S_ISDIR(st.st_mode):
                raise BatchUtilityInvalidConfigError(
                    f"Wrapper path '{path}' is not a directory",
                    details={"wrapper_path": str(path), "stage": stage},
                )
        except (BatchUtilitySymlinkBlockedError, BatchUtilityInvalidConfigError):
            raise
        except OSError:
            pass

        raise BatchUtilityInvalidConfigError(
            f"Failed to scan wrapper directory '{path}': {e}",
            details={
                "wrapper_path": str(path),
                "errno": getattr(e, "errno", None),
                "stage": stage,
            },
        )

    try:
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            raise BatchUtilityInvalidConfigError(
                f"Wrapper path '{path}' is not a directory",
                details={"wrapper_path": str(path), "stage": stage},
            )

        if expected_device is not None and st.st_dev != expected_device:
            raise BatchUtilityInvalidConfigError(
                f"WRAPPER_IDENTITY_CHANGED: Wrapper '{path}' physical identity changed (device mismatch)",
                details={
                    "wrapper_path": str(path),
                    "error": "WRAPPER_IDENTITY_CHANGED",
                    "stage": stage,
                    "expected_device": expected_device,
                    "current_device": st.st_dev,
                    "expected_inode": expected_inode,
                    "current_inode": st.st_ino,
                },
            )

        if expected_inode is not None and st.st_ino != expected_inode:
            raise BatchUtilityInvalidConfigError(
                f"WRAPPER_IDENTITY_CHANGED: Wrapper '{path}' physical identity changed (inode mismatch)",
                details={
                    "wrapper_path": str(path),
                    "error": "WRAPPER_IDENTITY_CHANGED",
                    "stage": stage,
                    "expected_device": expected_device,
                    "current_device": st.st_dev,
                    "expected_inode": expected_inode,
                    "current_inode": st.st_ino,
                },
            )

        dir_handle = FdPath(fd, clean_path)
        yield dir_handle, st
    finally:
        os.close(fd)


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
    expected_identities: Mapping[str, tuple[int, int]] | Sequence[tuple[int, int] | None] | None = None,
) -> tuple[list[FlattenCandidate], list[FlattenError]]:
    candidates = []
    errors = []

    for idx, w_path in enumerate(wrapper_paths):
        clean_path = str(w_path).rstrip("/") or "/"

        exp_dev, exp_ino = None, None
        if expected_identities is not None:
            if isinstance(expected_identities, Mapping):
                exp_id = (
                    expected_identities.get(w_path)
                    or expected_identities.get(clean_path)
                )
                if exp_id is None:
                    try:
                        resolved_k = str(Path(clean_path).resolve())
                        exp_id = expected_identities.get(resolved_k)
                    except OSError:
                        pass
                if exp_id is not None:
                    exp_dev, exp_ino = exp_id
            elif isinstance(expected_identities, Sequence) and idx < len(expected_identities):
                exp_id = expected_identities[idx]
                if exp_id is not None:
                    exp_dev, exp_ino = exp_id

        with acquire_wrapper_dir(
            clean_path,
            expected_device=exp_dev,
            expected_inode=exp_ino,
            stage="DISCOVERY",
        ) as (dir_handle, _st):
            target_parent = Path(clean_path).parent
            try:
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

    return candidates, errors
