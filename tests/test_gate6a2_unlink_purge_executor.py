from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from app.batch.plans import OperationItem
from app.db import create_engine_and_session, init_db
from app.execution.executor import execute_item
from app.models import QuarantineEntry, utcnow
from app.quarantine.bulk import quarantine_entry_identity_material
from app.quarantine.bulk_lifecycle import freeze_bulk_plan_item, validate_bulk_plan_item
from app.quarantine.unlink_purge import build_unlink_manifest


def _setup_service(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)
    engine, SessionLocal = create_engine_and_session(tmp_path / "lifecycle.db")
    init_db(engine)
    service = SimpleNamespace(
        SessionLocal=SessionLocal,
        settings=SimpleNamespace(
            quarantine_root=trash,
            allowed_roots=[data],
        ),
    )
    return service, data, trash


def _seed_transactional_entry(service, data: Path, trash: Path):
    payload = b"gate6a2-freeze-validate-authority"
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
        identity = quarantine_entry_identity_material(entry)
        manifest = build_unlink_manifest(entry, trash)
        assert manifest["blockers"] == []

    return entry_id, identity, manifest, public_view


def _plan_metadata(entry_id: int, preview_digest: str) -> dict[str, object]:
    return {
        "action": "purge",
        "entry_ids": [entry_id],
        "preview_digest": preview_digest,
        "purge_semantics": "unlink_v1",
    }


def _item_metadata(
    entry_id: int,
    identity: dict[str, object],
    manifest: dict[str, object],
    preview_digest: str,
) -> str:
    return json.dumps(
        {
            "quarantine_entry_id": entry_id,
            "preview_digest": preview_digest,
            "purge_semantics": "unlink_v1",
            "entry_identity": identity,
            "unlink_manifest": manifest,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def test_freeze_recognizes_unlink_operation_and_keeps_exact_draft_authority(tmp_path: Path) -> None:
    service, data, trash = _setup_service(tmp_path)
    entry_id, identity, manifest, public_view = _seed_transactional_entry(service, data, trash)
    digest = "12" * 32
    metadata_json = _item_metadata(entry_id, identity, manifest, digest)

    updates = freeze_bulk_plan_item(
        service,
        plan_kind="quarantine-bulk-purge",
        item={
            "id": 101,
            "operation": "quarantine_unlink_purge",
            "source_path": str(public_view),
            "target_path": None,
            "metadata_json": metadata_json,
        },
        plan_metadata=_plan_metadata(entry_id, digest),
    )

    assert updates is not None
    frozen_metadata = json.loads(updates.get("metadata_json", metadata_json))
    assert frozen_metadata["purge_semantics"] == "unlink_v1"
    assert frozen_metadata["unlink_manifest"] == manifest
    assert "purge_topology_manifest" not in frozen_metadata
    assert updates["expected_device"] == identity["device"]
    assert updates["expected_inode"] == identity["inode"]
    assert updates["expected_size"] == identity["size"]
    assert updates["expected_mtime_ns"] == identity["mtime_ns"]
    assert updates["expected_hash"] == identity["content_hash"]


def test_validate_rejects_unlink_authority_drift_after_freeze(tmp_path: Path) -> None:
    service, data, trash = _setup_service(tmp_path)
    entry_id, identity, manifest, public_view = _seed_transactional_entry(service, data, trash)
    digest = "34" * 32
    metadata_json = _item_metadata(entry_id, identity, manifest, digest)

    original_inode = public_view.stat(follow_symlinks=False).st_ino
    public_view.unlink()
    public_view.write_bytes(b"foreign-replacement-after-freeze")
    assert public_view.stat(follow_symlinks=False).st_ino != original_inode

    item = SimpleNamespace(
        id=102,
        operation="quarantine_unlink_purge",
        source_path=str(public_view),
        target_path=None,
        metadata_json=metadata_json,
        expected_device=identity["device"],
        expected_inode=identity["inode"],
        expected_size=identity["size"],
        expected_mtime_ns=identity["mtime_ns"],
        expected_hash=identity["content_hash"],
    )
    result = validate_bulk_plan_item(
        service,
        plan_kind="quarantine-bulk-purge",
        item=item,
        plan_metadata=_plan_metadata(entry_id, digest),
    )

    assert result is not None
    assert result["state"] == "stale"
    assert result["reason"] == "UNLINK_AUTHORITY_CHANGED"
    assert "IDENTITY_MISMATCH:public_view" in result["actual"]["blockers"]


def test_executor_dispatches_only_new_unlink_operation_and_keeps_old_refusal(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    source = trash / "selected.bin"
    source.write_bytes(b"dispatch-only")
    manifest = {
        "purge_semantics": "unlink_v1",
        "selected_entry_id": 7,
        "active_attempt_generation": 1,
        "owned_paths": [],
        "blockers": [],
    }
    calls: list[dict[str, object]] = []

    def fake_execute_journaled_unlink_purge(
        session_factory,
        *,
        entry_id: int,
        quarantine_root,
        frozen_manifest,
        worker_id: str,
    ):
        calls.append(
            {
                "session_factory": session_factory,
                "entry_id": entry_id,
                "quarantine_root": Path(quarantine_root),
                "frozen_manifest": frozen_manifest,
                "worker_id": worker_id,
            }
        )
        return {
            "purge_semantics": "unlink_v1",
            "removed_count": 0,
            "removed_roles": [],
            "recovered_missing_roles": [],
            "already_terminal": False,
        }

    import app.quarantine.unlink_purge as unlink_purge

    monkeypatch.setattr(
        unlink_purge,
        "execute_journaled_unlink_purge",
        fake_execute_journaled_unlink_purge,
    )

    def session_factory():
        raise AssertionError("mock dispatch must not open a database session")

    new_result = execute_item(
        OperationItem(
            sequence=1,
            operation="quarantine_unlink_purge",
            source=source,
        ),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=trash,
        plan_id="gate6a2-dispatch",
        session_factory=session_factory,
        worker_id="worker-1",
        quarantine_entry_id=7,
        unlink_manifest=manifest,
    )

    assert new_result.state == "completed"
    assert new_result.reason == "purged"
    assert calls == [
        {
            "session_factory": session_factory,
            "entry_id": 7,
            "quarantine_root": trash,
            "frozen_manifest": manifest,
            "worker_id": "worker-1",
        }
    ]

    old_result = execute_item(
        OperationItem(
            sequence=2,
            operation="quarantine_purge",
            source=source,
        ),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=trash,
        plan_id="gate6a-old-refusal",
        session_factory=session_factory,
        worker_id="worker-1",
        quarantine_entry_id=7,
        purge_manifest={"legacy": True},
    )

    assert old_result.state == "failed"
    assert old_result.reason.startswith(
        "EOPNOTSUPP: Gate6-A bulk permanent purge is deferred"
    )
    assert len(calls) == 1
