from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem


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


def _counts(client: TestClient) -> tuple[int, int]:
    with client.app.state.service.SessionLocal() as session:
        return (
            session.scalar(select(func.count(BatchPlan.id))) or 0,
            session.scalar(select(func.count(BatchPlanItem.id))) or 0,
        )


def test_bulk_plan_rejects_blocked_preview_without_persistence(tmp_path: Path) -> None:
    client = _client(tmp_path)
    missing_entry_id = 999999
    preview = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [missing_entry_id],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["eligible_count"] == 0
    assert preview_body["blocked_count"] == 1
    assert preview_body["items"][0]["reason"] == "MISSING_ENTRY"
    before = _counts(client)

    response = client.post(
        "/api/quarantine/bulk-plan",
        json={
            "action": "restore",
            "entry_ids": [missing_entry_id],
            "conflict_policy": "skip",
            "expected_preview_digest": preview_body["preview_digest"],
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "BULK_SELECTION_BLOCKED"
    assert body["error"]["details"]["blocked_items"] == [
        {"entry_id": missing_entry_id, "eligible": False, "reason": "MISSING_ENTRY"}
    ]
    assert _counts(client) == before
