from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.batch.plans import OperationItem
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.execution.executor import execute_item
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, TaskLock, utcnow
from app.quarantine.purge import build_purge_topology_manifest


DEFERRED_REASON = "PERMANENT_PURGE_DEFERRED_UNSAFE_HARDLINK_SCOPE"


def _setup_admin_client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
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


def _seed_active_entry(client: TestClient) -> int:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-plan1-deferred-purge"
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "selected.bin"),
            quarantine_path=str(trash / "pending.bin"),
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
        attempt.mkdir(parents=True, exist_ok=True)
        anchor = attempt / "anchor"
        captured = attempt / "captured_source"
        public_view = trash / f"selected.q-{entry.id}.bin"
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
        return entry.id


def test_bulk_purge_preview_is_gate6a2_eligible_without_mutation(tmp_path: Path) -> None:
    client = _setup_admin_client(tmp_path)
    entry_id = _seed_active_entry(client)
    service = client.app.state.service
    with service.SessionLocal() as session:
        before = session.get(QuarantineEntry, entry_id)
        assert before is not None
        snapshot = (before.state, before.tx_phase, before.active_attempt_generation)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [entry_id]},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["eligible_count"] == 1
    assert body["blocked_count"] == 0
    assert body["items"][0]["eligible"] is True
    assert body["items"][0]["purge_semantics"] == "unlink_v1"
    assert body["items"][0]["mutation_blockers"] == []

    with service.SessionLocal() as session:
        after = session.get(QuarantineEntry, entry_id)
        assert after is not None
        assert (after.state, after.tx_phase, after.active_attempt_generation) == snapshot


def test_bulk_purge_plan_generation_creates_zero_plan_when_capability_deferred(tmp_path: Path) -> None:
    client = _setup_admin_client(tmp_path)
    entry_id = _seed_active_entry(client)
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [entry_id]},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    digest = preview.json()["preview_digest"]

    response = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": [entry_id],
            "expected_preview_digest": digest,
            "confirmation": "DELETE",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BULK_SELECTION_BLOCKED"
    service = client.app.state.service
    with service.SessionLocal() as session:
        assert session.query(BatchPlan).count() == 0
        assert session.query(BatchPlanItem).count() == 0


def test_worker_rejects_handcrafted_purge_and_preserves_external_hardlink(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    quarantine_root = data / ".nas-file-center-trash"
    attempt = quarantine_root / ".tx" / "entry-1" / "attempt-1"
    attempt.mkdir(parents=True)

    payload = b"gate6a-b10-external-hardlink-must-survive"
    anchor = attempt / "anchor"
    captured_source = attempt / "captured_source"
    public_view = quarantine_root / "selected.q-1.bin"
    external = data / "external-unselected.bin"
    anchor.write_bytes(payload)
    os.link(anchor, captured_source)
    os.link(anchor, public_view)
    os.link(anchor, external)
    st = anchor.stat(follow_symlinks=False)
    digest = hashlib.sha256(payload).hexdigest()

    engine, SessionLocal = create_engine_and_session(tmp_path / "plan1-worker.db")
    init_db(engine)
    with SessionLocal() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.add(TaskLock(id=1, locked=True, owner="worker-1", acquired_at=utcnow()))
        session.add(
            QuarantineEntry(
                id=1,
                original_path=str(data / "selected.bin"),
                quarantine_path=str(public_view),
                state="active",
                tx_phase="active",
                authoritative_anchor_path=str(anchor),
                active_attempt_generation=1,
                device=st.st_dev,
                inode=st.st_ino,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                content_hash=digest,
            )
        )
        session.commit()

    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        manifest = build_purge_topology_manifest(entry, quarantine_root, owner_lookup=lambda _: None)
        assert manifest["blockers"] == []

    result = execute_item(
        OperationItem(
            sequence=1,
            operation="quarantine_purge",
            source=public_view,
            expected_device=st.st_dev,
            expected_inode=st.st_ino,
            expected_size=st.st_size,
            expected_mtime_ns=st.st_mtime_ns,
            expected_hash=digest,
        ),
        allowed_roots=[data],
        allow_mutation=True,
        allow_delete=True,
        quarantine_root=quarantine_root,
        plan_id="plan1-deferred-purge",
        session_factory=SessionLocal,
        worker_id="worker-1",
        quarantine_entry_id=1,
        purge_manifest=manifest,
    )

    assert result.state == "failed"
    assert result.reason.startswith("EOPNOTSUPP: Gate6-A bulk permanent purge is deferred")
    assert anchor.read_bytes() == payload
    assert captured_source.read_bytes() == payload
    assert public_view.read_bytes() == payload
    assert external.read_bytes() == payload
    assert not (quarantine_root / ".tx" / "entry-1" / "attempt-2").exists()
    with SessionLocal() as session:
        entry = session.get(QuarantineEntry, 1)
        assert entry is not None
        assert entry.state == "active"
        assert entry.tx_phase == "active"
        assert entry.active_attempt_generation == 1
        assert entry.purged_at is None
