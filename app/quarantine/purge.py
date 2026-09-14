from __future__ import annotations

import hashlib
import json
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
    include_payload_identity: bool = False,
) -> dict[str, Any]:
    """Build the read-only Gate6-A transactional purge topology manifest."""
    manifest = _build_preview_purge_topology_manifest(
        entry,
        quarantine_root,
        owner_lookup=owner_lookup,
    )
    if include_payload_identity:
        manifest["frozen_payload_identity"] = {
            "device": entry.device,
            "inode": entry.inode,
            "size": entry.size,
            "mtime_ns": entry.mtime_ns,
            "content_hash": str(entry.content_hash or "").lower(),
        }
    return manifest

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


def _require_frozen_payload_identity(
    frozen_manifest: dict[str, Any],
) -> tuple[int, int, int, int, str]:
    raw = frozen_manifest.get("frozen_payload_identity")
    if not isinstance(raw, dict):
        raise StateConflictError("PURGE_FROZEN_IDENTITY_MISSING: frozen payload identity is required")
    required = ("device", "inode", "size", "mtime_ns", "content_hash")
    if any(raw.get(key) is None for key in required):
        raise StateConflictError("PURGE_FROZEN_IDENTITY_MISSING: frozen payload identity is incomplete")
    try:
        device = int(raw["device"])
        inode = int(raw["inode"])
        size = int(raw["size"])
        mtime_ns = int(raw["mtime_ns"])
    except (TypeError, ValueError) as exc:
        raise StateConflictError("PURGE_FROZEN_IDENTITY_MISSING: frozen payload identity is invalid") from exc
    content_hash = str(raw.get("content_hash") or "").lower()
    if not content_hash:
        raise StateConflictError("PURGE_FROZEN_IDENTITY_MISSING: frozen payload hash is required")
    return device, inode, size, mtime_ns, content_hash

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


def _intent_time_purge_ownership_reason(
    session: Any,
    entry: QuarantineEntry,
    frozen_manifest: dict[str, Any],
    quarantine_root: Path,
) -> str | None:
    """Revalidate DB ownership authority inside the purge-intent write transaction.

    This helper is intentionally filesystem-free.  Filesystem topology is observed
    before BEGIN IMMEDIATE; this second fence binds the mutable DB ownership facts
    to the same transaction that changes the selected row from active to purging.
    """
    tx_root = quarantine_root / ".tx"
    frozen_historical: dict[int, Path] = {}
    for alias in list(frozen_manifest.get("aliases") or []):
        if alias.get("role") != "historical_conflict_candidate":
            continue
        try:
            owner_id = int(alias.get("owner_entry_id"))
        except (TypeError, ValueError):
            return "UNKNOWN_PAYLOAD_OWNER"
        if owner_id <= 0:
            return "UNKNOWN_PAYLOAD_OWNER"
        frozen_historical[owner_id] = Path(str(alias.get("path") or ""))

    # Every historical owner that was explicitly frozen must still be exactly the
    # same non-authoritative conflict lineage when irreversible intent is committed.
    for owner_id, frozen_path in frozen_historical.items():
        owner = session.get(QuarantineEntry, owner_id)
        if owner is None:
            return "UNKNOWN_PAYLOAD_OWNER"
        if owner.state == "active":
            return "SHARED_ACTIVE_PAYLOAD"
        if owner.state == "restoring":
            return "SHARED_RESTORING_PAYLOAD"
        if owner.state == "restored":
            return "SHARED_RESTORED_PAYLOAD"
        if not (
            owner.state == "conflict"
            and owner.tx_phase == "conflict"
            and owner.authoritative_anchor_path is None
        ):
            return "UNKNOWN_PAYLOAD_OWNER_STATE"
        if not _same_persisted_payload_identity(owner, entry):
            return "HISTORICAL_CONFLICT_IDENTITY_MISMATCH"
        expected_candidate = _expected_historical_candidate_path(owner, tx_root)
        if expected_candidate is None or expected_candidate != frozen_path:
            return "HISTORICAL_CONFLICT_PATH_MISMATCH"

    # A new DB owner can be created after the read-only filesystem topology pass.
    # Bind active/restoring/restored ownership and newly-created historical lineage
    # before the selected row is allowed to enter purging.  Terminal purged rows
    # carry stale identity metadata but no live authority, so they are ignored here.
    other_entries = session.query(QuarantineEntry).filter(QuarantineEntry.id != entry.id).all()
    for owner in other_entries:
        if owner.id in frozen_historical:
            continue
        if not _same_persisted_payload_identity(owner, entry):
            continue
        if owner.state == "active":
            return "SHARED_ACTIVE_PAYLOAD"
        if owner.state == "restoring":
            return "SHARED_RESTORING_PAYLOAD"
        if owner.state == "restored":
            return "SHARED_RESTORED_PAYLOAD"
        if (
            owner.state == "conflict"
            and owner.tx_phase == "conflict"
            and owner.authoritative_anchor_path is None
        ):
            return "PURGE_TOPOLOGY_CHANGED"

    return None


def _begin_transactional_purge_intent(
    session_factory: Any,
    entry_id: int,
    worker_id: str,
    frozen_manifest: dict[str, Any] | None = None,
    quarantine_root: Path | str | None = None,
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
        if frozen_manifest is None:
            session.rollback()
            raise StateConflictError("PURGE_FROZEN_IDENTITY_MISSING: frozen purge authority is required")
        expected_identity = _require_frozen_payload_identity(frozen_manifest)
        current_identity = (
            int(entry.device or 0),
            int(entry.inode or 0),
            int(entry.size or 0),
            int(entry.mtime_ns or 0),
            str(entry.content_hash or "").lower(),
        )
        if current_identity != expected_identity:
            session.rollback()
            raise StateConflictError(
                f"PURGE_FROZEN_IDENTITY_CHANGED: quarantine entry #{entry_id} identity changed after Freeze"
            )
        if quarantine_root is not None:
            ownership_reason = _intent_time_purge_ownership_reason(
                session,
                entry,
                frozen_manifest,
                Path(quarantine_root),
            )
            if ownership_reason is not None:
                session.rollback()
                raise StateConflictError(
                    f"{ownership_reason}: purge ownership changed before irreversible intent "
                    f"for quarantine entry #{entry_id}"
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


_PURGE_DESTROY_MARKER = "destroy-intent.json"


def _manifest_sha256(frozen_manifest: dict[str, Any]) -> str:
    payload = json.dumps(
        frozen_manifest,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _destroy_marker_material(
    *,
    entry_id: int,
    generation: int,
    expected_device: int | None,
    expected_inode: int | None,
    expected_size: int | None,
    expected_mtime_ns: int | None,
    expected_hash: str,
    frozen_manifest: dict[str, Any],
) -> dict[str, Any]:
    aliases = list(frozen_manifest.get("aliases") or [])
    return {
        "schema_version": 1,
        "entry_id": entry_id,
        "generation": generation,
        "device": expected_device,
        "inode": expected_inode,
        "original_size": expected_size,
        "mtime_ns": expected_mtime_ns,
        "content_hash": expected_hash.lower(),
        "manifest_sha256": _manifest_sha256(frozen_manifest),
        "slots": sorted(_purge_slot_name(alias) for alias in aliases),
    }


def _assert_no_unknown_purge_slots(
    purge_dir: Path,
    valid_roots: list[Path],
    aliases: list[dict[str, Any]],
) -> None:
    """Fail closed if the exclusive purge namespace contains an unbound object."""
    known_names = {_purge_slot_name(alias) for alias in aliases}
    known_names.add(_PURGE_DESTROY_MARKER)
    try:
        with safe_open_parent_fd(purge_dir, valid_roots) as (parent_fd, leaf):
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            dir_fd = os.open(leaf, flags, dir_fd=parent_fd)
            try:
                actual_names = set(os.listdir(dir_fd))
            finally:
                os.close(dir_fd)
    except OSError as exc:
        raise StateConflictError(
            f"PURGE_QUALIFICATION_FAILED: cannot inspect purge namespace {purge_dir}: {exc}"
        ) from exc

    unknown_names = sorted(actual_names - known_names)
    if unknown_names:
        raise StateConflictError(
            f"UNKNOWN_PURGE_SLOT: unrecognized object in purge namespace: {unknown_names[0]}"
        )


def _read_destroy_marker(
    purge_dir: Path,
    valid_roots: list[Path],
    expected: dict[str, Any],
) -> bool:
    marker_path = purge_dir / _PURGE_DESTROY_MARKER
    if not os.path.lexists(marker_path):
        return False
    try:
        with safe_open_parent_fd(marker_path, valid_roots) as (dir_fd, leaf):
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(leaf, flags, dir_fd=dir_fd)
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_size <= 0 or st.st_size > 65536:
                    raise StateConflictError("PURGE_RECOVERY_REQUIRED: invalid destroy-intent marker type/size")
                chunks: list[bytes] = []
                remaining = st.st_size
                while remaining > 0:
                    chunk = os.read(fd, min(remaining, 65536))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
            finally:
                os.close(fd)
        actual = json.loads(b"".join(chunks).decode("utf-8"))
    except StateConflictError:
        raise
    except Exception as exc:
        raise StateConflictError(f"PURGE_RECOVERY_REQUIRED: invalid destroy-intent marker: {exc}") from exc
    if actual != expected:
        raise StateConflictError("PURGE_RECOVERY_REQUIRED: destroy-intent marker identity mismatch")
    return True


def _ensure_destroy_marker(
    session_factory: Any,
    worker_id: str,
    purge_dir: Path,
    valid_roots: list[Path],
    expected: dict[str, Any],
) -> None:
    marker_path = purge_dir / _PURGE_DESTROY_MARKER
    payload = json.dumps(
        expected,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    renew_and_assert_worker_lease(session_factory, worker_id)
    try:
        with safe_open_parent_fd(marker_path, valid_roots) as (dir_fd, leaf):
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(leaf, flags, 0o600, dir_fd=dir_fd)
            except FileExistsError:
                fd = None
            if fd is not None:
                try:
                    offset = 0
                    while offset < len(payload):
                        offset += os.write(fd, payload[offset:])
                    os.fsync(fd)
                finally:
                    os.close(fd)
            os.fsync(dir_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise StateConflictError(f"PURGE_RECOVERY_REQUIRED: cannot persist destroy-intent marker: {exc}") from exc
    if not _read_destroy_marker(purge_dir, valid_roots, expected):
        raise StateConflictError("PURGE_RECOVERY_REQUIRED: destroy-intent marker missing after creation")


def _qualify_original_payload_fd(
    fd: int,
    *,
    expected_device: int | None,
    expected_inode: int | None,
    expected_size: int | None,
    expected_mtime_ns: int | None,
    expected_hash: str,
    failure_prefix: str,
) -> os.stat_result:
    st = os.fstat(fd)
    if not (
        stat.S_ISREG(st.st_mode)
        and st.st_dev == expected_device
        and st.st_ino == expected_inode
        and st.st_size == expected_size
        and st.st_mtime_ns == expected_mtime_ns
    ):
        raise StateConflictError(f"{failure_prefix}: payload identity mismatch")
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(fd, 1024 * 1024):
        digest.update(chunk)
    if digest.hexdigest().lower() != expected_hash.lower():
        raise StateConflictError(f"{failure_prefix}: payload hash mismatch")
    return st


def _assert_zeroized_closure(
    purge_dir: Path,
    valid_roots: list[Path],
    aliases: list[dict[str, Any]],
    *,
    expected_device: int | None,
    expected_inode: int | None,
) -> None:
    _assert_no_unknown_purge_slots(purge_dir, valid_roots, aliases)

    for alias in aliases:
        captured_path = purge_dir / _purge_slot_name(alias)
        if not os.path.lexists(captured_path):
            raise StateConflictError(
                f"PURGE_RECOVERY_REQUIRED: expected private tombstone is missing: {captured_path}"
            )
        try:
            with safe_open_parent_fd(captured_path, valid_roots) as (dir_fd, leaf):
                fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
                try:
                    st = os.fstat(fd)
                finally:
                    os.close(fd)
        except OSError as exc:
            raise StateConflictError(
                f"PURGE_DESTRUCTION_FAILED: cannot inspect private tombstone {captured_path}: {exc}"
            ) from exc
        if not (
            stat.S_ISREG(st.st_mode)
            and st.st_dev == expected_device
            and st.st_ino == expected_inode
            and st.st_size == 0
        ):
            raise StateConflictError(
                f"PURGE_DESTRUCTION_FAILED: private tombstone identity mismatch: {captured_path}"
            )

    for alias in aliases:
        source_path = Path(str(alias.get("path") or ""))
        if not os.path.lexists(source_path):
            continue
        try:
            with safe_open_parent_fd(source_path, valid_roots) as (dir_fd, leaf):
                fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
                try:
                    st = os.fstat(fd)
                finally:
                    os.close(fd)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise StateConflictError(
                f"PURGE_DESTRUCTION_FAILED: cannot inspect frozen source tombstone {source_path}: {exc}"
            ) from exc
        if not (
            stat.S_ISREG(st.st_mode)
            and st.st_dev == expected_device
            and st.st_ino == expected_inode
            and st.st_size == 0
        ):
            raise StateConflictError(
                f"PURGE_DESTRUCTION_FAILED: foreign object remains at frozen source: {source_path}"
            )


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


def _execute_time_purge_ownership_reason(
    session: Any,
    entry: QuarantineEntry,
    frozen_manifest: dict[str, Any],
    quarantine_root: Path,
) -> str | None:
    """Revalidate ownership authority without defeating frozen capture-before-qualification semantics."""
    current_manifest = build_purge_topology_manifest(
        entry,
        quarantine_root,
        owner_lookup=lambda owner_id: session.get(QuarantineEntry, owner_id),
    )

    # Frozen §6.3 intentionally permits a known source pathname to be replaced
    # after classification: Capture retires that object first, then private-slot
    # qualification preserves it and fails closed. Do not turn that allowed race
    # into an execute-time rejection. All other current blockers remain fatal.
    current_blockers = [
        str(reason)
        for reason in list(current_manifest.get("blockers") or [])
        if not str(reason).startswith("IDENTITY_MISMATCH:")
    ]
    if current_blockers:
        return current_blockers[0]

    frozen_historical = {
        int(owner_id) for owner_id in list(frozen_manifest.get("historical_conflict_entry_ids") or [])
    }
    current_historical = {
        int(owner_id) for owner_id in list(current_manifest.get("historical_conflict_entry_ids") or [])
    }
    if current_historical - frozen_historical:
        return "PURGE_TOPOLOGY_CHANGED"

    tx_root = quarantine_root / ".tx"
    for alias in list(frozen_manifest.get("aliases") or []):
        if alias.get("role") != "historical_conflict_candidate":
            continue
        try:
            owner_id = int(alias.get("owner_entry_id"))
        except (TypeError, ValueError):
            return "UNKNOWN_PAYLOAD_OWNER"
        owner = session.get(QuarantineEntry, owner_id)
        if owner is None:
            return "UNKNOWN_PAYLOAD_OWNER"
        if owner.state == "active":
            return "SHARED_ACTIVE_PAYLOAD"
        if owner.state == "restoring":
            return "SHARED_RESTORING_PAYLOAD"
        if owner.state == "restored":
            return "SHARED_RESTORED_PAYLOAD"
        if not (
            owner.state == "conflict"
            and owner.tx_phase == "conflict"
            and owner.authoritative_anchor_path is None
        ):
            return "UNKNOWN_PAYLOAD_OWNER_STATE"
        if not _same_persisted_payload_identity(owner, entry):
            return "HISTORICAL_CONFLICT_IDENTITY_MISMATCH"
        expected_candidate = _expected_historical_candidate_path(owner, tx_root)
        if expected_candidate is None or Path(str(alias.get("path") or "")) != expected_candidate:
            return "HISTORICAL_CONFLICT_PATH_MISMATCH"

    return None


def execute_transactional_purge_capture(
    session_factory: Any,
    entry_id: int,
    worker_id: str | None,
    frozen_manifest: dict[str, Any],
    quarantine_root: Path | str,
    allowed_roots: list[Path | str],
) -> None:
    """Capture every frozen alias into an atomic no-overwrite private hard-link witness."""
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
        if current_state == "active" and current_tx_phase == "active":
            topology_reason = _execute_time_purge_ownership_reason(
                session,
                entry,
                frozen_manifest,
                q_root,
            )
            if topology_reason is not None:
                raise StateConflictError(
                    f"{topology_reason}: purge ownership changed before Execute for quarantine entry #{entry_id}"
                )

    purge_dir: Path | None = None
    if current_state == "active" and current_tx_phase == "active":
        _begin_transactional_purge_intent(
            session_factory,
            entry_id,
            worker,
            frozen_manifest,
            q_root,
        )
    elif current_state == "purging" and current_tx_phase == "purging":
        frozen_generation = _frozen_selected_attempt_generation(frozen_manifest, entry_id)
        if current_generation < frozen_generation:
            raise StateConflictError(
                "PURGE_RECOVERY_REQUIRED: purge capture generation regressed "
                f"(frozen={frozen_generation}, current={current_generation})"
            )
        if current_generation > frozen_generation:
            current_attempt_dir = (
                q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{current_generation}"
            )
            if os.path.lexists(current_attempt_dir):
                if current_attempt_dir.is_symlink() or not current_attempt_dir.is_dir():
                    raise StateConflictError(
                        "PURGE_RECOVERY_REQUIRED: current purge attempt is not a safe directory "
                        f"(generation={current_generation})"
                    )
                current_purge_dir = current_attempt_dir / "purge"
                if os.path.lexists(current_purge_dir):
                    if current_purge_dir.is_symlink() or not current_purge_dir.is_dir():
                        raise StateConflictError(
                            "PURGE_RECOVERY_REQUIRED: current purge namespace is not a safe directory "
                            f"(generation={current_generation})"
                        )
                    purge_dir = current_purge_dir
                else:
                    try:
                        attempt_children = list(current_attempt_dir.iterdir())
                    except OSError as exc:
                        raise StateConflictError(
                            "PURGE_RECOVERY_REQUIRED: cannot classify current purge attempt "
                            f"(generation={current_generation}): {exc}"
                        ) from exc
                    if attempt_children:
                        raise StateConflictError(
                            "PURGE_RECOVERY_REQUIRED: current purge attempt contains unexpected evidence "
                            f"(generation={current_generation})"
                        )
                    renew_and_assert_worker_lease(session_factory, worker)
                    try:
                        os.mkdir(current_purge_dir, mode=0o700)
                    except FileExistsError as exc:
                        raise StateConflictError(
                            "PURGE_RECOVERY_REQUIRED: purge namespace appeared during recovery "
                            f"(generation={current_generation})"
                        ) from exc
                    purge_dir = current_purge_dir
            # If the current attempt directory is absent, the generation was only
            # durably allocated. Allocate a fresh monotonic generation below. This
            # remains valid even after multiple consecutive allocation-only crashes.
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
    for alias in aliases:
        source_path = Path(str(alias.get("path") or ""))
        target_path = purge_dir / _purge_slot_name(alias)

        # Existing write-once slots are recovery evidence. Never mutate or replace
        # them here; qualification decides whether they are expected or foreign.
        if os.path.lexists(target_path):
            continue
        if not os.path.lexists(source_path):
            raise StateConflictError(
                f"PURGE_RECOVERY_REQUIRED: purge source and captured slot are both missing: {source_path}"
            )

        try:
            with safe_open_parent_fd(source_path, valid_roots) as (src_dir_fd, src_leaf):
                with safe_open_parent_fd(target_path, valid_roots) as (dst_dir_fd, dst_leaf):
                    renew_and_assert_worker_lease(session_factory, worker)
                    os.link(
                        src_leaf,
                        dst_leaf,
                        src_dir_fd=src_dir_fd,
                        dst_dir_fd=dst_dir_fd,
                        follow_symlinks=False,
                    )
        except FileExistsError as exc:
            raise StateConflictError(f"Purge capture slot is occupied: {target_path}") from exc
        except OSError as exc:
            raise StateConflictError(
                f"PURGE_CAPTURE_FAILED: cannot atomically capture {source_path} into {target_path}: {exc}"
            ) from exc


def qualify_transactional_purge_capture(
    session_factory: Any,
    entry_id: int,
    worker_id: str | None,
    frozen_manifest: dict[str, Any],
    quarantine_root: Path | str,
    allowed_roots: list[Path | str],
) -> list[Path]:
    """Fully qualify all private hard-link witnesses before irreversible zeroization."""
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

    expected_device, expected_inode, expected_size, expected_mtime_ns, expected_hash = (
        _require_frozen_payload_identity(frozen_manifest)
    )
    if generation <= 0:
        raise StateConflictError("PURGE_QUALIFICATION_FAILED: missing frozen payload identity")

    q_root = Path(quarantine_root)
    valid_roots = [Path(root) for root in allowed_roots]
    if q_root not in valid_roots:
        valid_roots.append(q_root)
    aliases = list(frozen_manifest.get("aliases") or [])
    purge_dir = q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{generation}" / "purge"
    _assert_no_unknown_purge_slots(purge_dir, valid_roots, aliases)

    # Existing source aliases are allowed because capture is a hard-link witness,
    # not a pathname retirement. Any foreign replacement blocks before ftruncate.
    for alias in aliases:
        source_path = Path(str(alias.get("path") or ""))
        if not os.path.lexists(source_path):
            continue
        try:
            with safe_open_parent_fd(source_path, valid_roots) as (dir_fd, leaf):
                fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
                try:
                    _qualify_original_payload_fd(
                        fd,
                        expected_device=expected_device,
                        expected_inode=expected_inode,
                        expected_size=expected_size,
                        expected_mtime_ns=expected_mtime_ns,
                        expected_hash=expected_hash,
                        failure_prefix=f"PURGE_QUALIFICATION_FAILED: frozen source {source_path}",
                    )
                finally:
                    os.close(fd)
        except StateConflictError:
            raise
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise StateConflictError(
                f"PURGE_QUALIFICATION_FAILED: cannot qualify frozen source {source_path}: {exc}"
            ) from exc

    qualified: list[Path] = []
    for alias in aliases:
        captured_path = purge_dir / _purge_slot_name(alias)
        if not os.path.lexists(captured_path):
            raise StateConflictError(
                f"PURGE_RECOVERY_REQUIRED: expected private capture is missing: {captured_path}"
            )
        try:
            with safe_open_parent_fd(captured_path, valid_roots) as (dir_fd, leaf):
                fd = os.open(leaf, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=dir_fd)
                try:
                    _qualify_original_payload_fd(
                        fd,
                        expected_device=expected_device,
                        expected_inode=expected_inode,
                        expected_size=expected_size,
                        expected_mtime_ns=expected_mtime_ns,
                        expected_hash=expected_hash,
                        failure_prefix=f"PURGE_QUALIFICATION_FAILED: captured slot {captured_path}",
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

    if not qualified:
        raise StateConflictError("PURGE_RECOVERY_REQUIRED: no qualified private capture exists")
    return qualified


def _destroy_one_qualified_purge_slot(
    session_factory: Any,
    worker_id: str,
    captured_path: Path,
    valid_roots: list[Path],
    *,
    expected_device: int | None,
    expected_inode: int | None,
    expected_size: int | None,
    expected_mtime_ns: int | None,
    expected_hash: str,
) -> None:
    """Re-qualify one descriptor and irreversibly zeroize that exact inode."""
    try:
        with safe_open_parent_fd(captured_path, valid_roots) as (dir_fd, leaf):
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(leaf, flags, dir_fd=dir_fd)
            try:
                st = _qualify_original_payload_fd(
                    fd,
                    expected_device=expected_device,
                    expected_inode=expected_inode,
                    expected_size=expected_size,
                    expected_mtime_ns=expected_mtime_ns,
                    expected_hash=expected_hash,
                    failure_prefix=f"PURGE_DESTRUCTION_FAILED: captured slot {captured_path}",
                )
                renew_and_assert_worker_lease(session_factory, worker_id)
                os.ftruncate(fd, 0)
                os.fsync(fd)
                after = os.fstat(fd)
                if not (
                    stat.S_ISREG(after.st_mode)
                    and after.st_dev == st.st_dev
                    and after.st_ino == st.st_ino
                    and after.st_size == 0
                ):
                    raise StateConflictError(
                        f"PURGE_DESTRUCTION_FAILED: descriptor zeroization did not close payload: {captured_path}"
                    )
            finally:
                os.close(fd)
    except StateConflictError:
        raise
    except OSError as exc:
        raise StateConflictError(
            f"PURGE_DESTRUCTION_FAILED: cannot safely zeroize captured slot {captured_path}: {exc}"
        ) from exc



def _fsync_zeroized_purge_tombstone(
    session_factory: Any,
    worker_id: str,
    captured_path: Path,
    valid_roots: list[Path],
    *,
    expected_device: int,
    expected_inode: int,
) -> None:
    """Prove durability of an already-zeroized exact payload inode without re-truncating it."""
    try:
        with safe_open_parent_fd(captured_path, valid_roots) as (dir_fd, leaf):
            flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(leaf, flags, dir_fd=dir_fd)
            try:
                before = os.fstat(fd)
                if not (
                    stat.S_ISREG(before.st_mode)
                    and before.st_dev == expected_device
                    and before.st_ino == expected_inode
                    and before.st_size == 0
                ):
                    raise StateConflictError(
                        f"PURGE_DURABILITY_FAILED: zeroized tombstone identity mismatch: {captured_path}"
                    )
                renew_and_assert_worker_lease(session_factory, worker_id)
                os.fsync(fd)
                after = os.fstat(fd)
                if not (
                    stat.S_ISREG(after.st_mode)
                    and after.st_dev == expected_device
                    and after.st_ino == expected_inode
                    and after.st_size == 0
                ):
                    raise StateConflictError(
                        f"PURGE_DURABILITY_FAILED: zeroized tombstone changed during fsync: {captured_path}"
                    )
            finally:
                os.close(fd)
    except StateConflictError:
        raise
    except OSError as exc:
        raise StateConflictError(
            f"PURGE_DURABILITY_FAILED: cannot fsync zeroized tombstone {captured_path}: {exc}"
        ) from exc

def destroy_transactional_purge_capture(
    session_factory: Any,
    entry_id: int,
    worker_id: str | None,
    frozen_manifest: dict[str, Any],
    quarantine_root: Path | str,
    allowed_roots: list[Path | str],
) -> None:
    """Zeroize one fully qualified captured inode, prove tombstone closure, then commit purged."""
    if not worker_id or not str(worker_id).strip():
        raise PermissionError("Transactional purge destruction requires valid worker authority")

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

    expected_device, expected_inode, expected_size, expected_mtime_ns, expected_hash = (
        _require_frozen_payload_identity(frozen_manifest)
    )
    if generation <= 0:
        raise StateConflictError("PURGE_DESTRUCTION_FAILED: missing frozen payload identity")

    q_root = Path(quarantine_root)
    valid_roots = [Path(root) for root in allowed_roots]
    if q_root not in valid_roots:
        valid_roots.append(q_root)
    aliases = list(frozen_manifest.get("aliases") or [])
    purge_dir = q_root / ".tx" / f"entry-{entry_id}" / f"attempt-{generation}" / "purge"
    marker_expected = _destroy_marker_material(
        entry_id=entry_id,
        generation=generation,
        expected_device=expected_device,
        expected_inode=expected_inode,
        expected_size=expected_size,
        expected_mtime_ns=expected_mtime_ns,
        expected_hash=expected_hash,
        frozen_manifest=frozen_manifest,
    )

    marker_exists = _read_destroy_marker(purge_dir, valid_roots, marker_expected)
    if marker_exists:
        try:
            _assert_zeroized_closure(
                purge_dir,
                valid_roots,
                aliases,
                expected_device=expected_device,
                expected_inode=expected_inode,
            )
        except StateConflictError:
            # Marker can validly precede the one destructive syscall. In that
            # state every capture must still fully qualify at original identity.
            qualified = qualify_transactional_purge_capture(
                session_factory,
                entry_id,
                worker,
                frozen_manifest,
                quarantine_root,
                allowed_roots,
            )
        else:
            qualified = []
    else:
        qualified = qualify_transactional_purge_capture(
            session_factory,
            entry_id,
            worker,
            frozen_manifest,
            quarantine_root,
            allowed_roots,
        )

    if qualified:
        _ensure_destroy_marker(
            session_factory,
            worker,
            purge_dir,
            valid_roots,
            marker_expected,
        )
        _destroy_one_qualified_purge_slot(
            session_factory,
            worker,
            qualified[0],
            valid_roots,
            expected_device=expected_device,
            expected_inode=expected_inode,
            expected_size=expected_size,
            expected_mtime_ns=expected_mtime_ns,
            expected_hash=expected_hash,
        )
        _assert_zeroized_closure(
            purge_dir,
            valid_roots,
            aliases,
            expected_device=expected_device,
            expected_inode=expected_inode,
        )

    if not _read_destroy_marker(purge_dir, valid_roots, marker_expected):
        raise StateConflictError("PURGE_RECOVERY_REQUIRED: valid destroy-intent marker is required")
    _assert_zeroized_closure(
        purge_dir,
        valid_roots,
        aliases,
        expected_device=expected_device,
        expected_inode=expected_inode,
    )
    if not aliases:
        raise StateConflictError(
            "PURGE_RECOVERY_REQUIRED: frozen purge aliases are required for durability proof"
        )
    durability_path = purge_dir / _purge_slot_name(aliases[0])
    _fsync_zeroized_purge_tombstone(
        session_factory,
        worker,
        durability_path,
        valid_roots,
        expected_device=expected_device,
        expected_inode=expected_inode,
    )
    _assert_zeroized_closure(
        purge_dir,
        valid_roots,
        aliases,
        expected_device=expected_device,
        expected_inode=expected_inode,
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
        current_identity = (
            int(entry.device or 0),
            int(entry.inode or 0),
            int(entry.size or 0),
            int(entry.mtime_ns or 0),
            str(entry.content_hash or "").lower(),
        )
        if current_identity != (
            expected_device,
            expected_inode,
            expected_size,
            expected_mtime_ns,
            expected_hash,
        ):
            session.rollback()
            raise StateConflictError(
                f"PURGE_FROZEN_IDENTITY_CHANGED: quarantine entry #{entry_id} identity changed before terminal purge commit"
            )
        entry.state = "purged"
        entry.tx_phase = "purged"
        entry.purged_at = utcnow()
        session.commit()
