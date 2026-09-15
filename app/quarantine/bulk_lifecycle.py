from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy.orm import object_session

from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.exceptions import StateConflictError
from app.models import BatchPlanItem, QuarantineEntry
from app.quarantine.bulk import quarantine_entry_identity_material
from app.quarantine.purge import build_purge_topology_manifest, validate_purge_topology_manifest
from app.quarantine.candidate import qualify_candidate_anchor_fd
from app.quarantine.unlink_purge import SEMANTICS_VERSION, revalidate_unlink_manifest


def _entry_id(metadata_json: str | None) -> int:
    metadata = json.loads(metadata_json or "{}")
    entry_id = metadata.get("quarantine_entry_id")
    if not isinstance(entry_id, int) or isinstance(entry_id, bool) or entry_id <= 0:
        raise StateConflictError("Gate6-A plan item is missing a valid quarantine_entry_id")
    return entry_id


def _restore_metadata(metadata_json: str | None) -> dict[str, Any]:
    try:
        metadata = json.loads(metadata_json or "{}")
    except Exception as exc:
        raise StateConflictError("Gate6-A restore item metadata_json is malformed") from exc
    if not isinstance(metadata, dict):
        raise StateConflictError("Gate6-A restore item metadata_json is not an object")
    return metadata


def _unlink_metadata(metadata_json: str | None) -> dict[str, Any]:
    try:
        metadata = json.loads(metadata_json or "{}")
    except Exception as exc:
        raise StateConflictError("Gate6-A2 unlink item metadata_json is malformed") from exc
    if not isinstance(metadata, dict):
        raise StateConflictError("Gate6-A2 unlink item metadata_json is not an object")
    return metadata


def _gate6a2_unlink_binding_error(
    *,
    plan_metadata: dict[str, Any] | None,
    metadata: dict[str, Any],
    entry_id: int,
    source_path: str,
    entry: QuarantineEntry,
    frozen_expected: dict[str, Any] | None = None,
) -> str | None:
    if metadata.get("purge_semantics") != SEMANTICS_VERSION:
        return "Gate6-A2 unlink item purge_semantics is invalid"

    manifest = metadata.get("unlink_manifest")
    if not isinstance(manifest, dict):
        return "Gate6-A2 unlink item lacks its frozen unlink_manifest"
    if manifest.get("purge_semantics") != SEMANTICS_VERSION:
        return "Gate6-A2 unlink manifest purge_semantics is invalid"
    if manifest.get("selected_entry_id") != entry_id:
        return "Gate6-A2 unlink manifest selected entry disagrees with item authority"
    if manifest.get("blockers"):
        return "Gate6-A2 unlink manifest is already blocked"

    frozen_identity = metadata.get("entry_identity")
    if not isinstance(frozen_identity, dict):
        return "Gate6-A2 unlink item entry_identity is malformed"
    if frozen_identity.get("entry_id") != entry_id:
        return "Gate6-A2 unlink item entry_identity owner is invalid"

    if str(source_path) != str(entry.quarantine_path):
        return "Gate6-A2 unlink source_path disagrees with quarantine_entry_id owner"

    plan_meta = plan_metadata if isinstance(plan_metadata, dict) else {}
    if plan_meta.get("action") != "purge":
        return "Gate6-A2 unlink plan action is invalid"
    if plan_meta.get("purge_semantics") != SEMANTICS_VERSION:
        return "Gate6-A2 unlink plan purge_semantics is invalid"
    if metadata.get("preview_digest") != plan_meta.get("preview_digest"):
        return "Gate6-A2 unlink preview_digest disagrees with plan authority"

    selected_entry_ids = plan_meta.get("entry_ids")
    if not isinstance(selected_entry_ids, list):
        return "Gate6-A2 unlink plan entry_ids authority is malformed"
    if entry_id not in selected_entry_ids:
        return "Gate6-A2 unlink quarantine_entry_id is not in the frozen plan selection"

    current_identity = quarantine_entry_identity_material(entry)
    if current_identity != frozen_identity:
        return "Gate6-A2 unlink current qentry disagrees with frozen entry_identity"

    if frozen_expected is not None:
        expected_from_identity = {
            "device": frozen_identity.get("device"),
            "inode": frozen_identity.get("inode"),
            "size": frozen_identity.get("size"),
            "mtime_ns": frozen_identity.get("mtime_ns"),
            "content_hash": frozen_identity.get("content_hash"),
        }
        if frozen_expected != expected_from_identity:
            return "Gate6-A2 unlink frozen expected_* identity disagrees with item authority"

    return None


def _gate6a_restore_binding_error(
    *,
    plan_metadata: dict[str, Any] | None,
    metadata: dict[str, Any],
    entry_id: int,
    source_path: str,
    target_path: str | None,
    entry: QuarantineEntry,
    item_id: int | None = None,
    frozen_expected: dict[str, Any] | None = None,
) -> str | None:
    if str(source_path) != str(entry.quarantine_path):
        return "Gate6-A restore source_path disagrees with quarantine_entry_id owner"

    plan_meta = plan_metadata if isinstance(plan_metadata, dict) else {}
    plan_policy = plan_meta.get("conflict_policy")
    if plan_policy in {"skip", "rename"} and metadata.get("conflict_policy") != plan_policy:
        return "Gate6-A restore conflict_policy disagrees with plan authority"

    plan_preview_digest = plan_meta.get("preview_digest")
    if isinstance(plan_preview_digest, str) and metadata.get("preview_digest") != plan_preview_digest:
        return "Gate6-A restore preview_digest disagrees with plan authority"

    selected_entry_ids = plan_meta.get("entry_ids")
    if selected_entry_ids is not None:
        if not isinstance(selected_entry_ids, list):
            return "Gate6-A restore plan entry_ids authority is malformed"
        if entry_id not in selected_entry_ids:
            return "Gate6-A restore quarantine_entry_id is not in the frozen plan selection"

    # New Gate6-A plans persist authority outside mutable BatchPlanItem fields, keyed by
    # the database-owned item id.  Freeze/Validate pass item_id explicitly.  At Execute,
    # the resolved qentry and the exact executing row are identity-mapped in the same
    # SQLAlchemy Session, so the helper can recover that stable row id without trusting
    # metadata_json/source_path/target_path.
    raw_item_authority = plan_meta.get("restore_item_authority")
    worker_item: BatchPlanItem | None = None
    resolved_item_id = item_id
    if raw_item_authority is not None:
        if not isinstance(raw_item_authority, dict):
            return "Gate6-A restore plan-level item authority is malformed"

        raw_metadata_qid = metadata.get("quarantine_entry_id")
        if not isinstance(raw_metadata_qid, int) or isinstance(raw_metadata_qid, bool) or raw_metadata_qid <= 0:
            return "Gate6-A restore item lost valid quarantine_entry_id authority"
        if raw_metadata_qid != entry_id:
            return "Gate6-A restore item quarantine_entry_id disagrees with frozen recovery authority"

        if resolved_item_id is None:
            session = object_session(entry)
            if session is not None:
                executing_rows = [
                    obj
                    for obj in session.identity_map.values()
                    if isinstance(obj, BatchPlanItem)
                    and obj.operation == "restore"
                    and obj.state == "executing"
                ]
                if len(executing_rows) == 1:
                    worker_item = executing_rows[0]
                    resolved_item_id = int(worker_item.id)
                elif len(executing_rows) > 1:
                    return "Gate6-A restore executing plan-item authority is ambiguous"

        if resolved_item_id is None:
            return "Gate6-A restore could not resolve frozen plan-item authority"

        item_authority = raw_item_authority.get(str(resolved_item_id))
        if not isinstance(item_authority, dict):
            return "Gate6-A restore frozen plan-item authority record is missing or malformed"

        if item_authority.get("quarantine_entry_id") != entry_id:
            return "Gate6-A restore quarantine_entry_id disagrees with frozen plan-item authority"

        expected_authority = {
            "source_path": str(source_path),
            "target_path": str(target_path or ""),
            "conflict_policy": metadata.get("conflict_policy"),
            "preview_digest": metadata.get("preview_digest"),
            "skip_preexisting_target": metadata.get("skip_preexisting_target") is True,
        }
        for key, current in expected_authority.items():
            if item_authority.get(key) != current:
                return f"Gate6-A restore frozen plan-item authority disagrees on {key}"

        entry_identity = item_authority.get("entry_identity")
        if not isinstance(entry_identity, dict):
            return "Gate6-A restore frozen qentry identity authority is malformed"
        current_entry_identity = quarantine_entry_identity_material(entry)
        stable_identity_keys = (
            "entry_id",
            "original_path",
            "quarantine_path",
            "authoritative_anchor_path",
            "active_attempt_generation",
            "device",
            "inode",
            "size",
            "mtime_ns",
            "content_hash",
        )
        if any(
            current_entry_identity.get(key) != entry_identity.get(key)
            for key in stable_identity_keys
        ):
            return "Gate6-A restore current qentry disagrees with frozen plan-item identity authority"

        effective_frozen_expected = frozen_expected
        if effective_frozen_expected is None and worker_item is not None:
            effective_frozen_expected = {
                "device": worker_item.expected_device,
                "inode": worker_item.expected_inode,
                "size": worker_item.expected_size,
                "mtime_ns": worker_item.expected_mtime_ns,
                "content_hash": worker_item.expected_hash,
            }
        if effective_frozen_expected is not None:
            authority_expected = {
                "device": entry_identity.get("device"),
                "inode": entry_identity.get("inode"),
                "size": entry_identity.get("size"),
                "mtime_ns": entry_identity.get("mtime_ns"),
                "content_hash": entry_identity.get("content_hash"),
            }
            if effective_frozen_expected != authority_expected:
                return "Gate6-A restore frozen expected_* identity disagrees with plan-item authority"

    raw_authority = plan_meta.get("restore_skip_authority", {})
    if raw_authority is None:
        raw_authority = {}
    if not isinstance(raw_authority, dict):
        return "Gate6-A restore plan-level skip authority is malformed"

    authority = raw_authority.get(str(entry_id))
    declared_skip = metadata.get("skip_preexisting_target") is True
    authorized_skip = authority is not None
    if declared_skip != authorized_skip:
        return "Gate6-A restore frozen skip authority mismatch"
    if not declared_skip:
        return None
    if not isinstance(authority, dict):
        return "Gate6-A restore frozen skip authority record is malformed"

    expected_authority = {
        "source_path": str(source_path),
        "target_path": str(target_path or ""),
        "conflict_policy": metadata.get("conflict_policy"),
        "preview_digest": metadata.get("preview_digest"),
    }
    for key, expected in expected_authority.items():
        if authority.get(key) != expected:
            return f"Gate6-A restore frozen skip authority disagrees on {key}"
    if metadata.get("conflict_policy") != "skip":
        return "Gate6-A restore frozen skip authority requires conflict_policy=skip"
    if str(target_path or "") != str(entry.original_path):
        return "Gate6-A restore frozen skip target disagrees with quarantine original_path"
    return None


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


def _unlink_frozen_identity_updates(identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "expected_device": int(identity["device"]),
        "expected_inode": int(identity["inode"]),
        "expected_size": int(identity["size"]),
        "expected_mtime_ns": int(identity["mtime_ns"]),
        "expected_hash": identity.get("content_hash"),
    }


def freeze_bulk_plan_item(
    service,
    *,
    plan_kind: str,
    item: dict[str, Any],
    plan_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return plan-item Freeze updates for Gate6-A kinds, or None when not owned here."""
    if plan_kind == "quarantine-bulk-purge" and item.get("operation") == "quarantine_unlink_purge":
        metadata = _unlink_metadata(item.get("metadata_json"))
        entry_id = _entry_id(item.get("metadata_json"))
        manifest = metadata.get("unlink_manifest")

        with service.SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            if entry is None:
                raise StateConflictError(f"Quarantine entry #{entry_id} no longer exists at Freeze")
            if entry.state != "active":
                raise StateConflictError(
                    f"Quarantine entry #{entry_id} is no longer active at Freeze (state={entry.state})"
                )

            binding_error = _gate6a2_unlink_binding_error(
                plan_metadata=plan_metadata,
                metadata=metadata,
                entry_id=entry_id,
                source_path=str(item.get("source_path") or ""),
                entry=entry,
            )
            if binding_error is not None:
                raise StateConflictError(binding_error)

            assert isinstance(manifest, dict)
            validation = revalidate_unlink_manifest(
                entry,
                service.settings.quarantine_root,
                manifest,
            )
            if not validation["valid"]:
                blockers = ",".join(validation["blockers"])
                raise StateConflictError(
                    f"UNLINK_AUTHORITY_CHANGED: unlink authority changed for quarantine entry #{entry_id}: {blockers}"
                )

            frozen_identity = metadata["entry_identity"]
            assert isinstance(frozen_identity, dict)
            updates = _unlink_frozen_identity_updates(frozen_identity)

        return {
            **updates,
            "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        }

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
            topology_reason = validate_purge_topology_manifest(stored_manifest, current_manifest)
            if topology_reason is not None:
                if topology_reason == "PURGE_TOPOLOGY_CHANGED":
                    raise StateConflictError(
                        f"PURGE_TOPOLOGY_CHANGED: purge topology changed for quarantine entry #{entry_id}"
                    )
                raise StateConflictError(
                    f"{topology_reason}: purge topology is no longer eligible for quarantine entry #{entry_id}"
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

    metadata = _restore_metadata(item.get("metadata_json"))
    entry_id = _entry_id(item.get("metadata_json"))

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        if entry is None:
            raise StateConflictError(f"Quarantine entry #{entry_id} no longer exists at Freeze")
        if entry.state != "active":
            raise StateConflictError(
                f"Quarantine entry #{entry_id} is no longer active at Freeze (state={entry.state})"
            )
        binding_error = _gate6a_restore_binding_error(
            plan_metadata=plan_metadata,
            metadata=metadata,
            entry_id=entry_id,
            source_path=str(item.get("source_path") or ""),
            target_path=item.get("target_path"),
            entry=entry,
            item_id=int(item.get("id")),
        )
        if binding_error is not None:
            raise StateConflictError(binding_error)
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


def validate_bulk_plan_item(
    service,
    *,
    plan_kind: str,
    item: Any,
    plan_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Validate one frozen Gate6-A item without mutating quarantine state or payload."""
    if plan_kind == "quarantine-bulk-purge" and item.operation == "quarantine_unlink_purge":
        try:
            metadata = _unlink_metadata(item.metadata_json)
            entry_id = _entry_id(item.metadata_json)
        except StateConflictError as exc:
            return {
                "state": "stale",
                "reason": "UNLINK_AUTHORITY_INVALID",
                "actual": {"error": str(exc)},
            }

        manifest = metadata.get("unlink_manifest")
        with service.SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            if entry is None:
                return {
                    "state": "stale",
                    "reason": "UNLINK_AUTHORITY_CHANGED",
                    "actual": {"blockers": ["QUARANTINE_ENTRY_MISSING"]},
                }
            if entry.state != "active":
                return {
                    "state": "stale",
                    "reason": "UNLINK_AUTHORITY_CHANGED",
                    "actual": {"blockers": ["ENTRY_NOT_ACTIVE"]},
                }

            binding_error = _gate6a2_unlink_binding_error(
                plan_metadata=plan_metadata,
                metadata=metadata,
                entry_id=entry_id,
                source_path=str(item.source_path),
                entry=entry,
                frozen_expected={
                    "device": item.expected_device,
                    "inode": item.expected_inode,
                    "size": item.expected_size,
                    "mtime_ns": item.expected_mtime_ns,
                    "content_hash": item.expected_hash,
                },
            )
            if binding_error is not None:
                return {
                    "state": "stale",
                    "reason": "UNLINK_AUTHORITY_CHANGED",
                    "actual": {"blockers": [binding_error]},
                }

            if not isinstance(manifest, dict):
                return {
                    "state": "stale",
                    "reason": "UNLINK_AUTHORITY_CHANGED",
                    "actual": {"blockers": ["INVALID_UNLINK_MANIFEST"]},
                }

            validation = revalidate_unlink_manifest(
                entry,
                service.settings.quarantine_root,
                manifest,
            )
            if not validation["valid"]:
                return {
                    "state": "stale",
                    "reason": "UNLINK_AUTHORITY_CHANGED",
                    "actual": {"blockers": list(validation["blockers"])},
                }

        return {
            "state": "validated",
            "reason": "bulk unlink purge validated",
            "actual": None,
        }

    if plan_kind == "quarantine-bulk-purge" and item.operation == "quarantine_purge":
        metadata = json.loads(item.metadata_json or "{}")
        entry_id = _entry_id(item.metadata_json)
        frozen_manifest = metadata.get("frozen_purge_topology_manifest")
        if not isinstance(frozen_manifest, dict):
            return {
                "state": "stale",
                "reason": "PURGE_TOPOLOGY_CHANGED",
                "actual": {"error": "missing frozen purge topology manifest"},
            }

        with service.SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            if entry is None:
                return {
                    "state": "stale",
                    "reason": "PURGE_QUALIFICATION_FAILED",
                    "actual": {"error": "quarantine entry missing"},
                }
            if entry.state != "active":
                return {
                    "state": "stale",
                    "reason": "PURGE_QUALIFICATION_FAILED",
                    "actual": {"state": entry.state, "tx_phase": entry.tx_phase},
                }

            current_manifest = build_purge_topology_manifest(
                entry,
                service.settings.quarantine_root,
                owner_lookup=lambda owner_id: session.get(QuarantineEntry, owner_id),
            )
            topology_reason = validate_purge_topology_manifest(frozen_manifest, current_manifest)
            if topology_reason is not None:
                return {
                    "state": "stale",
                    "reason": topology_reason,
                    "actual": {"purge_topology_manifest": current_manifest},
                }
            if not entry.authoritative_anchor_path:
                return {
                    "state": "stale",
                    "reason": "PURGE_QUALIFICATION_FAILED",
                    "actual": {"error": "authoritative anchor missing"},
                }
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
                "reason": "PURGE_QUALIFICATION_FAILED",
                "actual": {"error": str(exc)},
            }

        return {"state": "validated", "reason": "bulk purge validated", "actual": None}

    if plan_kind != "quarantine-bulk-restore" or item.operation != "restore":
        return None

    try:
        metadata = _restore_metadata(item.metadata_json)
        entry_id = _entry_id(item.metadata_json)
    except StateConflictError as exc:
        return {
            "state": "stale",
            "reason": "restore_frozen_authority_invalid",
            "actual": {"error": str(exc)},
        }

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
        binding_error = _gate6a_restore_binding_error(
            plan_metadata=plan_metadata,
            metadata=metadata,
            entry_id=entry_id,
            source_path=str(item.source_path),
            target_path=item.target_path,
            entry=entry,
            item_id=int(item.id),
            frozen_expected={
                "device": item.expected_device,
                "inode": item.expected_inode,
                "size": item.expected_size,
                "mtime_ns": item.expected_mtime_ns,
                "content_hash": item.expected_hash,
            },
        )
        if binding_error is not None:
            return {
                "state": "stale",
                "reason": f"restore_frozen_authority_invalid: {binding_error}",
                "actual": {"error": binding_error},
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

    if metadata.get("skip_preexisting_target") is True:
        return {
            "state": "validated",
            "reason": "bulk restore frozen pre-existing target skip",
            "actual": {"target_path": str(item.target_path)},
        }

    target = Path(item.target_path)
    if os.path.lexists(target):
        return {
            "state": "stale",
            "reason": "restore_target_occupied",
            "actual": {"target_path": str(target)},
        }

    return {"state": "validated", "reason": "bulk restore validated", "actual": None}
