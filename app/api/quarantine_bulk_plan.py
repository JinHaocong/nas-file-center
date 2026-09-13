from __future__ import annotations

import json

from sqlalchemy import text

from app.models import BatchPlan, BatchPlanItem, QuarantineEntry
from app.quarantine.bulk import quarantine_entry_identity_material


def persist_bulk_draft(
    service,
    *,
    action: str,
    entry_ids: list[int],
    preview_items: dict[int, dict[str, object]],
    preview_digest: str,
    conflict_policy: str | None,
    expected_db_identities: dict[int, dict[str, object]] | None = None,
) -> tuple[int, str]:
    is_restore = action == "restore"
    plan_kind = "quarantine-bulk-restore" if is_restore else "quarantine-bulk-purge"
    plan_metadata: dict[str, object] = {
        "action": action,
        "entry_ids": entry_ids,
        "preview_digest": preview_digest,
    }
    if is_restore:
        plan_metadata["conflict_policy"] = conflict_policy

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        entries: dict[int, QuarantineEntry] = {}
        for entry_id in entry_ids:
            entry = session.get(QuarantineEntry, entry_id)
            if entry is None or entry.state != "active":
                session.rollback()
                raise RuntimeError(f"preview changed for quarantine entry {entry_id}")
            if expected_db_identities is not None:
                expected_identity = expected_db_identities.get(entry_id)
                current_identity = quarantine_entry_identity_material(entry)
                if expected_identity is None or current_identity != expected_identity:
                    session.rollback()
                    raise RuntimeError(f"preview identity changed for quarantine entry {entry_id}")
            entries[entry_id] = entry

        plan = BatchPlan(
            name=plan_kind,
            kind=plan_kind,
            status="draft",
            expected_changes=len(entry_ids),
            expected_reclaim_bytes=0,
            metadata_json=json.dumps(plan_metadata, ensure_ascii=False, sort_keys=True),
        )
        session.add(plan)
        session.flush()

        for sequence, entry_id in enumerate(entry_ids, start=1):
            entry = entries[entry_id]
            preview_item = preview_items[entry_id]
            if is_restore:
                operation = "restore"
                target_path = str(preview_item["target_path"])
                item_metadata = {
                    "quarantine_entry_id": entry_id,
                    "conflict_policy": conflict_policy,
                    "preview_digest": preview_digest,
                }
            else:
                operation = "quarantine_purge"
                target_path = None
                item_metadata = {
                    "quarantine_entry_id": entry_id,
                    "preview_digest": preview_digest,
                    "purge_topology_manifest": preview_item["purge_topology_manifest"],
                }

            session.add(
                BatchPlanItem(
                    plan_id=plan.id,
                    sequence=sequence,
                    operation=operation,
                    source_path=entry.quarantine_path,
                    target_path=target_path,
                    keep_path=None,
                    expected_size=0,
                    expected_mtime_ns=0,
                    expected_device=0,
                    expected_inode=0,
                    expected_hash=None,
                    state="planned",
                    metadata_json=json.dumps(item_metadata, ensure_ascii=False, sort_keys=True),
                )
            )

        session.commit()
        return plan.id, plan_kind
