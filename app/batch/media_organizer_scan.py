"""Stream bounded JSONL previews for recursively discovered organizing units."""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from typing import Callable, TextIO

from app.config_sharing import shared_config_gid, require_shared_directory
from app.batch.media_organizer_units import discover_semantic_units
from app.batch.media_organizer_reports import compact_preview_record, mapping_identifier


def write_semantic_preview(selection: Path, *, allowed_roots: list[Path], out: TextIO,
                           quarantine_root: Path | None = None,
                           exclude_roots: list[Path] | None = None,
                           exclude_dir_names: list[str] | None = None,
                           mapping_root: Path | None = None,
                           max_items: int = 10,
                           check_cancelled: Callable[[], None] | None = None,
                           on_progress: Callable[[int, dict], None] | None = None) -> dict:
    """Write one small result per independent unit; never modify source media."""
    started = time.monotonic()
    summary = {"unit_count": 0, "ready_count": 0, "blocked_count": 0,
               "already_organized_count": 0, "skipped_count": 0,
               "file_count": 0, "needed_moves": 0, "renamed_count": 0,
               "read_only": True}
    mapping_fd = None
    if mapping_root is not None:
        mapping_root = Path(mapping_root)
        info = os.lstat(mapping_root)
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ValueError("full mapping root must be an existing real directory")
        gid = shared_config_gid()
        if gid is not None:
            require_shared_directory(mapping_root, gid)
        mapping_fd = os.open(mapping_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for preview in discover_semantic_units(selection, allowed_roots=allowed_roots,
                                               quarantine_root=quarantine_root,
                                               exclude_roots=exclude_roots,
                                               exclude_dir_names=exclude_dir_names,
                                               check_cancelled=check_cancelled):
            mapping_id = None
            proposed = preview.get("items", []) if preview.get("status") == "ready" else []
            if mapping_fd is not None and proposed:
                mapping_id = mapping_identifier(preview["unit"])
                filename = f"{mapping_id}.jsonl"
                mode = 0o640 if gid is not None else 0o600
                fd = os.open(
                    filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    mode, dir_fd=mapping_fd,
                )
                with os.fdopen(fd, "w", encoding="utf-8") as mapping:
                    if gid is not None:
                        created = os.fstat(mapping.fileno())
                        if (not stat.S_ISREG(created.st_mode)
                                or created.st_gid != gid
                                or created.st_uid != os.geteuid()):
                            raise PermissionError("SHARED_CONFIG: mapping evidence group mismatch")
                        # Only the newly created mapping file can be adjusted.
                        os.fchmod(mapping.fileno(), mode)
                    for item in proposed:
                        row = {key: item[key] for key in (
                            "source", "target", "target_name", "kind", "bytes",
                        )}
                        mapping.write(json.dumps(
                            row, ensure_ascii=False, separators=(",", ":"),
                        ) + "\n")
                    mapping.flush()
                    os.fsync(mapping.fileno())
                os.fsync(mapping_fd)
            record = compact_preview_record(
                preview, max_items=max_items, mapping_id=mapping_id,
            )
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
    finally:
        if mapping_fd is not None:
            os.close(mapping_fd)
    summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return summary
