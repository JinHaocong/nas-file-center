import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from app.batch_utilities.errors import BatchUtilityInvalidConfigError, BatchUtilityLimitExceededError


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
        wrapper = Path(w_path)
        try:
            with os.scandir(w_path) as it:
                for entry in it:
                    child_source = entry.path
                    child_target = str(wrapper.parent / entry.name)

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
                details={"wrapper_path": w_path, "errno": getattr(e, "errno", None)},
            )

    return candidates, errors
