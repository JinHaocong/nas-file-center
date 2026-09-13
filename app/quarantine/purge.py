from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import text

from app.exceptions import StateConflictError
from app.models import QuarantineEntry
from app.quarantine.bulk import (
    _expected_historical_candidate_path,
    _matches_persisted_identity,
    _same_persisted_payload_identity,
    build_purge_topology_manifest as _build_preview_purge_topology_manifest,
)
from app.quarantine.tx_allocator import allocate_and_create_attempt_dir
from app.tasks.recovery import assert_active_worker_lease, renew_and_assert_worker_lease


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


def _begin_transactional_purge_intent(
    session_factory: Any,
    entry_id: int,
    worker_id: str,
) -> None:
    """Commit Gate6-A irreversible purge intent before any filesystem capture syscall."""
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            session.rollback()
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        if entry.state != "active" or entry.tx_phase != "active":
            state = entry.state
            tx_phase = entry.tx_phase
            session.rollback()
            raise StateConflictError(
                f"Quarantine entry #{entry_id} must still be active before purge "
                f"(state={state}, tx_phase={tx_phase})"
            )
        entry.state = "purging"
        entry.tx_phase = "purging"
        session.commit()


def _allocate_transactional_purge_attempt(
    session_factory: Any,
    entry_id: int,
    worker_id: str,
    quarantine_root: Path | str,
) -> tuple[int, Path, Path]:
    """Allocate a new monotonic exclusive attempt and its write-once purge namespace."""
    generation, attempt_dir = allocate_and_create_attempt_dir(
        session_factory,
        entry_id,
        worker_id,
        quarantine_root=quarantine_root,
    )
    purge_dir = attempt_dir / "purge"
    renew_and_assert_worker_lease(session_factory, worker_id)
    os.mkdir(purge_dir, mode=0o700)
    return generation, attempt_dir, purge_dir


def execute_transactional_purge_capture(
    session_factory: Any,
    entry_id: int,
    worker_id: str | None,
    frozen_manifest: dict[str, Any],
    quarantine_root: Path | str,
    allowed_roots: list[Path | str],
) -> None:
    """Worker-only Gate6-A purge capture entrypoint. Capture semantics are added incrementally by TDD."""
    if not worker_id or not str(worker_id).strip():
        raise PermissionError("Transactional purge capture requires valid worker authority")

    raise NotImplementedError("Gate6-A transactional purge capture is not implemented yet")
