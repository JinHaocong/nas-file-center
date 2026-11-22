"""Deterministic final names for a fixed resource package.

This module never touches the filesystem. P, V and homogeneous flat packages
are independently numbered from 001, preserving the original final extension.
Non-media files retain their name unless a casefold collision needs a suffix.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


MEDIA_BUCKET_PATTERN = re.compile(
    r"^(?P<kind>p|v)(?:_(?P<index>[1-9]\d*))? (?P<label>\[\d+ [^/]+\])$",
    re.IGNORECASE,
)


def media_source_sort_key(path: str, unit: Path) -> tuple:
    """Sort actual bucket indices numerically and ordinary paths lexically."""
    relative = os.path.relpath(path, unit)
    parts = Path(relative).parts
    folded = []
    for part in parts[:-1]:
        bucket = MEDIA_BUCKET_PATTERN.fullmatch(part)
        if bucket is not None and bucket.group("index") is not None:
            folded.append((
                bucket.group("kind").casefold() + "_", int(bucket.group("index")),
                bucket.group("label").casefold() + "/",
            ))
        else:
            folded.append((part.casefold() + "/", -1, ""))
    folded.append((parts[-1].casefold(), -1, ""))
    return tuple(folded), relative


def numbered_name(index: int, name: str) -> str:
    if not isinstance(index, int) or index < 1:
        raise ValueError("Numbering index must be positive")
    return f"{index:03d}{Path(name).suffix}"


def allocate_names(rows: list[dict], *, kind: str) -> tuple[list[str], int]:
    """Return unique target basenames aligned with the already-sorted rows.

    Every name in a numbered bucket has a distinct ordinal, even if the
    original filename is identical. Other is conservatively left intact,
    except duplicates are suffixed without colliding with any existing
    original basename or any prior allocation.
    """
    if kind in ("P", "V", "flat"):
        names = [numbered_name(index, row["name"]) for index, row in enumerate(rows, 1)]
        return names, 0

    if kind != "Other":
        raise ValueError("Unknown media package group")

    originals = {row["name"].casefold() for row in rows}
    allocated: set[str] = set()
    output: list[str] = []
    resolved = 0
    for ordinal, row in enumerate(rows, 1):
        original = row["name"]
        proposed = original
        if proposed.casefold() in allocated:
            resolved += 1
            path = Path(original)
            for suffix_number in range(2, len(rows) + 3):
                candidate = f"{path.stem}__dup{suffix_number:03d}{path.suffix}"
                if len(candidate.encode("utf-8")) > 255:
                    candidate = f"file_{ordinal:06d}__dup{suffix_number:03d}{path.suffix}"
                if (candidate.casefold() not in allocated
                        and candidate.casefold() not in originals):
                    proposed = candidate
                    break
            else:
                raise ValueError("Cannot find a safe collision-free Other filename")
        if proposed.casefold() in allocated:
            raise ValueError("Duplicate allocated media package destination")
        allocated.add(proposed.casefold())
        output.append(proposed)
    return output, resolved
