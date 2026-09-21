from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import time
from typing import Any, Iterable

from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from app.batch.plans import OperationItem
from app.batch_utilities.empty_dir_quarantine import safe_open_parent_fd
from app.config import Settings
from app.exceptions import StateConflictError
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    IndexedPath,
    MediaAsset,
    OperationJournal,
    utcnow,
)
from app.path_safety import is_reserved_quarantine_path, require_allowed_path


OPERATION_ID = "media_corrupt_unlink_delete"
SEMANTICS_VERSION = "media_corrupt_unlink_v1"
PLAN_KIND = "media-corrupt-delete"
CONFIRMATION_TOKEN = "DELETE_CORRUPT_FILES"
_HASH_CHUNK_BYTES = 8 * 1024 * 1024


def _json(payload: Any) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(payload: Any) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _mtime_ns(st: os.stat_result) -> int:
    return int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))


def _identity_payload(
    *,
    path: str,
    device: int,
    inode: int,
    size: int,
    mtime_ns: int,
    content_hash: str,
) -> dict[str, Any]:
    return {
        "path": path,
        "object_type": "regular_file",
        "device": int(device),
        "inode": int(inode),
        "size": int(size),
        "mtime_ns": int(mtime_ns),
        "sha256": content_hash.lower(),
    }


def _build_evidence(asset: MediaAsset, indexed: IndexedPath) -> dict[str, Any]:
    return {
        "semantics": SEMANTICS_VERSION,
        "media_asset_id": int(asset.id),
        "indexed_path_id": int(indexed.id),
        "path": indexed.absolute_path,
        "device": int(asset.observed_device),
        "inode": int(asset.observed_inode),
        "size": int(asset.observed_size),
        "mtime_ns": int(asset.observed_mtime_ns),
        "sha256": str(asset.corrupt_sha256 or "").lower(),
        "probe_generation": asset.probe_generation,
        "integrity_status": asset.integrity_status,
        "integrity_reason_code": asset.integrity_reason_code,
    }


def _live_identity_blockers(
    *,
    evidence: dict[str, Any],
    settings: Settings,
) -> list[str]:
    blockers: list[str] = []
    raw_path = Path(str(evidence["path"]))
    if raw_path.is_symlink() or os.path.islink(raw_path):
        return ["SOURCE_SYMLINK"]

    try:
        source = require_allowed_path(raw_path, settings.allowed_roots)
    except Exception:
        return ["SOURCE_OUTSIDE_ALLOWED_ROOTS"]

    if is_reserved_quarantine_path(source, settings.quarantine_root):
        blockers.append("SOURCE_IN_QUARANTINE")

    try:
        st = os.lstat(source)
    except FileNotFoundError:
        blockers.append("SOURCE_MISSING")
        return blockers
    except OSError:
        blockers.append("SOURCE_UNREADABLE")
        return blockers

    if stat.S_ISLNK(st.st_mode):
        blockers.append("SOURCE_SYMLINK")
    elif not stat.S_ISREG(st.st_mode):
        blockers.append("SOURCE_NOT_REGULAR")

    if (
        int(st.st_dev) != int(evidence["device"])
        or int(st.st_ino) != int(evidence["inode"])
        or int(st.st_size) != int(evidence["size"])
        or _mtime_ns(st) != int(evidence["mtime_ns"])
    ):
        blockers.append("SOURCE_IDENTITY_CHANGED")

    return blockers


def build_corrupt_delete_preview(
    session_factory: sessionmaker,
    settings: Settings,
    asset_ids: list[int],
) -> dict[str, Any]:
    if not asset_ids:
        raise ValueError("media_asset_ids must not be empty")
    if len(asset_ids) > 5000:
        raise ValueError("media_asset_ids exceeds maximum of 5000")
    normalized = [int(value) for value in asset_ids]
    if any(value <= 0 for value in normalized):
        raise ValueError("media_asset_ids must contain positive integers")
    if len(set(normalized)) != len(normalized):
        raise ValueError("media_asset_ids must be unique")

    with session_factory() as session:
        rows = session.execute(
            select(MediaAsset, IndexedPath)
            .join(IndexedPath, IndexedPath.id == MediaAsset.indexed_path_id)
            .where(MediaAsset.id.in_(normalized))
        ).all()
        by_id = {int(asset.id): (asset, indexed) for asset, indexed in rows}

        items: list[dict[str, Any]] = []
        for asset_id in normalized:
            pair = by_id.get(asset_id)
            if pair is None:
                items.append({
                    "media_asset_id": asset_id,
                    "eligible": False,
                    "blockers": ["MEDIA_ASSET_NOT_FOUND"],
                })
                continue

            asset, indexed = pair
            evidence = _build_evidence(asset, indexed)
            blockers: list[str] = []

            if asset.integrity_status != "corrupt":
                blockers.append("MEDIA_NOT_CORRUPT")
            if not _valid_sha256(asset.corrupt_sha256):
                blockers.append("CORRUPT_SHA256_MISSING")
            if (
                int(asset.observed_device) != int(indexed.device)
                or int(asset.observed_inode) != int(indexed.inode)
                or int(asset.observed_size) != int(indexed.size)
                or int(asset.observed_mtime_ns) != int(indexed.mtime_ns)
                or asset.source_scan_generation != indexed.scan_generation
            ):
                blockers.append("INDEX_EVIDENCE_CHANGED")

            blockers.extend(_live_identity_blockers(evidence=evidence, settings=settings))
            blockers = list(dict.fromkeys(blockers))
            evidence_digest = _digest(evidence)
            items.append({
                "media_asset_id": asset_id,
                "indexed_path_id": int(indexed.id),
                "path": indexed.absolute_path,
                "size": int(indexed.size),
                "media_kind": asset.media_kind,
                "integrity_status": asset.integrity_status,
                "integrity_reason_code": asset.integrity_reason_code,
                "evidence_digest": evidence_digest,
                "evidence": evidence,
                "eligible": not blockers,
                "blockers": blockers,
            })

    preview_material = {
        "semantics": SEMANTICS_VERSION,
        "selected_media_asset_ids": normalized,
        "items": [
            {
                "media_asset_id": item.get("media_asset_id"),
                "indexed_path_id": item.get("indexed_path_id"),
                "path": item.get("path"),
                "evidence_digest": item.get("evidence_digest"),
                "eligible": item.get("eligible"),
                "blockers": item.get("blockers"),
            }
            for item in items
        ],
    }
    return {
        "semantics": SEMANTICS_VERSION,
        "selected_media_asset_ids": normalized,
        "items": items,
        "eligible_count": sum(1 for item in items if item.get("eligible")),
        "blocked_count": sum(1 for item in items if not item.get("eligible")),
        "total_bytes": sum(
            int(item.get("size") or 0)
            for item in items
            if item.get("eligible")
        ),
        "preview_digest": _digest(preview_material),
    }


def create_corrupt_delete_plan(
    session_factory: sessionmaker,
    settings: Settings,
    *,
    asset_ids: list[int],
    expected_preview_digest: str,
    confirmation: str,
    requested_by_user_id: int | None,
) -> dict[str, Any]:
    if confirmation != CONFIRMATION_TOKEN:
        raise ValueError(
            f"Permanent corrupt-media deletion requires confirmation token '{CONFIRMATION_TOKEN}'"
        )
    if not settings.allow_mutation:
        raise StateConflictError("Filesystem mutation is disabled")
    if not settings.allow_delete:
        raise StateConflictError("Permanent deletion is disabled")

    preview = build_corrupt_delete_preview(session_factory, settings, asset_ids)
    if preview["preview_digest"] != expected_preview_digest:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_PREVIEW_CHANGED")
    blocked = [item for item in preview["items"] if not item["eligible"]]
    if blocked:
        raise StateConflictError(
            "MEDIA_CORRUPT_DELETE_BLOCKED: "
            + "; ".join(
                f"asset #{item['media_asset_id']}={','.join(item['blockers'])}"
                for item in blocked[:10]
            )
        )

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        now = utcnow()
        plan = BatchPlan(
            name=f"media-corrupt-delete-{now.strftime('%Y%m%d-%H%M%S')}",
            kind=PLAN_KIND,
            status="draft",
            expected_changes=len(preview["items"]),
            expected_reclaim_bytes=int(preview["total_bytes"]),
            metadata_json=_json({
                "action": "permanent_delete_corrupt_media",
                "semantics": SEMANTICS_VERSION,
                "preview_digest": preview["preview_digest"],
                "media_asset_ids": preview["selected_media_asset_ids"],
                "requested_by_user_id": requested_by_user_id,
                "bypasses_quarantine": True,
            }),
            created_at=now,
        )
        session.add(plan)
        session.flush()

        for sequence, item in enumerate(preview["items"], 1):
            evidence = item["evidence"]
            session.add(BatchPlanItem(
                plan_id=int(plan.id),
                sequence=sequence,
                operation=OPERATION_ID,
                source_path=str(evidence["path"]),
                target_path=None,
                keep_path=None,
                expected_size=int(evidence["size"]),
                expected_mtime_ns=int(evidence["mtime_ns"]),
                expected_device=int(evidence["device"]),
                expected_inode=int(evidence["inode"]),
                expected_hash=str(evidence["sha256"]),
                state="planned",
                reason=None,
                metadata_json=_json({
                    "media_asset_id": int(evidence["media_asset_id"]),
                    "indexed_path_id": int(evidence["indexed_path_id"]),
                    "probe_generation": evidence["probe_generation"],
                    "integrity_reason_code": evidence["integrity_reason_code"],
                    "evidence_digest": item["evidence_digest"],
                    "preview_digest": preview["preview_digest"],
                    "delete_semantics": SEMANTICS_VERSION,
                    "bypasses_quarantine": True,
                }),
            ))

        session.add(AuditEvent(
            operation="media_corrupt_delete_plan",
            path=None,
            result="created",
            details_json=_json({
                "plan_id": int(plan.id),
                "preview_digest": preview["preview_digest"],
                "media_asset_ids": preview["selected_media_asset_ids"],
                "expected_changes": len(preview["items"]),
                "expected_reclaim_bytes": int(preview["total_bytes"]),
                "semantics": SEMANTICS_VERSION,
                "bypasses_quarantine": True,
                "requested_by_user_id": requested_by_user_id,
            }),
        ))
        session.commit()
        return {
            "id": int(plan.id),
            "status": plan.status,
            "expected_changes": int(plan.expected_changes),
            "expected_reclaim_bytes": int(plan.expected_reclaim_bytes),
            "preview_digest": preview["preview_digest"],
        }


def _load_frozen_row(
    session,
    *,
    plan_id: int,
    operation_item: OperationItem | None = None,
    item_id: int | None = None,
) -> tuple[BatchPlan, BatchPlanItem, dict[str, Any], dict[str, Any], dict[str, Any]]:
    plan = session.get(BatchPlan, plan_id)
    if plan is None or plan.kind != PLAN_KIND:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_MISSING: plan")

    try:
        plan_meta = json.loads(plan.metadata_json or "{}")
    except Exception as exc:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_INVALID: plan metadata") from exc
    if not isinstance(plan_meta, dict):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_INVALID: plan metadata")
    if (
        plan_meta.get("semantics") != SEMANTICS_VERSION
        or plan_meta.get("action") != "permanent_delete_corrupt_media"
        or plan_meta.get("bypasses_quarantine") is not True
    ):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_CHANGED: plan semantics")

    if item_id is not None:
        row = session.get(BatchPlanItem, int(item_id))
        rows = [row] if row is not None and row.plan_id == plan_id else []
    elif operation_item is not None:
        rows = list(
            session.scalars(
                select(BatchPlanItem).where(
                    BatchPlanItem.plan_id == plan_id,
                    BatchPlanItem.sequence == operation_item.sequence,
                    BatchPlanItem.operation == OPERATION_ID,
                )
            )
        )
    else:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_MISSING: item selector")

    if len(rows) != 1 or rows[0] is None:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_MISSING: item")
    row = rows[0]
    if row.operation != OPERATION_ID:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_CHANGED: operation")

    if operation_item is not None:
        if row.source_path != str(operation_item.source):
            raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_CHANGED: source")
        for attr in (
            "expected_device",
            "expected_inode",
            "expected_size",
            "expected_mtime_ns",
            "expected_hash",
        ):
            if getattr(row, attr) != getattr(operation_item, attr):
                raise StateConflictError(
                    f"MEDIA_CORRUPT_DELETE_AUTHORITY_CHANGED: {attr}"
                )

    try:
        item_meta = json.loads(row.metadata_json or "{}")
    except Exception as exc:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_INVALID: item metadata") from exc
    if not isinstance(item_meta, dict):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_INVALID: item metadata")

    asset_id = item_meta.get("media_asset_id")
    indexed_id = item_meta.get("indexed_path_id")
    if (
        not isinstance(asset_id, int)
        or isinstance(asset_id, bool)
        or asset_id <= 0
        or not isinstance(indexed_id, int)
        or isinstance(indexed_id, bool)
        or indexed_id <= 0
        or item_meta.get("delete_semantics") != SEMANTICS_VERSION
        or item_meta.get("preview_digest") != plan_meta.get("preview_digest")
        or item_meta.get("bypasses_quarantine") is not True
        or not _valid_sha256(row.expected_hash)
    ):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_CHANGED: item semantics")

    manifest = {
        "semantics": SEMANTICS_VERSION,
        "plan_id": int(plan.id),
        "item_id": int(row.id),
        "sequence": int(row.sequence),
        "media_asset_id": int(asset_id),
        "indexed_path_id": int(indexed_id),
        "preview_digest": item_meta.get("preview_digest"),
        "evidence_digest": item_meta.get("evidence_digest"),
        "probe_generation": item_meta.get("probe_generation"),
        "integrity_reason_code": item_meta.get("integrity_reason_code"),
        "identity": _identity_payload(
            path=row.source_path,
            device=row.expected_device,
            inode=row.expected_inode,
            size=row.expected_size,
            mtime_ns=row.expected_mtime_ns,
            content_hash=str(row.expected_hash),
        ),
    }
    if not isinstance(manifest["evidence_digest"], str) or len(manifest["evidence_digest"]) != 64:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_CHANGED: evidence digest")
    return plan, row, plan_meta, item_meta, manifest


def _assert_live_media_evidence(
    session,
    *,
    row: BatchPlanItem,
    item_meta: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    asset = session.get(MediaAsset, manifest["media_asset_id"])
    indexed = session.get(IndexedPath, manifest["indexed_path_id"])
    if asset is None or indexed is None or int(asset.indexed_path_id) != int(indexed.id):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_EVIDENCE_MISSING")
    if asset.integrity_status != "corrupt":
        raise StateConflictError("MEDIA_CORRUPT_DELETE_EVIDENCE_CHANGED: status")
    if (
        asset.probe_generation != item_meta.get("probe_generation")
        or asset.corrupt_sha256 != row.expected_hash
        or indexed.absolute_path != row.source_path
        or int(asset.observed_device) != int(row.expected_device)
        or int(asset.observed_inode) != int(row.expected_inode)
        or int(asset.observed_size) != int(row.expected_size)
        or int(asset.observed_mtime_ns) != int(row.expected_mtime_ns)
        or int(indexed.device) != int(row.expected_device)
        or int(indexed.inode) != int(row.expected_inode)
        or int(indexed.size) != int(row.expected_size)
        or int(indexed.mtime_ns) != int(row.expected_mtime_ns)
        or asset.source_scan_generation != indexed.scan_generation
    ):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_EVIDENCE_CHANGED: identity")

    evidence = _build_evidence(asset, indexed)
    if _digest(evidence) != manifest["evidence_digest"]:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_EVIDENCE_CHANGED: digest")



def assert_corrupt_delete_frozen_evidence_current(
    session_factory: sessionmaker,
    settings: Settings,
    *,
    plan_id: int,
    item_id: int,
) -> dict[str, Any]:
    """Read-only evidence fence used by Plan Validate before generic SHA256 freshness."""
    with session_factory() as session:
        _plan, row, _plan_meta, item_meta, manifest = _load_frozen_row(
            session,
            plan_id=plan_id,
            item_id=item_id,
        )
        _assert_live_media_evidence(
            session,
            row=row,
            item_meta=item_meta,
            manifest=manifest,
        )
    _source_stat_exact(
        manifest["identity"],
        allowed_roots=settings.allowed_roots,
        quarantine_root=settings.quarantine_root,
    )
    return manifest


def _journal_payload(row: OperationJournal) -> dict[str, Any]:
    try:
        value = json.loads(row.before_json or "{}")
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _journals(session, item_id: int) -> list[OperationJournal]:
    return list(
        session.scalars(
            select(OperationJournal)
            .where(
                OperationJournal.operation == OPERATION_ID,
                OperationJournal.plan_item_id == item_id,
            )
            .order_by(OperationJournal.id.asc())
        )
    )


def _phase_journal(
    rows: list[OperationJournal],
    *,
    phase: str,
    manifest: dict[str, Any],
) -> OperationJournal | None:
    found: list[OperationJournal] = []
    for row in rows:
        payload = _journal_payload(row)
        if payload.get("phase") != phase:
            continue
        if payload.get("manifest") != manifest:
            raise StateConflictError("MEDIA_CORRUPT_DELETE_JOURNAL_AUTHORITY_CHANGED")
        found.append(row)
    if len(found) > 1:
        raise StateConflictError(f"MEDIA_CORRUPT_DELETE_JOURNAL_DUPLICATE_{phase.upper()}")
    return found[0] if found else None


def _task_user_authority(
    plan_meta: dict[str, Any],
    item_meta: dict[str, Any],
) -> tuple[int, int | None]:
    execution = item_meta.get("execution")
    task_id = execution.get("task_id") if isinstance(execution, dict) else None
    if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_TASK_AUTHORITY_MISSING")
    raw_user = plan_meta.get("requested_by_user_id")
    user_id = (
        int(raw_user)
        if isinstance(raw_user, int) and not isinstance(raw_user, bool) and raw_user > 0
        else None
    )
    return task_id, user_id


def _source_stat_exact(
    identity: dict[str, Any],
    *,
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str,
) -> os.stat_result:
    raw_path = Path(str(identity["path"]))
    if raw_path.is_symlink() or os.path.islink(raw_path):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_SOURCE_SYMLINK")
    source = require_allowed_path(raw_path, allowed_roots)
    if is_reserved_quarantine_path(source, quarantine_root):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_SOURCE_IN_QUARANTINE")

    try:
        st = os.lstat(source)
    except FileNotFoundError as exc:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_SOURCE_MISSING") from exc
    if (
        not stat.S_ISREG(st.st_mode)
        or stat.S_ISLNK(st.st_mode)
        or int(st.st_dev) != int(identity["device"])
        or int(st.st_ino) != int(identity["inode"])
        or int(st.st_size) != int(identity["size"])
        or _mtime_ns(st) != int(identity["mtime_ns"])
    ):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_SOURCE_IDENTITY_CHANGED")
    return st


def _hash_open_fd(fd: int, *, session_factory: sessionmaker, worker_id: str) -> str:
    from app.tasks.recovery import renew_and_assert_worker_lease

    digest = hashlib.sha256()
    last_fence = time.monotonic()
    while True:
        chunk = os.read(fd, _HASH_CHUNK_BYTES)
        if not chunk:
            break
        digest.update(chunk)
        if time.monotonic() - last_fence >= 2.0:
            renew_and_assert_worker_lease(session_factory, worker_id)
            last_fence = time.monotonic()
    return digest.hexdigest()


def _unlink_exact_manifest(
    manifest: dict[str, Any],
    *,
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str,
    session_factory: sessionmaker,
    worker_id: str,
) -> str:
    from app.tasks.recovery import renew_and_assert_worker_lease

    identity = manifest["identity"]
    raw_path = Path(identity["path"])
    if raw_path.is_symlink() or os.path.islink(raw_path):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_SOURCE_SYMLINK")

    source = require_allowed_path(raw_path, allowed_roots)
    if is_reserved_quarantine_path(source, quarantine_root):
        raise StateConflictError("MEDIA_CORRUPT_DELETE_SOURCE_IN_QUARANTINE")

    with safe_open_parent_fd(source, allowed_roots) as (parent_fd, leaf):
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(leaf, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            return "absent_after_intent"

        try:
            before = os.fstat(fd)
            if (
                not stat.S_ISREG(before.st_mode)
                or int(before.st_dev) != int(identity["device"])
                or int(before.st_ino) != int(identity["inode"])
                or int(before.st_size) != int(identity["size"])
                or _mtime_ns(before) != int(identity["mtime_ns"])
            ):
                raise StateConflictError("MEDIA_CORRUPT_DELETE_SOURCE_IDENTITY_CHANGED")

            actual_hash = _hash_open_fd(
                fd,
                session_factory=session_factory,
                worker_id=worker_id,
            )
            after = os.fstat(fd)
            if (
                int(after.st_dev) != int(identity["device"])
                or int(after.st_ino) != int(identity["inode"])
                or int(after.st_size) != int(identity["size"])
                or _mtime_ns(after) != int(identity["mtime_ns"])
            ):
                raise StateConflictError("MEDIA_CORRUPT_DELETE_SOURCE_CHANGED_DURING_HASH")
            if actual_hash != identity["sha256"]:
                raise StateConflictError("MEDIA_CORRUPT_DELETE_SOURCE_HASH_CHANGED")
        finally:
            os.close(fd)

        renew_and_assert_worker_lease(session_factory, worker_id)
        try:
            immediate = os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return "absent_after_intent"
        if (
            not stat.S_ISREG(immediate.st_mode)
            or int(immediate.st_dev) != int(identity["device"])
            or int(immediate.st_ino) != int(identity["inode"])
            or int(immediate.st_size) != int(identity["size"])
            or _mtime_ns(immediate) != int(identity["mtime_ns"])
        ):
            raise StateConflictError("MEDIA_CORRUPT_DELETE_SOURCE_CHANGED_BEFORE_UNLINK")

        os.unlink(leaf, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return "unlinked_by_nfc"


def _ensure_terminal_audit(
    session,
    *,
    manifest: dict[str, Any],
    task_id: int,
    user_id: int | None,
    terminal_result: str,
) -> None:
    existing = list(
        session.scalars(
            select(AuditEvent).where(
                AuditEvent.operation == OPERATION_ID,
                AuditEvent.result == "completed",
            )
        )
    )
    for event in existing:
        try:
            details = json.loads(event.details_json or "{}")
        except Exception:
            continue
        if (
            isinstance(details, dict)
            and details.get("plan_id") == manifest["plan_id"]
            and details.get("item_id") == manifest["item_id"]
            and details.get("evidence_digest") == manifest["evidence_digest"]
        ):
            return

    session.add(AuditEvent(
        operation=OPERATION_ID,
        path=manifest["identity"]["path"],
        result="completed",
        details_json=_json({
            "plan_id": manifest["plan_id"],
            "item_id": manifest["item_id"],
            "task_id": task_id,
            "user_id": user_id,
            "media_asset_id": manifest["media_asset_id"],
            "indexed_path_id": manifest["indexed_path_id"],
            "preview_digest": manifest["preview_digest"],
            "evidence_digest": manifest["evidence_digest"],
            "integrity_reason_code": manifest["integrity_reason_code"],
            "semantics": SEMANTICS_VERSION,
            "terminal_result": terminal_result,
            "bypassed_quarantine": True,
            "sha256": manifest["identity"]["sha256"],
        }),
    ))


def _finalize_terminal(
    session,
    *,
    row: BatchPlanItem,
    manifest: dict[str, Any],
    task_id: int,
    user_id: int | None,
    terminal_result: str,
    now,
) -> None:
    journals = _journals(session, int(row.id))
    if _phase_journal(journals, phase="terminal", manifest=manifest) is None:
        session.add(OperationJournal(
            operation=OPERATION_ID,
            sequence=int(row.sequence),
            plan_id=int(row.plan_id),
            plan_item_id=int(row.id),
            task_id=task_id,
            user_id=user_id,
            before_json=_json({
                "phase": "terminal",
                "manifest": manifest,
            }),
            after_json=_json({
                "phase": "deleted",
                "terminal_result": terminal_result,
                "path": None,
            }),
            metadata_before_json=_json(manifest["identity"]),
            metadata_after_json="{}",
            created_at=now,
        ))

    indexed = session.get(IndexedPath, manifest["indexed_path_id"])
    if indexed is not None:
        if (
            indexed.absolute_path == manifest["identity"]["path"]
            and int(indexed.device) == int(manifest["identity"]["device"])
            and int(indexed.inode) == int(manifest["identity"]["inode"])
            and int(indexed.size) == int(manifest["identity"]["size"])
            and int(indexed.mtime_ns) == int(manifest["identity"]["mtime_ns"])
        ):
            session.delete(indexed)

    _ensure_terminal_audit(
        session,
        manifest=manifest,
        task_id=task_id,
        user_id=user_id,
        terminal_result=terminal_result,
    )
    row.state = "completed"
    row.reason = (
        "permanently deleted corrupt media without quarantine"
        if terminal_result == "unlinked_by_nfc"
        else "source absent after durable corrupt-media delete intent"
    )


def execute_corrupt_media_delete(
    operation_item: OperationItem,
    *,
    plan_id: str,
    allowed_roots: Iterable[Path | str],
    quarantine_root: Path | str,
    session_factory: sessionmaker,
    worker_id: str,
) -> str:
    from app.tasks.recovery import assert_active_worker_lease

    try:
        numeric_plan_id = int(plan_id)
    except (TypeError, ValueError) as exc:
        raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_MISSING: invalid plan id") from exc

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        now = utcnow()
        assert_active_worker_lease(session, worker_id, now=now)
        plan, row, plan_meta, item_meta, manifest = _load_frozen_row(
            session,
            plan_id=numeric_plan_id,
            operation_item=operation_item,
        )
        task_id, user_id = _task_user_authority(plan_meta, item_meta)
        journals = _journals(session, int(row.id))
        terminal = _phase_journal(journals, phase="terminal", manifest=manifest)
        if terminal is not None:
            row.state = "completed"
            row.reason = "already permanently deleted corrupt media"
            _ensure_terminal_audit(
                session,
                manifest=manifest,
                task_id=task_id,
                user_id=user_id,
                terminal_result="terminal_recovered",
            )
            session.commit()
            return row.reason

        intent = _phase_journal(journals, phase="intent", manifest=manifest)
        if intent is None:
            _assert_live_media_evidence(
                session,
                row=row,
                item_meta=item_meta,
                manifest=manifest,
            )
            _source_stat_exact(
                manifest["identity"],
                allowed_roots=allowed_roots,
                quarantine_root=quarantine_root,
            )
            session.add(OperationJournal(
                operation=OPERATION_ID,
                sequence=int(row.sequence),
                plan_id=numeric_plan_id,
                plan_item_id=int(row.id),
                task_id=task_id,
                user_id=user_id,
                before_json=_json({
                    "phase": "intent",
                    "manifest": manifest,
                }),
                after_json="{}",
                metadata_before_json=_json(manifest["identity"]),
                metadata_after_json="{}",
                created_at=now,
            ))
        session.commit()

    terminal_result = _unlink_exact_manifest(
        manifest,
        allowed_roots=allowed_roots,
        quarantine_root=quarantine_root,
        session_factory=session_factory,
        worker_id=worker_id,
    )

    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        now = utcnow()
        assert_active_worker_lease(session, worker_id, now=now)
        _plan, row, plan_meta, item_meta, frozen_manifest = _load_frozen_row(
            session,
            plan_id=numeric_plan_id,
            item_id=manifest["item_id"],
        )
        if frozen_manifest != manifest:
            raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_CHANGED: terminal manifest")
        task_id, user_id = _task_user_authority(plan_meta, item_meta)
        journals = _journals(session, int(row.id))
        if _phase_journal(journals, phase="intent", manifest=manifest) is None:
            raise StateConflictError("MEDIA_CORRUPT_DELETE_INTENT_MISSING")
        _finalize_terminal(
            session,
            row=row,
            manifest=manifest,
            task_id=task_id,
            user_id=user_id,
            terminal_result=terminal_result,
            now=now,
        )
        session.commit()

    return (
        "permanently deleted corrupt media without quarantine"
        if terminal_result == "unlinked_by_nfc"
        else "source absent after durable corrupt-media delete intent"
    )


def reconcile_corrupt_media_delete(
    session,
    item: BatchPlanItem,
    plan_id: int,
    job_id: int,
    user_id: int | None,
    settings: Settings,
    now,
    **_kwargs: Any,
) -> bool:
    if item.operation != OPERATION_ID:
        return False

    try:
        _plan, row, _plan_meta, item_meta, manifest = _load_frozen_row(
            session,
            plan_id=plan_id,
            item_id=int(item.id),
        )
        if row.source_path != item.source_path:
            raise StateConflictError("MEDIA_CORRUPT_DELETE_AUTHORITY_CHANGED: recovery source")
        journals = _journals(session, int(item.id))
        terminal = _phase_journal(journals, phase="terminal", manifest=manifest)
        intent = _phase_journal(journals, phase="intent", manifest=manifest)
    except Exception as exc:
        item.state = "failed"
        item.reason = f"corrupt-media delete reconciliation authority invalid: {exc}"
        return True

    if terminal is not None:
        _finalize_terminal(
            session,
            row=row,
            manifest=manifest,
            task_id=job_id,
            user_id=user_id,
            terminal_result="terminal_recovered",
            now=now,
        )
        return True

    source = Path(item.source_path)
    if intent is None:
        try:
            _assert_live_media_evidence(
                session,
                row=row,
                item_meta=item_meta,
                manifest=manifest,
            )
            _source_stat_exact(
                manifest["identity"],
                allowed_roots=settings.allowed_roots,
                quarantine_root=settings.quarantine_root,
            )
        except Exception as exc:
            item.state = "failed"
            item.reason = f"corrupt-media delete reconciliation before intent failed: {exc}"
            return True
        item.state = "planned"
        item.reason = None
        return True

    if not os.path.lexists(source):
        _finalize_terminal(
            session,
            row=row,
            manifest=manifest,
            task_id=job_id,
            user_id=user_id,
            terminal_result="absent_after_intent",
            now=now,
        )
        return True

    try:
        _source_stat_exact(
            manifest["identity"],
            allowed_roots=settings.allowed_roots,
            quarantine_root=settings.quarantine_root,
        )
    except Exception as exc:
        item.state = "failed"
        item.reason = f"source changed after durable corrupt-media delete intent: {exc}"
        return True

    item.state = "planned"
    item.reason = None
    return True
