from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.exceptions import StateConflictError
from app.models import QuarantineEntry
from app.quarantine.bulk import build_purge_topology_manifest
from app.quarantine.candidate import qualify_candidate_anchor_fd


def _entry_id(metadata_json: str | None) -> int:
    metadata = json.loads(metadata_json or "{}")
    entry_id = metadata.get("quarantine_entry_id")
    if not isinstance(entry_id, int) or isinstance(entry_id, bool) or entry_id <= 0:
        raise StateConflictError("Gate6-A plan item is missing a valid quarantine_entry_id")
    return entry_id


def _qualify_authoritative_anchor(
    service,
    *,
    entry_id: int,
    anchor_path: Path,
    expected_device: int,
    expected_inode: int,
    expected_size: int,
    expected_mtime_ns: int,
    expected_hash: str,
    phase: str,
):
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
                        f"Quarantine entry #{entry_id} authoritative anchor failed Gate6-A {phase} qualification"
                    )
                return os.fstat(fd)
            finally:
                os.close(fd)
    except StateConflictError:
        raise
    except (OSError, ValueError) as exc:
        raise StateConflictError(
            f"Quarantine entry #{entry_id} authoritative anchor could not be safely qualified at {phase}: {exc}"
        ) from exc


def _frozen_identity_updates(frozen_stat, expected_hash: str) -> dict[str, Any]:
    return {
        "expected_device": int(frozen_stat.st_dev),
        "expected_inode": int(frozen_stat.st_ino),
        "expected_size": int(frozen_stat.st_size),
        "expected_mtime_ns": int(
            getattr(frozen_stat, "st_mtime_ns", frozen_stat.st_mtime * 1e9)
        ),
        "expected_hash": expected_hash,
    }


def freeze_bulk_plan_item(
    service,
    *,
    plan_kind: str,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    """Return plan-item Freeze updates for Gate6-A kinds, or None when not owned here."""
    if plan_kind == "quarantine-bulk-purge" and item.get("operation") == "quarantine_purge":
        metadata = json.loads(item.get("metadata_json") or "{}")
        entry_id = _entry_id(item.get("metadata_json"))
        stored_manifest = metadata.get("purge_topology_manifest")
        if not isinstance(stored_manifest, dict):
            raise StateConflictError(
                f"Quarantine entry #{entry_id} purge Draft lacks its topology manifest"
            )

        with service.SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            if entry is None:
                raise StateConflictError(f"Quarantine entry #{entry_id} no longer exists at Freeze")
            if entry.state != "active":
                raise StateConflictError(
                    f"Quarantine entry #{entry_id} is no longer active at Freeze (state={entry.state})"
                )

            current_manifest = build_purge_topology_manifest(
                entry,
                service.settings.quarantine_root,
                owner_lookup=lambda owner_id: session.get(QuarantineEntry, owner_id),
            )
            blockers = list(current_manifest.get("blockers") or [])
            if blockers:
                raise StateConflictError(
                    f"{blockers[0]}: purge topology is no longer eligible for quarantine entry #{entry_id}"
                )
            if current_manifest != stored_manifest:
                raise StateConflictError(
                    f"PURGE_TOPOLOGY_CHANGED: purge topology changed for quarantine entry #{entry_id}"
                )
            if not entry.authoritative_anchor_path:
                raise StateConflictError(
                    f"Quarantine entry #{entry_id} lacks an authoritative anchor at Freeze"
                )
            if not entry.content_hash:
                raise StateConflictError(
                    f"Quarantine entry #{entry_id} lacks an authoritative SHA256 at Freeze"
                )

            anchor_path = Path(entry.authoritative_anchor_path)
            expected_device = int(entry.device)
            expected_inode = int(entry.inode)
            expected_size = int(entry.size)
            expected_mtime_ns = int(entry.mtime_ns)
            expected_hash = str(entry.content_hash)

        frozen_stat = _qualify_authoritative_anchor(
            service,
            entry_id=entry_id,
            anchor_path=anchor_path,
            expected_device=expected_device,
            expected_inode=expected_inode,
            expected_size=expected_size,
            expected_mtime_ns=expected_mtime_ns,
            expected_hash=expected_hash,
            phase="Freeze",
        )
        metadata["frozen_purge_topology_manifest"] = current_manifest
        return {
            **_frozen_identity_updates(frozen_stat, expected_hash),
            "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        }

    if plan_kind != "quarantine-bulk-restore" or item.get("operation") != "restore":
        return None

    entry_id = _entry_id(item.get("metadata_json"))

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

    frozen_stat = _qualify_authoritative_anchor(
        service,
        entry_id=entry_id,
        anchor_path=anchor_path,
        expected_device=expected_device,
        expected_inode=expected_inode,
        expected_size=expected_size,
        expected_mtime_ns=expected_mtime_ns,
        expected_hash=expected_hash,
        phase="Freeze",
    )

    return _frozen_identity_updates(frozen_stat, expected_hash)


def validate_bulk_plan_item(service, *, plan_kind: str, item: Any) -> dict[str, Any] | None:
    """Validate one frozen Gate6-A item without mutating quarantine state or payload."""
    if plan_kind != "quarantine-bulk-restore" or item.operation != "restore":
        return None

    entry_id = _entry_id(item.metadata_json)
    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            return {"state": "stale", "reason": "quarantine_entry_missing", "actual": None}
        if entry.state != "active":
            return {
                "state": "stale",
                "reason": "quarantine_entry_not_active",
                "actual": {"state": entry.state, "tx_phase": entry.tx_phase},
            }
        if not entry.authoritative_anchor_path:
            return {"state": "stale", "reason": "authoritative_anchor_missing", "actual": None}
        anchor_path = Path(entry.authoritative_anchor_path)

    try:
        _qualify_authoritative_anchor(
            service,
            entry_id=entry_id,
            anchor_path=anchor_path,
            expected_device=int(item.expected_device),
            expected_inode=int(item.expected_inode),
            expected_size=int(item.expected_size),
            expected_mtime_ns=int(item.expected_mtime_ns),
            expected_hash=str(item.expected_hash or ""),
            phase="Validate",
        )
    except StateConflictError as exc:
        return {
            "state": "stale",
            "reason": "restore_source_identity_changed",
            "actual": {"error": str(exc)},
        }

    if not item.target_path:
        return {"state": "stale", "reason": "restore_target_missing", "actual": None}

    target = Path(item.target_path)
    if os.path.lexists(target):
        return {
            "state": "stale",
            "reason": "restore_target_occupied",
            "actual": {"target_path": str(target)},
        }

    return {"state": "validated", "reason": "bulk restore validated", "actual": None}
