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

        for i in range(1, 11):
            f = root1_path / f"file_{i:02d}.png"
            f.write_text(f"content {i}")
            st = f.stat()
            p = IndexedPath(
                root_key=str(root1_path),
                absolute_path=str(f),
                relative_path=f"file_{i:02d}.png",
                basename=f.name,
                stem=f.stem,
                suffix=".png",
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                device=st.st_dev,
                inode=st.st_ino,
                is_dir=False,
                scan_generation=1,
            )
            session.add(p)

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


def test_preview_api_suffix_transform_success_and_zero_side_effects(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]

    # Record DB counts before preview
    with service.SessionLocal() as session:
        plan_count_before = session.scalar(select(func.count(BatchPlan.id))) or 0
        item_count_before = session.scalar(select(func.count(BatchPlanItem.id))) or 0
        job_count_before = session.scalar(select(func.count(WorkJob.id))) or 0
        q_count_before = session.scalar(select(func.count(QuarantineEntry.id))) or 0

    resp = client.post(
        "/api/batch-utilities/preview",
        json={
            "action": {
                "type": "suffix_transform",
                "root_ids": [1],
                "mode": "change",
                "suffix": ".webp",
            },
            "page": 1,
            "page_size": 5,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["utility_action"] == "suffix_transform"
    assert data["matched_count"] == 10
    assert data["planned_operations_count"] == 10
    assert data["blocking_conflict_count"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 5
    assert len(data["items"]) == 5
    assert all(it["decision"] == "RENAME" for it in data["items"])
    assert all(it["target_path"].endswith(".webp") for it in data["items"])

    # Zero side effects verification
    with service.SessionLocal() as session:
        assert session.scalar(select(func.count(BatchPlan.id))) == plan_count_before
        assert session.scalar(select(func.count(BatchPlanItem.id))) == item_count_before
        assert session.scalar(select(func.count(WorkJob.id))) == job_count_before
        assert session.scalar(select(func.count(QuarantineEntry.id))) == q_count_before


def test_preview_api_suffix_transform_blocking_conflict(api_test_env):
    client = api_test_env["client"]
    root1_path = api_test_env["root1_path"]

    # Create unvacated target collision: file_01.png -> file_01.png.bak
    collision_target = root1_path / "file_01.png.bak"
    collision_target.write_text("already exists")

    resp = client.post(
        "/api/batch-utilities/preview",
        json={
            "action": {
                "type": "suffix_transform",
                "root_ids": [1],
                "mode": "append",
                "suffix": ".bak",
            }
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["blocking_conflict_count"] >= 1
    conflict_rows = [r for r in data["items"] if r["decision"] == "BLOCKING_CONFLICT"]
    assert any(r["reason_code"] == "TARGET_EXISTS" for r in conflict_rows)



def test_preview_api_invalid_suffix_rejected(api_test_env):
    client = api_test_env["client"]

    resp = client.post(
        "/api/batch-utilities/preview",
        json={
            "action": {
                "type": "suffix_transform",
                "root_ids": [1],
                "mode": "append",
                "suffix": "path/like/suffix",
            }
        },
    )
    assert resp.status_code == 422
    err = resp.json()
    assert err["error"]["code"] == "BATCH_UTILITY_INVALID_CONFIG"


def test_generate_plan_api_suffix_transform_success(api_test_env):
    client = api_test_env["client"]
    service = api_test_env["service"]

    prev_resp = client.post(
        "/api/batch-utilities/preview",
        json={
            "action": {
                "type": "suffix_transform",
                "root_ids": [1],
                "mode": "change",
                "suffix": ".webp",
            }
        },
    )
    assert prev_resp.status_code == 200
    preview_digest = prev_resp.json()["preview_digest"]

    gen_resp = client.post(
        "/api/batch-utilities/generate-plan",
        json={
            "action": {
                "type": "suffix_transform",
                "root_ids": [1],
                "mode": "change",
                "suffix": ".webp",
            },
            "expected_preview_digest": preview_digest,
        },
    )
    assert gen_resp.status_code == 201
    plan_data = gen_resp.json()
    assert plan_data["status"] == "draft"
    assert plan_data["utility_action"] == "suffix_transform"
    assert plan_data["expected_changes"] == 10

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_data["id"])
        assert plan is not None
        assert plan.status == "draft"
        items = session.query(BatchPlanItem).filter_by(plan_id=plan.id).all()
        assert len(items) == 10
        assert all(it.operation == "rename" for it in items)


def test_generate_plan_api_digest_mismatch(api_test_env):
    client = api_test_env["client"]

    resp = client.post(
        "/api/batch-utilities/generate-plan",
        json={
            "action": {
                "type": "suffix_transform",
                "root_ids": [1],
                "mode": "change",
                "suffix": ".webp",
            },
            "expected_preview_digest": "f" * 64,
        },
    )
    assert resp.status_code == 409
    err = resp.json()
    assert err["error"]["code"] == "PREVIEW_CHANGED"


def test_generate_plan_api_blocking_conflict_rejected(api_test_env):
    client = api_test_env["client"]
    root1_path = api_test_env["root1_path"]

    # Target already exists on disk
    target = root1_path / "file_01.png.bak"
    target.write_text("collision")

    prev_resp = client.post(
        "/api/batch-utilities/preview",
        json={
            "action": {
                "type": "suffix_transform",
                "root_ids": [1],
                "mode": "append",
                "suffix": ".bak",
            }
        },
    )
    digest = prev_resp.json()["preview_digest"]

    gen_resp = client.post(
        "/api/batch-utilities/generate-plan",
        json={
            "action": {
                "type": "suffix_transform",
                "root_ids": [1],
                "mode": "append",
                "suffix": ".bak",
            },
            "expected_preview_digest": digest,
        },
    )
    assert gen_resp.status_code == 409
    err = gen_resp.json()
    assert err["error"]["code"] == "BATCH_UTILITY_COLLISION"


def test_generate_plan_api_specific_error_codes(api_test_env, monkeypatch):
    """Reviewer reproduction G: Test specific error codes for TARGET_SYMLINK, NAME_TOO_LONG, CASE_ONLY_COLLISION, TARGET_EXISTS."""
    import os
    client = api_test_env["client"]
    root1_path = api_test_env["root1_path"]

    # 1. TARGET_SYMLINK -> BATCH_UTILITY_SYMLINK_BLOCKED
    other_file = root1_path / "other_raw.txt"
    other_file.write_text("other")
    link_target = root1_path / "file_01.png.sym"
    link_target.symlink_to(other_file)

    p_resp = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "suffix_transform", "root_ids": [1], "mode": "append", "suffix": ".sym"}},
    )
    assert p_resp.status_code == 200
    digest = p_resp.json()["preview_digest"]

    g_resp = client.post(
        "/api/batch-utilities/generate-plan",
        json={"action": {"type": "suffix_transform", "root_ids": [1], "mode": "append", "suffix": ".sym"}, "expected_preview_digest": digest},
    )
    assert g_resp.status_code == 409
    assert g_resp.json()["error"]["code"] == "BATCH_UTILITY_SYMLINK_BLOCKED"

    # 2. NAME_TOO_LONG -> BATCH_UTILITY_NAME_TOO_LONG (via pathconf monkeypatch)
    orig_pathconf = os.pathconf
    def mock_pathconf(path, name):
        if name == "PC_NAME_MAX":
            return 10
        return orig_pathconf(path, name)

    monkeypatch.setattr(os, "pathconf", mock_pathconf)

    p_resp2 = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "suffix_transform", "root_ids": [1], "mode": "append", "suffix": ".toolong"}},
    )
    assert p_resp2.status_code == 200
    digest2 = p_resp2.json()["preview_digest"]

    g_resp2 = client.post(
        "/api/batch-utilities/generate-plan",
        json={"action": {"type": "suffix_transform", "root_ids": [1], "mode": "append", "suffix": ".toolong"}, "expected_preview_digest": digest2},
    )
    assert g_resp2.status_code == 409
    assert g_resp2.json()["error"]["code"] == "BATCH_UTILITY_NAME_TOO_LONG"

    monkeypatch.undo()

    # 3. CASE_ONLY_COLLISION -> BATCH_UTILITY_CASE_COLLISION
    # Create file_01.png.case
    case_target = root1_path / "FILE_01.PNG.CASE"
    case_target.write_text("case collision")

    p_resp3 = client.post(
        "/api/batch-utilities/preview",
        json={"action": {"type": "suffix_transform", "root_ids": [1], "mode": "append", "suffix": ".case"}},
    )
    assert p_resp3.status_code == 200
    digest3 = p_resp3.json()["preview_digest"]

    g_resp3 = client.post(
        "/api/batch-utilities/generate-plan",
        json={"action": {"type": "suffix_transform", "root_ids": [1], "mode": "append", "suffix": ".case"}, "expected_preview_digest": digest3},
    )
    assert g_resp3.status_code == 409
    assert g_resp3.json()["error"]["code"] == "BATCH_UTILITY_CASE_COLLISION"



def test_generate_plan_api_empty_plan_rejected(api_test_env):
    client = api_test_env["client"]

    # Changing .png to .png results in NO_CHANGE for all files
    prev_resp = client.post(
        "/api/batch-utilities/preview",
        json={
            "action": {
                "type": "suffix_transform",
                "root_ids": [1],
                "mode": "change",
                "suffix": ".png",
            }
        },
    )
    digest = prev_resp.json()["preview_digest"]

    gen_resp = client.post(
        "/api/batch-utilities/generate-plan",
        json={
            "action": {
                "type": "suffix_transform",
                "root_ids": [1],
                "mode": "change",
                "suffix": ".png",
            },
            "expected_preview_digest": digest,
        },
    )
    assert gen_resp.status_code == 422
    err = gen_resp.json()
    assert err["error"]["code"] == "BATCH_UTILITY_EMPTY_PLAN"
