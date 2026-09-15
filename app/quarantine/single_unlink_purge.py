from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from app.exceptions import StateConflictError
from app.models import (
    AuditEvent,
    DuplicateFile,
    DuplicateGroup,
    IndexRoot,
    IndexedPath,
    OperationJournal,
    QuarantineEntry,
)
from app.quarantine.unlink_purge import (
    OPERATION_ID,
    SEMANTICS_VERSION,
    build_unlink_manifest,
    execute_journaled_unlink_purge,
)


_CANONICAL_ROLES = (
    "authoritative_anchor",
    "captured_source",
    "public_view",
)


def _absolute_lexical(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _fresh_survivor_advisory(
    service: Any,
    *,
    entry_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Return scoped post-unlink evidence without granting mutation authority."""
    quarantine_root = _absolute_lexical(service.settings.quarantine_root)
    verified_survivors: list[str] = []
    independent_copies: list[str] = []
    verification_incomplete = False

    try:
        with service.SessionLocal() as session:
            current_roots = {
                str(_absolute_lexical(root))
                for root in session.scalars(select(IndexRoot.root))
            }
            candidates = list(
                session.scalars(
                    select(IndexedPath)
                    .where(
                        IndexedPath.is_dir.is_(False),
                        IndexedPath.device == int(entry_snapshot["device"]),
                        IndexedPath.inode == int(entry_snapshot["inode"]),
                    )
                    .order_by(IndexedPath.absolute_path.asc())
                )
            )

            for candidate in candidates:
                path = _absolute_lexical(candidate.absolute_path)
                root = str(_absolute_lexical(candidate.root_key))
                if root not in current_roots:
                    verification_incomplete = True
                    continue
                if not _is_within(path, Path(root)):
                    verification_incomplete = True
                    continue
                if _is_within(path, quarantine_root):
                    continue
                try:
                    st = os.lstat(path)
                except OSError:
                    verification_incomplete = True
                    continue
                if (
                    stat.S_ISREG(st.st_mode)
                    and not os.path.islink(path)
                    and int(st.st_dev) == int(entry_snapshot["device"])
                    and int(st.st_ino) == int(entry_snapshot["inode"])
                ):
                    verified_survivors.append(str(path))
                else:
                    verification_incomplete = True

            content_hash = entry_snapshot.get("content_hash")
            if content_hash:
                group_ids = list(
                    session.scalars(
                        select(DuplicateGroup.id).where(
                            DuplicateGroup.content_hash == str(content_hash)
                        )
                    )
                )
                if group_ids:
                    copies = list(
                        session.scalars(
                            select(DuplicateFile)
                            .where(DuplicateFile.group_id.in_(group_ids))
                            .order_by(DuplicateFile.absolute_path.asc())
                        )
                    )
                    for copy in copies:
                        if (
                            int(copy.device) == int(entry_snapshot["device"])
                            and int(copy.inode) == int(entry_snapshot["inode"])
                        ):
                            continue
                        path = _absolute_lexical(copy.absolute_path)
                        if _is_within(path, quarantine_root):
                            continue
                        independent_copies.append(str(path))
    except Exception:
        # Advisory lookup must never widen or roll back already-proven unlink
        # authority. Report the scope as incomplete instead of overstating it.
        verification_incomplete = True

    verified_survivors = sorted(set(verified_survivors))
    independent_copies = sorted(set(independent_copies))
    if verification_incomplete:
        survivor_status = "incomplete"
    elif verified_survivors:
        survivor_status = "found"
    else:
        survivor_status = "none_found"

    return {
        "survivor_scope": "indexed_roots_only",
        "survivor_status": survivor_status,
        "hardlink_survivor_count": len(verified_survivors),
        "hardlink_survivor_paths": verified_survivors,
        "independent_copy_count": len(independent_copies),
        "independent_copy_paths": independent_copies,
    }


def _parse_json_object(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _durable_terminal_recovery_evidence(
    session: Any,
    *,
    entry: QuarantineEntry,
    quarantine_root: Path | str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prove a purged entry belongs to the completed unlink_v1 operation.

    A terminal state alone is never sufficient authority. Recovery is accepted
    only when one canonical durable authority record, one exact-path intent for
    every frozen role, and one matching terminal record all bind this entry to
    quarantine_unlink_purge / unlink_v1.
    """
    entry_id = int(entry.id)
    rows = list(
        session.scalars(
            select(OperationJournal)
            .where(OperationJournal.operation == OPERATION_ID)
            .order_by(OperationJournal.sequence.asc(), OperationJournal.id.asc())
        )
    )
    records = [
        (row, _parse_json_object(row.before_json), _parse_json_object(row.after_json))
        for row in rows
    ]

    authorities = [
        before
        for _, before, _ in records
        if before.get("entry_id") == entry_id
        and before.get("phase") == "authority"
        and before.get("purge_semantics") == SEMANTICS_VERSION
    ]
    if len(authorities) != 1:
        raise StateConflictError(
            f"UNLINK_SINGLE_TERMINAL_PROOF_INVALID: expected one authority for entry #{entry_id}"
        )

    manifest = authorities[0].get("manifest")
    if not isinstance(manifest, dict):
        raise StateConflictError("UNLINK_SINGLE_TERMINAL_PROOF_INVALID: manifest missing")
    if (
        manifest.get("purge_semantics") != SEMANTICS_VERSION
        or manifest.get("selected_entry_id") != entry_id
        or manifest.get("blockers")
    ):
        raise StateConflictError("UNLINK_SINGLE_TERMINAL_PROOF_INVALID: manifest binding")

    generation = int(entry.active_attempt_generation or 0)
    if generation <= 0 or manifest.get("active_attempt_generation") != generation:
        raise StateConflictError("UNLINK_SINGLE_TERMINAL_PROOF_INVALID: generation binding")

    root = _absolute_lexical(quarantine_root)
    attempt = root / ".tx" / f"entry-{entry_id}" / f"attempt-{generation}"
    expected_paths = {
        "authoritative_anchor": attempt / "anchor",
        "captured_source": attempt / "captured_source",
        "public_view": _absolute_lexical(entry.quarantine_path),
    }
    if not entry.authoritative_anchor_path or (
        _absolute_lexical(entry.authoritative_anchor_path)
        != expected_paths["authoritative_anchor"]
    ):
        raise StateConflictError("UNLINK_SINGLE_TERMINAL_PROOF_INVALID: anchor binding")

    frozen_items = manifest.get("owned_paths")
    if not isinstance(frozen_items, list) or len(frozen_items) != len(_CANONICAL_ROLES):
        raise StateConflictError("UNLINK_SINGLE_TERMINAL_PROOF_INVALID: canonical paths missing")

    by_role: dict[str, dict[str, Any]] = {}
    observed_roles: list[str] = []
    for raw in frozen_items:
        if not isinstance(raw, dict):
            raise StateConflictError("UNLINK_SINGLE_TERMINAL_PROOF_INVALID: malformed frozen path")
        role = raw.get("role")
        if not isinstance(role, str) or role not in expected_paths or role in by_role:
            raise StateConflictError("UNLINK_SINGLE_TERMINAL_PROOF_INVALID: frozen role binding")
        observed_roles.append(role)
        if _absolute_lexical(raw.get("path", "")) != expected_paths[role]:
            raise StateConflictError(
                f"UNLINK_SINGLE_TERMINAL_PROOF_INVALID: path binding for {role}"
            )
        if (
            raw.get("object_type") != "regular_file"
            or raw.get("device") != entry.device
            or raw.get("inode") != entry.inode
            or raw.get("size") != entry.size
            or raw.get("mtime_ns") != entry.mtime_ns
            or raw.get("content_hash") != entry.content_hash
        ):
            raise StateConflictError(
                f"UNLINK_SINGLE_TERMINAL_PROOF_INVALID: identity binding for {role}"
            )
        by_role[role] = raw

    if tuple(observed_roles) != _CANONICAL_ROLES:
        raise StateConflictError("UNLINK_SINGLE_TERMINAL_PROOF_INVALID: role order")

    terminal_rows = [
        (before, after)
        for _, before, after in records
        if before.get("entry_id") == entry_id
        and before.get("phase") == "terminal"
        and before.get("purge_semantics") == SEMANTICS_VERSION
    ]
    if len(terminal_rows) != 1:
        raise StateConflictError(
            f"UNLINK_SINGLE_TERMINAL_PROOF_INVALID: expected one terminal for entry #{entry_id}"
        )
    terminal_before, terminal_after = terminal_rows[0]
    if (
        terminal_before.get("entry_id") != entry_id
        or terminal_after.get("entry_id") != entry_id
        or terminal_after.get("phase") != "purged"
        or terminal_after.get("purge_semantics") != SEMANTICS_VERSION
    ):
        raise StateConflictError("UNLINK_SINGLE_TERMINAL_PROOF_INVALID: terminal binding")

    intents = [
        (before, after)
        for _, before, after in records
        if before.get("entry_id") == entry_id and before.get("phase") == "unlink_intent"
    ]
    if len(intents) != len(_CANONICAL_ROLES):
        raise StateConflictError("UNLINK_SINGLE_TERMINAL_PROOF_INVALID: exact-path intents")

    removed_roles: list[str] = []
    recovered_missing_roles: list[str] = []
    for role in _CANONICAL_ROLES:
        frozen = by_role[role]
        path_text = str(_absolute_lexical(frozen["path"]))
        expected_identity = {
            "object_type": frozen.get("object_type"),
            "device": frozen.get("device"),
            "inode": frozen.get("inode"),
            "size": frozen.get("size"),
            "mtime_ns": frozen.get("mtime_ns"),
            "content_hash": frozen.get("content_hash"),
        }
        matches = [
            (before, after)
            for before, after in intents
            if before.get("purge_semantics") == SEMANTICS_VERSION
            and before.get("role") == role
            and before.get("path") == path_text
            and before.get("frozen_identity") == expected_identity
        ]
        if len(matches) != 1:
            raise StateConflictError(
                f"UNLINK_SINGLE_TERMINAL_PROOF_INVALID: intent binding for {role}"
            )
        _, after = matches[0]
        if (
            after.get("phase") == "unlinked"
            and after.get("purge_semantics") == SEMANTICS_VERSION
            and after.get("entry_id") == entry_id
            and after.get("role") == role
            and after.get("path") == path_text
        ):
            removed_roles.append(role)
        else:
            # Terminal publication proves the frozen path was absent and had
            # durable exact-path intent even if a completion checkpoint was lost.
            recovered_missing_roles.append(role)

    return manifest, {
        "purge_semantics": SEMANTICS_VERSION,
        "removed_count": len(removed_roles),
        "removed_roles": removed_roles,
        "recovered_missing_roles": recovered_missing_roles,
        "already_terminal": True,
    }


def _matching_single_terminal_events(
    session: Any,
    *,
    entry_id: int,
) -> list[tuple[AuditEvent, dict[str, Any]]]:
    matches: list[tuple[AuditEvent, dict[str, Any]]] = []
    events = list(
        session.scalars(
            select(AuditEvent).where(
                AuditEvent.operation == OPERATION_ID,
                AuditEvent.result == "purged",
            )
        )
    )
    for event in events:
        details = _parse_json_object(event.details_json)
        if details.get("quarantine_entry_id") == entry_id:
            matches.append((event, details))
    return matches


def _persist_single_terminal_audit(
    service: Any,
    *,
    entry_id: int,
    entry_snapshot: dict[str, Any],
    details: dict[str, Any],
) -> None:
    """Publish one Single Clear success audit, repairing a crash gap idempotently."""
    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            session.rollback()
            raise StateConflictError(f"Quarantine entry #{entry_id} not found")
        if entry.state != "purged" or entry.tx_phase != "purged":
            session.rollback()
            raise StateConflictError(
                f"UNLINK_SINGLE_TERMINAL_STATE_INVALID: entry #{entry_id} "
                f"state={entry.state} tx_phase={entry.tx_phase}"
            )

        # Re-prove exact unlink_v1 authority inside the same write transaction
        # used for audit publication. A bare purged state can never repair audit.
        _durable_terminal_recovery_evidence(
            session,
            entry=entry,
            quarantine_root=service.settings.quarantine_root,
        )

        events = _matching_single_terminal_events(session, entry_id=entry_id)
        if len(events) > 1:
            session.rollback()
            raise StateConflictError(
                f"UNLINK_SINGLE_TERMINAL_AUDIT_DUPLICATE: entry #{entry_id}"
            )
        if events:
            event, existing = events[0]
            if (
                event.path != str(entry_snapshot["quarantine_path"])
                or existing.get("purge_semantics") != SEMANTICS_VERSION
                or existing.get("terminal_result") != "purged"
            ):
                session.rollback()
                raise StateConflictError(
                    f"UNLINK_SINGLE_TERMINAL_AUDIT_INVALID: entry #{entry_id}"
                )
            session.commit()
            return

        session.add(
            AuditEvent(
                operation=OPERATION_ID,
                path=str(entry_snapshot["quarantine_path"]),
                result="purged",
                details_json=json.dumps(details, ensure_ascii=False, sort_keys=True),
            )
        )
        session.commit()


def purge_single_transactional_entry(
    service: Any,
    entry_id: int,
    *,
    confirmation: str,
    is_admin: bool,
) -> dict[str, Any]:
    """Run the public single Clear action through Gate6-A2 unlink semantics."""
    if not is_admin:
        raise PermissionError("Only administrator can purge quarantine entries")
    if not service.settings.allow_mutation:
        raise ValueError("Filesystem mutation is disabled")
    if not service.settings.allow_delete:
        raise ValueError("Permanent deletion is disabled")
    if confirmation != "DELETE":
        raise ValueError("Confirmation token must be 'DELETE'")

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise KeyError(f"Quarantine entry #{entry_id} not found")
        entry_snapshot = {
            "id": int(entry.id),
            "device": int(entry.device),
            "inode": int(entry.inode),
            "size": int(entry.size),
            "mtime_ns": int(entry.mtime_ns),
            "content_hash": entry.content_hash,
            "original_path": entry.original_path,
            "quarantine_path": entry.quarantine_path,
        }

        if entry.state == "active" and entry.tx_phase == "active":
            manifest = build_unlink_manifest(entry, service.settings.quarantine_root)
            recovery_evidence: dict[str, Any] | None = None
        elif entry.state == "purged" and entry.tx_phase == "purged":
            manifest, recovery_evidence = _durable_terminal_recovery_evidence(
                session,
                entry=entry,
                quarantine_root=service.settings.quarantine_root,
            )
        else:
            raise StateConflictError(
                f"Cannot unlink-purge quarantine entry in state '{entry.state}' phase '{entry.tx_phase}'"
            )

    blockers = list(manifest.get("blockers") or [])
    if blockers:
        raise StateConflictError("UNLINK_MANIFEST_INVALID:" + ",".join(blockers))

    mutation = execute_journaled_unlink_purge(
        service.SessionLocal,
        entry_id=entry_id,
        quarantine_root=service.settings.quarantine_root,
        frozen_manifest=manifest,
    )
    audit_mutation = recovery_evidence if recovery_evidence is not None else mutation
    advisory = _fresh_survivor_advisory(service, entry_snapshot=entry_snapshot)

    details = {
        "operation": OPERATION_ID,
        "purge_semantics": SEMANTICS_VERSION,
        "quarantine_entry_id": entry_id,
        "frozen_owned_roles": [str(item["role"]) for item in manifest["owned_paths"]],
        "removed_roles": list(audit_mutation.get("removed_roles") or []),
        "recovered_missing_roles": list(
            audit_mutation.get("recovered_missing_roles") or []
        ),
        "survivor_scope": advisory["survivor_scope"],
        "survivor_status": advisory["survivor_status"],
        "hardlink_survivor_count": advisory["hardlink_survivor_count"],
        "hardlink_survivor_paths": advisory["hardlink_survivor_paths"],
        "independent_copy_count": advisory["independent_copy_count"],
        "independent_copy_paths": advisory["independent_copy_paths"],
        "terminal_result": "purged",
    }
    _persist_single_terminal_audit(
        service,
        entry_id=entry_id,
        entry_snapshot=entry_snapshot,
        details=details,
    )

    return {
        "id": entry_id,
        "entry_id": entry_id,
        "state": "purged",
        "status": "purged",
        "purged": True,
        "purge_semantics": SEMANTICS_VERSION,
        "removed_count": int(mutation.get("removed_count") or 0),
        "removed_roles": list(mutation.get("removed_roles") or []),
        "recovered_missing_roles": list(mutation.get("recovered_missing_roles") or []),
        **advisory,
    }
