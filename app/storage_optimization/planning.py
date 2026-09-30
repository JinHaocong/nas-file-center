from __future__ import annotations

import hashlib
import json
from typing import Any

from app.planning.dedupe_preview import DedupePreviewCompilation, normalize_storage_action
from app.storage_optimization.metadata import (
    StorageMetadataError,
    capture_file_metadata,
    hardlink_metadata_compatibility,
    ownership_can_be_preserved,
)


def build_storage_action_snapshot(
    compilation: DedupePreviewCompilation,
    storage_action: str,
) -> dict[str, dict[str, Any]]:
    """Read-only per-source eligibility overlay for an Advanced Dedupe preview.

    This function MUST NOT run capability probes or create filesystem objects.
    It only reads ordinary stat/xattr metadata needed to explain whether the
    selected storage action is semantically eligible before Draft generation.
    """
    action = normalize_storage_action(storage_action)
    snapshot: dict[str, dict[str, Any]] = {}

    for group in compilation.groups:
        if group.status != "actionable" or group.recommended_keep is None:
            continue
        keep_path = group.recommended_keep.absolute_path
        members_by_path = {member.absolute_path: member for member in group.members}
        for source_path in group.quarantine_candidates:
            member = members_by_path.get(source_path)
            info: dict[str, Any] = {
                "storage_action": action,
                "keep_path": keep_path,
                "source_path": source_path,
                "expected_size": int(group.file_size),
                "scan_root_index": (
                    int(member.scan_root_index)
                    if member is not None
                    and member.scan_root_index is not None
                    else None
                ),
                "actionable": True,
                "reason": "QUARANTINE_ACTIONABLE",
                "capability": "NOT_CHECKED",
            }

            if action == "hardlink":
                try:
                    compatible, reason, _, source_metadata = hardlink_metadata_compatibility(
                        keep_path,
                        source_path,
                    )
                    if compatible and source_metadata.link_count != 1:
                        compatible = False
                        reason = "SOURCE_HAS_MULTIPLE_HARDLINKS"
                except StorageMetadataError as exc:
                    compatible = False
                    reason = f"HARDLINK_METADATA_UNAVAILABLE:{exc}"
                info["actionable"] = bool(compatible)
                info["reason"] = reason
            elif action == "reflink":
                try:
                    source_metadata = capture_file_metadata(source_path)
                except StorageMetadataError as exc:
                    info["actionable"] = False
                    info["reason"] = f"REFLINK_METADATA_UNAVAILABLE:{exc}"
                else:
                    if source_metadata.link_count != 1:
                        info["actionable"] = False
                        info["reason"] = "SOURCE_HAS_MULTIPLE_HARDLINKS"
                    elif ownership_can_be_preserved(source_metadata):
                        info["reason"] = "REFLINK_METADATA_PRESERVABLE"
                    else:
                        info["actionable"] = False
                        info["reason"] = "REFLINK_OWNERSHIP_UNPRESERVABLE"

            snapshot[source_path] = info

    return snapshot


def storage_action_snapshot_digest(
    snapshot: dict[str, dict[str, Any]],
) -> str:
    canonical = {
        path: {
            key: value
            for key, value in sorted(info.items())
            if key != "capability"
        }
        for path, info in sorted(snapshot.items())
    }
    payload = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def actionable_storage_paths(
    snapshot: dict[str, dict[str, Any]],
) -> frozenset[str]:
    return frozenset(
        path for path, info in snapshot.items() if info.get("actionable") is True
    )


def storage_action_reclaim_bytes(
    snapshot: dict[str, dict[str, Any]],
) -> int:
    return sum(
        int(info.get("expected_size") or 0)
        for info in snapshot.values()
        if info.get("actionable") is True
    )


def storage_action_released_bytes_by_scan_root(
    snapshot: dict[str, dict[str, Any]],
    scan_root_count: int,
) -> dict[str, int]:
    totals = {str(index): 0 for index in range(max(0, int(scan_root_count)))}
    for info in snapshot.values():
        if info.get("actionable") is not True:
            continue
        raw_index = info.get("scan_root_index")
        if not isinstance(raw_index, int) or isinstance(raw_index, bool):
            continue
        key = str(raw_index)
        if key not in totals:
            continue
        totals[key] += int(info.get("expected_size") or 0)
    return totals
