from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select, text

from app.exceptions import StateConflictError
from app.models import AuditEvent, BatchPlan, BatchPlanItem, QuarantineEntry, utcnow
from app.quarantine.purge_advisory import discover_unlink_purge_advisory
from app.quarantine.unlink_purge import OPERATION_ID, SEMANTICS_VERSION


_TERMINAL_RESULT = "purged"


def _metadata(row: BatchPlanItem) -> dict[str, Any]:
    try:
        value = json.loads(row.metadata_json or "{}")
    except Exception as exc:
        raise StateConflictError(
            f"UNLINK_PURGE_TERMINAL_METADATA_INVALID: item #{row.id} metadata is malformed"
        ) from exc
    if not isinstance(value, dict):
        raise StateConflictError(
            f"UNLINK_PURGE_TERMINAL_METADATA_INVALID: item #{row.id} metadata is not an object"
        )
    return value


def _frozen_authority(row: BatchPlanItem) -> tuple[int, str, dict[str, Any], dict[str, Any]]:
    metadata = _metadata(row)
    raw_qid = metadata.get("quarantine_entry_id")
    if not isinstance(raw_qid, int) or isinstance(raw_qid, bool) or raw_qid <= 0:
        raise StateConflictError(
            f"UNLINK_PURGE_TERMINAL_AUTHORITY_INVALID: item #{row.id} quarantine_entry_id"
        )
    if metadata.get("purge_semantics") != SEMANTICS_VERSION:
        raise StateConflictError(
            f"UNLINK_PURGE_TERMINAL_AUTHORITY_INVALID: item #{row.id} purge semantics"
        )
    preview_digest = metadata.get("preview_digest")
    if not isinstance(preview_digest, str) or not preview_digest:
        raise StateConflictError(
            f"UNLINK_PURGE_TERMINAL_AUTHORITY_INVALID: item #{row.id} preview digest"
        )
    manifest = metadata.get("unlink_manifest")
    if not isinstance(manifest, dict):
        raise StateConflictError(
            f"UNLINK_PURGE_TERMINAL_AUTHORITY_INVALID: item #{row.id} unlink manifest"
        )
    if manifest.get("purge_semantics") != SEMANTICS_VERSION:
        raise StateConflictError(
            f"UNLINK_PURGE_TERMINAL_AUTHORITY_INVALID: item #{row.id} manifest semantics"
        )
    if manifest.get("selected_entry_id") != raw_qid:
        raise StateConflictError(
            f"UNLINK_PURGE_TERMINAL_AUTHORITY_INVALID: item #{row.id} selected entry binding"
        )
    return int(raw_qid), preview_digest, manifest, metadata


def _matching_terminal_events(session: Any, *, plan_id: int, item_id: int) -> list[tuple[AuditEvent, dict[str, Any]]]:
    matches: list[tuple[AuditEvent, dict[str, Any]]] = []
    events = list(
        session.scalars(
            select(AuditEvent).where(
                AuditEvent.operation == OPERATION_ID,
                AuditEvent.result == "completed",
            )
        )
    )
    for event in events:
        try:
            details = json.loads(event.details_json or "{}")
        except Exception:
            continue
        if not isinstance(details, dict):
            continue
        if details.get("plan_id") == plan_id and details.get("item_id") == item_id:
            matches.append((event, details))
    return matches


def _already_bound(
    metadata: dict[str, Any],
    events: list[tuple[AuditEvent, dict[str, Any]]],
    *,
    qentry_id: int,
    preview_digest: str,
) -> bool:
    advisory = metadata.get("terminal_advisory")
    if not isinstance(advisory, dict) or len(events) != 1:
        return False
    details = events[0][1]
    return (
        details.get("quarantine_entry_id") == qentry_id
        and details.get("preview_digest") == preview_digest
        and details.get("purge_semantics") == SEMANTICS_VERSION
        and details.get("terminal_result") == _TERMINAL_RESULT
        and details.get("survivor_scope") == advisory.get("scope")
        and details.get("survivor_status") == advisory.get("status")
        and details.get("hardlink_survivor_paths") == advisory.get("hardlink_survivors")
    )


def finalize_bulk_unlink_terminal_audits(
    session_factory: Any,
    *,
    plan_id: int,
    task_id: int,
    worker_id: str | None,
) -> None:
    """Enrich Gate6-A2 terminal success audit exactly once with fresh advisory.

    Filesystem/index advisory discovery is intentionally performed outside a
    SQLite write transaction.  The subsequent write transaction rechecks the
    exact frozen item authority and the worker lease before persisting the
    advisory and enriching (rather than duplicating) the worker's success event.
    """
    pending: list[dict[str, Any]] = []

    with session_factory() as session:
        plan = session.get(BatchPlan, plan_id)
        if plan is None:
            raise KeyError(f"Plan #{plan_id} not found")

        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(
                    BatchPlanItem.plan_id == plan_id,
                    BatchPlanItem.operation == OPERATION_ID,
                    BatchPlanItem.state == "completed",
                )
                .order_by(BatchPlanItem.sequence)
            )
        )
        for item in items:
            qentry_id, preview_digest, manifest, metadata = _frozen_authority(item)
            events = _matching_terminal_events(
                session,
                plan_id=plan_id,
                item_id=int(item.id),
            )
            if len(events) > 1:
                raise StateConflictError(
                    f"UNLINK_PURGE_TERMINAL_AUDIT_DUPLICATE: plan #{plan_id} item #{item.id}"
                )
            if _already_bound(
                metadata,
                events,
                qentry_id=qentry_id,
                preview_digest=preview_digest,
            ):
                continue

            entry = session.get(QuarantineEntry, qentry_id)
            if entry is None:
                raise StateConflictError(
                    f"UNLINK_PURGE_TERMINAL_ENTRY_MISSING: quarantine entry #{qentry_id}"
                )
            if entry.state != "purged" or entry.tx_phase != "purged":
                raise StateConflictError(
                    "UNLINK_PURGE_TERMINAL_STATE_INVALID: "
                    f"entry #{qentry_id} state={entry.state} tx_phase={entry.tx_phase}"
                )

            advisory = discover_unlink_purge_advisory(session, entry, manifest)
            pending.append(
                {
                    "item_id": int(item.id),
                    "qentry_id": qentry_id,
                    "preview_digest": preview_digest,
                    "manifest": json.loads(json.dumps(manifest, sort_keys=True)),
                    "advisory": advisory,
                }
            )

    for terminal in pending:
        with session_factory() as session:
            session.execute(text("BEGIN IMMEDIATE"))
            now = utcnow()
            if worker_id is not None:
                from app.tasks.recovery import assert_active_worker_lease

                assert_active_worker_lease(session, worker_id, now=now)

            item = session.get(BatchPlanItem, terminal["item_id"])
            if item is None or item.plan_id != plan_id or item.operation != OPERATION_ID:
                raise StateConflictError(
                    f"UNLINK_PURGE_TERMINAL_ITEM_CHANGED: item #{terminal['item_id']}"
                )
            if item.state != "completed":
                raise StateConflictError(
                    f"UNLINK_PURGE_TERMINAL_ITEM_NOT_COMPLETED: item #{item.id} state={item.state}"
                )

            qentry_id, preview_digest, manifest, metadata = _frozen_authority(item)
            if (
                qentry_id != terminal["qentry_id"]
                or preview_digest != terminal["preview_digest"]
                or manifest != terminal["manifest"]
            ):
                raise StateConflictError(
                    f"UNLINK_PURGE_TERMINAL_AUTHORITY_CHANGED: item #{item.id}"
                )

            entry = session.get(QuarantineEntry, qentry_id)
            if entry is None or entry.state != "purged" or entry.tx_phase != "purged":
                raise StateConflictError(
                    f"UNLINK_PURGE_TERMINAL_ENTRY_CHANGED: quarantine entry #{qentry_id}"
                )

            events = _matching_terminal_events(
                session,
                plan_id=plan_id,
                item_id=int(item.id),
            )
            if len(events) > 1:
                raise StateConflictError(
                    f"UNLINK_PURGE_TERMINAL_AUDIT_DUPLICATE: plan #{plan_id} item #{item.id}"
                )

            advisory = terminal["advisory"]
            metadata["terminal_advisory"] = advisory
            item.metadata_json = json.dumps(metadata, ensure_ascii=False, sort_keys=True)

            if events:
                event, details = events[0]
            else:
                event = AuditEvent(
                    operation=OPERATION_ID,
                    path=item.source_path,
                    result="completed",
                    details_json="{}",
                )
                session.add(event)
                details = {}

            details.update(
                {
                    "plan_id": plan_id,
                    "item_id": int(item.id),
                    "quarantine_entry_id": qentry_id,
                    "preview_digest": preview_digest,
                    "purge_semantics": SEMANTICS_VERSION,
                    "terminal_result": _TERMINAL_RESULT,
                    "survivor_scope": advisory.get("scope"),
                    "survivor_status": advisory.get("status"),
                    "hardlink_survivor_count": len(advisory.get("hardlink_survivors") or []),
                    "hardlink_survivor_paths": list(advisory.get("hardlink_survivors") or []),
                    "stale_candidates": list(advisory.get("stale_candidates") or []),
                    "out_of_scope_candidates": list(advisory.get("out_of_scope_candidates") or []),
                    "same_content_scope": advisory.get("same_content_scope"),
                    "same_content_status": advisory.get("same_content_status"),
                    "same_content_independent_copy_count": len(
                        advisory.get("same_content_independent_copies") or []
                    ),
                    "same_content_independent_copies": list(
                        advisory.get("same_content_independent_copies") or []
                    ),
                    "diagnostics": list(advisory.get("diagnostics") or []),
                    "reason": details.get("reason") or item.reason or "purged",
                    "target": item.target_path,
                    "result_path": details.get("result_path"),
                }
            )
            details.setdefault("task_id", task_id)
            event.details_json = json.dumps(details, ensure_ascii=False, sort_keys=True)
            session.commit()
