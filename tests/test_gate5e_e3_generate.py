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
import pytest
from app.models import BatchPlan, BatchPlanItem

def test_generate_flatten_one_level_success(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("a")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action, "page": 1, "page_size": 50})
    assert resp.status_code == 200
    preview_digest = resp.json()["preview_digest"]
    
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 201, resp.text
    
    data = resp.json()
    plan_id = data["id"]
    
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        
        
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).all()
        assert len(items) == 1
        assert items[0].operation == "move"
        assert items[0].source_path == str(wrapper / "a.txt")
        assert items[0].expected_hash is None


def test_generate_e3_draft_physical_identity_ownership(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper_ident"
    wrapper.mkdir()
    f = wrapper / "a.txt"
    f.write_text("hello identity")
    st = f.stat()
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    digest = resp.json()["preview_digest"]
    
    resp = client.post("/api/batch-utilities/generate-plan", json={"action": action, "expected_preview_digest": digest})
    assert resp.status_code == 201
    plan_id = resp.json()["id"]
    
    # 1. Inspect BatchPlanItem before Freeze
    with service.SessionLocal() as session:
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).all()
        assert len(items) == 1
        assert items[0].expected_device == 0
        assert items[0].expected_inode == 0
        assert items[0].expected_mtime_ns == 0
        assert items[0].expected_hash is None
        
    # 2. Freeze and inspect physical identity captured
    service.freeze_plan(plan_id)
    with service.SessionLocal() as session:
        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).all()
        assert len(items) == 1
        assert items[0].expected_device == st.st_dev
        assert items[0].expected_inode == st.st_ino
        assert items[0].expected_mtime_ns == st.st_mtime_ns

def test_generate_flatten_one_level_preview_changed(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("a")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    req = {
        "action": action,
        "expected_preview_digest": "0" * 64
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PREVIEW_CHANGED"

def test_generate_flatten_one_level_conflict(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper"
    wrapper.mkdir()
    (wrapper / "a.txt").write_text("a")
    # Conflict: target exists
    (root / "a.txt").write_text("exists")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    preview_digest = resp.json()["preview_digest"]
    
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_COLLISION"

def test_generate_flatten_one_level_empty_plan(api_test_env):
    client = api_test_env["client"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper"
    wrapper.mkdir()
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    preview_digest = resp.json()["preview_digest"]
    
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_EMPTY_PLAN"


def test_generate_flatten_mixed_safe_and_blocked_fails_closed(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper_mixed"
    wrapper.mkdir()
    (wrapper / "blocked.txt").write_text("blocked")
    (wrapper / "safe.txt").write_text("safe")
    # Make target for blocked exist
    (root / "blocked.txt").write_text("exists")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    assert resp.json()["planned_operations_count"] == 1
    preview_digest = resp.json()["preview_digest"]
    
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_COLLISION"
    
    # Verify zero plans created
    with service.SessionLocal() as session:
        plans = session.query(BatchPlan).all()
        assert len(plans) == 0


def test_generate_flatten_symlink_fails_closed(api_test_env):
    import os
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper_sym_child_gen"
    wrapper.mkdir()
    (wrapper / "real.txt").write_text("real")
    os.symlink("real.txt", wrapper / "child.link")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    preview_digest = resp.json()["preview_digest"]
    
    req = {
        "action": action,
        "expected_preview_digest": preview_digest
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_SYMLINK_BLOCKED"
    
    with service.SessionLocal() as session:
        plans = session.query(BatchPlan).all()
        assert len(plans) == 0


def test_generate_flatten_source_outside_allowed_roots_raises_cross_root(api_test_env, tmp_path):
    from unittest.mock import patch
    from app.batch_utilities.flatten import FlattenCandidate
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]
    wrapper = root / "wrapper_cross_src"
    wrapper.mkdir()
    
    outside = tmp_path / "outside_secret"
    outside.mkdir()
    outside_f = outside / "secret.txt"
    outside_f.write_text("secret")
    
    action = {
        "type": "flatten_one_level",
        "wrapper_paths": [str(wrapper)]
    }
    
    cand = FlattenCandidate(
        wrapper_path=str(wrapper),
        source_path=str(outside_f),
        target_path=str(root / "secret.txt"),
        object_type="file",
        size=6,
        mtime_ns=0,
        device=0,
        inode=0,
        is_dir=False,
    )
    
    with patch("app.batch_utilities.compiler.discover_flatten_one_level", return_value=([cand], [])):
        resp = client.post("/api/batch-utilities/preview", json={"action": action})
        assert resp.status_code == 200
        preview_digest = resp.json()["preview_digest"]
        
        req = {
            "action": action,
            "expected_preview_digest": preview_digest
        }
        resp = client.post("/api/batch-utilities/generate-plan", json=req)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "BATCH_UTILITY_CROSS_ROOT"
        
        with service.SessionLocal() as session:
            plans = session.query(BatchPlan).all()
            assert len(plans) == 0
