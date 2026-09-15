from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.batch.plans import OperationItem
from app.config import Settings
from app.exceptions import StateConflictError
from app.execution.executor import execute_item
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, utcnow


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


def _active_entry(client: TestClient) -> tuple[int, Path, Path]:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-bulk-restore-freeze"
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "restore-freeze.txt"),
            quarantine_path=str(trash / "pending-restore-freeze.txt"),
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
        public_view = trash / f"restore-freeze.q-{entry.id}.txt"
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
        return entry.id, anchor, public_view


def _restore_draft(client: TestClient, entry_id: int) -> int:
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "restore", "entry_ids": [entry_id], "conflict_policy": "skip"},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    response = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": [entry_id],
            "conflict_policy": "skip",
            "expected_preview_digest": preview.json()["preview_digest"],
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return int(response.json()["id"])


def test_bulk_restore_freeze_rejects_entry_that_is_no_longer_active(tmp_path: Path) -> None:
    client = _client(tmp_path)
    entry_id, anchor, public_view = _active_entry(client)
    plan_id = _restore_draft(client, entry_id)
    service = client.app.state.service

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        entry.state = "conflict"
        entry.tx_phase = "conflict"
        session.commit()

    with pytest.raises(StateConflictError):
        service.freeze_plan(plan_id)

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "draft"
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "planned"
        assert item.expected_device == 0
        assert item.expected_inode == 0
        assert item.expected_mtime_ns == 0
        assert item.expected_hash is None

    assert anchor.exists()
    assert public_view.exists()


def test_bulk_restore_freeze_captures_authoritative_physical_identity(tmp_path: Path) -> None:
    client = _client(tmp_path)
    entry_id, anchor, public_view = _active_entry(client)
    plan_id = _restore_draft(client, entry_id)
    service = client.app.state.service
    before = anchor.stat(follow_symlinks=False)
    expected_hash = hashlib.sha256(anchor.read_bytes()).hexdigest()

    frozen = service.freeze_plan(plan_id)
    assert frozen.status == "frozen"

    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.state == "planned"
        assert item.expected_device == before.st_dev
        assert item.expected_inode == before.st_ino
        assert item.expected_size == before.st_size
        assert item.expected_mtime_ns == before.st_mtime_ns
        assert item.expected_hash == expected_hash

    assert anchor.exists()
    assert public_view.exists()


def test_bulk_restore_validate_rejects_foreign_target_occupied_after_freeze(tmp_path: Path) -> None:
    client = _client(tmp_path)
    entry_id, anchor, public_view = _active_entry(client)
    plan_id = _restore_draft(client, entry_id)
    service = client.app.state.service

    frozen = service.freeze_plan(plan_id)
    assert frozen.status == "frozen"

    with service.SessionLocal() as session:
        item = session.query(BatchPlanItem).filter_by(plan_id=plan_id).one()
        assert item.target_path is not None
        target = Path(item.target_path)

    assert not target.exists()
    foreign_payload = b"foreign-owner-must-survive"
    target.write_bytes(foreign_payload)

    detail = service.validate_plan(plan_id)

    assert detail["status"] == "stale"
    assert detail["items"][0]["state"] == "stale"
    assert target.read_bytes() == foreign_payload

    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert entry.state == "active"
        assert entry.tx_phase == "active"

    assert anchor.exists()
    assert public_view.exists()


def test_bulk_restore_worker_compat_uses_exact_frozen_plan_target(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path)
    entry_id, anchor, public_view = _active_entry(client)
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    frozen_target = data / "frozen-rename-target.txt"
    original_target = data / "restore-freeze.txt"

    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if lock is None:
            lock = TaskLock(id=1)
            session.add(lock)
        lock.locked = True
        lock.owner = "worker-gate6a"
        lock.acquired_at = utcnow()
        session.commit()

    from app.quarantine.capability import MutationCapability

    monkeypatch.setattr(
        "app.quarantine.capability.resolve_mutation_capability",
        lambda *args, **kwargs: MutationCapability.COMPAT_TRANSACTIONAL,
    )

    st = anchor.stat(follow_symlinks=False)
    item = OperationItem(
        sequence=1,
        operation="restore",
        source=public_view,
        target=frozen_target,
        expected_size=st.st_size,
        expected_hash=hashlib.sha256(anchor.read_bytes()).hexdigest(),
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
        expected_mtime_ns=st.st_mtime_ns,
    )

    result = execute_item(
        item,
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=service.settings.quarantine_root,
        plan_id="gate6a-worker-restore",
        session_factory=service.SessionLocal,
        worker_id="worker-gate6a",
        quarantine_entry_id=entry_id,
    )

    assert result.state == "completed"
    assert result.result_path == frozen_target
    assert frozen_target.exists()
    assert frozen_target.read_bytes() == anchor.read_bytes()
    assert not original_target.exists()
    assert not public_view.exists()
