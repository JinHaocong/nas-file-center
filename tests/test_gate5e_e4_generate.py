import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.main import create_app
from app.models import IndexRoot, User, BatchPlan, BatchPlanItem
from app.config import Settings
from app.service import FileCenterService
from app.auth.password import hash_password
import app.batch_utilities.compiler as compiler_mod
import app.batch_utilities.empty_dirs as empty_dirs_mod


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


def test_generate_remove_empty_dirs_success(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]

    scope = root / "scope"
    (scope / "a" / "b").mkdir(parents=True)

    action = {
        "type": "remove_empty_dirs",
        "scope_paths": [str(scope)],
    }

    # Step 1: Preview
    resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": action, "page": 1, "page_size": 50},
    )
    assert resp.status_code == 200
    digest = resp.json()["preview_digest"]

    # Step 2: Generate
    req = {
        "action": action,
        "expected_preview_digest": digest,
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 201, resp.text

    data = resp.json()
    plan_id = data["id"]
    assert data["utility_action"] == "remove_empty_dirs"
    assert data["expected_changes"] == 2
    assert data["expected_reclaim_bytes"] == 0

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "draft"
        assert plan.kind == "batch-utility"
        meta = json.loads(plan.metadata_json)
        assert meta["utility_action"] == "remove_empty_dirs"
        assert meta["scope_paths"] == [str(scope.resolve())]

        items = session.query(BatchPlanItem).filter_by(plan_id=plan_id).order_by(BatchPlanItem.sequence).all()
        assert len(items) == 2

        # Item 0: a/b (deepest-first)
        assert items[0].sequence == 1
        assert items[0].operation == "rmdir_empty"
        assert items[0].source_path == str(scope / "a" / "b")
        assert items[0].target_path is None
        assert items[0].keep_path is None
        assert items[0].expected_device == 0
        assert items[0].expected_inode == 0
        assert items[0].expected_mtime_ns == 0
        assert items[0].expected_size == 0
        assert items[0].expected_hash is None
        assert items[0].state == "planned"

        # Item 1: a
        assert items[1].sequence == 2
        assert items[1].operation == "rmdir_empty"
        assert items[1].source_path == str(scope / "a")
        assert items[1].target_path is None
        assert items[1].expected_device == 0
        assert items[1].expected_inode == 0


def test_generate_remove_empty_dirs_preview_changed(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]

    scope = root / "scope"
    (scope / "a").mkdir(parents=True)

    action = {
        "type": "remove_empty_dirs",
        "scope_paths": [str(scope)],
    }

    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    digest = resp.json()["preview_digest"]

    # Mutate disk: add a file inside scope/a
    (scope / "a" / "blocker.txt").write_text("blocked")

    # Generate should fail with 409 PREVIEW_CHANGED
    req = {
        "action": action,
        "expected_preview_digest": digest,
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "PREVIEW_CHANGED"

    # Zero plans persisted
    with service.SessionLocal() as session:
        plans_count = session.query(func.count(BatchPlan.id)).scalar()
        assert plans_count == 0


def test_generate_remove_empty_dirs_empty_plan_fails(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]

    scope = root / "scope"
    (scope / "dir_with_file").mkdir(parents=True)
    (scope / "dir_with_file" / "data.bin").write_bytes(b"123")

    action = {
        "type": "remove_empty_dirs",
        "scope_paths": [str(scope)],
    }

    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    assert resp.json()["candidate_count"] == 0
    digest = resp.json()["preview_digest"]

    req = {
        "action": action,
        "expected_preview_digest": digest,
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_EMPTY_PLAN"

    with service.SessionLocal() as session:
        plans_count = session.query(func.count(BatchPlan.id)).scalar()
        assert plans_count == 0


def test_generate_phase_b_zero_filesystem_reads(api_test_env, monkeypatch):
    client = api_test_env["client"]
    service = api_test_env["service"]
    root = api_test_env["root1_path"]

    scope = root / "scope"
    (scope / "child").mkdir(parents=True)

    action = {
        "type": "remove_empty_dirs",
        "scope_paths": [str(scope)],
    }

    resp = client.post("/api/batch-utilities/preview", json={"action": action})
    assert resp.status_code == 200
    digest = resp.json()["preview_digest"]

    # Wrap _persist_batch_utility_draft to poison discovery/traversal during Phase B
    orig_persist = service._persist_batch_utility_draft

    def poisoned_persist(*args, **kwargs):
        def forbidden(*a, **kw):
            raise RuntimeError("FILESYSTEM WORK FORBIDDEN IN PHASE B")
        monkeypatch.setattr(empty_dirs_mod, "discover_remove_empty_dirs", forbidden)
        monkeypatch.setattr(empty_dirs_mod, "validate_remove_empty_scopes_preflight", forbidden)
        return orig_persist(*args, **kwargs)

    monkeypatch.setattr(service, "_persist_batch_utility_draft", poisoned_persist)

    req = {
        "action": action,
        "expected_preview_digest": digest,
    }
    resp = client.post("/api/batch-utilities/generate-plan", json=req)
    assert resp.status_code == 201
    plan_id = resp.json()["id"]

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
