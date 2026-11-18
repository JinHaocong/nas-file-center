"""Bounded preview reports and full, paginated source→target mapping evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

ALLOWED_STATUS_FILTERS = frozenset({"all", "ready", "blocked", "skipped", "already_organized"})
_MAPPING_ID = re.compile(r"^[0-9a-f]{64}$")
MAX_MAPPING_BYTES = 512 * 1024 * 1024


def mapping_identifier(unit: str) -> str:
    if not isinstance(unit, str) or not unit:
        raise ValueError("mapping unit must be a non-empty literal path")
    return hashlib.sha256(unit.encode("utf-8")).hexdigest()


def compact_preview_record(record: dict, *, max_items: int = 10,
                           mapping_id: str | None = None) -> dict:
    """Keep a small UI sample while referencing the complete private mapping."""
    if not isinstance(max_items, int) or not 0 <= max_items <= 100:
        raise ValueError("max_items must be within 0..100")
    status = record["status"]
    proposed = list(record.get("items", [])) if status == "ready" else []
    sample = [{k: item[k] for k in ("source", "target", "target_name", "kind", "bytes")
               if k in item} for item in proposed[:max_items]]
    if proposed and (not isinstance(mapping_id, str) or not _MAPPING_ID.fullmatch(mapping_id)):
        raise ValueError("complete mapping id is required for a ready unit with moves")
    return {
        "unit": record["unit"], "status": status, "reason": record.get("reason"),
        "operation": record.get("operation"), "totals": record.get("totals", {}),
        "groups": record.get("groups", []), "needed_moves": int(record.get("needed_moves", 0)),
        "renamed_count": int(record.get("renamed_count", 0)),
        "total_files": sum(int(n) for n in record.get("totals", {}).values()),
        "total_proposals": len(proposed), "sample_moves": sample,
        "mapping_id": mapping_id if proposed else None,
        "truncated": len(proposed) > max_items,
        "input_fingerprint": record.get("input_fingerprint"),
        "conflicts": record.get("conflicts", []), "read_only": True,
    }


def read_preview_page(data: Path, *, page: int, page_size: int,
                      status_filter: str = "all") -> tuple[list[dict], int]:
    """Apply a status filter before slicing without materializing the report."""
    if (not isinstance(page, int) or not isinstance(page_size, int)
            or page < 1 or not 1 <= page_size <= 100):
        raise ValueError("invalid preview pagination")
    if status_filter not in ALLOWED_STATUS_FILTERS:
        raise ValueError("invalid preview status filter")
    offset = (page - 1) * page_size
    count = 0
    page_rows = []
    with Path(data).open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if status_filter != "all" and row.get("status") != status_filter:
                continue
            if offset <= count < offset + page_size:
                page_rows.append(row)
            count += 1
    return page_rows, count


def read_preview_mapping(mapping_root: Path, mapping_id: str, *, page: int,
                         page_size: int) -> tuple[list[dict], int]:
    """Read a private full source→target map without allowing arbitrary paths."""
    if not isinstance(mapping_id, str) or not _MAPPING_ID.fullmatch(mapping_id):
        raise ValueError("invalid mapping identity")
    if (not isinstance(page, int) or not isinstance(page_size, int)
            or page < 1 or not 1 <= page_size <= 100):
        raise ValueError("invalid mapping pagination")
    root = Path(mapping_root)
    root_stat = os.lstat(root)
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise ValueError("unsafe mapping report directory")
    path = root / f"{mapping_id}.jsonl"
    fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_size > MAX_MAPPING_BYTES):
            raise ValueError("unsafe full mapping report")
        offset = (page - 1) * page_size
        count = 0
        rows = []
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            for line in stream:
                row = json.loads(line)
                if not isinstance(row, dict) or not all(
                    isinstance(row.get(key), str) and row[key]
                    for key in ("source", "target", "target_name", "kind")
                ) or row.get("kind") not in ("P", "V", "Other"):
                    raise ValueError("invalid full mapping record")
                if (not isinstance(row.get("bytes"), int) or row["bytes"] < 0
                        or "identity" in row):
                    raise ValueError("unsafe full mapping fields")
                if offset <= count < offset + page_size:
                    rows.append(row)
                count += 1
        return rows, count
    finally:
        if fd >= 0:
            os.close(fd)
