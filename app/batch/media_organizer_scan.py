"""Stream bounded JSONL previews for recursively discovered organizing units."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, TextIO

from app.batch.media_organizer_units import discover_semantic_units
from app.batch.media_organizer_reports import compact_preview_record


def write_semantic_preview(selection: Path, *, allowed_roots: list[Path], out: TextIO,
                           quarantine_root: Path | None = None,
                           exclude_roots: list[Path] | None = None,
                           max_items: int = 10,
                           check_cancelled: Callable[[], None] | None = None,
                           on_progress: Callable[[int, dict], None] | None = None) -> dict:
    """Write one small result per independent unit; never modify source media."""
    started = time.monotonic()
    summary = {"unit_count": 0, "ready_count": 0, "blocked_count": 0,
               "already_organized_count": 0, "skipped_count": 0,
               "file_count": 0, "needed_moves": 0, "renamed_count": 0,
               "read_only": True}
    for preview in discover_semantic_units(selection, allowed_roots=allowed_roots,
                                           quarantine_root=quarantine_root,
                                           exclude_roots=exclude_roots,
                                           check_cancelled=check_cancelled):
        record = compact_preview_record(preview, max_items=max_items)
        out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        summary["unit_count"] += 1
        name = record["status"] + "_count"
        if name in summary:
            summary[name] += 1
        summary["file_count"] += record["total_files"]
        summary["needed_moves"] += record["needed_moves"]
        summary["renamed_count"] += record["renamed_count"]
        if on_progress is not None and (summary["unit_count"] == 1 or summary["unit_count"] % 25 == 0):
            on_progress(summary["unit_count"], dict(summary))
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return summary
