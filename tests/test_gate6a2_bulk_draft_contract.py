from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.api.quarantine_bulk_plan import persist_bulk_draft
from app.db import create_engine_and_session, init_db
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, utcnow
from app.quarantine.bulk import quarantine_entry_identity_material


def test_purge_draft_uses_unlink_operation_and_persists_frozen_authority(tmp_path: Path) -> None:
    engine, SessionLocal = create_engine_and_session(tmp_path / "draft.db")
    init_db(engine)
    service = SimpleNamespace(SessionLocal=SessionLocal)

    with SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(tmp_path / "source.bin"),
            quarantine_path=str(tmp_path / "trash.bin"),
            state="active",
            tx_phase="active",
            authoritative_anchor_path=str(tmp_path / "anchor"),
            active_attempt_generation=1,
            device=11,
            inode=22,
            size=33,
            mtime_ns=44,
            content_hash="ab" * 32,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id
        expected_identity = quarantine_entry_identity_material(entry)

    frozen_manifest = {
        "purge_semantics": "unlink_v1",
        "selected_entry_id": entry_id,
        "active_attempt_generation": 1,
        "owned_paths": [
            {
                "role": "public_view",
                "path": str(tmp_path / "trash.bin"),
                "object_type": "regular_file",
                "device": 11,
                "inode": 22,
                "size": 33,
                "mtime_ns": 44,
                "content_hash": "ab" * 32,
            }
        ],
        "blockers": [],
    }
    digest = "cd" * 32

    plan_id, plan_kind = persist_bulk_draft(
        service,
        action="purge",
        entry_ids=[entry_id],
        preview_items={
            entry_id: {
                "entry_id": entry_id,
                "eligible": True,
                "purge_semantics": "unlink_v1",
                "unlink_manifest": frozen_manifest,
            }
        },
        preview_digest=digest,
        conflict_policy=None,
        expected_db_identities={entry_id: expected_identity},
    )

    assert plan_kind == "quarantine-bulk-purge"
    with SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        plan_meta = json.loads(plan.metadata_json or "{}")
        assert plan_meta["preview_digest"] == digest
        assert plan_meta["purge_semantics"] == "unlink_v1"

        item = session.query(BatchPlanItem).filter(BatchPlanItem.plan_id == plan_id).one()
        assert item.operation == "quarantine_unlink_purge"
        item_meta = json.loads(item.metadata_json or "{}")
        assert item_meta["preview_digest"] == digest
        assert item_meta["purge_semantics"] == "unlink_v1"
        assert item_meta["entry_identity"] == expected_identity
        assert item_meta["unlink_manifest"] == frozen_manifest
