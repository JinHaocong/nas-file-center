from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from typing import Any

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.auth.password import hash_password
from app.config import Settings
from app.db import create_engine_and_session
from app.main import create_app
from app.service import FileCenterService
from app.models import (
    Base,
    FilterPolicy,
    IndexRoot,
    IndexedPath,
    OrganizerProfile,
    User,
    Workflow,
    WorkflowRevision,
)
from app.workflows.compiler import WorkflowCompiler
from app.workflows.errors import (
    WorkflowRevisionConflictError,
    WorkflowValidationError,
)
from app.workflows.graph import VirtualCandidate, VirtualOperation, VirtualPathGraph
from app.workflows.schema import (
    OrganizeStep,
    ScanStep,
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowGeneratePlanRequest,
    WorkflowPreviewRequest,
    WorkflowUpdateRequest,
)
from app.workflows.service import WorkflowService


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
        # Create IndexRoot
        root1 = IndexRoot(id=1, root=str(data_dir))
        session.add(root1)

        # Create FilterPolicy
        policy = FilterPolicy(
            id=1,
            exclude_dir_names_json=json.dumps([".git", ".recycle", "@eaDir", ".nas-file-center-trash"]),
        )
        session.merge(policy)
        session.commit()

    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"

    # Login to get session
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


# =========================================================================
# P1-03: Organizer Global Exclude and Digest
# =========================================================================
def test_p1_03_organizer_global_exclude_and_digest(hotfix2_env):
    """P1-03: Organizer workflow must respect FilterPolicy global exclude directory names and update digest."""
    client = hotfix2_env["client"]
    data_dir = hotfix2_env["data_dir"]
    SessionLocal = hotfix2_env["SessionLocal"]

    # Set up directory tree
    git_dir = data_dir / ".git"
    git_dir.mkdir()
    (git_dir / "obj.dat").write_bytes(b"git_data")

    sub_git_dir = data_dir / "subdir" / ".git"
    sub_git_dir.mkdir(parents=True)
    (sub_git_dir / "head").write_bytes(b"ref")

    git2_dir = data_dir / ".git2"
    git2_dir.mkdir()
    (git2_dir / "img.jpg").write_bytes(b"jpeg_data")

    mygit_dir = data_dir / "my.git"
    mygit_dir.mkdir()
    (mygit_dir / "vid.mp4").write_bytes(b"mp4_data")

    normal_dir = data_dir / "album1"
    normal_dir.mkdir()
    (normal_dir / "pic.jpg").write_bytes(b"photo")

    # Create an organizer workflow
    create_payload = {
        "name": "Organizer Exclude Test",
        "description": "Test global excludes in organizer workflow",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "scan_step", "type": "scan", "root_ids": [1]},
                {
                    "id": "org_step",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Org Snapshot",
                        "image_extensions": ["jpg"],
                        "video_extensions": ["mp4"],
                        "rename_template": "{name} [test]",
                        "recursive": True,
                    },
                },
            ],
        },
    }
    wf_res = client.post("/api/workflows", json=create_payload)
    assert wf_res.status_code == 201
    wf_id = wf_res.json()["id"]

    # Preview workflow
    preview_res = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"root_ids": [1]}},
    )
    assert preview_res.status_code == 200
    pdata = preview_res.json()

    # Sources in preview items
    sources = [item["source_path"] for item in pdata["items"]]

    # .git and subdir/.git MUST NOT be in sources
    for src in sources:
        assert "/.git/" not in src and not src.endswith("/.git")
        assert "subdir/.git" not in src

    # .git2 and my.git MUST be present
    assert any(".git2" in src for src in sources), f".git2 should be included, got: {sources}"
    assert any("my.git" in src for src in sources), f"my.git should be included, got: {sources}"
    assert any("album1" in src for src in sources), f"album1 should be included, got: {sources}"

    initial_digest = pdata["compile_digest"]

    # Now update FilterPolicy exclude_dir_names_json
    with SessionLocal() as session:
        pol = session.get(FilterPolicy, 1)
        pol.exclude_dir_names_json = json.dumps([".git", ".recycle", "@eaDir", ".nas-file-center-trash", ".git2"])
        session.commit()

    # Re-preview
    preview2 = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"root_ids": [1]}},
    )
    assert preview2.status_code == 200
    pdata2 = preview2.json()

    # .git2 must now be excluded
    sources2 = [item["source_path"] for item in pdata2["items"]]
    assert not any(".git2" in src for src in sources2)
    # Digest must change because FilterPolicy excludes changed
    assert pdata2["compile_digest"] != initial_digest


# =========================================================================
# P1-04: Empty roots fail closed and IndexRoot boundary validation
# =========================================================================
def test_p1_04_empty_roots_and_boundary_validation(hotfix2_env):
    """P1-04: Empty roots fail closed with 422 ROOT_REQUIRED. Invalid/unauthorized root IDs fail with 422 INDEX_ROOT_NOT_FOUND."""
    client = hotfix2_env["client"]
    SessionLocal = hotfix2_env["SessionLocal"]

    # 1. File workflow with no root specified in definition and empty runtime inputs
    wf_payload = {
        "name": "File Empty Root Test",
        "description": "Empty root test",
        "definition": {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": []},
                {"id": "s2", "type": "rename", "pattern": "a", "replacement": "b"},
            ],
        },
    }
    wf_res = client.post("/api/workflows", json=wf_payload)
    assert wf_res.status_code == 201
    wf_id = wf_res.json()["id"]

    # Preview with empty runtime roots -> 422 ROOT_REQUIRED
    p_empty = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"root_ids": []}})
    assert p_empty.status_code == 422
    assert p_empty.json()["error"]["code"] == "ROOT_REQUIRED"

    # Preview with non-existent root ID [9999] -> 422 INDEX_ROOT_NOT_FOUND
    p_missing = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"root_ids": [9999]}})
    assert p_missing.status_code == 422
    assert p_missing.json()["error"]["code"] == "INDEX_ROOT_NOT_FOUND"

    # File workflow with > 16 roots -> 422 ROOT_LIMIT_EXCEEDED
    p_too_many = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"root_ids": list(range(1, 18))}},
    )
    assert p_too_many.status_code == 422
    assert p_too_many.json()["error"]["code"] == "ROOT_LIMIT_EXCEEDED"

    # 2. Organizer workflow with 0 roots -> 422 ROOT_REQUIRED
    org_payload = {
        "name": "Org Root Test",
        "description": "Org roots test",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": []},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {"name": "Test Org"},
                },
            ],
        },
    }
    org_wf_res = client.post("/api/workflows", json=org_payload)
    assert org_wf_res.status_code == 201
    org_wf_id = org_wf_res.json()["id"]

    org_empty = client.post(f"/api/workflows/{org_wf_id}/preview", json={"runtime_inputs": {"root_ids": []}})
    assert org_empty.status_code == 422
    assert org_empty.json()["error"]["code"] == "ROOT_REQUIRED"


# =========================================================================
# P2-07: Real SQLite Concurrency Transaction
# =========================================================================
def test_p2_07_real_sqlite_concurrency_transaction(hotfix2_env):
    """P2-07: Concurrent updates on same workflow with expected_current_revision=1. Exactly one succeeds, one gets 409 conflict, no 500 or locked DB."""
    client = hotfix2_env["client"]
    settings = hotfix2_env["settings"]
    SessionLocal = hotfix2_env["SessionLocal"]

    service = WorkflowService(SessionLocal, settings)

    # Create a workflow
    create_req = WorkflowCreateRequest(
        name="Concurrency Test Workflow",
        description="Testing concurrent updates",
        definition=WorkflowDefinition(
            schema_version=1,
            mode="file",
            steps=[
                ScanStep(id="s1", type="scan", root_ids=[1]),
            ],
        ),
    )
    wf_info = service.create_workflow(user_id=1, payload=create_req)
    wf_id = wf_info["id"]
    assert wf_info["current_revision"] == 1

    results = []

    def perform_update(thread_idx: int):
        update_req = WorkflowUpdateRequest(
            name=f"Updated by Thread {thread_idx}",
            expected_current_revision=1,
        )
        try:
            res = service.update_workflow(user_id=1, workflow_id=wf_id, payload=update_req)
            return ("SUCCESS", res["current_revision"])
        except WorkflowRevisionConflictError as e:
            return ("CONFLICT", e.code)
        except Exception as e:
            return ("ERROR", type(e).__name__, str(e))

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(perform_update, 1)
        f2 = executor.submit(perform_update, 2)
        r1 = f1.result()
        r2 = f2.result()

    outcomes = [r1[0], r2[0]]
    assert "SUCCESS" in outcomes, f"One thread must succeed, got {r1}, {r2}"
    assert "CONFLICT" in outcomes, f"One thread must get revision conflict 409, got {r1}, {r2}"
    assert "ERROR" not in outcomes, f"No unexpected exceptions allowed, got {r1}, {r2}"

    # Verify final revision in DB is 2
    final_wf = service.get_workflow(wf_id)
    assert final_wf["current_revision"] == 2


# =========================================================================
# P2-08: Organizer profile_snapshot strict validation and immutability
# =========================================================================
def test_p2_08_organizer_profile_snapshot_strict_validation(hotfix2_env):
    """P2-08: profile_snapshot must be strictly validated with extra='forbid' and strong types at create/update time."""
    client = hotfix2_env["client"]

    # 1. Invalid profile_snapshot: string for numbering_start -> 422
    bad_payload_type = {
        "name": "Bad Snapshot Number",
        "description": "test",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Test",
                        "numbering_start": "not_an_int",
                    },
                },
            ],
        },
    }
    r1 = client.post("/api/workflows", json=bad_payload_type)
    assert r1.status_code == 422

    # 2. Invalid profile_snapshot: extra unknown field -> 422
    bad_payload_extra = {
        "name": "Bad Snapshot Extra",
        "description": "test",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Test",
                        "unknown_custom_field": "disallowed",
                    },
                },
            ],
        },
    }
    r2 = client.post("/api/workflows", json=bad_payload_extra)
    assert r2.status_code == 422

    # 3. Invalid profile_snapshot: string instead of list of strings for image_extensions -> 422
    bad_payload_list = {
        "name": "Bad Snapshot List",
        "description": "test",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Test",
                        "image_extensions": "jpg,png",
                    },
                },
            ],
        },
    }
    r3 = client.post("/api/workflows", json=bad_payload_list)
    assert r3.status_code == 422

    # 4. Valid snapshot immutability check
    good_payload = {
        "name": "Immutable Snapshot Test",
        "description": "test",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {
                        "name": "Original Name",
                        "rename_template": "{name} [ORIGINAL]",
                    },
                },
            ],
        },
    }
    r4 = client.post("/api/workflows", json=good_payload)
    assert r4.status_code == 201
    wf_id = r4.json()["id"]

    # Get workflow and verify snapshot in definition
    wf_get = client.get(f"/api/workflows/{wf_id}")
    assert wf_get.status_code == 200
    snapshot_saved = wf_get.json()["definition"]["steps"][1]["profile_snapshot"]
    assert snapshot_saved["name"] == "Original Name"
    assert snapshot_saved["rename_template"] == "{name} [ORIGINAL]"


# =========================================================================
# P2-09: Runtime root contract ambiguity
# =========================================================================
def test_p2_09_runtime_root_contract_ambiguity(hotfix2_env):
    """P2-09: Ambiguous root inputs (both root_ids and runtime_inputs specified) must return 422 AMBIGUOUS_RUNTIME_INPUTS."""
    client = hotfix2_env["client"]

    wf_payload = {
        "name": "Ambiguity Test",
        "description": "test",
        "definition": {
            "schema_version": 1,
            "mode": "file",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
            ],
        },
    }
    wf_res = client.post("/api/workflows", json=wf_payload)
    assert wf_res.status_code == 201
    wf_id = wf_res.json()["id"]

    # 1. Preview request specifying BOTH root_ids AND runtime_inputs -> 422 AMBIGUOUS_RUNTIME_INPUTS
    ambig_preview = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={
            "root_ids": [1],
            "runtime_inputs": {"root_ids": [1]},
        },
    )
    assert ambig_preview.status_code == 422
    assert ambig_preview.json()["error"]["code"] == "AMBIGUOUS_RUNTIME_INPUTS"

    # 2. Generate plan request specifying BOTH root_ids AND runtime_inputs -> 422 AMBIGUOUS_RUNTIME_INPUTS
    ambig_plan = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={
            "expected_compile_digest": "0" * 64,
            "root_ids": [1],
            "runtime_inputs": {"root_ids": [1]},
        },
    )
    assert ambig_plan.status_code == 422
    assert ambig_plan.json()["error"]["code"] == "AMBIGUOUS_RUNTIME_INPUTS"

    # 3. Organizer workflow preview with multiple root IDs -> 422 ORGANIZER_SINGLE_ROOT_REQUIRED
    org_payload = {
        "name": "Org Multi Root",
        "description": "test",
        "definition": {
            "schema_version": 1,
            "mode": "organizer",
            "steps": [
                {"id": "s1", "type": "scan", "root_ids": [1]},
                {
                    "id": "s2",
                    "type": "organize",
                    "profile_snapshot": {"name": "Org Multi"},
                },
            ],
        },
    }
    org_res = client.post("/api/workflows", json=org_payload)
    assert org_res.status_code == 201
    org_id = org_res.json()["id"]

    org_multi = client.post(
        f"/api/workflows/{org_id}/preview",
        json={"runtime_inputs": {"root_ids": [1, 2]}},
    )
    assert org_multi.status_code == 422
    assert org_multi.json()["error"]["code"] == "ORGANIZER_SINGLE_ROOT_REQUIRED"


# =========================================================================
# P2-10: Virtual Graph O(n) Performance Test
# =========================================================================
def test_p2_10_virtual_graph_performance():
    """P2-10: VirtualPathGraph dependency resolution on 10,000 candidates (20,000 operations) must finish in < 5 seconds."""
    graph = VirtualPathGraph(allowed_roots=[Path("/data")])

    num_candidates = 10000
    for i in range(num_candidates):
        src_path = f"/data/dir_{i}/file_{i}.txt"
        mid_path = f"/data/dir_{i}/renamed_{i}.txt"
        dst_path = f"/data/dest_{i}/renamed_{i}.txt"

        cand = VirtualCandidate(
            id=i,
            original_path=src_path,
            original_root_id=1,
            current_path=dst_path,
            current_root_id=1,
            size=100,
            mtime_ns=0,
            operations=[
                VirtualOperation(
                    candidate_id=i,
                    workflow_step_index=1,
                    candidate_operation_index=0,
                    operation="rename",
                    source=src_path,
                    target=mid_path,
                ),
                VirtualOperation(
                    candidate_id=i,
                    workflow_step_index=2,
                    candidate_operation_index=1,
                    operation="move",
                    source=mid_path,
                    target=dst_path,
                ),
            ],
        )
        graph.add_candidate(cand)

    t0 = time.perf_counter()
    planned_ops = graph.resolve_ordered_operations()
    elapsed = time.perf_counter() - t0

    assert len(planned_ops) == num_candidates * 2
    assert elapsed < 5.0, f"Graph resolution took {elapsed:.2f}s, exceeding 5.0s limit (O(n^2) regression detected)"

