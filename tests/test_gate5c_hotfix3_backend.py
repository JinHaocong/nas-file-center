import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import (
    BatchPlan,
    FilterPolicy,
    IndexRoot,
    IndexedPath,
    Workflow,
    WorkflowRevision,
)
from app.service import FileCenterService


@pytest.fixture
def hf3_client(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        quarantine_root=quarantine_dir,
        allowed_roots_raw=str(data_dir),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
    )
    service = FileCenterService(settings)

    (data_dir / "doc1.txt").write_text("hello 1")

    with service.SessionLocal() as session:
        root = IndexRoot(id=1, root=str(data_dir))
        session.add(root)
        policy = FilterPolicy(
            id=1,
            exclude_dir_names_json=json.dumps([".git", ".recycle", "@eaDir", ".nas-file-center-trash"]),
        )
        session.merge(policy)

        session.add(
            IndexedPath(
                root_key=str(root.root),
                absolute_path=str(data_dir / "doc1.txt"),
                relative_path="doc1.txt",
                basename="doc1.txt",
                stem="doc1",
                suffix=".txt",
                size=7,
                mtime_ns=1_700_000_000_000_000_000,
                is_dir=False,
                scan_generation="gen1",
            )
        )
        session.commit()

    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    client.headers["Referer"] = "http://testserver/"

    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    )
    assert login_resp.status_code == 200

    yield client, service, tmp_path


def test_strict_sha_trailing_newline_rejected(hf3_client):
    client, service, tmp_path = hf3_client

    # Create file workflow
    wf_resp = client.post(
        "/api/workflows",
        json={
            "name": "Lineage SHA Test Workflow",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {"id": "r1", "type": "rename", "pattern": "doc", "replacement": "report"},
                ],
            },
        },
    )
    assert wf_resp.status_code == 201
    wf_id = wf_resp.json()["id"]

    # Preview and generate draft plan
    prev_resp = client.post(f"/api/workflows/{wf_id}/preview", json={"revision": 1, "page": 1, "page_size": 50})
    assert prev_resp.status_code == 200
    compile_digest = prev_resp.json()["compile_digest"]
    assert len(compile_digest) == 64

    gen_resp = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={"expected_compile_digest": compile_digest, "revision": 1, "plan_name": "Test Plan"},
    )
    assert gen_resp.status_code == 201
    plan_id = gen_resp.json()["plan_id"]

    # Freeze & modify file to make it stale
    assert client.post(f"/api/plans/{plan_id}/freeze").status_code == 200
    (tmp_path / "data" / "doc1.txt").write_text("hello 1 modified")
    assert client.post(f"/api/plans/{plan_id}/validate").status_code == 200
    assert client.get(f"/api/plans/{plan_id}").json()["status"] == "stale"

    # Test 1: compile_digest with trailing newline "a"*64 + "\n"
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        meta = json.loads(plan.metadata_json)
        meta["compile_digest"] = "a" * 64 + "\n"
        plan.metadata_json = json.dumps(meta)
        session.commit()

    reb_resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={"page": 1, "page_size": 50})
    assert reb_resp.status_code == 400
    assert reb_resp.json()["error"]["code"] == "PLAN_REBUILD_LINEAGE_MISSING"

    # Test 2: compile_digest with trailing carriage return "a"*64 + "\r"
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        meta = json.loads(plan.metadata_json)
        meta["compile_digest"] = "a" * 64 + "\r"
        plan.metadata_json = json.dumps(meta)
        session.commit()

    reb_resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={"page": 1, "page_size": 50})
    assert reb_resp.status_code == 400
    assert reb_resp.json()["error"]["code"] == "PLAN_REBUILD_LINEAGE_MISSING"

    # Test 3: compile_digest with trailing space "a"*64 + " "
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        meta = json.loads(plan.metadata_json)
        meta["compile_digest"] = "a" * 64 + " "
        plan.metadata_json = json.dumps(meta)
        session.commit()

    reb_resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={"page": 1, "page_size": 50})
    assert reb_resp.status_code == 400
    assert reb_resp.json()["error"]["code"] == "PLAN_REBUILD_LINEAGE_MISSING"

    # Test 4: definition_sha256 with trailing newline "b"*64 + "\n"
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        meta = json.loads(plan.metadata_json)
        meta["compile_digest"] = compile_digest
        meta["definition_sha256"] = "b" * 64 + "\n"
        plan.metadata_json = json.dumps(meta)
        session.commit()

    reb_resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={"page": 1, "page_size": 50})
    assert reb_resp.status_code == 400
    assert reb_resp.json()["error"]["code"] == "PLAN_REBUILD_LINEAGE_MISSING"

    # Test 5: definition_sha256 with trailing carriage return "b"*64 + "\r"
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        meta = json.loads(plan.metadata_json)
        meta["definition_sha256"] = "b" * 64 + "\r"
        plan.metadata_json = json.dumps(meta)
        session.commit()

    reb_resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={"page": 1, "page_size": 50})
    assert reb_resp.status_code == 400
    assert reb_resp.json()["error"]["code"] == "PLAN_REBUILD_LINEAGE_MISSING"

    # Test 6: definition_sha256 with trailing space "b"*64 + " "
    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        meta = json.loads(plan.metadata_json)
        meta["definition_sha256"] = "b" * 64 + " "
        plan.metadata_json = json.dumps(meta)
        session.commit()

    reb_resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={"page": 1, "page_size": 50})
    assert reb_resp.status_code == 400
    assert reb_resp.json()["error"]["code"] == "PLAN_REBUILD_LINEAGE_MISSING"

    # Test 7: Valid 64 hex accepts
    with service.SessionLocal() as session:
        rev = session.query(WorkflowRevision).filter_by(workflow_id=wf_id, revision=1).first()
        plan = session.get(BatchPlan, plan_id)
        meta = json.loads(plan.metadata_json)
        meta["compile_digest"] = compile_digest
        meta["definition_sha256"] = rev.definition_sha256
        plan.metadata_json = json.dumps(meta)
        session.commit()

    reb_resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={"page": 1, "page_size": 50})
    assert reb_resp.status_code == 200
    assert len(reb_resp.json()["compile_digest"]) == 64
