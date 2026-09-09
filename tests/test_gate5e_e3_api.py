import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.main import create_app
from app.models import Base, IndexRoot, IndexedPath, BatchPlan, BatchPlanItem, WorkJob, QuarantineEntry
from app.config import Settings
from app.service import FileCenterService
from app.auth.password import hash_password
from app.models import User

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
        session.commit()
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

def test_preview_flatten_one_level(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    
    wrapper = root / "wrapper"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("a")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": action, "page": 1, "page_size": 50}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["utility_action"] == "flatten_one_level"
    assert data["preview_source"] == "live-directory-readonly"
    assert data["planned_operations_count"] == 1
    
    items = data["items"]
    assert len(items) == 1
    assert items[0]["source_path"] == str(wrapper / "a.txt")
    assert items[0]["target_path"] == str(root / "a.txt")
    assert items[0]["decision"] == "MOVE"
    assert items[0]["wrapper_path"] == str(wrapper)
    assert items[0]["object_type"] == "file"
    assert items[0]["index_root_id"] is None
    assert items[0]["index_root_path"] is None


def test_preview_wrapper_symlink_error(api_test_env):
    import os
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    
    real_wrapper = root / "real_w"
    real_wrapper.mkdir()
    sym_wrapper = root / "sym_w"
    os.symlink(str(real_wrapper), str(sym_wrapper))
    
    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(sym_wrapper)]}}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_SYMLINK_BLOCKED"


def test_preview_wrapper_cross_root_error(api_test_env, tmp_path):
    client = api_test_env["client"]
    outside = tmp_path / "outside_w"
    outside.mkdir(parents=True)
    
    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(outside)]}}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_CROSS_ROOT"


def test_preview_wrapper_child_symlink(api_test_env):
    import os
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    
    wrapper = root / "wrapper_sym_child"
    wrapper.mkdir()
    (wrapper / "real.txt").write_text("real")
    os.symlink("real.txt", wrapper / "link.txt")
    
    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "flatten_one_level", "wrapper_paths": [str(wrapper)]}}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["planned_operations_count"] == 1
    rows_by_src = {it["source_path"]: it for it in data["items"]}
    assert rows_by_src[str(wrapper / "real.txt")]["decision"] == "MOVE"
    assert rows_by_src[str(wrapper / "link.txt")]["decision"] == "BLOCKING_CONFLICT"
    assert rows_by_src[str(wrapper / "link.txt")]["reason_code"] == "WRAPPER_CHILD_SYMLINK"

