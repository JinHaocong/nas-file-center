from __future__ import annotations

from collections import defaultdict
import re
from typing import Iterable

from app.indexing.indexer import IndexedEntry


def match_entries(
    entries: Iterable[IndexedEntry],
    *,
    mode: str,
    normalize_pattern: str | None = None,
    normalize_replacement: str = "",
) -> dict[str, list[IndexedEntry]]:
    if mode in {"normalized", "normalized-relative-path"}:
        norm_mode = "normalized"
    elif mode in {"relative-path", "basename", "stem"}:
        norm_mode = mode
    else:
        raise ValueError(f"Unsupported match mode: {mode}")

    if norm_mode == "normalized" and not normalize_pattern:
        raise ValueError("normalize_pattern is required for normalized mode")

    pattern = re.compile(normalize_pattern) if normalize_pattern else None
    grouped: dict[str, list[IndexedEntry]] = defaultdict(list)
    for entry in entries:
        if entry.is_dir:
            continue
        if norm_mode == "relative-path":
            key = entry.relative_path
        elif norm_mode == "basename":
            key = entry.basename
        elif norm_mode == "stem":
            key = entry.stem
        else:
            key = pattern.sub(normalize_replacement, entry.relative_path)  # type: ignore[union-attr]
        grouped[key].append(entry)

    result: dict[str, list[IndexedEntry]] = {}
    for key in sorted(grouped):
        values = sorted(grouped[key], key=lambda item: (item.root_key, item.relative_path, str(item.absolute_path)))
        if len(values) >= 2:
            result[key] = values
    return result
