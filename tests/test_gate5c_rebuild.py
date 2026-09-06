from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.main import create_app
from app.models import (
    BatchPlan,
    BatchPlanItem,
    FilterPolicy,
    IndexRoot,
    IndexedPath,
    WorkJob,
    Workflow,
    WorkflowRevision,
)
from app.service import FileCenterService
from app.workflows.revisions import canonical_json_dumps, compute_definition_sha256


@pytest.fixture
def gate5c_env(tmp_path: Path):
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
        "client": client,
        "settings": settings,
        "SessionLocal": service.SessionLocal,
        "service": service,
        "data_dir": data_dir,
        "quarantine_dir": quarantine_dir,
    }


def _index_file(session, root_key: str, path: Path, rel_name: str):
    item = IndexedPath(
        root_key=root_key,
        absolute_path=str(path),
        relative_path=rel_name,
        basename=path.name,
        stem=path.stem,
        suffix=path.suffix,
        size=path.stat().st_size if path.exists() else 100,
        mtime_ns=1_000_000,
        is_dir=False,
        scan_generation="gen1",
    )
    session.add(item)
    session.commit()


def test_workflow_list_returns_mode(gate5c_env):
    """WorkflowListItem must include 'mode' ('file' or 'organizer') resolved from current definition."""
    client = gate5c_env["client"]

    # Create file workflow
    wf1_payload = {
        "name": "File WF",
        "definition": {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {"id": "s2", "type": "touch", "touch_now": True, "mtime_ns": None},
            ],
        },
    }
    r1 = client.post("/api/workflows", json=wf1_payload)
    assert r1.status_code == 201

    # Create organizer workflow
    wf2_payload = {
        "name": "Organizer WF",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {"id": "s2", "type": "organize", "profile_snapshot": {"name": "Test"}},
            ],
        },
    }
    r2 = client.post("/api/workflows", json=wf2_payload)
    assert r2.status_code == 201

    # Call list
    list_res = client.get("/api/workflows")
    assert list_res.status_code == 200
    items = list_res.json()
    assert isinstance(items, list)
    by_name = {it["name"]: it for it in items}

    assert "mode" in by_name["File WF"]
    assert by_name["File WF"]["mode"] == "file"
    assert "mode" in by_name["Organizer WF"]
    assert by_name["Organizer WF"]["mode"] == "organizer"


def test_rebuild_preview_eligibility_and_validations(gate5c_env):
    """Test rebuild-preview rejection on ineligible plans, archived workflows, and malformed lineages."""
    client = gate5c_env["client"]
    SessionLocal = gate5c_env["SessionLocal"]
    data_dir = gate5c_env["data_dir"]

    # Prepare file and index
    f1 = data_dir / "test.txt"
    f1.write_text("hello")
    with SessionLocal() as session:
        _index_file(session, str(data_dir), f1, "test.txt")

    # 1. Non-existent plan -> 404
    res = client.post("/api/plans/9999/rebuild-preview", json={})
    assert res.status_code == 404

    # 2. Non-workflow plan -> 400 PLAN_REBUILD_NOT_ELIGIBLE
    with SessionLocal() as session:
        non_wf_plan = BatchPlan(
            name="Manual Plan",
            kind="manual",
            status="stale",
            expected_changes=1,
            expected_reclaim_bytes=0,
            metadata_json=json.dumps({"source": "manual"}),
        )
        session.add(non_wf_plan)
        session.commit()
        non_wf_id = non_wf_plan.id

    res = client.post(f"/api/plans/{non_wf_id}/rebuild-preview", json={})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "PLAN_REBUILD_NOT_ELIGIBLE"

    # 3. Non-stale workflow plan (e.g. status='draft' or 'ready') -> 400 PLAN_REBUILD_NOT_ELIGIBLE
    wf_payload = {
        "name": "WF Rebuild Test",
        "definition": {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {"id": "s2", "type": "touch", "touch_now": True, "mtime_ns": None},
            ],
        },
    }
    wf_resp = client.post("/api/workflows", json=wf_payload)
    assert wf_resp.status_code == 201
    wf_id = wf_resp.json()["id"]

    # Preview and generate draft plan
    prev_resp = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"root_ids": [1]}})
    assert prev_resp.status_code == 200
    compile_digest = prev_resp.json()["compile_digest"]
    def_sha = prev_resp.json()["definition_sha256"]

    gen_resp = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={"expected_compile_digest": compile_digest, "runtime_inputs": {"root_ids": [1]}},
    )
    assert gen_resp.status_code == 201
    draft_plan_id = gen_resp.json()["plan_id"]

    # Draft plan is not stale -> rejected!
    res = client.post(f"/api/plans/{draft_plan_id}/rebuild-preview", json={})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "PLAN_REBUILD_NOT_ELIGIBLE"

    # Make plan stale for further tests
    with SessionLocal() as session:
        p = session.get(BatchPlan, draft_plan_id)
        p.status = "stale"
        session.commit()

    # 4. Active WorkJob running on plan -> 400 PLAN_REBUILD_NOT_ELIGIBLE
    with SessionLocal() as session:
        active_job = WorkJob(
            kind="batch-plan-execute",
            status="running",
            state_json=json.dumps({"plan_id": draft_plan_id}),
        )
        session.add(active_job)
        session.commit()
        active_job_id = active_job.id

    res = client.post(f"/api/plans/{draft_plan_id}/rebuild-preview", json={})
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "PLAN_REBUILD_NOT_ELIGIBLE"

    # Clean up active job
    with SessionLocal() as session:
        j = session.get(WorkJob, active_job_id)
        session.delete(j)
        session.commit()

    # 5. Archived Workflow -> 409 WORKFLOW_ARCHIVED (Erratum E2)
    del_resp = client.delete(f"/api/workflows/{wf_id}?expected_current_revision=1")
    assert del_resp.status_code == 200
    res = client.post(f"/api/plans/{draft_plan_id}/rebuild-preview", json={})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "WORKFLOW_ARCHIVED"

    # Unarchive workflow
    with SessionLocal() as session:
        wf = session.get(Workflow, wf_id)
        wf.archived_at = None
        session.commit()

    # 6. Malformed lineage metadata -> 400 PLAN_REBUILD_LINEAGE_MISSING (not 500)
    for bad_meta in [
        "{invalid json",
        json.dumps({"source": "workflow"}),  # missing fields
        json.dumps({"source": "workflow", "workflow_id": "not_int", "workflow_revision": 1, "definition_sha256": def_sha, "runtime_inputs": {"root_ids": [1]}, "compile_digest": compile_digest}),
        json.dumps({"source": "workflow", "workflow_id": wf_id, "workflow_revision": -1, "definition_sha256": def_sha, "runtime_inputs": {"root_ids": [1]}, "compile_digest": compile_digest}),
        json.dumps({"source": "workflow", "workflow_id": wf_id, "workflow_revision": 1, "definition_sha256": "wrong_sha", "runtime_inputs": {"root_ids": [1]}, "compile_digest": compile_digest}),
        json.dumps({"source": "workflow", "workflow_id": wf_id, "workflow_revision": 1, "definition_sha256": def_sha, "runtime_inputs": {"root_ids": []}, "compile_digest": compile_digest}),
    ]:
        with SessionLocal() as session:
            p = session.get(BatchPlan, draft_plan_id)
            p.metadata_json = bad_meta
            session.commit()

        res = client.post(f"/api/plans/{draft_plan_id}/rebuild-preview", json={})
        assert res.status_code == 400, f"Expected 400 for {bad_meta}, got {res.status_code}"
        assert res.json()["error"]["code"] == "PLAN_REBUILD_LINEAGE_MISSING"


def test_rebuild_preview_and_create_draft_lifecycle(gate5c_env):
    """Test successful rebuild preview (including touch visibility by default) and rebuild creating a new draft."""
    client = gate5c_env["client"]
    SessionLocal = gate5c_env["SessionLocal"]
    data_dir = gate5c_env["data_dir"]

    # Setup files and index
    f1 = data_dir / "file1.txt"
    f1.write_text("content1")
    f2 = data_dir / "file2.txt"
    f2.write_text("content2")
    with SessionLocal() as session:
        _index_file(session, str(data_dir), f1, "file1.txt")
        _index_file(session, str(data_dir), f2, "file2.txt")

    # 1. Create Workflow Revision 1
    wf_payload = {
        "name": "Rebuild Happy Path WF",
        "definition": {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {"id": "s2", "type": "rename", "pattern": "file", "replacement": "renamed_file"},
                {"id": "s3", "type": "touch", "touch_now": True, "mtime_ns": None},
            ],
        },
    }
    wf_resp = client.post("/api/workflows", json=wf_payload)
    assert wf_resp.status_code == 201
    wf_id = wf_resp.json()["id"]

    # Generate Draft from r1
    prev_r1 = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"root_ids": [1]}})
    assert prev_r1.status_code == 200
    digest_r1 = prev_r1.json()["compile_digest"]
    def_sha_r1 = prev_r1.json()["definition_sha256"]

    gen_resp = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={"expected_compile_digest": digest_r1, "runtime_inputs": {"root_ids": [1]}},
    )
    assert gen_resp.status_code == 201
    plan_id = gen_resp.json()["plan_id"]

    # 2. Update workflow to Revision 2 (to verify rebuild uses exact historical revision r1!)
    wf_r2_payload = {
        "expected_current_revision": 1,
        "name": "Rebuild Happy Path WF Updated",
        "definition": {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {"id": "s2", "type": "quarantine", "reason": "Test Quarantine"},
            ],
        },
    }
    up_resp = client.put(f"/api/workflows/{wf_id}", json=wf_r2_payload)
    assert up_resp.status_code == 200
    assert up_resp.json()["current_revision"] == 2

    # Mark original plan as stale
    with SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        p.status = "stale"
        session.commit()

    # Record snapshot before preview to ensure ZERO DB/FS mutation
    with SessionLocal() as session:
        initial_plan_count = session.scalar(text("SELECT count(*) FROM batch_plans"))
        initial_item_count = session.scalar(text("SELECT count(*) FROM batch_plan_items"))
        p_orig = session.get(BatchPlan, plan_id)
        orig_metadata = p_orig.metadata_json

    # 3. Call rebuild-preview (Default only_changed=false, touches must be visible!)
    res = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={})
    assert res.status_code == 200
    preview_data = res.json()

    assert preview_data["source_plan_id"] == plan_id
    assert preview_data["workflow_id"] == wf_id
    assert preview_data["workflow_revision"] == 1  # EXACT historical revision!
    assert preview_data["definition_sha256"] == def_sha_r1
    assert preview_data["preview_source"] == "index"
    assert preview_data["live_filesystem_verified"] is False
    assert len(preview_data["items"]) == 4  # 2 renames + 2 touches!
    assert any(it["operation"] == "touch" for it in preview_data["items"]), "Touches must be visible by default!"
    rebuild_digest = preview_data["compile_digest"]

    # Verify zero DB mutation
    with SessionLocal() as session:
        assert session.scalar(text("SELECT count(*) FROM batch_plans")) == initial_plan_count
        assert session.scalar(text("SELECT count(*) FROM batch_plan_items")) == initial_item_count
        p_now = session.get(BatchPlan, plan_id)
        assert p_now.status == "stale"
        assert p_now.metadata_json == orig_metadata

    # 4. Rebuild call with wrong digest -> 409 PREVIEW_CHANGED
    res_bad = client.post(
        f"/api/plans/{plan_id}/rebuild",
        json={"expected_compile_digest": "0" * 64},
    )
    assert res_bad.status_code == 409
    assert res_bad.json()["error"]["code"] == "PREVIEW_CHANGED"

    # 5. Successful Rebuild call
    res_ok = client.post(
        f"/api/plans/{plan_id}/rebuild",
        json={"expected_compile_digest": rebuild_digest, "plan_name": "Rebuilt Draft Plan"},
    )
    assert res_ok.status_code in {200, 201}
    new_plan_id = res_ok.json()["id"]
    assert new_plan_id != plan_id

    # Verify New Plan properties
    with SessionLocal() as session:
        new_plan = session.get(BatchPlan, new_plan_id)
        assert new_plan.status == "draft"
        new_meta = json.loads(new_plan.metadata_json)
        assert new_meta["source"] == "workflow"
        assert new_meta["workflow_id"] == wf_id
        assert new_meta["workflow_revision"] == 1
        assert new_meta["definition_sha256"] == def_sha_r1
        assert new_meta["compile_digest"] == rebuild_digest
        assert new_meta["rebuild_of_plan_id"] == plan_id
        assert new_meta["rebuild_source_status"] == "stale"

        # Check physical identities in items are 0/empty
        items = session.query(BatchPlanItem).filter_by(plan_id=new_plan_id).all()
        assert len(items) == 4
        for item in items:
            assert item.expected_inode == 0
            assert item.expected_device == 0
            assert item.expected_mtime_ns == 0
            assert item.expected_hash == ""

        # Verify source stale plan is UNCHANGED
        orig_p = session.get(BatchPlan, plan_id)
        assert orig_p.status == "stale"
        assert orig_p.metadata_json == orig_metadata

        # Verify 0 WorkJobs and 0 OperationJournal entries written
        assert session.scalar(text(f"SELECT count(*) FROM work_jobs WHERE json_extract(state_json, '$.plan_id') = {new_plan_id}")) == 0
        assert session.scalar(text(f"SELECT count(*) FROM operation_journal WHERE plan_id = {new_plan_id}")) == 0


def test_rebuild_transaction_race_condition(gate5c_env):
    """Test Erratum E1: final transaction verifies source plan still exists, still stale, no active job, unchanged."""
    client = gate5c_env["client"]
    SessionLocal = gate5c_env["SessionLocal"]
    data_dir = gate5c_env["data_dir"]

    race_f = data_dir / "race.txt"
    race_f.write_text("race")
    with SessionLocal() as session:
        _index_file(session, str(data_dir), race_f, "race.txt")

    wf_payload = {
        "name": "Race WF",
        "definition": {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {"id": "s2", "type": "touch", "touch_now": True, "mtime_ns": None},
            ],
        },
    }
    wf_resp = client.post("/api/workflows", json=wf_payload)
    wf_id = wf_resp.json()["id"]

    prev_res = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"root_ids": [1]}})
    digest = prev_res.json()["compile_digest"]

    gen_res = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={"expected_compile_digest": digest, "runtime_inputs": {"root_ids": [1]}},
    )
    plan_id = gen_res.json()["plan_id"]

    with SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        p.status = "stale"
        session.commit()

    # Call preview
    prev_rb = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={})
    rebuild_digest = prev_rb.json()["compile_digest"]

    # Simulate race: right before rebuild call, plan status was modified to 'ready' or deleted
    with SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        p.status = "ready"
        session.commit()

    # Rebuild must fail closed with 409 PREVIEW_CHANGED or 400
    res = client.post(
        f"/api/plans/{plan_id}/rebuild",
        json={"expected_compile_digest": rebuild_digest},
    )
    assert res.status_code in {400, 409}
    assert res.json()["error"]["code"] in {"PLAN_REBUILD_NOT_ELIGIBLE", "PREVIEW_CHANGED"}
