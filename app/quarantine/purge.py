from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
from typing import Any, Callable

from sqlalchemy import text

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.exceptions import StateConflictError
from app.models import QuarantineEntry, utcnow
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


def _purge_slot_name(alias: dict[str, Any]) -> str:
    role = str(alias.get("role") or "")
    slot_by_role = {
        "authoritative_anchor": "current-anchor",
        "captured_source": "captured-source",
        "public_view": "public-view",
    }
    if role == "historical_conflict_candidate":
        try:
            owner_entry_id = int(alias.get("owner_entry_id"))
        except (TypeError, ValueError):
            raise StateConflictError("Historical purge alias is missing a valid owner entry id")
        if owner_entry_id <= 0:
            raise StateConflictError("Historical purge alias is missing a valid owner entry id")
        return f"linked-conflict-{owner_entry_id}-anchor"
    if role in slot_by_role:
        return slot_by_role[role]
    raise StateConflictError(f"Unsupported purge capture alias role: {role}")


def _frozen_selected_attempt_generation(
    frozen_manifest: dict[str, Any],
    entry_id: int,
) -> int:
    """Return the selected authoritative anchor generation bound by the frozen manifest."""
    for alias in list(frozen_manifest.get("aliases") or []):
        if alias.get("role") != "authoritative_anchor":
            continue
        try:
            owner_entry_id = int(alias.get("owner_entry_id"))
        except (TypeError, ValueError):
            continue
        if owner_entry_id != entry_id:
            continue
        anchor_path = Path(str(alias.get("path") or ""))
        attempt_name = anchor_path.parent.name
        if anchor_path.name != "anchor" or not attempt_name.startswith("attempt-"):
            break
        try:
            generation = int(attempt_name.removeprefix("attempt-"))
        except ValueError:
            break
        if generation > 0:
            return generation
        break
    raise StateConflictError("PURGE_RECOVERY_REQUIRED: frozen authoritative attempt generation is invalid")


def execute_transactional_purge_capture(
    session_factory: Any,
    entry_id: int,
    worker_id: str | None,
    frozen_manifest: dict[str, Any],
    quarantine_root: Path | str,
    allowed_roots: list[Path | str],
) -> None:
    """Capture the frozen Gate6-A purge alias set into one exclusive private attempt."""
    if not worker_id or not str(worker_id).strip():
        raise PermissionError("Transactional purge capture requires valid worker authority")

    worker = str(worker_id)
    q_root = Path(quarantine_root)
    valid_roots = [Path(root) for root in allowed_roots]
    if q_root not in valid_roots:
        valid_roots.append(q_root)

    with session_factory() as session:
        assert_active_worker_lease(session, worker)
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        current_state = entry.state
        current_tx_phase = entry.tx_phase
        current_generation = int(entry.active_attempt_generation or 0)

    purge_dir: Path | None = None
    if current_state == "active" and current_tx_phase == "active":
        _begin_transactional_purge_intent(session_factory, entry_id, worker)
    elif current_state == "purging" and current_tx_phase == "purging":
        frozen_generation = _frozen_selected_attempt_generation(frozen_manifest, entry_id)
        if current_generation != frozen_generation:
            current_attempt_dir = (
                q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{current_generation}"
            )
            allocation_only_crash = (
                current_generation == frozen_generation + 1
                and not os.path.lexists(current_attempt_dir)
            )
            resumable_capture = (
                current_generation == frozen_generation + 1
                and current_attempt_dir.is_dir()
                and (current_attempt_dir / "purge").is_dir()
            )
            if resumable_capture:
                purge_dir = current_attempt_dir / "purge"
            elif not allocation_only_crash:
                raise StateConflictError(
                    "PURGE_RECOVERY_REQUIRED: purge capture generation already advanced "
                    f"(frozen={frozen_generation}, current={current_generation})"
                )
    else:
        raise StateConflictError(
            f"Quarantine entry #{entry_id} cannot enter purge capture "
            f"(state={current_state}, tx_phase={current_tx_phase})"
        )

    if purge_dir is None:
        _, _, purge_dir = _allocate_transactional_purge_attempt(
            session_factory,
            entry_id,
            worker,
            q_root,
        )

    aliases = list(frozen_manifest.get("aliases") or [])
    any_source_exists = any(
        os.path.lexists(Path(str(alias.get("path") or "")))
        for alias in aliases
    )
    for alias in aliases:
        source_path = Path(str(alias.get("path") or ""))
        target_path = purge_dir / _purge_slot_name(alias)
        source_exists = os.path.lexists(source_path)
        target_exists = os.path.lexists(target_path)
        if target_exists and not source_exists:
            continue
        if target_exists:
            raise StateConflictError(f"Purge capture slot is occupied: {target_path}")
        if not source_exists:
            if not any_source_exists:
                continue
            raise StateConflictError(
                f"PURGE_RECOVERY_REQUIRED: purge source and captured slot are both missing: {source_path}"
            )
        with safe_open_parent_fd(source_path, valid_roots) as (src_dir_fd, src_leaf):
            with safe_open_parent_fd(target_path, valid_roots) as (dst_dir_fd, dst_leaf):
                try:
                    os.stat(dst_leaf, dir_fd=dst_dir_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise StateConflictError(f"Purge capture slot is occupied: {target_path}")
                renew_and_assert_worker_lease(session_factory, worker)
                os.rename(
                    src_leaf,
                    dst_leaf,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )


def qualify_transactional_purge_capture(
    session_factory: Any,
    entry_id: int,
    worker_id: str | None,
    frozen_manifest: dict[str, Any],
    quarantine_root: Path | str,
    allowed_roots: list[Path | str],
) -> list[Path]:
    """Fully qualify every captured private slot without performing destructive unlink."""
    if not worker_id or not str(worker_id).strip():
        raise PermissionError("Transactional purge qualification requires valid worker authority")

    worker = str(worker_id)
    with session_factory() as session:
        assert_active_worker_lease(session, worker)
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        if entry.state != "purging" or entry.tx_phase != "purging":
            raise StateConflictError(
                f"Quarantine entry #{entry_id} is not in purging state "
                f"(state={entry.state}, tx_phase={entry.tx_phase})"
            )
        generation = int(entry.active_attempt_generation or 0)
        expected_device = entry.device
        expected_inode = entry.inode
        expected_size = entry.size
        expected_mtime_ns = entry.mtime_ns
        expected_hash = (entry.content_hash or "").lower()

    if generation <= 0 or not expected_hash:
        raise StateConflictError("PURGE_QUALIFICATION_FAILED: missing frozen payload identity")

    aliases = list(frozen_manifest.get("aliases") or [])
    for alias in aliases:
        source_path = Path(str(alias.get("path") or ""))
        if os.path.lexists(source_path):
            raise StateConflictError(
                f"PURGE_QUALIFICATION_FAILED: frozen source still exists: {source_path}"
            )

    q_root = Path(quarantine_root)
    valid_roots = [Path(root) for root in allowed_roots]
    if q_root not in valid_roots:
        valid_roots.append(q_root)
    purge_dir = q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{generation}" / "purge"

    qualified: list[Path] = []
    for alias in aliases:
        captured_path = purge_dir / _purge_slot_name(alias)
        if not os.path.lexists(captured_path):
            continue
        try:
            with safe_open_parent_fd(captured_path, valid_roots) as (dir_fd, leaf):
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(leaf, flags, dir_fd=dir_fd)
                try:
                    st = os.fstat(fd)
                    if not (
                        stat.S_ISREG(st.st_mode)
                        and st.st_dev == expected_device
                        and st.st_ino == expected_inode
                        and st.st_size == expected_size
                        and st.st_mtime_ns == expected_mtime_ns
                    ):
                        raise StateConflictError(
                            f"PURGE_QUALIFICATION_FAILED: captured slot identity mismatch: {captured_path}"
                        )
                    digest = hashlib.sha256()
                    while chunk := os.read(fd, 1024 * 1024):
                        digest.update(chunk)
                    if digest.hexdigest().lower() != expected_hash:
                        raise StateConflictError(
                            f"PURGE_QUALIFICATION_FAILED: captured slot hash mismatch: {captured_path}"
                        )
                finally:
                    os.close(fd)
        except StateConflictError:
            raise
        except OSError as exc:
            raise StateConflictError(
                f"PURGE_QUALIFICATION_FAILED: cannot qualify captured slot {captured_path}: {exc}"
            ) from exc
        qualified.append(captured_path)

    return qualified


def destroy_transactional_purge_capture(
    session_factory: Any,
    entry_id: int,
    worker_id: str | None,
    frozen_manifest: dict[str, Any],
    quarantine_root: Path | str,
    allowed_roots: list[Path | str],
) -> None:
    """Destroy only fully qualified captured payload slots, then commit terminal purged state."""
    if not worker_id or not str(worker_id).strip():
        raise PermissionError("Transactional purge destruction requires valid worker authority")

    worker = str(worker_id)
    qualified = qualify_transactional_purge_capture(
        session_factory,
        entry_id,
        worker,
        frozen_manifest,
        quarantine_root,
        allowed_roots,
    )

    with session_factory() as session:
        assert_active_worker_lease(session, worker)
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        if entry.state != "purging" or entry.tx_phase != "purging":
            raise StateConflictError(
                f"Quarantine entry #{entry_id} is not in purging state "
                f"(state={entry.state}, tx_phase={entry.tx_phase})"
            )
        generation = int(entry.active_attempt_generation or 0)

    q_root = Path(quarantine_root)
    valid_roots = [Path(root) for root in allowed_roots]
    if q_root not in valid_roots:
        valid_roots.append(q_root)

    for alias in list(frozen_manifest.get("aliases") or []):
        source_path = Path(str(alias.get("path") or ""))
        if os.path.lexists(source_path):
            raise StateConflictError(
                f"PURGE_DESTRUCTION_FAILED: frozen source reappeared: {source_path}"
            )

    for captured_path in qualified:
        with safe_open_parent_fd(captured_path, valid_roots) as (dir_fd, leaf):
            renew_and_assert_worker_lease(session_factory, worker)
            try:
                os.unlink(leaf, dir_fd=dir_fd)
            except OSError as exc:
                raise StateConflictError(
                    f"PURGE_DESTRUCTION_FAILED: cannot unlink qualified slot {captured_path}: {exc}"
                ) from exc

    # Prove exact source + captured-slot closure before terminal DB state. This is
    # read-only filesystem observation and intentionally occurs outside any SQLite write tx.
    purge_dir = q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{generation}" / "purge"
    for alias in list(frozen_manifest.get("aliases") or []):
        source_path = Path(str(alias.get("path") or ""))
        captured_path = purge_dir / _purge_slot_name(alias)
        if os.path.lexists(source_path):
            raise StateConflictError(
                f"PURGE_DESTRUCTION_FAILED: frozen source still exists: {source_path}"
            )
        if os.path.lexists(captured_path):
            raise StateConflictError(
                f"PURGE_DESTRUCTION_FAILED: captured slot still exists: {captured_path}"
            )

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker)
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            session.rollback()
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        if entry.state != "purging" or entry.tx_phase != "purging":
            state = entry.state
            tx_phase = entry.tx_phase
            session.rollback()
            raise StateConflictError(
                f"Quarantine entry #{entry_id} changed before terminal purge commit "
                f"(state={state}, tx_phase={tx_phase})"
            )
        if int(entry.active_attempt_generation or 0) != generation:
            current_generation = int(entry.active_attempt_generation or 0)
            session.rollback()
            raise StateConflictError(
                f"Quarantine entry #{entry_id} purge generation changed "
                f"(expected={generation}, current={current_generation})"
            )
        entry.state = "purged"
        entry.tx_phase = "purged"
        entry.purged_at = utcnow()
        session.commit()
