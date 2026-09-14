from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(reason='Gate6-A v0.3.6 COMPAT permanent purge release path is deferred after B10; dormant purge-core safety is covered by direct transactional/recovery tests')

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

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
    payload = b"gate6a-purge-draft"
    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "purge.txt"),
            quarantine_path=str(trash / "pending-purge.txt"),
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
        public_view = trash / f"purge.q-{entry.id}.txt"
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


def test_bulk_plan_generates_purge_draft_from_exact_preview(tmp_path: Path) -> None:
    client = _client(tmp_path)
    entry_id = _active_entry(client)
    service = client.app.state.service
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={"action": "purge", "entry_ids": [entry_id]},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["eligible_count"] == 1
    digest = preview_body["preview_digest"]
    manifest = preview_body["items"][0]["purge_topology_manifest"]

    response = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "purge",
            "entry_ids": [entry_id],
            "confirmation": "DELETE",
            "expected_preview_digest": digest,
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "quarantine-bulk-purge"
    assert body["status"] == "draft"
    assert body["preview_digest"] == digest

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, body["id"])
        assert plan is not None
        assert plan.kind == "quarantine-bulk-purge"
        assert plan.status == "draft"
        assert plan.expected_changes == 1
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id))
        assert item is not None
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert item.operation == "quarantine_purge"
        assert item.source_path == entry.quarantine_path
        assert item.target_path is None
        assert item.state == "planned"
        assert item.expected_size == 0
        assert item.expected_device == 0
        assert item.expected_inode == 0
        assert item.expected_mtime_ns == 0
        assert item.expected_hash is None
        assert json.loads(item.metadata_json) == {
            "quarantine_entry_id": entry_id,
            "preview_digest": digest,
            "purge_topology_manifest": manifest,
        }
