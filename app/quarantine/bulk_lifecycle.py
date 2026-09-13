from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.exceptions import StateConflictError
from app.models import QuarantineEntry
from app.quarantine.candidate import qualify_candidate_anchor_fd


def freeze_bulk_plan_item(
    service,
    *,
    plan_kind: str,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    """Return plan-item Freeze updates for Gate6-A kinds, or None when not owned here."""
    if plan_kind != "quarantine-bulk-restore" or item.get("operation") != "restore":
        return None

    metadata = json.loads(item.get("metadata_json") or "{}")
    entry_id = metadata.get("quarantine_entry_id")
    if not isinstance(entry_id, int) or isinstance(entry_id, bool) or entry_id <= 0:
        raise StateConflictError("Bulk restore plan item is missing a valid quarantine_entry_id")

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"Quarantine entry #{entry_id} no longer exists at Freeze")
        if entry.state != "active":
            raise StateConflictError(
                f"Quarantine entry #{entry_id} is no longer active at Freeze (state={entry.state})"
            )
        if not entry.authoritative_anchor_path:
            raise StateConflictError(f"Quarantine entry #{entry_id} lacks an authoritative anchor at Freeze")
        if not entry.content_hash:
            raise StateConflictError(f"Quarantine entry #{entry_id} lacks an authoritative SHA256 at Freeze")

        anchor_path = Path(entry.authoritative_anchor_path)
        expected_device = int(entry.device)
        expected_inode = int(entry.inode)
        expected_size = int(entry.size)
        expected_mtime_ns = int(entry.mtime_ns)
        expected_hash = str(entry.content_hash)

    valid_roots = list(service.settings.allowed_roots)
    quarantine_root = Path(service.settings.quarantine_root)
    if quarantine_root not in valid_roots:
        valid_roots.append(quarantine_root)

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        with safe_open_parent_fd(anchor_path, valid_roots) as (parent_fd, leaf_name):
            fd = os.open(leaf_name, flags, dir_fd=parent_fd)
            try:
                qualified = qualify_candidate_anchor_fd(
                    fd,
                    expected_dev=expected_device,
                    expected_ino=expected_inode,
                    expected_size=expected_size,
                    expected_hash=expected_hash,
                    expected_mtime_ns=expected_mtime_ns,
                )
                if not qualified:
                    raise StateConflictError(
                        f"Quarantine entry #{entry_id} authoritative anchor failed Gate6-A Freeze qualification"
                    )
                frozen_stat = os.fstat(fd)
            finally:
                os.close(fd)
    except StateConflictError:
        raise
    except (OSError, ValueError) as exc:
        raise StateConflictError(
            f"Quarantine entry #{entry_id} authoritative anchor could not be safely qualified at Freeze: {exc}"
        ) from exc

    return {
        "expected_device": int(frozen_stat.st_dev),
        "expected_inode": int(frozen_stat.st_ino),
        "expected_size": int(frozen_stat.st_size),
        "expected_mtime_ns": int(
            getattr(frozen_stat, "st_mtime_ns", frozen_stat.st_mtime * 1e9)
        ),
        "expected_hash": expected_hash,
    }
