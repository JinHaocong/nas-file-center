from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class TransformDecision(str, Enum):
    ACTIONABLE = "ACTIONABLE"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class TransformedBasenameResult:
    decision: TransformDecision
    target_basename: str | None
    reason_code: str | None = None
    reason: str | None = None


def canonicalize_suffix(suffix: str) -> str:
    if not isinstance(suffix, str):
        raise ValueError("suffix must be a string")
    s = suffix.strip()
    if not s:
        raise ValueError("suffix cannot be empty")
    if "\0" in s:
        raise ValueError("suffix cannot contain NUL bytes")
    if "/" in s or "\\" in s:
        raise ValueError("suffix cannot contain path separators")
    if s == ".":
        raise ValueError("suffix cannot be empty or just a dot")
    if not s.startswith("."):
        s = "." + s
    if s == ".":
        raise ValueError("suffix cannot be empty or just a dot")
    return s


def compute_transformed_basename(
    basename: str,
    *,
    mode: str,
    target_suffix: str,
) -> TransformedBasenameResult:
    canon_suffix = canonicalize_suffix(target_suffix)

    if mode == "append":
        return TransformedBasenameResult(
            decision=TransformDecision.ACTIONABLE,
            target_basename=f"{basename}{canon_suffix}",
        )

    if mode == "change":
        # Suffix of the filename
        curr_suffix = Path(basename).suffix
        if not curr_suffix:
            return TransformedBasenameResult(
                decision=TransformDecision.SKIPPED,
                target_basename=None,
                reason_code="NO_EXISTING_SUFFIX",
                reason="Source file has no existing extension",
            )

        if curr_suffix == canon_suffix:
            return TransformedBasenameResult(
                decision=TransformDecision.SKIPPED,
                target_basename=None,
                reason_code="NO_CHANGE",
                reason="Source file already has the target extension",
            )

        stem = basename[:-len(curr_suffix)]
        return TransformedBasenameResult(
            decision=TransformDecision.ACTIONABLE,
            target_basename=f"{stem}{canon_suffix}",
        )

    raise ValueError(f"Unsupported suffix transform mode: {mode}")
