from __future__ import annotations

import json

from sqlalchemy import text

from app.models import BatchPlan, BatchPlanItem, QuarantineEntry
from app.quarantine.bulk import quarantine_entry_identity_material
from app.quarantine.unlink_purge import SEMANTICS_VERSION, revalidate_unlink_manifest


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
    else:
        plan_metadata["purge_semantics"] = SEMANTICS_VERSION

    with service.SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))

        if expected_db_identities is not None:
            for identity_entry_id, expected_identity in expected_db_identities.items():
                current_entry = session.get(QuarantineEntry, identity_entry_id)
                if current_entry is None:
                    session.rollback()
                    raise RuntimeError(
                        f"preview identity owner disappeared for quarantine entry {identity_entry_id}"
                    )
                if quarantine_entry_identity_material(current_entry) != expected_identity:
                    session.rollback()
                    raise RuntimeError(
                        f"preview identity changed for quarantine entry {identity_entry_id}"
                    )

        entries: dict[int, QuarantineEntry] = {}
        for entry_id in entry_ids:
            entry = session.get(QuarantineEntry, entry_id)
            if entry is None or entry.state != "active":
                session.rollback()
                raise RuntimeError(f"preview changed for quarantine entry {entry_id}")
            entries[entry_id] = entry

        if not is_restore:
            quarantine_root = service.settings.quarantine_root
            for entry_id in entry_ids:
                preview_item = preview_items[entry_id]
                manifest = preview_item.get("unlink_manifest")
                if preview_item.get("purge_semantics") != SEMANTICS_VERSION:
                    session.rollback()
                    raise RuntimeError(
                        f"preview unlink semantics changed for quarantine entry {entry_id}"
                    )
                if not isinstance(manifest, dict):
                    session.rollback()
                    raise RuntimeError(
                        f"preview unlink manifest missing for quarantine entry {entry_id}"
                    )

                validation = revalidate_unlink_manifest(
                    entries[entry_id],
                    quarantine_root,
                    manifest,
                )
                if not validation["valid"]:
                    session.rollback()
                    blockers = ",".join(validation["blockers"])
                    raise RuntimeError(
                        f"preview unlink authority changed for quarantine entry {entry_id}: {blockers}"
                    )

        if is_restore:
            plan_metadata["restore_skip_authority"] = {
                str(entry_id): {
                    "source_path": str(entries[entry_id].quarantine_path),
                    "target_path": str(preview_items[entry_id]["target_path"]),
                    "conflict_policy": conflict_policy,
                    "preview_digest": preview_digest,
                }
                for entry_id in entry_ids
                if preview_items[entry_id].get("skip_preexisting_target") is True
            }

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

        restore_items: list[tuple[BatchPlanItem, int]] = []
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
                    **(
                        {"skip_preexisting_target": True}
                        if preview_item.get("skip_preexisting_target") is True
                        else {}
                    ),
                }
            else:
                manifest = preview_item.get("unlink_manifest")
                if preview_item.get("purge_semantics") != SEMANTICS_VERSION:
                    session.rollback()
                    raise RuntimeError(
                        f"preview unlink semantics changed for quarantine entry {entry_id}"
                    )
                if not isinstance(manifest, dict):
                    session.rollback()
                    raise RuntimeError(
                        f"preview unlink manifest missing for quarantine entry {entry_id}"
                    )
                if manifest.get("purge_semantics") != SEMANTICS_VERSION:
                    session.rollback()
                    raise RuntimeError(
                        f"preview unlink manifest semantics changed for quarantine entry {entry_id}"
                    )
                if manifest.get("selected_entry_id") != entry_id:
                    session.rollback()
                    raise RuntimeError(
                        f"preview unlink manifest owner changed for quarantine entry {entry_id}"
                    )
                if manifest.get("blockers"):
                    session.rollback()
                    raise RuntimeError(
                        f"preview unlink manifest blocked for quarantine entry {entry_id}"
                    )

                operation = "quarantine_unlink_purge"
                target_path = None
                expected_identity = (
                    expected_db_identities.get(entry_id)
                    if expected_db_identities is not None
                    else quarantine_entry_identity_material(entry)
                )
                if expected_identity is None:
                    session.rollback()
                    raise RuntimeError(
                        f"preview identity missing for quarantine entry {entry_id}"
                    )
                item_metadata = {
                    "quarantine_entry_id": entry_id,
                    "preview_digest": preview_digest,
                    "purge_semantics": SEMANTICS_VERSION,
                    "entry_identity": expected_identity,
                    "unlink_manifest": manifest,
                }

            row = BatchPlanItem(
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
            session.add(row)
            if is_restore:
                restore_items.append((row, entry_id))

        if is_restore:
            # Item ids are database-owned and stable. Bind every restore row to plan-level
            # authority so post-Freeze mutation of BatchPlanItem metadata/source/target cannot
            # redefine which QuarantineEntry that exact row is allowed to restore.
            session.flush()
            plan_metadata["restore_item_authority"] = {
                str(row.id): {
                    "quarantine_entry_id": entry_id,
                    "source_path": str(entries[entry_id].quarantine_path),
                    "target_path": str(row.target_path or ""),
                    "conflict_policy": conflict_policy,
                    "preview_digest": preview_digest,
                    "skip_preexisting_target": (
                        preview_items[entry_id].get("skip_preexisting_target") is True
                    ),
                    "entry_identity": quarantine_entry_identity_material(entries[entry_id]),
                }
                for row, entry_id in restore_items
            }
            plan.metadata_json = json.dumps(plan_metadata, ensure_ascii=False, sort_keys=True)

        session.commit()
        return plan.id, plan_kind
