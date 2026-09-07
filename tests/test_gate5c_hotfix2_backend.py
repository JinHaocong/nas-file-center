import json
import re
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


@pytest.fixture
def hotfix2_env(tmp_path: Path):
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
    client.headers["Referer"] = "http://testserver/"

    login_resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    )
    assert login_resp.status_code == 200

    # Seed an indexed file
    f = data_dir / "sample.txt"
    f.write_text("hello sample")
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

    # Create a valid workflow
    r_wf = client.post("/api/workflows", json={
        "name": "Hotfix2 WF",
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

    # Mark plan stale so it qualifies for rebuild preview
    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        p.status = "stale"
        session.commit()

    return {
        "service": service,
        "client": client,
        "data_dir": data_dir,
        "plan_id": plan_id,
        "wf_id": wf_id,
    }


def test_red_nonhex_compile_digest_rebuild_preview_rejected(hotfix2_env):
    """P2-09: compile_digest with 'z'*64 must be rejected with 400 PLAN_REBUILD_LINEAGE_MISSING."""
    service: FileCenterService = hotfix2_env["service"]
    client: TestClient = hotfix2_env["client"]
    plan_id: int = hotfix2_env["plan_id"]

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        meta = json.loads(p.metadata_json)
        meta["compile_digest"] = "z" * 64
        p.metadata_json = json.dumps(meta)
        session.commit()

    resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={})
    assert resp.status_code == 400, f"Expected 400 but got {resp.status_code}: {resp.text}"
    err = resp.json().get("error", {})
    assert err.get("code") == "PLAN_REBUILD_LINEAGE_MISSING"


def test_red_nonhex_definition_sha_rebuild_preview_rejected(hotfix2_env):
    """P2-09: definition_sha256 with 'g'*64 must be rejected with 400 PLAN_REBUILD_LINEAGE_MISSING."""
    service: FileCenterService = hotfix2_env["service"]
    client: TestClient = hotfix2_env["client"]
    plan_id: int = hotfix2_env["plan_id"]

    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        meta = json.loads(p.metadata_json)
        meta["definition_sha256"] = "g" * 64
        p.metadata_json = json.dumps(meta)
        session.commit()

    resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={})
    assert resp.status_code == 400, f"Expected 400 but got {resp.status_code}: {resp.text}"
    err = resp.json().get("error", {})
    assert err.get("code") == "PLAN_REBUILD_LINEAGE_MISSING"


def test_red_invalid_length_and_whitespace_sha_rejected(hotfix2_env):
    """P2-09: 63-char, 65-char, and whitespace-containing SHAs must be rejected with 400."""
    service: FileCenterService = hotfix2_env["service"]
    client: TestClient = hotfix2_env["client"]
    plan_id: int = hotfix2_env["plan_id"]

    invalid_shas = [
        "a" * 63,
        "a" * 65,
        " " + "a" * 63,
        ("a" * 63) + " ",
        "",
        "a" * 32 + " " + "b" * 31,
    ]

    for bad_sha in invalid_shas:
        with service.SessionLocal() as session:
            p = session.get(BatchPlan, plan_id)
            meta = json.loads(p.metadata_json)
            meta["compile_digest"] = bad_sha
            p.metadata_json = json.dumps(meta)
            session.commit()

        resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={})
        assert resp.status_code == 400, f"Expected 400 for '{bad_sha}' but got {resp.status_code}: {resp.text}"
        err = resp.json().get("error", {})
        assert err.get("code") == "PLAN_REBUILD_LINEAGE_MISSING"
