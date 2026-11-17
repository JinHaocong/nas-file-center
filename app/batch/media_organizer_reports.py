"""Bounded, read-only preview report projection and safe pagination."""
from __future__ import annotations

import json
from pathlib import Path

ALLOWED_STATUS_FILTERS = frozenset({"all", "ready", "blocked", "skipped", "already_organized"})


def compact_preview_record(record: dict, *, max_items: int = 10) -> dict:
    """Remove mutable input identities and cap the displayed mapping sample."""
    if not isinstance(max_items, int) or not 0 <= max_items <= 100:
        raise ValueError("max_items must be within 0..100")
    status = record["status"]
    proposed = list(record.get("items", [])) if status == "ready" else []
    sample = [{k: item[k] for k in ("source", "target", "target_name", "kind", "bytes")
               if k in item} for item in proposed[:max_items]]
    return {
        "unit": record["unit"], "status": status, "reason": record.get("reason"),
        "operation": record.get("operation"), "totals": record.get("totals", {}),
        "groups": record.get("groups", []), "needed_moves": int(record.get("needed_moves", 0)),
        "renamed_count": int(record.get("renamed_count", 0)),
        "total_files": sum(int(n) for n in record.get("totals", {}).values()),
        "total_proposals": len(proposed), "sample_moves": sample,
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
