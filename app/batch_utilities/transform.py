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
    raw = suffix.strip()
    if not raw or raw == ".":
        raise ValueError("suffix cannot be empty or just a dot")
    if "\0" in raw:
        raise ValueError("suffix cannot contain NUL bytes")
    if "/" in raw or "\\" in raw:
        raise ValueError("suffix cannot contain path separators")
    body = raw[1:] if raw.startswith(".") else raw
    parts = body.split(".")
    if not body or any(part == "" for part in parts):
        raise ValueError("suffix has invalid format or dot structure")
    return "." + body



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
