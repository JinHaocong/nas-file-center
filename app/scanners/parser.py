from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParsedGroup:
    content_hash: str
    file_size: int
    files: tuple[Path, ...]


def _get(mapping: dict[str, Any], *names: str):
    for name in names:
        if name in mapping:
            return mapping[name]
    return None


def _candidate_groups(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("Unsupported fclones JSON report shape")
    for key in ("groups", "file_groups", "duplicate_groups"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    # Some machine-readable producers wrap the result one level deeper.
    for key in ("report", "result", "data"):
        value = payload.get(key)
        if isinstance(value, dict):
            try:
                return _candidate_groups(value)
            except ValueError:
                pass
    raise ValueError("No duplicate groups found in fclones JSON report")


def parse_fclones_report(path: Path | str) -> list[ParsedGroup]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    parsed: list[ParsedGroup] = []
    for raw in _candidate_groups(payload):
        if not isinstance(raw, dict):
            continue
        content_hash = _get(raw, "file_hash", "hash", "content_hash")
        file_size = _get(raw, "file_len", "size", "file_size", "len")
        files = _get(raw, "files", "paths", "members")
        if isinstance(files, dict):
            files = files.get("paths") or files.get("files")
        if content_hash is None or file_size is None or not isinstance(files, list):
            continue
        paths = tuple(Path(str(p)) for p in files)
        if len(paths) < 2:
            continue
        parsed.append(ParsedGroup(str(content_hash), int(file_size), paths))
    return parsed
