from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, BatchPlanItem


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
