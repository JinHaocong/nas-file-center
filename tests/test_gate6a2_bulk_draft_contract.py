from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.quarantine_bulk_plan import persist_bulk_draft
from app.db import create_engine_and_session, init_db
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, utcnow
from app.quarantine.bulk import quarantine_entry_identity_material
from app.quarantine.unlink_purge import build_unlink_manifest


def _setup_service(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)
    engine, SessionLocal = create_engine_and_session(tmp_path / "draft.db")
    init_db(engine)
    service = SimpleNamespace(
        SessionLocal=SessionLocal,
        settings=SimpleNamespace(quarantine_root=trash),
    )
    return service, data, trash


def _seed_transactional_entry(service, data: Path, trash: Path):
    payload = b"gate6a2-bulk-draft-authority"
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "source.bin"),
            quarantine_path=str(trash / "pending.bin"),
            state="active",
            tx_phase="active",
            active_attempt_generation=1,
            size=len(payload),
            content_hash=hashlib.sha256(payload).hexdigest(),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()

        attempt = trash / ".tx" / f"entry-{entry.id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"selected.q-{entry.id}.bin"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        st = anchor.stat(follow_symlinks=False)

        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.device = st.st_dev
        entry.inode = st.st_ino
        entry.size = st.st_size
        entry.mtime_ns = st.st_mtime_ns
        session.commit()

        entry_id = entry.id
        expected_identity = quarantine_entry_identity_material(entry)
        frozen_manifest = build_unlink_manifest(entry, trash)
        assert frozen_manifest["blockers"] == []

    return entry_id, expected_identity, frozen_manifest, public_view


def _preview_item(entry_id: int, frozen_manifest: dict) -> dict[int, dict[str, object]]:
    return {
        entry_id: {
            "entry_id": entry_id,
            "eligible": True,
            "purge_semantics": "unlink_v1",
            "unlink_manifest": frozen_manifest,
        }
    }


def test_purge_draft_uses_unlink_operation_and_persists_frozen_authority(tmp_path: Path) -> None:
    service, data, trash = _setup_service(tmp_path)
    entry_id, expected_identity, frozen_manifest, _ = _seed_transactional_entry(
        service, data, trash
    )
    digest = "cd" * 32

    plan_id, plan_kind = persist_bulk_draft(
        service,
        action="purge",
        entry_ids=[entry_id],
        preview_items=_preview_item(entry_id, frozen_manifest),
        preview_digest=digest,
        conflict_policy=None,
        expected_db_identities={entry_id: expected_identity},
    )

    assert plan_kind == "quarantine-bulk-purge"
    with service.SessionLocal() as session:
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


def test_purge_draft_rejects_aba_replacement_after_preview_authority_is_frozen(
    tmp_path: Path,
) -> None:
    service, data, trash = _setup_service(tmp_path)
    entry_id, expected_identity, frozen_manifest, public_view = _seed_transactional_entry(
        service, data, trash
    )

    original_inode = public_view.stat(follow_symlinks=False).st_ino
    public_view.unlink()
    public_view.write_bytes(b"foreign-aba-replacement")
    assert public_view.stat(follow_symlinks=False).st_ino != original_inode

    with pytest.raises(RuntimeError, match="preview unlink authority changed"):
        persist_bulk_draft(
            service,
            action="purge",
            entry_ids=[entry_id],
            preview_items=_preview_item(entry_id, frozen_manifest),
            preview_digest="ef" * 32,
            conflict_policy=None,
            expected_db_identities={entry_id: expected_identity},
        )

    with service.SessionLocal() as session:
        assert session.query(BatchPlan).count() == 0
        assert session.query(BatchPlanItem).count() == 0
