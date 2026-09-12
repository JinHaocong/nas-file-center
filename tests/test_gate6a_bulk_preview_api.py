from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _setup_admin_client(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=trash,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
        allow_delete=True,
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200
    return client


def test_bulk_preview_rejects_empty_selection(tmp_path: Path) -> None:
    """Gate6-A bulk preview requires at least one explicit quarantine entry ID."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_rejects_duplicate_entry_ids(tmp_path: Path) -> None:
    """Duplicate selection is invalid; Gate6-A must never silently deduplicate it."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [7, 7],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422
