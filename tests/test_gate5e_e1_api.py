from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from app.main import create_app
from app.models import Base, IndexRoot, IndexedPath, BatchPlan, BatchPlanItem, WorkJob, QuarantineEntry
from app.config import Settings
from app.service import FileCenterService


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

    # Seed 60 files under data_dir / root1 so page 1 and page 2 both have items
    root1_path = data_dir / "root1"
    root1_path.mkdir()

    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root1_path))
        session.add(r)
        session.commit()

        for i in range(1, 65):
            f = root1_path / f"file_{i:03d}.txt"
            f.write_text(f"content {i}")
            st = f.stat()
            p = IndexedPath(
                root_key=str(root1_path),
                absolute_path=str(f),
                relative_path=f"file_{i:03d}.txt",
                basename=f.name,
                stem=f.stem,
                suffix=".txt",
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                device=st.st_dev,
                inode=st.st_ino,
                is_dir=False,
                scan_generation=1,
            )
            session.add(p)

        from app.auth.password import hash_password
        from app.models import User
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
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"

    return {
        "service": service,
        "settings": settings,
        "client": client,
        "data_dir": data_dir,
        "root1_path": root1_path,
    }


def test_preview_api_valid_request_and_zero_side_effects(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]

    # Record DB counts before
    with service.SessionLocal() as session:
        plan_count_before = session.scalar(select(func.count(BatchPlan.id))) or 0
        item_count_before = session.scalar(select(func.count(BatchPlanItem.id))) or 0
        job_count_before = session.scalar(select(func.count(WorkJob.id))) or 0
        quarantine_count_before = session.scalar(select(func.count(QuarantineEntry.id))) or 0

    payload = {
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {
                "field": "extension",
                "operator": "eq",
                "value": "txt",
            },
        },
        "page": 1,
        "page_size": 50,
    }

    resp = client.post("/api/batch-utilities/preview", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["utility_action"] == "quarantine_filtered"
    assert data["preview_source"] == "index-readonly-safety"
    assert data["live_filesystem_verified"] is False
    assert data["page"] == 1
    assert data["page_size"] == 50
    assert data["total_pages"] == 2
    assert len(data["items"]) == 50
    assert len(data["preview_digest"]) == 64
    assert len(data["action_config_digest"]) == 64
    assert len(data["source_snapshot_digest"]) == 64

    # Assert 0 side effects on DB
    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(BatchPlan.id))) == plan_count_before
        assert session.scalar(select(func.count(BatchPlanItem.id))) == item_count_before
        assert session.scalar(select(func.count(WorkJob.id))) == job_count_before
        assert session.scalar(select(func.count(QuarantineEntry.id))) == quarantine_count_before


def test_preview_api_pagination_and_digest_invariance(api_test_env):
    client = api_test_env["client"]

    base_action = {
        "type": "quarantine_filtered",
        "root_ids": [1],
        "filter": {
            "field": "extension",
            "operator": "eq",
            "value": "txt",
        },
    }

    # Page 1
    resp1 = client.post("/api/batch-utilities/preview", json={"action": base_action, "page": 1, "page_size": 50})
    assert resp1.status_code == 200
    d1 = resp1.json()

    # Page 2
    resp2 = client.post("/api/batch-utilities/preview", json={"action": base_action, "page": 2, "page_size": 50})
    assert resp2.status_code == 200
    d2 = resp2.json()

    # Page size 25
    resp3 = client.post("/api/batch-utilities/preview", json={"action": base_action, "page": 1, "page_size": 25})
    assert resp3.status_code == 200
    d3 = resp3.json()

    # Items differ between pages
    assert [r["source_path"] for r in d1["items"]] != [r["source_path"] for r in d2["items"]]
    assert len(d1["items"]) == 50
    assert len(d2["items"]) == 14

    # Digests are invariant across pagination
    assert d1["preview_digest"] == d2["preview_digest"]
    assert d1["preview_digest"] == d3["preview_digest"]
    assert d1["action_config_digest"] == d2["action_config_digest"]
    assert d1["source_snapshot_digest"] == d2["source_snapshot_digest"]


def test_preview_api_error_envelopes(api_test_env):
    client = api_test_env["client"]

    # 1. Scope not found -> 404 BATCH_UTILITY_SCOPE_NOT_FOUND
    resp_404 = client.post("/api/batch-utilities/preview", json={
        "action": {"type": "quarantine_filtered", "root_ids": [999]},
    })
    assert resp_404.status_code == 404
    err_404 = resp_404.json()
    assert "error" in err_404
    assert err_404["error"]["code"] == "BATCH_UTILITY_SCOPE_NOT_FOUND"

    # 2. Invalid config: page_size > 500 -> 422 BATCH_UTILITY_INVALID_CONFIG
    resp_page_size = client.post("/api/batch-utilities/preview", json={
        "action": {"type": "quarantine_filtered", "root_ids": [1]},
        "page_size": 501,
    })
    assert resp_page_size.status_code == 422
    err_ps = resp_page_size.json()
    assert "error" in err_ps
    assert err_ps["error"]["code"] == "BATCH_UTILITY_INVALID_CONFIG"

    # 3. Invalid config: unimplemented action -> 422 BATCH_UTILITY_INVALID_CONFIG
    resp_unimp = client.post("/api/batch-utilities/preview", json={
        "action": {"type": "suffix_transform", "root_ids": [1]},
    })
    assert resp_unimp.status_code == 422
    err_unimp = resp_unimp.json()
    assert "error" in err_unimp
    assert err_unimp["error"]["code"] == "BATCH_UTILITY_INVALID_CONFIG"

    # 4. Invalid config: malformed filter AST -> 422 BATCH_UTILITY_INVALID_CONFIG
    resp_bad_filter = client.post("/api/batch-utilities/preview", json={
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {"field": "unknown_field", "operator": "eq", "value": "val"},
        },
    })
    assert resp_bad_filter.status_code == 422
    err_bf = resp_bad_filter.json()
    assert "error" in err_bf
    assert err_bf["error"]["code"] == "BATCH_UTILITY_INVALID_CONFIG"
