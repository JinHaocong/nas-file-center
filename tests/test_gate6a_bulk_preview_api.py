from __future__ import annotations

import re
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


def test_bulk_preview_rejects_unsupported_action(tmp_path: Path) -> None:
    """Only the frozen restore and purge actions are valid Gate6-A bulk operations."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "archive",
            "entry_ids": [7],
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_rejects_unsupported_restore_conflict_policy(tmp_path: Path) -> None:
    """Bulk restore conflict handling is frozen to skip or deterministic rename only."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [7],
            "conflict_policy": "overwrite",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_rejects_conflict_policy_for_purge(tmp_path: Path) -> None:
    """Purge has no restore conflict policy; sending one is invalid instead of ignored."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "purge",
            "entry_ids": [7],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_rejects_custom_target_for_purge(tmp_path: Path) -> None:
    """Bulk purge must reject restore-only custom target input instead of ignoring it."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "purge",
            "entry_ids": [7],
            "custom_target": str(tmp_path / "forbidden-target.txt"),
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_bulk_preview_marks_missing_entry_blocked(tmp_path: Path) -> None:
    """Preview remains read-only and reports a missing selected member as blocked."""
    client = _setup_admin_client(tmp_path)

    response = client.post(
        "/api/quarantine/bulk-preview",
        json={
            "action": "restore",
            "entry_ids": [999],
            "conflict_policy": "skip",
        },
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "restore"
    assert body["entry_ids"] == [999]
    assert body["eligible_count"] == 0
    assert body["blocked_count"] == 1
    assert body["items"] == [
        {
            "entry_id": 999,
            "eligible": False,
            "reason": "MISSING_ENTRY",
        }
    ]
    assert re.fullmatch(r"[0-9a-f]{64}", body["preview_digest"])
