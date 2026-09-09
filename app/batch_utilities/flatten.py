import os
from dataclasses import dataclass
from pathlib import Path

@dataclass
class FlattenCandidate:
    source_path: str
    target_path: str
    size: int
    is_dir: bool

@dataclass
class FlattenError:
    source_path: str
    conflict_type: str
    reason: str

def discover_flatten_one_level(wrapper_paths: list[str]) -> tuple[list[FlattenCandidate], list[FlattenError]]:
    candidates = []
    errors = []

    for w_path in wrapper_paths:
        wrapper = Path(w_path)
        try:
            with os.scandir(w_path) as it:
                for entry in it:
                    child_source = entry.path
                    child_target = str(wrapper.parent / entry.name)

                    if entry.is_symlink():
                        errors.append(FlattenError(
                            source_path=child_source,
                            conflict_type="WRAPPER_CHILD_SYMLINK",
                            reason="Wrapper child is a symlink"
                        ))
                        continue

                    if not entry.is_file() and not entry.is_dir():
                        errors.append(FlattenError(
                            source_path=child_source,
                            conflict_type="UNSUPPORTED_OBJECT",
                            reason="Wrapper child is an unsupported object type"
                        ))
                        continue

                    candidates.append(FlattenCandidate(
                        source_path=child_source,
                        target_path=child_target,
                        size=entry.stat().st_size if entry.is_file() else 0,
                        is_dir=entry.is_dir()
                    ))
        except OSError as e:
            errors.append(FlattenError(
                source_path=w_path,
                conflict_type="SCANDIR_FAILED",
                reason=f"Failed to scan wrapper directory: {e}"
            ))

    return candidates, errors
