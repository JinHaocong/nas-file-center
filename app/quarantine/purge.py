from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.quarantine.bulk import (
    _expected_historical_candidate_path,
    _matches_persisted_identity,
    _same_persisted_payload_identity,
    build_purge_topology_manifest as _build_preview_purge_topology_manifest,
)


def build_purge_topology_manifest(
    entry: Any,
    quarantine_root: Path | str,
    *,
    owner_lookup: Callable[[int], Any | None] | None = None,
) -> dict[str, Any]:
    """Build the read-only Gate6-A transactional purge topology manifest."""
    return _build_preview_purge_topology_manifest(
        entry,
        quarantine_root,
        owner_lookup=owner_lookup,
    )


def validate_purge_topology_manifest(
    frozen_manifest: dict[str, Any],
    current_manifest: dict[str, Any],
) -> str | None:
    """Return the fail-closed reason for current topology, or None when unchanged."""
    blockers = list(current_manifest.get("blockers") or [])
    if blockers:
        return str(blockers[0])
    if current_manifest != frozen_manifest:
        return "PURGE_TOPOLOGY_CHANGED"
    return None


def classify_cross_entry_alias_owner(
    selected_entry: Any,
    owner: Any | None,
    candidate_path: Path | str,
    tx_root: Path | str,
) -> tuple[str | None, str | None]:
    """Classify one same-payload cross-entry private alias without mutating state."""
    candidate = Path(candidate_path)
    tx_root_path = Path(tx_root)

    if owner is None:
        return None, "UNKNOWN_PAYLOAD_OWNER"

    if owner.state == "active":
        return None, "SHARED_ACTIVE_PAYLOAD"
    if owner.state == "restoring":
        return None, "SHARED_RESTORING_PAYLOAD"
    if owner.state == "restored":
        return None, "SHARED_RESTORED_PAYLOAD"

    if (
        owner.state == "conflict"
        and owner.tx_phase == "conflict"
        and owner.authoritative_anchor_path is None
    ):
        expected_candidate = _expected_historical_candidate_path(owner, tx_root_path)
        if expected_candidate is None or candidate != expected_candidate:
            return None, "HISTORICAL_CONFLICT_PATH_MISMATCH"
        if not _same_persisted_payload_identity(owner, selected_entry):
            return None, "HISTORICAL_CONFLICT_IDENTITY_MISMATCH"
        if not _matches_persisted_identity(candidate, selected_entry):
            return None, "HISTORICAL_CONFLICT_IDENTITY_MISMATCH"
        return "historical_conflict_candidate", None

    return None, "UNKNOWN_PAYLOAD_OWNER_STATE"
