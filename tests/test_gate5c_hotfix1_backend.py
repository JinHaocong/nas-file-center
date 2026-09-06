import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, select

from app.config import Settings
from app.main import create_app
from app.models import (
    BatchPlan,
    FilterPolicy,
    IndexRoot,
    IndexedPath,
    Workflow,
    WorkflowRevision,
    utcnow,
)
from app.service import FileCenterService
from app.workflows.errors import WorkflowDigestMismatchError


@pytest.fixture
def hotfix1_env(tmp_path: Path):
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
    )
    service = FileCenterService(settings)

    with service.SessionLocal() as session:
        root1 = IndexRoot(id=1, root=str(data_dir))
        session.add(root1)
        policy = FilterPolicy(
            id=1,
            exclude_dir_names_json=json.dumps([".git", ".recycle", "@eaDir", ".nas-file-center-trash"]),
        )
        session.merge(policy)
        session.commit()

    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"

    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    )
    assert login_resp.status_code == 200

    return {
        "service": service,
        "client": client,
        "data_dir": data_dir,
    }


def test_red_rebuild_concurrent_workflow_archive_race(hotfix1_env):
    service: FileCenterService = hotfix1_env["service"]
    client: TestClient = hotfix1_env["client"]
    data_dir: Path = hotfix1_env["data_dir"]

    # Setup file and index
    f = data_dir / "test.txt"
    f.write_text("hello")
    with service.SessionLocal() as session:
        session.add(
            IndexedPath(
                root_key=str(data_dir),
                absolute_path=str(f),
                relative_path=f.name,
                basename=f.name,
                stem=f.stem,
                suffix=f.suffix,
                size=len(f.read_text()),
                mtime_ns=1_000_000,
                is_dir=False,
                scan_generation="gen1",
            )
        )
        session.commit()

    # Create workflow
    r_wf = client.post("/api/workflows", json={
        "name": "Race WF",
        "definition": {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {"id": "s2", "type": "touch", "touch_now": True, "mtime_ns": None},
            ],
        },
    })
    assert r_wf.status_code == 201
    wf_id = r_wf.json()["id"]

    # Preview and generate plan
    r_prev = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"root_ids": [1]}})
    assert r_prev.status_code == 200
    digest = r_prev.json()["compile_digest"]

    r_gen = client.post(f"/api/workflows/{wf_id}/generate-plan", json={
        "expected_compile_digest": digest,
        "runtime_inputs": {"root_ids": [1]},
    })
    assert r_gen.status_code == 201
    plan_id = r_gen.json()["plan_id"]

    # Mark plan stale
    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        p.status = "stale"
        session.commit()

    # Intercept compile_workflow_definition to simulate concurrent archive
    original_compile = service.workflow_service.compile_workflow_definition

    def compile_with_concurrent_archive(*args, **kwargs):
        res = original_compile(*args, **kwargs)
        # Concurrent archive before BEGIN IMMEDIATE
        with service.SessionLocal() as session2:
            wf_rec = session2.get(Workflow, wf_id)
            wf_rec.archived_at = utcnow()
            session2.commit()
        return res

    service.workflow_service.compile_workflow_definition = compile_with_concurrent_archive

    # Attempt rebuild: must be rejected with 409 PREVIEW_CHANGED, 0 draft created!
    with service.SessionLocal() as session:
        plans_before = session.scalar(text("SELECT count(*) FROM batch_plans"))

    with pytest.raises(WorkflowDigestMismatchError) as exc_info:
        service.rebuild_plan(plan_id, expected_compile_digest=digest)

    assert exc_info.value.code == "PREVIEW_CHANGED"
    assert exc_info.value.status_code == 409

    # Verify 0 drafts created
    with service.SessionLocal() as session:
        plans_after = session.scalar(text("SELECT count(*) FROM batch_plans"))
        assert plans_after == plans_before


def test_rebuild_concurrent_revision_changed_race(hotfix1_env):
    service: FileCenterService = hotfix1_env["service"]
    client: TestClient = hotfix1_env["client"]
    data_dir: Path = hotfix1_env["data_dir"]

    # Setup file and index
    f = data_dir / "test2.txt"
    f.write_text("hello2")
    with service.SessionLocal() as session:
        session.add(
            IndexedPath(
                root_key=str(data_dir),
                absolute_path=str(f),
                relative_path=f.name,
                basename=f.name,
                stem=f.stem,
                suffix=f.suffix,
                size=len(f.read_text()),
                mtime_ns=1_000_000,
                is_dir=False,
                scan_generation="gen1",
            )
        )
        session.commit()

    # Create workflow
    r_wf = client.post("/api/workflows", json={
        "name": "Race WF 2",
        "definition": {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {"id": "s2", "type": "touch", "touch_now": True, "mtime_ns": None},
            ],
        },
    })
    assert r_wf.status_code == 201
    wf_id = r_wf.json()["id"]

    r_prev = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"root_ids": [1]}})
    assert r_prev.status_code == 200
    digest = r_prev.json()["compile_digest"]

    r_gen = client.post(f"/api/workflows/{wf_id}/generate-plan", json={
        "expected_compile_digest": digest,
        "runtime_inputs": {"root_ids": [1]},
    })
    assert r_gen.status_code == 201
    plan_id = r_gen.json()["plan_id"]

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        p.status = "stale"
        session.commit()

    original_compile = service.workflow_service.compile_workflow_definition

    def compile_with_concurrent_rev_mod(*args, **kwargs):
        res = original_compile(*args, **kwargs)
        with service.SessionLocal() as session2:
            rev_rec = session2.scalar(
                select(WorkflowRevision).where(
                    WorkflowRevision.workflow_id == wf_id,
                    WorkflowRevision.revision == 1,
                )
            )
            rev_rec.definition_sha256 = "0" * 64
            session2.commit()
        return res

    service.workflow_service.compile_workflow_definition = compile_with_concurrent_rev_mod

    with pytest.raises(WorkflowDigestMismatchError) as exc_info:
        service.rebuild_plan(plan_id, expected_compile_digest=digest)

    assert exc_info.value.code == "PREVIEW_CHANGED"
    assert exc_info.value.status_code == 409
