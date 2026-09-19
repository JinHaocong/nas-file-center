from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.exceptions import StateConflictError
from app.models import OperationJournal, QuarantineEntry, utcnow
from app.tasks.recovery import assert_active_worker_lease, renew_and_assert_worker_lease


SEMANTICS_VERSION = "unlink_v1"
OPERATION_ID = "quarantine_unlink_purge"
_CANONICAL_ROLES = (
    "authoritative_anchor",
    "captured_source",
    "public_view",
)
_ROLE_SEQUENCE = {
    "authoritative_anchor": 1,
    "captured_source": 2,
    "public_view": 3,
}


def _absolute_lexical(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _identity_item(role: str, path: Path, entry: Any) -> tuple[dict[str, Any] | None, str | None]:
    if path.is_symlink() or os.path.islink(path):
        return None, f"SYMLINK:{role}"

    try:
        st = path.stat(follow_symlinks=False)
    except OSError:
        return None, f"MISSING_OR_UNREADABLE:{role}"

    if not stat.S_ISREG(st.st_mode):
        return None, f"NOT_REGULAR_FILE:{role}"

    if (
        st.st_dev != entry.device
        or st.st_ino != entry.inode
        or st.st_size != entry.size
        or st.st_mtime_ns != entry.mtime_ns
    ):
        return None, f"IDENTITY_MISMATCH:{role}"

    return (
        {
            "role": role,
            "path": str(path),
            "object_type": "regular_file",
            "device": st.st_dev,
            "inode": st.st_ino,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "content_hash": entry.content_hash,
        },
        None,
    )


def build_unlink_manifest(entry: Any, quarantine_root: Path | str) -> dict[str, Any]:
    """Build pathname-scoped unlink authority for one selected quarantine entry.

    This helper is intentionally read-only. It derives authority only from the
    selected entry's current NFC transaction namespace and public quarantine
    path. It never searches by inode and therefore cannot widen authority to a
    same-inode path owned by another entry.
    """
    root = _absolute_lexical(quarantine_root)
    tx_root = root / ".tx"
    generation = int(entry.active_attempt_generation or 0)
    attempt = tx_root / f"entry-{entry.id}" / f"attempt-{generation}"
    expected_anchor = attempt / "anchor"
    captured_source = attempt / "captured_source"
    public_view = _absolute_lexical(entry.quarantine_path)

    blockers: list[str] = []

    def add_blocker(code: str) -> None:
        if code not in blockers:
            blockers.append(code)

    if generation <= 0:
        add_blocker("INVALID_ACTIVE_GENERATION")

    if entry.state != "active" or entry.tx_phase != "active":
        add_blocker("ENTRY_NOT_ACTIVE")

    if root.is_symlink() or tx_root.is_symlink():
        add_blocker("UNSAFE_QUARANTINE_NAMESPACE")

    if not entry.authoritative_anchor_path:
        add_blocker("MISSING_AUTHORITATIVE_ANCHOR")
    elif _absolute_lexical(entry.authoritative_anchor_path) != expected_anchor:
        add_blocker("ANCHOR_PATH_MISMATCH")

    if not _is_within(public_view, root):
        add_blocker("PUBLIC_VIEW_OUTSIDE_QUARANTINE_ROOT")
    elif _is_within(public_view, tx_root):
        add_blocker("PUBLIC_VIEW_INSIDE_PRIVATE_NAMESPACE")

    # Mutation authority is selected-entry pathname scoped. Inspect only the
    # selected entry's current attempt directory so an unknown private object
    # fails closed without scanning sibling entries or widening by inode.
    if attempt.exists() and not attempt.is_symlink():
        try:
            for child in sorted(attempt.iterdir(), key=lambda path: path.name):
                if child.name not in {"anchor", "captured_source"}:
                    add_blocker("UNRECOGNIZED_PRIVATE_PATH")
        except OSError:
            add_blocker("PRIVATE_NAMESPACE_UNREADABLE")

    owned_paths: list[dict[str, Any]] = []
    for role, path in (
        ("authoritative_anchor", expected_anchor),
        ("captured_source", captured_source),
        ("public_view", public_view),
    ):
        item, blocker = _identity_item(role, path, entry)
        if blocker is not None:
            add_blocker(blocker)
            continue
        assert item is not None
        owned_paths.append(item)

    return {
        "purge_semantics": SEMANTICS_VERSION,
        "selected_entry_id": entry.id,
        "active_attempt_generation": generation,
        "owned_paths": owned_paths,
        "blockers": blockers,
    }


def revalidate_unlink_manifest(
    entry: Any,
    quarantine_root: Path | str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Revalidate frozen pathname authority immediately before mutation.

    This function is read-only. It rejects stale transaction identity, malformed
    frozen authority, symlinks, path drift, unknown selected-private objects,
    and ABA replacement before any unlink operation is allowed to begin.
    """
    root = _absolute_lexical(quarantine_root)
    tx_root = root / ".tx"
    generation = int(entry.active_attempt_generation or 0)
    attempt = tx_root / f"entry-{entry.id}" / f"attempt-{generation}"
    expected_paths = {
        "authoritative_anchor": attempt / "anchor",
        "captured_source": attempt / "captured_source",
        "public_view": _absolute_lexical(entry.quarantine_path),
    }
    canonical_roles = tuple(expected_paths)

    blockers: list[str] = []

    def add_blocker(code: str) -> None:
        if code not in blockers:
            blockers.append(code)

    if manifest.get("purge_semantics") != SEMANTICS_VERSION:
        add_blocker("SEMANTICS_MISMATCH")
    if manifest.get("selected_entry_id") != entry.id:
        add_blocker("SELECTED_ENTRY_MISMATCH")
    if manifest.get("active_attempt_generation") != generation:
        add_blocker("GENERATION_MISMATCH")
    if manifest.get("blockers"):
        add_blocker("FROZEN_MANIFEST_BLOCKED")

    if generation <= 0:
        add_blocker("INVALID_ACTIVE_GENERATION")
    if entry.state != "active" or entry.tx_phase != "active":
        add_blocker("ENTRY_NOT_ACTIVE")
    if root.is_symlink() or tx_root.is_symlink() or attempt.is_symlink():
        add_blocker("UNSAFE_QUARANTINE_NAMESPACE")

    expected_anchor = expected_paths["authoritative_anchor"]
    if not entry.authoritative_anchor_path:
        add_blocker("MISSING_AUTHORITATIVE_ANCHOR")
    elif _absolute_lexical(entry.authoritative_anchor_path) != expected_anchor:
        add_blocker("ANCHOR_PATH_MISMATCH")

    public_view = expected_paths["public_view"]
    if not _is_within(public_view, root):
        add_blocker("PUBLIC_VIEW_OUTSIDE_QUARANTINE_ROOT")
    elif _is_within(public_view, tx_root):
        add_blocker("PUBLIC_VIEW_INSIDE_PRIVATE_NAMESPACE")

    if attempt.exists() and not attempt.is_symlink():
        try:
            for child in sorted(attempt.iterdir(), key=lambda path: path.name):
                if child.name not in {"anchor", "captured_source"}:
                    add_blocker("UNRECOGNIZED_PRIVATE_PATH")
        except OSError:
            add_blocker("PRIVATE_NAMESPACE_UNREADABLE")

    frozen_items = manifest.get("owned_paths")
    if not isinstance(frozen_items, list):
        add_blocker("INVALID_OWNED_PATHS")
        frozen_items = []

    seen_roles: set[str] = set()
    observed_role_order: list[str] = []

    for frozen in frozen_items:
        if not isinstance(frozen, dict):
            add_blocker("INVALID_FROZEN_ITEM")
            continue

        role = frozen.get("role")
        if not isinstance(role, str) or role not in expected_paths:
            add_blocker("UNRECOGNIZED_FROZEN_ROLE")
            continue
        if role in seen_roles:
            add_blocker(f"DUPLICATE_FROZEN_ROLE:{role}")
            continue

        seen_roles.add(role)
        observed_role_order.append(role)
        expected_path = expected_paths[role]
        frozen_path = _absolute_lexical(frozen.get("path", ""))

        if frozen_path != expected_path:
            add_blocker(f"PATH_MISMATCH:{role}")
            continue

        if frozen.get("object_type") != "regular_file":
            add_blocker(f"FROZEN_OBJECT_TYPE_MISMATCH:{role}")

        if (
            frozen.get("device") != entry.device
            or frozen.get("inode") != entry.inode
            or frozen.get("size") != entry.size
            or frozen.get("mtime_ns") != entry.mtime_ns
            or frozen.get("content_hash") != entry.content_hash
        ):
            add_blocker(f"FROZEN_IDENTITY_MISMATCH:{role}")

        if expected_path.is_symlink() or os.path.islink(expected_path):
            add_blocker(f"SYMLINK:{role}")
            continue

        try:
            st = expected_path.stat(follow_symlinks=False)
        except OSError:
            add_blocker(f"MISSING_OR_UNREADABLE:{role}")
            continue

        if not stat.S_ISREG(st.st_mode):
            add_blocker(f"NOT_REGULAR_FILE:{role}")
            continue

        if (
            st.st_dev != frozen.get("device")
            or st.st_ino != frozen.get("inode")
            or st.st_size != frozen.get("size")
            or st.st_mtime_ns != frozen.get("mtime_ns")
        ):
            add_blocker(f"IDENTITY_MISMATCH:{role}")

    for role in canonical_roles:
        if role not in seen_roles:
            add_blocker(f"MISSING_FROZEN_ROLE:{role}")

    if tuple(observed_role_order) != canonical_roles:
        add_blocker("NONCANONICAL_ROLE_ORDER")

    return {
        "valid": not blockers,
        "purge_semantics": SEMANTICS_VERSION,
        "selected_entry_id": entry.id,
        "active_attempt_generation": generation,
        "blockers": blockers,
    }


def _revalidate_frozen_item_before_unlink(frozen: dict[str, Any]) -> Path:
    """Revalidate one already-authorized frozen path immediately before unlink."""
    role = frozen.get("role")
    path = _absolute_lexical(frozen.get("path", ""))

    if path.is_symlink() or os.path.islink(path):
        raise RuntimeError(f"SYMLINK:{role}")

    try:
        st = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise RuntimeError(f"MISSING_OR_UNREADABLE:{role}") from exc

    if not stat.S_ISREG(st.st_mode):
        raise RuntimeError(f"NOT_REGULAR_FILE:{role}")

    if (
        st.st_dev != frozen.get("device")
        or st.st_ino != frozen.get("inode")
        or st.st_size != frozen.get("size")
        or st.st_mtime_ns != frozen.get("mtime_ns")
    ):
        raise RuntimeError(f"IDENTITY_MISMATCH:{role}")

    return path


def _unlink_frozen_owned_paths(
    entry: Any,
    quarantine_root: Path | str,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Unlink only exact frozen NFC-owned leaf paths.

    This is an internal mutation primitive, intentionally not routed from API,
    executor, or service yet. Durable intent/recovery orchestration is added by
    the later Gate6-A2 recovery steps before this primitive becomes reachable
    from a production permanent-clear path.
    """
    validation = revalidate_unlink_manifest(entry, quarantine_root, manifest)
    if not validation["valid"]:
        blockers = ",".join(validation["blockers"])
        raise RuntimeError(f"UNLINK_MANIFEST_INVALID:{blockers}")

    frozen_items = tuple(dict(item) for item in manifest["owned_paths"])
    removed_roles: list[str] = []

    for frozen in frozen_items:
        path = _revalidate_frozen_item_before_unlink(frozen)
        os.unlink(path)
        removed_roles.append(str(frozen["role"]))

    return {
        "purge_semantics": SEMANTICS_VERSION,
        "removed_count": len(removed_roles),
        "removed_roles": removed_roles,
    }


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _positive_generation(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return int(value)


def _journal_records_for_entry(
    session: Any,
    entry_id: int,
    *,
    attempt_generation: int | None = None,
) -> list[tuple[OperationJournal, dict[str, Any]]]:
    """Return Gate6-A2 journal records scoped to one entry incarnation.

    OperationJournal is durable history and can outlive a QuarantineEntry row.
    SQLite may later reuse the numeric entry id; the quarantine transaction
    allocator then advances to a new attempt generation because the prior
    attempt namespace is still present.  Therefore entry_id alone is not a
    sufficient recovery key.

    Legacy unlink_v1 intent/terminal rows did not persist the generation at the
    top level.  They are still recoverable because journal ids are chronological:
    an authority row starts an epoch and its manifest carries the generation.
    Subsequent rows for the same entry inherit that epoch until the next
    authority row.  New rows also persist active_attempt_generation explicitly.
    """
    requested_generation = (
        _positive_generation(attempt_generation)
        if attempt_generation is not None
        else None
    )
    if attempt_generation is not None and requested_generation is None:
        return []

    rows = list(
        session.scalars(
            select(OperationJournal)
            .where(OperationJournal.operation == OPERATION_ID)
            .order_by(OperationJournal.id.asc())
        )
    )
    records: list[tuple[OperationJournal, dict[str, Any]]] = []
    epoch_generation: int | None = None

    for row in rows:
        try:
            payload = json.loads(row.before_json or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or payload.get("entry_id") != entry_id:
            continue

        explicit_generation = _positive_generation(
            payload.get("active_attempt_generation")
        )
        if payload.get("phase") == "authority":
            manifest = payload.get("manifest")
            manifest_generation = (
                _positive_generation(manifest.get("active_attempt_generation"))
                if isinstance(manifest, dict)
                else None
            )
            epoch_generation = explicit_generation or manifest_generation
            record_generation = epoch_generation
        else:
            record_generation = explicit_generation or epoch_generation

        if (
            requested_generation is not None
            and record_generation != requested_generation
        ):
            continue
        records.append((row, payload))

    return records


def _durable_authority_manifest(
    session: Any,
    entry_id: int,
    *,
    attempt_generation: int,
) -> dict[str, Any]:
    authorities = [
        payload
        for _, payload in _journal_records_for_entry(
            session,
            entry_id,
            attempt_generation=attempt_generation,
        )
        if payload.get("phase") == "authority"
    ]
    if len(authorities) != 1:
        raise StateConflictError(
            f"UNLINK_RECOVERY_AUTHORITY_INVALID: expected one durable authority record for entry #{entry_id}"
        )
    authority = authorities[0]
    if authority.get("purge_semantics") != SEMANTICS_VERSION:
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: semantics mismatch")
    manifest = authority.get("manifest")
    if not isinstance(manifest, dict):
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: manifest missing")
    if manifest.get("purge_semantics") != SEMANTICS_VERSION:
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: frozen manifest semantics mismatch")
    if manifest.get("selected_entry_id") != entry_id:
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: selected entry mismatch")
    return manifest


def _validate_purging_authority(
    entry: QuarantineEntry,
    quarantine_root: Path | str,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    root = _absolute_lexical(quarantine_root)
    tx_root = root / ".tx"
    generation = int(entry.active_attempt_generation or 0)
    attempt = tx_root / f"entry-{entry.id}" / f"attempt-{generation}"
    expected_paths = {
        "authoritative_anchor": attempt / "anchor",
        "captured_source": attempt / "captured_source",
        "public_view": _absolute_lexical(entry.quarantine_path),
    }

    if entry.state != "purging" or entry.tx_phase != "purging":
        raise StateConflictError(
            f"UNLINK_RECOVERY_STATE_INVALID: entry #{entry.id} is not in Gate6-A2 purge-in-progress state"
        )
    if generation <= 0:
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: generation missing")
    if manifest.get("purge_semantics") != SEMANTICS_VERSION:
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: semantics mismatch")
    if manifest.get("selected_entry_id") != entry.id:
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: selected entry mismatch")
    if manifest.get("active_attempt_generation") != generation:
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: generation mismatch")
    if manifest.get("blockers"):
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: frozen manifest was blocked")
    if root.is_symlink() or tx_root.is_symlink() or attempt.is_symlink():
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: unsafe quarantine namespace")
    if not entry.authoritative_anchor_path:
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: anchor authority missing")
    if _absolute_lexical(entry.authoritative_anchor_path) != expected_paths["authoritative_anchor"]:
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: anchor path mismatch")

    public_view = expected_paths["public_view"]
    if not _is_within(public_view, root) or _is_within(public_view, tx_root):
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: public view scope mismatch")

    if attempt.exists():
        if attempt.is_symlink():
            raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: symlinked attempt namespace")
        try:
            unknown = sorted(
                child.name
                for child in attempt.iterdir()
                if child.name not in {"anchor", "captured_source"}
            )
        except OSError as exc:
            raise StateConflictError(
                f"UNLINK_RECOVERY_AUTHORITY_INVALID: private namespace unreadable: {exc}"
            ) from exc
        if unknown:
            raise StateConflictError(
                f"UNLINK_RECOVERY_AUTHORITY_INVALID: unrecognized private path {unknown[0]}"
            )

    frozen_items = manifest.get("owned_paths")
    if not isinstance(frozen_items, list) or len(frozen_items) != len(_CANONICAL_ROLES):
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: canonical owned paths missing")

    observed_roles: list[str] = []
    canonical_items: list[dict[str, Any]] = []
    for raw in frozen_items:
        if not isinstance(raw, dict):
            raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: malformed frozen item")
        role = raw.get("role")
        if not isinstance(role, str) or role not in expected_paths:
            raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: unknown frozen role")
        if role in observed_roles:
            raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: duplicate frozen role")
        observed_roles.append(role)
        if _absolute_lexical(raw.get("path", "")) != expected_paths[role]:
            raise StateConflictError(f"UNLINK_RECOVERY_AUTHORITY_INVALID: path mismatch for {role}")
        if raw.get("object_type") != "regular_file":
            raise StateConflictError(f"UNLINK_RECOVERY_AUTHORITY_INVALID: object type mismatch for {role}")
        if (
            raw.get("device") != entry.device
            or raw.get("inode") != entry.inode
            or raw.get("size") != entry.size
            or raw.get("mtime_ns") != entry.mtime_ns
            or raw.get("content_hash") != entry.content_hash
        ):
            raise StateConflictError(f"UNLINK_RECOVERY_AUTHORITY_INVALID: identity mismatch for {role}")
        canonical_items.append(dict(raw))

    if tuple(observed_roles) != _CANONICAL_ROLES:
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: noncanonical role order")
    return tuple(canonical_items)


def _persist_initial_authority(
    session_factory: Any,
    entry_id: int,
    quarantine_root: Path | str,
    frozen_manifest: dict[str, Any],
) -> None:
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            session.rollback()
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        if entry.state != "active" or entry.tx_phase != "active":
            session.rollback()
            raise StateConflictError(
                f"UNLINK_PURGE_STATE_INVALID: entry #{entry_id} must be active before irreversible intent"
            )

        validation = revalidate_unlink_manifest(entry, quarantine_root, frozen_manifest)
        if not validation["valid"]:
            session.rollback()
            raise StateConflictError(
                "UNLINK_MANIFEST_INVALID:" + ",".join(validation["blockers"])
            )

        generation = int(entry.active_attempt_generation or 0)
        if generation <= 0:
            session.rollback()
            raise StateConflictError(
                f"UNLINK_RECOVERY_AUTHORITY_INVALID: generation missing for entry #{entry_id}"
            )

        if _journal_records_for_entry(
            session,
            entry_id,
            attempt_generation=generation,
        ):
            session.rollback()
            raise StateConflictError(
                f"UNLINK_RECOVERY_AUTHORITY_INVALID: unexpected prior Gate6-A2 journal "
                f"for entry #{entry_id} generation #{generation}"
            )

        authority = {
            "phase": "authority",
            "purge_semantics": SEMANTICS_VERSION,
            "entry_id": entry_id,
            "active_attempt_generation": generation,
            "manifest": frozen_manifest,
        }
        session.add(
            OperationJournal(
                operation=OPERATION_ID,
                sequence=0,
                plan_id=None,
                plan_item_id=None,
                task_id=None,
                user_id=None,
                before_json=_json_dumps(authority),
                after_json="{}",
                metadata_before_json="{}",
                metadata_after_json="{}",
            )
        )
        entry.state = "purging"
        entry.tx_phase = "purging"
        entry.updated_at = utcnow()
        session.commit()


def _find_path_intent(
    session: Any,
    entry_id: int,
    frozen: dict[str, Any],
    *,
    attempt_generation: int,
) -> OperationJournal | None:
    role = str(frozen.get("role") or "")
    path = str(_absolute_lexical(frozen.get("path", "")))
    matches: list[OperationJournal] = []
    for row, payload in _journal_records_for_entry(
        session,
        entry_id,
        attempt_generation=attempt_generation,
    ):
        if payload.get("phase") != "unlink_intent":
            continue
        if (
            payload.get("purge_semantics") == SEMANTICS_VERSION
            and payload.get("role") == role
            and payload.get("path") == path
            and payload.get("frozen_identity") == {
                "object_type": frozen.get("object_type"),
                "device": frozen.get("device"),
                "inode": frozen.get("inode"),
                "size": frozen.get("size"),
                "mtime_ns": frozen.get("mtime_ns"),
                "content_hash": frozen.get("content_hash"),
            }
        ):
            matches.append(row)
    if len(matches) > 1:
        raise StateConflictError(
            f"UNLINK_RECOVERY_INTENT_INVALID: duplicate durable intent for role {role}"
        )
    return matches[0] if matches else None


def _persist_path_intent(
    session_factory: Any,
    entry_id: int,
    quarantine_root: Path | str,
    frozen: dict[str, Any],
) -> int:
    role = str(frozen.get("role") or "")
    if role not in _ROLE_SEQUENCE:
        raise StateConflictError(f"UNLINK_RECOVERY_INTENT_INVALID: unsupported role {role}")

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            session.rollback()
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        if entry.state != "purging" or entry.tx_phase != "purging":
            session.rollback()
            raise StateConflictError(
                f"UNLINK_RECOVERY_STATE_INVALID: entry #{entry_id} left purge-in-progress state"
            )
        generation = int(entry.active_attempt_generation or 0)
        durable_manifest = _durable_authority_manifest(
            session,
            entry_id,
            attempt_generation=generation,
        )
        canonical_items = {
            str(item["role"]): item
            for item in _validate_purging_authority(entry, quarantine_root, durable_manifest)
        }
        # The caller performs the authoritative root-aware validation before this
        # helper. Do not infer or widen a path from inode facts here.
        if role not in canonical_items or canonical_items[role] != frozen:
            session.rollback()
            raise StateConflictError(
                f"UNLINK_RECOVERY_INTENT_INVALID: frozen authority mismatch for role {role}"
            )

        existing = _find_path_intent(
            session,
            entry_id,
            frozen,
            attempt_generation=generation,
        )
        if existing is not None:
            session.commit()
            return int(existing.id)

        payload = {
            "phase": "unlink_intent",
            "purge_semantics": SEMANTICS_VERSION,
            "entry_id": entry_id,
            "active_attempt_generation": generation,
            "role": role,
            "path": str(_absolute_lexical(frozen["path"])),
            "frozen_identity": {
                "object_type": frozen.get("object_type"),
                "device": frozen.get("device"),
                "inode": frozen.get("inode"),
                "size": frozen.get("size"),
                "mtime_ns": frozen.get("mtime_ns"),
                "content_hash": frozen.get("content_hash"),
            },
        }
        row = OperationJournal(
            operation=OPERATION_ID,
            sequence=_ROLE_SEQUENCE[role],
            plan_id=None,
            plan_item_id=None,
            task_id=None,
            user_id=None,
            before_json=_json_dumps(payload),
            after_json="{}",
            metadata_before_json="{}",
            metadata_after_json="{}",
        )
        session.add(row)
        session.flush()
        row_id = int(row.id)
        session.commit()
        return row_id


def _mark_path_complete(
    session_factory: Any,
    journal_id: int,
    entry_id: int,
    frozen: dict[str, Any],
    *,
    attempt_generation: int,
) -> None:
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        row = session.get(OperationJournal, journal_id)
        if row is None or row.operation != OPERATION_ID:
            session.rollback()
            raise StateConflictError("UNLINK_RECOVERY_INTENT_INVALID: intent row disappeared")
        try:
            before = json.loads(row.before_json or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            session.rollback()
            raise StateConflictError("UNLINK_RECOVERY_INTENT_INVALID: intent row malformed") from exc
        if (
            before.get("entry_id") != entry_id
            or before.get("phase") != "unlink_intent"
            or before.get("role") != frozen.get("role")
            or before.get("path") != str(_absolute_lexical(frozen.get("path", "")))
            or (
                before.get("active_attempt_generation") is not None
                and before.get("active_attempt_generation") != attempt_generation
            )
        ):
            session.rollback()
            raise StateConflictError("UNLINK_RECOVERY_INTENT_INVALID: intent row identity changed")
        row.after_json = _json_dumps(
            {
                "phase": "unlinked",
                "purge_semantics": SEMANTICS_VERSION,
                "entry_id": entry_id,
                "active_attempt_generation": attempt_generation,
                "role": frozen.get("role"),
                "path": str(_absolute_lexical(frozen.get("path", ""))),
            }
        )
        session.commit()


def _descriptor_unlink_frozen_path(
    quarantine_root: Path | str,
    frozen: dict[str, Any],
) -> None:
    root = _absolute_lexical(quarantine_root)
    path = _absolute_lexical(frozen.get("path", ""))
    if not _is_within(path, root):
        raise StateConflictError(f"UNLINK_PATH_OUTSIDE_QUARANTINE_ROOT:{frozen.get('role')}")

    try:
        with safe_open_parent_fd(path, [root]) as (parent_fd, leaf):
            st = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode):
                raise StateConflictError(f"NOT_REGULAR_FILE:{frozen.get('role')}")
            if (
                st.st_dev != frozen.get("device")
                or st.st_ino != frozen.get("inode")
                or st.st_size != frozen.get("size")
                or st.st_mtime_ns != frozen.get("mtime_ns")
            ):
                raise StateConflictError(f"IDENTITY_MISMATCH:{frozen.get('role')}")
            os.unlink(leaf, dir_fd=parent_fd)
            os.fsync(parent_fd)
    except FileNotFoundError:
        raise
    except StateConflictError:
        raise
    except OSError as exc:
        raise StateConflictError(
            f"UNLINK_FAILED:{frozen.get('role')}:{exc}"
        ) from exc


def _commit_terminal_purged(
    session_factory: Any,
    entry_id: int,
    quarantine_root: Path | str,
    *,
    worker_id: str | None = None,
) -> None:
    # Refresh the worker lease immediately before entering the terminal write
    # boundary. The authoritative lease assertion is repeated inside the same
    # BEGIN IMMEDIATE transaction that publishes terminal success, closing the
    # post-unlink/pre-terminal stale-worker window.
    if worker_id is not None:
        renew_and_assert_worker_lease(session_factory, worker_id)

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        if worker_id is not None:
            assert_active_worker_lease(session, worker_id, now=utcnow())

        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            session.rollback()
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        generation = int(entry.active_attempt_generation or 0)
        manifest = _durable_authority_manifest(
            session,
            entry_id,
            attempt_generation=generation,
        )
        frozen_items = _validate_purging_authority(entry, quarantine_root, manifest)

        for frozen in frozen_items:
            path = _absolute_lexical(frozen["path"])
            if os.path.lexists(path):
                session.rollback()
                raise StateConflictError(
                    f"UNLINK_TERMINAL_INCOMPLETE: authorized path still exists for {frozen['role']}"
                )
            if _find_path_intent(
                session,
                entry_id,
                frozen,
                attempt_generation=generation,
            ) is None:
                session.rollback()
                raise StateConflictError(
                    f"UNLINK_TERMINAL_UNPROVEN: missing path has no durable intent for {frozen['role']}"
                )

        now = utcnow()
        entry.state = "purged"
        entry.tx_phase = "purged"
        entry.purged_at = now
        entry.updated_at = now
        session.add(
            OperationJournal(
                operation=OPERATION_ID,
                sequence=1000,
                plan_id=None,
                plan_item_id=None,
                task_id=None,
                user_id=None,
                before_json=_json_dumps(
                    {
                        "phase": "terminal",
                        "purge_semantics": SEMANTICS_VERSION,
                        "entry_id": entry_id,
                        "active_attempt_generation": generation,
                    }
                ),
                after_json=_json_dumps(
                    {
                        "phase": "purged",
                        "purge_semantics": SEMANTICS_VERSION,
                        "entry_id": entry_id,
                        "active_attempt_generation": generation,
                    }
                ),
                metadata_before_json="{}",
                metadata_after_json="{}",
            )
        )
        session.commit()


def execute_journaled_unlink_purge(
    session_factory: Any,
    *,
    entry_id: int,
    quarantine_root: Path | str,
    frozen_manifest: dict[str, Any] | None,
    worker_id: str | None = None,
) -> dict[str, Any]:
    """Execute or resume pathname-scoped unlink purge with durable exact-path intent.

    The first call must supply the frozen manifest while the entry is active.
    It durably records new-operation authority and moves the entry to purging
    before any unlink. Each pathname receives its own committed unlink-intent
    record before mutation. Recovery may accept an absent frozen pathname only
    when that exact durable intent exists.
    """
    root = _absolute_lexical(quarantine_root)

    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        state = entry.state
        phase = entry.tx_phase
        generation = int(entry.active_attempt_generation or 0)

    if state == "active" and phase == "active":
        if frozen_manifest is None:
            raise StateConflictError("UNLINK_FROZEN_AUTHORITY_REQUIRED")
        _persist_initial_authority(
            session_factory,
            entry_id,
            root,
            frozen_manifest,
        )
    elif state == "purging" and phase == "purging":
        with session_factory() as session:
            durable_manifest = _durable_authority_manifest(
                session,
                entry_id,
                attempt_generation=generation,
            )
        if frozen_manifest is not None and frozen_manifest != durable_manifest:
            raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_CHANGED")
    elif state == "purged" and phase == "purged":
        return {
            "purge_semantics": SEMANTICS_VERSION,
            "removed_count": 0,
            "removed_roles": [],
            "recovered_missing_roles": [],
            "already_terminal": True,
        }
    else:
        raise StateConflictError(
            f"UNLINK_PURGE_STATE_INVALID: entry #{entry_id} state={state} tx_phase={phase}"
        )

    with session_factory() as session:
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        generation = int(entry.active_attempt_generation or 0)
        manifest = _durable_authority_manifest(
            session,
            entry_id,
            attempt_generation=generation,
        )
        frozen_items = _validate_purging_authority(entry, root, manifest)

    removed_roles: list[str] = []
    recovered_missing_roles: list[str] = []

    for frozen in frozen_items:
        role = str(frozen["role"])
        path = _absolute_lexical(frozen["path"])

        with session_factory() as session:
            existing_intent = _find_path_intent(
                session,
                entry_id,
                frozen,
                attempt_generation=generation,
            )

        if not os.path.lexists(path):
            if existing_intent is None:
                raise StateConflictError(
                    f"UNLINK_UNPROVEN_MISSING_PATH:{role}: absence predates durable exact-path intent"
                )
            recovered_missing_roles.append(role)
            continue

        # Revalidate while still in purge-in-progress state. This does not widen
        # authority: the path/identity must exactly match the persisted manifest.
        _revalidate_frozen_item_before_unlink(frozen)
        intent_id = _persist_path_intent(
            session_factory,
            entry_id,
            root,
            frozen,
        )

        if worker_id is not None:
            renew_and_assert_worker_lease(session_factory, worker_id)

        try:
            _descriptor_unlink_frozen_path(root, frozen)
        except FileNotFoundError:
            # The exact path had durable intent before this attempt. A concurrent
            # or resumed execution may therefore treat this exact absence as
            # idempotent, but no other pathname is inferred or added.
            recovered_missing_roles.append(role)
            continue

        removed_roles.append(role)
        _mark_path_complete(
            session_factory,
            intent_id,
            entry_id,
            frozen,
            attempt_generation=generation,
        )

    _commit_terminal_purged(
        session_factory,
        entry_id,
        root,
        worker_id=worker_id,
    )

    return {
        "purge_semantics": SEMANTICS_VERSION,
        "removed_count": len(removed_roles),
        "removed_roles": removed_roles,
        "recovered_missing_roles": recovered_missing_roles,
        "already_terminal": False,
    }
