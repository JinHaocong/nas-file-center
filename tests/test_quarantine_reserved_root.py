from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.path_safety import UnsafePathError, require_unreserved_path
from app.service import FileCenterService


def _setup_test_env(tmp_path: Path):
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
    service = FileCenterService(settings)
    app = create_app(settings)
    client = TestClient(app)
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200
    return client, service, data, trash


def test_require_unreserved_path_direct(tmp_path: Path):
    """Direct helper rejects accessing QUARANTINE_ROOT and its children."""
    data = tmp_path / "data"
    trash = data / ".nas-file-center-trash"
    child = trash / "plan-1" / "file.txt"

    with pytest.raises(UnsafePathError):
        require_unreserved_path(trash, trash)

    with pytest.raises(UnsafePathError):
        require_unreserved_path(child, trash)

    normal = data / "normal.txt"
    assert require_unreserved_path(normal, trash) == normal.resolve(strict=False)


def test_fs_browser_rejects_quarantine_root(tmp_path: Path):
    """Filesystem browser rejects accessing or descending into QUARANTINE_ROOT."""
    client, service, data, trash = _setup_test_env(tmp_path)

    # 1. Direct service call
    with pytest.raises((UnsafePathError, ValueError)):
        service.list_directory(str(trash))

    # 2. HTTP endpoint call
    resp = client.get(f"/api/filesystem/list?path={trash}")
    assert resp.status_code == 400


def test_index_creation_rejects_quarantine_root(tmp_path: Path):
    """Cannot register QUARANTINE_ROOT as an index root."""
    client, service, data, trash = _setup_test_env(tmp_path)

    resp = client.post(
        "/api/indexes",
        json={"root": str(trash)},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 400


def test_scan_creation_rejects_quarantine_root(tmp_path: Path):
    """Cannot enqueue scan job targeting QUARANTINE_ROOT."""
    client, service, data, trash = _setup_test_env(tmp_path)

    resp = client.post(
        "/api/scans",
        json={"name": "Trash Scan", "roots": [str(trash)]},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 400


def test_plan_creation_rejects_quarantine_root(tmp_path: Path):
    """Cannot create a plan containing source or target in QUARANTINE_ROOT."""
    client, service, data, trash = _setup_test_env(tmp_path)
    file_in_trash = trash / "file.txt"
    file_in_trash.write_text("trash file")

    resp = client.post(
        "/api/plans",
        json={
            "name": "Invalid Plan",
            "kind": "dedupe",
            "items": [
                {
                    "operation": "quarantine",
                    "source": str(file_in_trash),
                }
            ],
        },
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 400


def test_organizer_profile_rejects_quarantine_root(tmp_path: Path):
    """Cannot set organizer profile root to QUARANTINE_ROOT."""
    client, service, data, trash = _setup_test_env(tmp_path)

    resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "Trash Profile",
            "root": str(trash),
        },
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 400
