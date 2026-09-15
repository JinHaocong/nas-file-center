from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.exceptions import StateConflictError
from app.models import (
    AuditEvent,
    DuplicateFile,
    DuplicateGroup,
    IndexRoot,
    IndexedPath,
    QuarantineEntry,
)
from app.quarantine.unlink_purge import (
    OPERATION_ID,
    SEMANTICS_VERSION,
    build_unlink_manifest,
    execute_journaled_unlink_purge,
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
        if entry.state != "active" or entry.tx_phase != "active":
            raise StateConflictError(
                f"Cannot unlink-purge quarantine entry in state '{entry.state}' phase '{entry.tx_phase}'"
            )
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
        manifest = build_unlink_manifest(entry, service.settings.quarantine_root)

    blockers = list(manifest.get("blockers") or [])
    if blockers:
        raise StateConflictError("UNLINK_MANIFEST_INVALID:" + ",".join(blockers))

    mutation = execute_journaled_unlink_purge(
        service.SessionLocal,
        entry_id=entry_id,
        quarantine_root=service.settings.quarantine_root,
        frozen_manifest=manifest,
    )
    advisory = _fresh_survivor_advisory(service, entry_snapshot=entry_snapshot)

    details = {
        "operation": OPERATION_ID,
        "purge_semantics": SEMANTICS_VERSION,
        "quarantine_entry_id": entry_id,
        "frozen_owned_roles": [str(item["role"]) for item in manifest["owned_paths"]],
        "removed_roles": list(mutation.get("removed_roles") or []),
        "recovered_missing_roles": list(mutation.get("recovered_missing_roles") or []),
        "survivor_scope": advisory["survivor_scope"],
        "survivor_status": advisory["survivor_status"],
        "hardlink_survivor_count": advisory["hardlink_survivor_count"],
        "hardlink_survivor_paths": advisory["hardlink_survivor_paths"],
        "independent_copy_count": advisory["independent_copy_count"],
        "terminal_result": "purged",
    }
    with service.SessionLocal() as session:
        session.add(
            AuditEvent(
                operation=OPERATION_ID,
                path=str(entry_snapshot["quarantine_path"]),
                result="purged",
                details_json=json.dumps(details, ensure_ascii=False, sort_keys=True),
            )
        )
        session.commit()

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
