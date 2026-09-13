from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem, QuarantineEntry, utcnow


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


def _plan_counts(client: TestClient) -> tuple[int, int]:
    service = client.app.state.service
    with service.SessionLocal() as session:
        plans = session.scalar(select(func.count(BatchPlan.id))) or 0
        items = session.scalar(select(func.count(BatchPlanItem.id))) or 0
        return plans, items


def _seed_active_transactional_entry(client: TestClient, name: str = "restore.txt") -> int:
    service = client.app.state.service
    data = Path(service.settings.data_mount)
    trash = Path(service.settings.quarantine_root)
    payload = b"gate6a-plan-preview"

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / name),
            quarantine_path=str(trash / f"pending-{name}"),
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
        public_view = trash / f"{Path(name).stem}.q-{entry.id}{Path(name).suffix}"
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


def test_bulk_plan_requires_expected_preview_digest_and_persists_nothing(tmp_path: Path) -> None:
    client = _setup_admin_client(tmp_path)
    before = _plan_counts(client)

    response = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": [1],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422
    assert _plan_counts(client) == before


def test_bulk_plan_preview_changed_returns_409_and_persists_nothing(tmp_path: Path) -> None:
    client = _setup_admin_client(tmp_path)
    entry_id = _seed_active_transactional_entry(client)

    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [entry_id],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    preview_digest = preview.json()["preview_digest"]
    before = _plan_counts(client)

    service = client.app.state.service
    with service.SessionLocal() as session:
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        entry.mtime_ns += 1
        session.commit()

    response = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": [entry_id],
            "conflict_policy": "skip",
            "expected_preview_digest": preview_digest,
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PREVIEW_CHANGED"
    assert _plan_counts(client) == before


def test_bulk_plan_generates_restore_draft_from_exact_preview(tmp_path: Path) -> None:
    client = _setup_admin_client(tmp_path)
    entry_id = _seed_active_transactional_entry(client)
    service = client.app.state.service

    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [entry_id],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    digest = preview_body["preview_digest"]
    target_path = preview_body["items"][0]["target_path"]

    response = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": [entry_id],
            "conflict_policy": "skip",
            "expected_preview_digest": digest,
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "quarantine-bulk-restore"
    assert body["status"] == "draft"

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, body["id"])
        assert plan is not None
        assert plan.kind == "quarantine-bulk-restore"
        assert plan.status == "draft"
        assert plan.expected_changes == 1

        items = list(
            session.scalars(
                select(BatchPlanItem)
                .where(BatchPlanItem.plan_id == plan.id)
                .order_by(BatchPlanItem.sequence)
            )
        )
        assert len(items) == 1
        item = items[0]
        entry = session.get(QuarantineEntry, entry_id)
        assert entry is not None
        assert item.operation == "restore"
        assert item.source_path == entry.quarantine_path
        assert item.target_path == target_path
        assert item.state == "planned"
        assert item.expected_device == 0
        assert item.expected_inode == 0
        assert item.expected_mtime_ns == 0
        assert item.expected_hash is None
        assert json.loads(item.metadata_json) == {
            "quarantine_entry_id": entry_id,
            "conflict_policy": "skip",
            "preview_digest": digest,
        }
