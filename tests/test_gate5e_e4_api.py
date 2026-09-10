import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import IndexRoot, User
from app.config import Settings
from app.service import FileCenterService
from app.auth.password import hash_password


@pytest.fixture
def api_test_env(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()

    db_path = config_dir / "app.db"
    settings = Settings(
        config_dir=config_dir,
        reports_dir=tmp_path / "reports",
        backups_dir=tmp_path / "backups",
        logs_dir=tmp_path / "logs",
        fclones_home=tmp_path / "fclones",
        database_path=db_path,
        allowed_roots_raw=str(data_dir),
        quarantine_root=quarantine_dir,
        protect_last_file=True,
    )

    service = FileCenterService(settings)

    root1_path = data_dir / "root1"
    root1_path.mkdir()

    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root1_path))
        session.add(r)
        reg_user = User(
            username="normaluser",
            password_hash=hash_password("UserPassword123!"),
            is_active=True,
            role="user",
        )
        session.add(reg_user)
        session.commit()

    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "normaluser", "password": "UserPassword123!"},
    )
    assert login_resp.status_code == 200

    return {
        "service": service,
        "settings": settings,
        "client": client,
        "data_dir": data_dir,
        "root1_path": root1_path,
    }


def test_preview_remove_empty_dirs_success(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]

    scope = root / "scope"
    (scope / "a" / "b").mkdir(parents=True)

    action = {
        "type": "remove_empty_dirs",
        "scope_paths": [str(scope)],
    }

    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": action, "page": 1, "page_size": 50},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["utility_action"] == "remove_empty_dirs"
    assert data["preview_source"] == "live-directory-readonly"
    assert data["live_filesystem_verified"] is False
    assert data["planned_operations_count"] == 2
    assert data["matched_count"] == 2
    assert data["candidate_count"] == 2
    assert data["skipped_count"] == 0
    assert data["matched_bytes"] == 0
    assert data["candidate_bytes"] == 0
    assert data["expected_reclaim_bytes"] == 0

    items = data["items"]
    assert len(items) == 2
    # Deepest-first
    assert items[0]["relative_path"] == "a/b"
    assert items[0]["decision"] == "REMOVE_EMPTY_DIR"
    assert items[0]["object_type"] == "directory"
    assert items[0]["target_path"] is None

    assert items[1]["relative_path"] == "a"
    assert items[1]["decision"] == "REMOVE_EMPTY_DIR"

    # Zero mutation verification: directories still exist on disk
    assert (scope / "a" / "b").is_dir()
    assert (scope / "a").is_dir()


def test_preview_remove_empty_dirs_leaf_symlink_error(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]

    real_scope = root / "real_scope"
    real_scope.mkdir()
    sym_scope = root / "sym_scope"
    os.symlink(str(real_scope), str(sym_scope))

    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "remove_empty_dirs", "scope_paths": [str(sym_scope)]}},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_SYMLINK_BLOCKED"


def test_preview_remove_empty_dirs_missing_scope(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]

    missing_scope = root / "non_existent_scope"

    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "remove_empty_dirs", "scope_paths": [str(missing_scope)]}},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_SCOPE_NOT_FOUND"


def test_preview_remove_empty_dirs_scope_overlap(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]

    scope1 = root / "dir1"
    scope2 = scope1 / "sub"
    scope2.mkdir(parents=True)

    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "remove_empty_dirs", "scope_paths": [str(scope1), str(scope2)]}},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_SCOPE_OVERLAP"
