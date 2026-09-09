import json
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func

from app.main import create_app
from app.models import Base, IndexRoot, IndexedPath, BatchPlan, BatchPlanItem, WorkJob, QuarantineEntry
from app.config import Settings
from app.service import FileCenterService


@pytest.fixture
def generate_test_env(tmp_path):
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

    # Create 5 txt files in root1: file1..file5
    created_files = []
    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root1_path))
        session.add(r)
        session.commit()

        for i in range(1, 6):
            f = root1_path / f"file_{i:02d}.txt"
            f.write_text(f"content {i}")
            st = f.stat()
            created_files.append((f, st.st_size))
            p = IndexedPath(
                root_key=str(root1_path),
                absolute_path=str(f),
                relative_path=f"file_{i:02d}.txt",
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
            username="testuser",
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
        json={"username": "testuser", "password": "UserPassword123!"},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"

    return {
        "service": service,
        "settings": settings,
        "client": client,
        "data_dir": data_dir,
        "root1_path": root1_path,
        "created_files": created_files,
    }


def test_generate_plan_success_and_draft_properties(generate_test_env):
    client = generate_test_env["client"]
    service = generate_test_env["service"]
    root1_path = generate_test_env["root1_path"]

    # 1. First get preview to obtain preview_digest
    preview_payload = {
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {
                "field": "extension",
                "operator": "eq",
                "value": "txt",
            },
        },
    }
    prev_resp = client.post("/api/batch-utilities/preview", json=preview_payload)
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()
    digest = prev_data["preview_digest"]
    assert len(digest) == 64
    # 5 files in root1 with protect_last_file=True -> 4 actionable, 1 safety excluded
    assert prev_data["planned_operations_count"] == 4

    # 2. Call generate-plan
    gen_payload = {
        "action": preview_payload["action"],
        "expected_preview_digest": digest,
    }
    gen_resp = client.post("/api/batch-utilities/generate-plan", json=gen_payload)
    assert gen_resp.status_code == 201, f"Generate failed: {gen_resp.text}"
    gen_data = gen_resp.json()

    assert gen_data["id"] == gen_data["plan_id"]
    assert gen_data["status"] == "draft"
    assert gen_data["utility_action"] == "quarantine_filtered"
    assert gen_data["expected_changes"] == 4
    assert gen_data["expected_reclaim_bytes"] == prev_data["expected_reclaim_bytes"]
    assert gen_data["preview_digest"] == digest

    # 3. Verify DB state
    with service.SessionLocal() as session:
        # Check BatchPlan
        plans = session.scalars(select(BatchPlan)).all()
        assert len(plans) == 1
        plan = plans[0]
        assert plan.id == gen_data["plan_id"]
        assert plan.status == "draft"
        assert plan.kind == "batch-utility"
        assert plan.name == "batch-utility-quarantine-filtered"
        assert plan.expected_changes == 4

        # Check plan metadata
        plan_meta = json.loads(plan.metadata_json)
        assert plan_meta["source"] == "batch-utility"
        assert plan_meta["utility_action"] == "quarantine_filtered"
        assert plan_meta["utility_engine_version"] == 1
        assert plan_meta["preview_digest"] == digest
        assert "action_config_digest" in plan_meta
        assert "source_snapshot_digest" in plan_meta
        assert plan_meta["roots"] == [{"index_root_id": 1, "root": str(root1_path)}]
        assert plan_meta["effective_safety_policy"]["protect_last_file"] is True

        # Check 0 WorkJobs
        jobs_count = session.scalar(select(func.count(WorkJob.id)))
        assert jobs_count == 0

        # Check 0 QuarantineEntry
        qe_count = session.scalar(select(func.count(QuarantineEntry.id)))
        assert qe_count == 0

        # Check BatchPlanItems
        items = session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan.id).order_by(BatchPlanItem.sequence)).all()
        assert len(items) == 4
        for idx, item in enumerate(items, 1):
            assert item.sequence == idx
            assert item.operation == "quarantine"
            assert item.target_path is None
            assert item.keep_path is None
            assert item.expected_device == 0
            assert item.expected_inode == 0
            assert item.expected_mtime_ns == 0
            assert item.expected_hash is None
            assert item.state == "planned"

            item_meta = json.loads(item.metadata_json)
            assert item_meta["utility_action"] == "quarantine_filtered"
            assert item_meta["index_root_id"] == 1
            assert item_meta["index_root_path"] == str(root1_path)
            assert item_meta["protected_dir"] == str(root1_path)
            assert "relative_path" in item_meta

    # 4. Verify filesystem files are untouched
    for f, orig_sz in generate_test_env["created_files"]:
        assert f.exists()
        assert f.stat().st_size == orig_sz


def test_generate_plan_mismatched_preview_digest_fails_409(generate_test_env):
    client = generate_test_env["client"]
    service = generate_test_env["service"]

    gen_payload = {
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {
                "field": "extension",
                "operator": "eq",
                "value": "txt",
            },
        },
        "expected_preview_digest": "0" * 64,
    }
    gen_resp = client.post("/api/batch-utilities/generate-plan", json=gen_payload)
    assert gen_resp.status_code == 409
    err = gen_resp.json()
    assert err["error"]["code"] == "PREVIEW_CHANGED"
    assert err["error"]["details"]["expected_preview_digest"] == "0" * 64
    assert len(err["error"]["details"]["actual_preview_digest"]) == 64

    # Assert 0 plans created
    with service.SessionLocal() as session:
        plans_count = session.scalar(select(func.count(BatchPlan.id)))
        assert plans_count == 0


def test_generate_plan_empty_plan_fails_422(generate_test_env):
    client = generate_test_env["client"]
    service = generate_test_env["service"]

    # Filter for non-existent extension -> 0 candidates
    preview_payload = {
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {
                "field": "extension",
                "operator": "eq",
                "value": "nonexistent",
            },
        },
    }
    prev_resp = client.post("/api/batch-utilities/preview", json=preview_payload)
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()
    assert prev_data["planned_operations_count"] == 0

    gen_payload = {
        "action": preview_payload["action"],
        "expected_preview_digest": prev_data["preview_digest"],
    }
    gen_resp = client.post("/api/batch-utilities/generate-plan", json=gen_payload)
    assert gen_resp.status_code == 422
    err = gen_resp.json()
    assert err["error"]["code"] == "BATCH_UTILITY_EMPTY_PLAN"

    # Assert 0 plans created
    with service.SessionLocal() as session:
        plans_count = session.scalar(select(func.count(BatchPlan.id)))
        assert plans_count == 0


def test_generate_plan_phase_b_db_race_rollback(generate_test_env):
    client = generate_test_env["client"]
    service = generate_test_env["service"]

    preview_payload = {
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {
                "field": "extension",
                "operator": "eq",
                "value": "txt",
            },
        },
    }
    prev_resp = client.post("/api/batch-utilities/preview", json=preview_payload)
    assert prev_resp.status_code == 200
    digest = prev_resp.json()["preview_digest"]

    gen_payload = {
        "action": preview_payload["action"],
        "expected_preview_digest": digest,
    }

    # Simulate race condition in Phase B: compute_current_quarantine_filtered_db_lineage_digest returns a different lineage
    with patch(
        "app.service.compute_current_quarantine_filtered_db_lineage_digest",
        return_value="f" * 64,
    ):
        gen_resp = client.post("/api/batch-utilities/generate-plan", json=gen_payload)
        assert gen_resp.status_code == 409
        err = gen_resp.json()
        assert err["error"]["code"] == "PREVIEW_CHANGED"
        assert "Database lineage changed" in err["error"]["message"]

    # Verify no plans or items were committed
    with service.SessionLocal() as session:
        plans_count = session.scalar(select(func.count(BatchPlan.id)))
        assert plans_count == 0
        items_count = session.scalar(select(func.count(BatchPlanItem.id)))
        assert items_count == 0


def test_generate_plan_request_validation(generate_test_env):
    client = generate_test_env["client"]

    # 1. Invalid digest length (not 64 chars)
    resp = client.post("/api/batch-utilities/generate-plan", json={
        "action": {"type": "quarantine_filtered", "root_ids": [1]},
        "expected_preview_digest": "short",
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_INVALID_CONFIG"

    # 2. Extra forbid field
    resp = client.post("/api/batch-utilities/generate-plan", json={
        "action": {"type": "quarantine_filtered", "root_ids": [1]},
        "expected_preview_digest": "a" * 64,
        "unexpected": "extra",
    })
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "BATCH_UTILITY_INVALID_CONFIG"


def test_generate_plan_protect_last_file_false_omits_protected_dir(tmp_path):
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
        protect_last_file=False,
    )

    service = FileCenterService(settings)
    root1_path = data_dir / "root1"
    root1_path.mkdir()

    with service.SessionLocal() as session:
        r = IndexRoot(id=1, root=str(root1_path))
        session.add(r)
        session.commit()

        f = root1_path / "only_file.txt"
        f.write_text("hello")
        st = f.stat()
        p = IndexedPath(
            root_key=str(root1_path),
            absolute_path=str(f),
            relative_path="only_file.txt",
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
            username="testuser2",
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
        json={"username": "testuser2", "password": "UserPassword123!"},
    )
    assert login_resp.status_code == 200

    preview_payload = {
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {
                "field": "extension",
                "operator": "eq",
                "value": "txt",
            },
        },
    }
    prev_resp = client.post("/api/batch-utilities/preview", json=preview_payload)
    assert prev_resp.status_code == 200
    prev_data = prev_resp.json()
    assert prev_data["planned_operations_count"] == 1
    digest = prev_data["preview_digest"]

    gen_payload = {
        "action": preview_payload["action"],
        "expected_preview_digest": digest,
    }
    gen_resp = client.post("/api/batch-utilities/generate-plan", json=gen_payload)
    assert gen_resp.status_code == 201
    plan_id = gen_resp.json()["plan_id"]

    with service.SessionLocal() as session:
        items = session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)).all()
        assert len(items) == 1
        item_meta = json.loads(items[0].metadata_json)
        assert "protected_dir" not in item_meta


def test_generate_phase_b_zero_filter_compilation_under_write_lock(generate_test_env, monkeypatch):
    """Blocker B: verify compile_filter_to_sql is not called under Phase B write lock, and FilterPolicy change rejects."""
    import app.filters.compiler as filter_compiler
    import app.batch_utilities.compiler as batch_compiler
    from app.models import FilterPolicy

    client = generate_test_env["client"]
    service = generate_test_env["service"]

    preview_payload = {
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {
                "field": "extension",
                "operator": "eq",
                "value": "txt",
            },
        },
    }
    prev_resp = client.post("/api/batch-utilities/preview", json=preview_payload)
    assert prev_resp.status_code == 200
    digest = prev_resp.json()["preview_digest"]

    # Wrap _persist_batch_utility_draft to forbid filter compilation during write lock
    orig_persist = FileCenterService._persist_batch_utility_draft
    phase_b_compiler_calls = []

    def mock_compile_filter_to_sql(*args, **kwargs):
        phase_b_compiler_calls.append("compile_filter_to_sql")
        raise AssertionError("compile_filter_to_sql MUST NOT be called in Phase B write transaction!")

    def mock_parse_and_validate_filter(*args, **kwargs):
        phase_b_compiler_calls.append("_parse_and_validate_filter")
        raise AssertionError("_parse_and_validate_filter MUST NOT be called in Phase B write transaction!")

    def guarded_persist(self, *args, **kwargs):
        monkeypatch.setattr(batch_compiler, "compile_filter_to_sql", mock_compile_filter_to_sql)
        monkeypatch.setattr(batch_compiler, "_parse_and_validate_filter", mock_parse_and_validate_filter)
        return orig_persist(self, *args, **kwargs)

    monkeypatch.setattr(FileCenterService, "_persist_batch_utility_draft", guarded_persist)

    gen_payload = {
        "action": preview_payload["action"],
        "expected_preview_digest": digest,
    }
    gen_resp = client.post("/api/batch-utilities/generate-plan", json=gen_payload)
    assert gen_resp.status_code == 201
    assert len(phase_b_compiler_calls) == 0


def test_generate_phase_b_rejects_on_concurrent_filter_policy_change(generate_test_env, monkeypatch):
    """Blocker B: verify FilterPolicy change between Phase A and Phase B rejects as lineage changed."""
    from app.models import FilterPolicy

    client = generate_test_env["client"]

    preview_payload = {
        "action": {
            "type": "quarantine_filtered",
            "root_ids": [1],
            "filter": {
                "field": "extension",
                "operator": "eq",
                "value": "txt",
            },
        },
    }
    prev_resp = client.post("/api/batch-utilities/preview", json=preview_payload)
    assert prev_resp.status_code == 200
    digest = prev_resp.json()["preview_digest"]

    # Concurrently update FilterPolicy between Phase A and Phase B
    orig_persist = FileCenterService._persist_batch_utility_draft

    def mutate_policy_and_persist(self, *args, **kwargs):
        with self.SessionLocal() as session:
            pol = session.get(FilterPolicy, 1)
            if not pol:
                pol = FilterPolicy(id=1, exclude_dir_names_json=json.dumps(["concurrently_changed_dir"]))
                session.add(pol)
            else:
                pol.exclude_dir_names_json = json.dumps(["concurrently_changed_dir"])
            session.commit()
        return orig_persist(self, *args, **kwargs)

    monkeypatch.setattr(FileCenterService, "_persist_batch_utility_draft", mutate_policy_and_persist)

    gen_payload = {
        "action": preview_payload["action"],
        "expected_preview_digest": digest,
    }
    gen_resp = client.post("/api/batch-utilities/generate-plan", json=gen_payload)
    assert gen_resp.status_code == 409
    assert gen_resp.json()["error"]["code"] == "PREVIEW_CHANGED"

