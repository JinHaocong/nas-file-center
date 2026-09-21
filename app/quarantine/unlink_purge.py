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


def _is_cross_storage_entry(entry: Any) -> bool:
    return getattr(entry, "transaction_mode", None) == "cross_storage_transactional"


def _entry_quarantine_identity(entry: Any) -> tuple[int | None, int | None, int | None]:
    if _is_cross_storage_entry(entry):
        raw_dev = getattr(entry, "quarantine_device", None)
        raw_ino = getattr(entry, "quarantine_inode", None)
        raw_mtime = getattr(entry, "quarantine_mtime_ns", None)
        return (
            int(raw_dev) if raw_dev is not None else None,
            int(raw_ino) if raw_ino is not None else None,
            int(raw_mtime) if raw_mtime is not None else None,
        )
    return (
        int(entry.device) if entry.device is not None else None,
        int(entry.inode) if entry.inode is not None else None,
        int(entry.mtime_ns) if entry.mtime_ns is not None else None,
    )


def _expected_unlink_paths(entry: Any, attempt: Path) -> dict[str, Path]:
    public_view = _absolute_lexical(entry.quarantine_path)
    if _is_cross_storage_entry(entry):
        return {"public_view": public_view}
    return {
        "authoritative_anchor": attempt / "anchor",
        "captured_source": attempt / "captured_source",
        "public_view": public_view,
    }


def _allowed_private_names(entry: Any) -> set[str]:
    if _is_cross_storage_entry(entry):
        return set()
    return {"anchor", "captured_source"}


_METADATA_ONLY_ORPHAN_MODE = "cross_storage_missing_payload_v1"


def _prove_absent(path: Path, *, label: str) -> str | None:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"ORPHAN_ABSENCE_UNPROVEN:{label}:{exc.errno}"
    return f"ORPHAN_PATH_PRESENT:{label}"


def _metadata_only_orphan_material(
    entry: Any,
    quarantine_root: Path | str,
) -> tuple[dict[str, str] | None, list[str]]:
    """Prove the legacy cross-storage row owns no remaining filesystem object.

    This is a metadata-only compatibility authority for historical rows created
    by early Gate6-C builds. It never infers a replacement payload and never
    authorizes unlink of another path. The mode is available only when the exact
    original path, public quarantine view, and the entire selected entry private
    transaction namespace are all proven absent.
    """

    blockers: list[str] = []
    if not _is_cross_storage_entry(entry):
        return None, ["ORPHAN_MODE_REQUIRES_CROSS_STORAGE"]

    root = _absolute_lexical(quarantine_root)
    tx_root = root / ".tx"
    generation = int(entry.active_attempt_generation or 0)
    tx_entry_root = tx_root / f"entry-{entry.id}"
    public_view = _absolute_lexical(entry.quarantine_path)
    original_raw = Path(os.fspath(entry.original_path))

    if not original_raw.is_absolute():
        blockers.append("ORPHAN_ORIGINAL_PATH_NOT_ABSOLUTE")
        original = _absolute_lexical(original_raw)
    else:
        original = _absolute_lexical(original_raw)

    if generation <= 0:
        blockers.append("INVALID_ACTIVE_GENERATION")
    if entry.authoritative_anchor_path:
        blockers.append("ORPHAN_AUTHORITATIVE_ANCHOR_DECLARED")

    q_device, q_inode, q_mtime = _entry_quarantine_identity(entry)
    if q_device is None or q_inode is None or q_mtime is None:
        blockers.append("MISSING_CROSS_STORAGE_QUARANTINE_IDENTITY")

    if root.is_symlink() or tx_root.is_symlink():
        blockers.append("UNSAFE_QUARANTINE_NAMESPACE")

    if not _is_within(public_view, root):
        blockers.append("PUBLIC_VIEW_OUTSIDE_QUARANTINE_ROOT")
    elif _is_within(public_view, tx_root):
        blockers.append("PUBLIC_VIEW_INSIDE_PRIVATE_NAMESPACE")

    for path, label in (
        (original, "original_path"),
        (public_view, "public_view"),
        (tx_entry_root, "tx_entry_root"),
    ):
        blocker = _prove_absent(path, label=label)
        if blocker is not None:
            blockers.append(blocker)

    if blockers:
        return None, blockers

    return (
        {
            "mode": _METADATA_ONLY_ORPHAN_MODE,
            "original_path": str(original),
            "public_view": str(public_view),
            "tx_entry_root": str(tx_entry_root),
        },
        [],
    )


def _validate_metadata_only_orphan_manifest(
    entry: Any,
    quarantine_root: Path | str,
    manifest: dict[str, Any],
) -> list[str]:
    material, blockers = _metadata_only_orphan_material(entry, quarantine_root)
    if blockers:
        return blockers
    if material is None:
        return ["ORPHAN_AUTHORITY_MISSING"]
    if manifest.get("metadata_only_orphan") is not True:
        return ["ORPHAN_MANIFEST_MODE_MISSING"]
    if manifest.get("orphan_absence") != material:
        return ["ORPHAN_ABSENCE_AUTHORITY_CHANGED"]
    owned_paths = manifest.get("owned_paths")
    if owned_paths != []:
        return ["ORPHAN_MANIFEST_OWNED_PATHS_INVALID"]
    return []


def _identity_item(role: str, path: Path, entry: Any) -> tuple[dict[str, Any] | None, str | None]:
    if path.is_symlink() or os.path.islink(path):
        return None, f"SYMLINK:{role}"

    try:
        st = path.stat(follow_symlinks=False)
    except OSError:
        return None, f"MISSING_OR_UNREADABLE:{role}"

    if not stat.S_ISREG(st.st_mode):
        return None, f"NOT_REGULAR_FILE:{role}"

    expected_device, expected_inode, expected_mtime_ns = _entry_quarantine_identity(entry)
    if (
        expected_device is None
        or expected_inode is None
        or expected_mtime_ns is None
        or int(st.st_dev) != expected_device
        or int(st.st_ino) != expected_inode
        or int(st.st_size) != int(entry.size)
        or int(st.st_mtime_ns) != expected_mtime_ns
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
    expected_paths = _expected_unlink_paths(entry, attempt)
    public_view = expected_paths["public_view"]

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

    if not _is_cross_storage_entry(entry):
        expected_anchor = expected_paths["authoritative_anchor"]
        if not entry.authoritative_anchor_path:
            add_blocker("MISSING_AUTHORITATIVE_ANCHOR")
        elif _absolute_lexical(entry.authoritative_anchor_path) != expected_anchor:
            add_blocker("ANCHOR_PATH_MISMATCH")
    else:
        q_device, q_inode, q_mtime = _entry_quarantine_identity(entry)
        if q_device is None or q_inode is None or q_mtime is None:
            add_blocker("MISSING_CROSS_STORAGE_QUARANTINE_IDENTITY")

    if not _is_within(public_view, root):
        add_blocker("PUBLIC_VIEW_OUTSIDE_QUARANTINE_ROOT")
    elif _is_within(public_view, tx_root):
        add_blocker("PUBLIC_VIEW_INSIDE_PRIVATE_NAMESPACE")

    if _is_cross_storage_entry(entry):
        orphan_material, orphan_blockers = _metadata_only_orphan_material(
            entry,
            root,
        )
        if orphan_material is not None and not orphan_blockers and not blockers:
            return {
                "purge_semantics": SEMANTICS_VERSION,
                "selected_entry_id": entry.id,
                "active_attempt_generation": generation,
                "metadata_only_orphan": True,
                "orphan_absence": orphan_material,
                "owned_paths": [],
                "blockers": [],
            }

    # Mutation authority is selected-entry pathname scoped. Inspect only the
    # selected entry's current attempt directory so an unknown private object
    # fails closed without scanning sibling entries or widening by inode.
    if attempt.exists() and not attempt.is_symlink():
        try:
            for child in sorted(attempt.iterdir(), key=lambda path: path.name):
                if child.name not in _allowed_private_names(entry):
                    add_blocker("UNRECOGNIZED_PRIVATE_PATH")
        except OSError:
            add_blocker("PRIVATE_NAMESPACE_UNREADABLE")

    owned_paths: list[dict[str, Any]] = []
    for role, path in expected_paths.items():
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
    expected_paths = _expected_unlink_paths(entry, attempt)
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

    if not _is_cross_storage_entry(entry):
        expected_anchor = expected_paths["authoritative_anchor"]
        if not entry.authoritative_anchor_path:
            add_blocker("MISSING_AUTHORITATIVE_ANCHOR")
        elif _absolute_lexical(entry.authoritative_anchor_path) != expected_anchor:
            add_blocker("ANCHOR_PATH_MISMATCH")
    else:
        q_device, q_inode, q_mtime = _entry_quarantine_identity(entry)
        if q_device is None or q_inode is None or q_mtime is None:
            add_blocker("MISSING_CROSS_STORAGE_QUARANTINE_IDENTITY")

    public_view = expected_paths["public_view"]
    if not _is_within(public_view, root):
        add_blocker("PUBLIC_VIEW_OUTSIDE_QUARANTINE_ROOT")
    elif _is_within(public_view, tx_root):
        add_blocker("PUBLIC_VIEW_INSIDE_PRIVATE_NAMESPACE")

    if manifest.get("metadata_only_orphan") is True:
        for blocker in _validate_metadata_only_orphan_manifest(
            entry,
            root,
            manifest,
        ):
            add_blocker(blocker)
        return {
            "valid": not blockers,
            "purge_semantics": SEMANTICS_VERSION,
            "selected_entry_id": entry.id,
            "active_attempt_generation": generation,
            "blockers": blockers,
        }

    if attempt.exists() and not attempt.is_symlink():
        try:
            for child in sorted(attempt.iterdir(), key=lambda path: path.name):
                if child.name not in _allowed_private_names(entry):
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

        expected_device, expected_inode, expected_mtime_ns = _entry_quarantine_identity(entry)
        if (
            expected_device is None
            or expected_inode is None
            or expected_mtime_ns is None
            or frozen.get("device") != expected_device
            or frozen.get("inode") != expected_inode
            or frozen.get("size") != entry.size
            or frozen.get("mtime_ns") != expected_mtime_ns
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
        "metadata_only_orphan": manifest.get("metadata_only_orphan") is True,
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


def _journal_epochs_for_entry(
    session: Any,
    entry_id: int,
) -> list[tuple[int | None, list[tuple[OperationJournal, dict[str, Any]]]]]:
    """Return chronological Gate6-A2 authority epochs for one numeric entry id.

    OperationJournal intentionally outlives QuarantineEntry metadata. SQLite can
    later reuse a deleted numeric id, and maintenance may also remove the now-empty
    old transaction namespace. In that case a new entry can legitimately start at
    the same attempt generation as a completed historical incarnation.

    An authority row therefore starts an epoch. Generation scopes the epoch, but
    generation is not assumed globally unique across all future incarnations of the
    same numeric entry id.
    """
    rows = list(
        session.scalars(
            select(OperationJournal)
            .where(OperationJournal.operation == OPERATION_ID)
            .order_by(OperationJournal.id.asc())
        )
    )

    epochs: list[
        tuple[int | None, list[tuple[OperationJournal, dict[str, Any]]]]
    ] = []
    current_generation: int | None = None
    current_records: list[tuple[OperationJournal, dict[str, Any]]] | None = None

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
            current_generation = explicit_generation or manifest_generation
            current_records = []
            epochs.append((current_generation, current_records))
        elif current_records is None:
            # A row without a preceding authority cannot safely establish an
            # incarnation boundary. Ignore it here; recovery will never infer
            # authority from a free-standing intent/terminal record.
            continue
        elif (
            explicit_generation is not None
            and current_generation is not None
            and explicit_generation != current_generation
        ):
            # Malformed cross-generation row: leave it out of the established
            # epoch so it cannot silently widen recovery authority.
            continue

        assert current_records is not None
        current_records.append((row, payload))

    return epochs


def _journal_records_for_entry(
    session: Any,
    entry_id: int,
    *,
    attempt_generation: int | None = None,
) -> list[tuple[OperationJournal, dict[str, Any]]]:
    """Return Gate6-A2 records for the latest authority epoch in a generation.

    Legacy intent/terminal rows may omit the generation; they inherit it from the
    authority row that opened their epoch. If a terminal historical incarnation
    and a later incarnation reuse the same numeric entry id *and* generation, the
    later authority row starts a new epoch and recovery binds only to that latest
    epoch rather than merging both histories.
    """
    requested_generation = (
        _positive_generation(attempt_generation)
        if attempt_generation is not None
        else None
    )
    if attempt_generation is not None and requested_generation is None:
        return []

    epochs = _journal_epochs_for_entry(session, entry_id)
    if requested_generation is None:
        return [
            record
            for _generation, records in epochs
            for record in records
        ]

    matching = [
        records
        for generation, records in epochs
        if generation == requested_generation
    ]
    return matching[-1] if matching else []


def _journal_epoch_terminal_purged(
    records: list[tuple[OperationJournal, dict[str, Any]]],
    *,
    entry_id: int,
    attempt_generation: int,
) -> bool:
    """Prove that one prior authority epoch reached durable terminal purged state."""
    terminals: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for row, before in records:
        if before.get("phase") != "terminal":
            continue
        try:
            after = json.loads(row.after_json or "{}")
        except (TypeError, json.JSONDecodeError):
            return False
        if not isinstance(after, dict):
            return False
        terminals.append((before, after))

    if len(terminals) != 1:
        return False

    before, after = terminals[0]
    return (
        before.get("purge_semantics") == SEMANTICS_VERSION
        and before.get("entry_id") == entry_id
        and _positive_generation(before.get("active_attempt_generation"))
        == attempt_generation
        and after.get("phase") == "purged"
        and after.get("purge_semantics") == SEMANTICS_VERSION
        and after.get("entry_id") == entry_id
        and _positive_generation(after.get("active_attempt_generation"))
        == attempt_generation
    )

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
    expected_paths = _expected_unlink_paths(entry, attempt)

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
    if not _is_cross_storage_entry(entry):
        if not entry.authoritative_anchor_path:
            raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: anchor authority missing")
        if _absolute_lexical(entry.authoritative_anchor_path) != expected_paths["authoritative_anchor"]:
            raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: anchor path mismatch")
    else:
        q_device, q_inode, q_mtime = _entry_quarantine_identity(entry)
        if q_device is None or q_inode is None or q_mtime is None:
            raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: cross-storage identity missing")

    public_view = expected_paths["public_view"]
    if not _is_within(public_view, root) or _is_within(public_view, tx_root):
        raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: public view scope mismatch")

    if manifest.get("metadata_only_orphan") is True:
        orphan_blockers = _validate_metadata_only_orphan_manifest(
            entry,
            root,
            manifest,
        )
        if orphan_blockers:
            raise StateConflictError(
                "UNLINK_RECOVERY_AUTHORITY_INVALID: "
                + ",".join(orphan_blockers)
            )
        return ()

    if attempt.exists():
        if attempt.is_symlink():
            raise StateConflictError("UNLINK_RECOVERY_AUTHORITY_INVALID: symlinked attempt namespace")
        try:
            unknown = sorted(
                child.name
                for child in attempt.iterdir()
                if child.name not in _allowed_private_names(entry)
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
    canonical_roles = tuple(expected_paths)
    if not isinstance(frozen_items, list) or len(frozen_items) != len(canonical_roles):
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
        expected_device, expected_inode, expected_mtime_ns = _entry_quarantine_identity(entry)
        if (
            expected_device is None
            or expected_inode is None
            or expected_mtime_ns is None
            or raw.get("device") != expected_device
            or raw.get("inode") != expected_inode
            or raw.get("size") != entry.size
            or raw.get("mtime_ns") != expected_mtime_ns
            or raw.get("content_hash") != entry.content_hash
        ):
            raise StateConflictError(f"UNLINK_RECOVERY_AUTHORITY_INVALID: identity mismatch for {role}")
        canonical_items.append(dict(raw))

    if tuple(observed_roles) != canonical_roles:
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

        prior_records = _journal_records_for_entry(
            session,
            entry_id,
            attempt_generation=generation,
        )
        if prior_records:
            prior_authorities = [
                payload
                for _row, payload in prior_records
                if payload.get("phase") == "authority"
            ]
            prior_manifest = (
                prior_authorities[0].get("manifest")
                if len(prior_authorities) == 1
                and isinstance(prior_authorities[0].get("manifest"), dict)
                else None
            )
            reusable_historical_epoch = (
                prior_manifest is not None
                and prior_manifest != frozen_manifest
                and _journal_epoch_terminal_purged(
                    prior_records,
                    entry_id=entry_id,
                    attempt_generation=generation,
                )
            )
            if not reusable_historical_epoch:
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
