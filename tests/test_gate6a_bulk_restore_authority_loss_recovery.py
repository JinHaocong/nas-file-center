from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import BatchPlanItem, QuarantineEntry, TaskLock, utcnow
from app.quarantine.reconcile import reconcile_quarantine_transaction


def _client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    data.mkdir()
    trash = data / ".nas-file-center-trash"
    trash.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    app = create_app(
        Settings(
            config_dir=config,
            data_mount=data,
            allowed_roots_raw=str(data),
            quarantine_root=trash,
            initial_admin_username="admin",
            initial_admin_password="AdminPassword123!",
            allow_mutation=True,
            allow_delete=True,
        )
    )
    client = TestClient(app)
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return client


def _active_entry(client: TestClient) -> tuple[int, Path, Path, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    original = data / "authority-loss-restore.txt"
    payload = b"gate6a-authority-loss-recovery"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original),
            quarantine_path=str(trash / "pending-authority-loss.txt"),
            state="active",
            tx_phase="active",
            active_attempt_generation=1,
            size=0,
            content_hash=None,
            mtime_ns=0,
            device=0,
            inode=0,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.flush()

        attempt = trash / ".tx" / f"entry-{entry.id}" / "attempt-1"
        attempt.mkdir(parents=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"authority-loss.q-{entry.id}.txt"
        anchor.write_bytes(payload)
        os.link(anchor, captured)
        os.link(anchor, public_view)
        st = anchor.stat(follow_symlinks=False)

        entry.quarantine_path = str(public_view)
        entry.authoritative_anchor_path = str(anchor)
        entry.size = st.st_size
        entry.content_hash = hashlib.sha256(payload).hexdigest()
        entry.mtime_ns = st.st_mtime_ns
        entry.device = st.st_dev
        entry.inode = st.st_ino
        session.commit()
        return int(entry.id), anchor, public_view, original


def _prepare_rename_plan(client: TestClient, entry_id: int, original: Path) -> tuple[int, int, Path]:
    original.write_bytes(b"foreign-owner-forces-rename")
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "restore", "entry_ids": [entry_id], "conflict_policy": "rename"},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    generated = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": [entry_id],
            "conflict_policy": "rename",
            "expected_preview_digest": preview.json()["preview_digest"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert generated.status_code == 200
    plan_id = int(generated.json()["id"])

    service = client.app.state.service
    assert service.freeze_plan(plan_id).status == "frozen"
    assert service.validate_plan(plan_id)["status"] == "ready"
    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.target_path is not None
        frozen_target = Path(item.target_path)
        item_id = int(item.id)
    assert frozen_target != original
    assert not frozen_target.exists()
    return plan_id, item_id, frozen_target


def _arm_restoring(service, item_id: int, entry_id: int, *, metadata_json: str) -> None:
    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        entry = session.get(QuarantineEntry, entry_id)
        assert item is not None and entry is not None
        item.state = "executing"
        item.metadata_json = metadata_json
        entry.state = "restoring"
        entry.tx_phase = "restoring"
        entry.updated_at = utcnow()
        session.commit()


def _lease(service, worker_id: str) -> None:
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = worker_id
        lock.acquired_at = utcnow()
        session.commit()


def _current_metadata(service, item_id: int) -> dict:
    with service.SessionLocal() as session:
        item = session.get(BatchPlanItem, item_id)
        assert item is not None
        meta = json.loads(item.metadata_json or "{}")
        assert isinstance(meta, dict)
        return meta


def _assert_authority_loss_failed_closed(
    service,
    *,
    entry_id: int,
    original: Path,
    frozen_target: Path,
    public_view: Path,
) -> None:
    # Authority loss must be detected before any restore-side filesystem mutation.
    assert not original.exists()
    assert not frozen_target.exists()
    assert public_view.exists()
    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert (entry.state, entry.tx_phase) == ("conflict", "conflict")
        assert entry.last_error is not None
        assert "authority" in entry.last_error.lower()


def _reconcile(service, entry_id: int, worker_id: str) -> None:
    reconcile_quarantine_transaction(
        service.SessionLocal,
        entry_id,
        worker_id=worker_id,
        quarantine_root=service.settings.quarantine_root,
        allowed_roots=service.settings.allowed_roots,
    )


def test_restoring_gate6a_malformed_metadata_fails_closed_without_fallback_to_original(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, _anchor, public_view, original = _active_entry(client)
    _plan_id, item_id, frozen_target = _prepare_rename_plan(client, entry_id, original)
    original.unlink()
    _arm_restoring(service, item_id, entry_id, metadata_json="{malformed-json")

    worker_id = "worker-gate6a-authority-loss-malformed"
    _lease(service, worker_id)
    _reconcile(service, entry_id, worker_id)

    _assert_authority_loss_failed_closed(
        service,
        entry_id=entry_id,
        original=original,
        frozen_target=frozen_target,
        public_view=public_view,
    )


def test_restoring_gate6a_missing_qentry_binding_fails_closed_without_fallback_to_original(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, _anchor, public_view, original = _active_entry(client)
    _plan_id, item_id, frozen_target = _prepare_rename_plan(client, entry_id, original)
    original.unlink()

    meta = _current_metadata(service, item_id)
    meta.pop("quarantine_entry_id", None)
    undo = meta.get("undo")
    if isinstance(undo, dict):
        undo.pop("quarantine_entry_id", None)
    _arm_restoring(service, item_id, entry_id, metadata_json=json.dumps(meta, ensure_ascii=False))

    worker_id = "worker-gate6a-authority-loss-missing-qid"
    _lease(service, worker_id)
    _reconcile(service, entry_id, worker_id)

    _assert_authority_loss_failed_closed(
        service,
        entry_id=entry_id,
        original=original,
        frozen_target=frozen_target,
        public_view=public_view,
    )


def test_restoring_gate6a_invalid_qentry_binding_fails_closed_without_fallback_to_original(tmp_path: Path) -> None:
    client = _client(tmp_path)
    service = client.app.state.service
    entry_id, _anchor, public_view, original = _active_entry(client)
    _plan_id, item_id, frozen_target = _prepare_rename_plan(client, entry_id, original)
    original.unlink()

    meta = _current_metadata(service, item_id)
    meta["quarantine_entry_id"] = "not-an-entry-id"
    undo = meta.get("undo")
    if isinstance(undo, dict):
        undo.pop("quarantine_entry_id", None)
    _arm_restoring(service, item_id, entry_id, metadata_json=json.dumps(meta, ensure_ascii=False))

    worker_id = "worker-gate6a-authority-loss-invalid-qid"
    _lease(service, worker_id)
    _reconcile(service, entry_id, worker_id)

    _assert_authority_loss_failed_closed(
        service,
        entry_id=entry_id,
        original=original,
        frozen_target=frozen_target,
        public_view=public_view,
    )
