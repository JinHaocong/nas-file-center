from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.api.quarantine_bulk as bulk_api
from app.api.quarantine_bulk_plan import persist_bulk_draft as real_persist_bulk_draft
from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, utcnow


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


def _active_entry(client: TestClient) -> int:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-phase-a-phase-b-race"
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "restore-race.txt"),
            quarantine_path=str(trash / "pending-restore-race.txt"),
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
        public_view = trash / f"restore-race.q-{entry.id}.txt"
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


def _counts(client: TestClient) -> tuple[int, int]:
    with client.app.state.service.SessionLocal() as session:
        return (
            session.scalar(select(func.count(BatchPlan.id))) or 0,
            session.scalar(select(func.count(BatchPlanItem.id))) or 0,
        )


def test_bulk_plan_rejects_db_identity_change_between_phase_a_and_phase_b(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path)
    entry_id = _active_entry(client)
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "restore", "entry_ids": [entry_id], "conflict_policy": "skip"},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    assert preview.json()["eligible_count"] == 1
    before = _counts(client)

    def racing_persist(service, **kwargs):
        with service.SessionLocal() as session:
            entry = session.get(QuarantineEntry, entry_id)
            assert entry is not None
            entry.mtime_ns += 1
            session.commit()
        return real_persist_bulk_draft(service, **kwargs)

    monkeypatch.setattr(bulk_api, "persist_bulk_draft", racing_persist)

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

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PREVIEW_CHANGED"
    assert _counts(client) == before
