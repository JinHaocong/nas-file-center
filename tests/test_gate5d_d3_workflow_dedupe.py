from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.password import hash_password
from app.config import Settings
from app.main import create_app
from app.models import (
    BatchPlan,
    BatchPlanItem,
    DuplicateFile,
    DuplicateGroup,
    IndexRoot,
    ScanJob,
    User,
    Workflow,
    WorkflowRevision,
    utcnow,
)
from app.planning.dedupe_preview import compute_current_dedupe_db_lineage_digest
from app.service import FileCenterService, PlanStaleError, StateConflictError
from app.workflows.errors import (
    DedupeRescanRequiredError,
    WorkflowArchivedError,
    WorkflowDigestMismatchError,
    WorkflowValidationError,
)
from app.workflows.schema import (
    DedupeStep,
    FilterStep,
    MoveStep,
    OrganizeStep,
    QuarantineStep,
    RenameStep,
    ScanStep,
    TouchStep,
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowGeneratePlanRequest,
    WorkflowPreviewRequest,
    WorkflowUpdateRequest,
)
from app.workflows.validation import validate_workflow_definition


# ============================================================================
# Fixtures & Helpers
# ============================================================================

@pytest.fixture
def workflow_test_env(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    quarantine_dir = tmp_path / "quarantine"
    quarantine_dir.mkdir()
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    settings = Settings(
        config_dir=config_dir,
        data_mount=data_dir,
        quarantine_root=quarantine_dir,
        allowed_roots_raw=str(data_dir),
        protect_last_file=True,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    app = create_app(settings)
    service = app.state.service

    with service.SessionLocal() as session:
        session.add(IndexRoot(id=1, root=str(data_dir)))
        session.add(
            User(
                username="testuser",
                password_hash=hash_password("Password123!"),
                is_active=True,
                role="admin",
            )
        )
        session.commit()

    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "testuser", "password": "Password123!"},
    )
    assert login_resp.status_code == 200

    return {
        "client": client,
        "service": service,
        "SessionLocal": service.SessionLocal,
        "settings": settings,
        "data_dir": data_dir,
        "quarantine_dir": quarantine_dir,
    }


def _create_completed_scan(SessionLocal, *, scan_id: int, roots: list[str], status: str = "completed") -> None:
    with SessionLocal() as session:
        session.add(
            ScanJob(
                id=scan_id,
                name=f"scan-{scan_id}",
                mode="normal",
                roots_json=json.dumps(roots),
                status=status,
                started_at=utcnow(),
                finished_at=utcnow(),
                total_groups=0,
                total_files_in_groups=0,
                reclaimable_bytes=0,
            )
        )
        session.commit()


def _setup_duplicate_test_data(SessionLocal, root: Path, *, scan_id: int) -> tuple[Path, Path]:
    _create_completed_scan(SessionLocal, scan_id=scan_id, roots=[str(root)])
    first = root / f"dup-{scan_id}-keeper.bin"
    second = root / f"dup-{scan_id}-victim.bin"
    first.write_bytes(b"duplicate_content_data_128" * 5)
    second.write_bytes(b"duplicate_content_data_128" * 5)
    file_sz = first.stat().st_size

    with SessionLocal() as session:
        group = DuplicateGroup(
            id=scan_id * 10 + 1,
            scan_job_id=scan_id,
            content_hash=f"hash-{scan_id}",
            file_size=file_sz,
            member_count=2,
        )
        session.add(group)
        session.flush()

        session.add_all([
            DuplicateFile(
                group_id=group.id,
                root_id=0,
                absolute_path=str(first),
                relative_path=first.name,
                top_level_dir=str(root),
                size=file_sz,
                mtime_ns=2000,
                device=0,
                inode=0,
            ),
            DuplicateFile(
                group_id=group.id,
                root_id=0,
                absolute_path=str(second),
                relative_path=second.name,
                top_level_dir=str(root),
                size=file_sz,
                mtime_ns=1000,
                device=0,
                inode=0,
            ),
        ])
        session.commit()

    return first, second


def _count_plan_state(SessionLocal) -> tuple[int, int]:
    with SessionLocal() as session:
        p_count = session.scalar(select(func.count(BatchPlan.id))) or 0
        i_count = session.scalar(select(func.count(BatchPlanItem.id))) or 0
        return p_count, i_count


# ============================================================================
# Section 17 Test Requirements (1 to 22)
# ============================================================================

# 1. Dedupe Definition exact topology
def test_1_dedupe_workflow_valid_single_step():
    step = DedupeStep(
        id="step-1",
        type="dedupe",
        scorer_config={
            "schema_version": 1,
            "selection_mode": "weighted",
            "factors": {
                "mtime": {"mode": "newest", "weight": 50},
            },
        },
    )
    defn = WorkflowDefinition(schema_version=1, mode="dedupe", steps=[step])
    validate_workflow_definition(defn)
    assert defn.mode == "dedupe"
    assert len(defn.steps) == 1
    assert defn.steps[0].type == "dedupe"


def test_1_dedupe_workflow_rejects_empty_steps():
    with pytest.raises(WorkflowValidationError) as exc_info:
        WorkflowDefinition(schema_version=1, mode="dedupe", steps=[])
    assert exc_info.value.code == "EMPTY_STEPS"


def test_1_dedupe_workflow_rejects_multiple_steps():
    step1 = DedupeStep(id="d1", type="dedupe", scorer_config={})
    step2 = DedupeStep(id="d2", type="dedupe", scorer_config={})
    defn = WorkflowDefinition(schema_version=1, mode="dedupe", steps=[step1, step2])
    with pytest.raises(WorkflowValidationError) as exc_info:
        validate_workflow_definition(defn)
    assert exc_info.value.code == "INVALID_PIPELINE_STRUCTURE"
    assert "exactly 1 step" in exc_info.value.message


@pytest.mark.parametrize(
    "forbidden_step",
    [
        ScanStep(id="s1", type="scan", root_ids=[1]),
        FilterStep(id="f1", type="filter", filter={"field": "name", "operator": "equals", "value": "a"}),
        RenameStep(id="r1", type="rename", pattern="a", replacement="b"),
        MoveStep(id="m1", type="move", destination_root_id=1),
        TouchStep(id="t1", type="touch"),
        QuarantineStep(id="q1", type="quarantine"),
        OrganizeStep(id="o1", type="organize", profile_snapshot={"name": "test-prof"}),
    ],
)
def test_1_dedupe_workflow_rejects_forbidden_step_combinations(forbidden_step):
    d_step = DedupeStep(id="d1", type="dedupe", scorer_config={})
    # Both [forbidden, dedupe] and [dedupe, forbidden]
    defn1 = WorkflowDefinition(schema_version=1, mode="dedupe", steps=[forbidden_step, d_step])
    with pytest.raises(WorkflowValidationError) as exc1:
        validate_workflow_definition(defn1)
    assert exc1.value.code == "INVALID_PIPELINE_STRUCTURE"

    defn2 = WorkflowDefinition(schema_version=1, mode="dedupe", steps=[d_step, forbidden_step])
    with pytest.raises(WorkflowValidationError) as exc2:
        validate_workflow_definition(defn2)
    assert exc2.value.code == "INVALID_PIPELINE_STRUCTURE"


# 2. Dedupe step rejected in file and organizer workflows
def test_2_file_and_organizer_modes_reject_dedupe_step():
    d_step = DedupeStep(id="d1", type="dedupe", scorer_config={})
    with pytest.raises(WorkflowValidationError) as exc_info:
        WorkflowDefinition(
            schema_version=1,
            mode="file",
            steps=[ScanStep(id="s1", type="scan", root_ids=[1]), d_step],
        )
    assert exc_info.value.code in ("UNSUPPORTED_STEP", "INVALID_PIPELINE_STRUCTURE")

    with pytest.raises(WorkflowValidationError) as exc_info2:
        WorkflowDefinition(
            schema_version=1,
            mode="organizer",
            steps=[ScanStep(id="s1", type="scan", root_ids=[1]), d_step],
        )
    assert exc_info2.value.code in ("UNSUPPORTED_STEP", "INVALID_PIPELINE_STRUCTURE")


# 3. Canonical scorer config validation
def test_3_dedupe_workflow_validates_scorer_config():
    # Unknown keys
    step_unknown = DedupeStep(id="d1", type="dedupe", scorer_config={"unknown_key": 123})
    defn_u = WorkflowDefinition(schema_version=1, mode="dedupe", steps=[step_unknown])
    with pytest.raises(WorkflowValidationError) as exc_u:
        validate_workflow_definition(defn_u)
    assert exc_u.value.code == "DEDUPE_INVALID_CONFIG"

    # Reserved factors
    step_res = DedupeStep(
        id="d2",
        type="dedupe",
        scorer_config={
            "schema_version": 1,
            "selection_mode": "weighted",
            "factors": {"resolution": {"weight": 100}},
        },
    )
    defn_r = WorkflowDefinition(schema_version=1, mode="dedupe", steps=[step_res])
    with pytest.raises(WorkflowValidationError) as exc_r:
        validate_workflow_definition(defn_r)
    assert exc_r.value.code == "DEDUPE_FACTOR_UNAVAILABLE"


# 4. Strict scan_job_id runtime inputs
def test_4_runtime_inputs_strict_scan_job_id(workflow_test_env):
    client = workflow_test_env["client"]

    # Create a dedupe workflow
    wf_resp = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 4",
            "description": "testing runtime inputs",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    )
    assert wf_resp.status_code == 201
    wf_id = wf_resp.json()["id"]

    # Boolean scan_job_id rejected with 422
    resp_bool = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"scan_job_id": True}})
    assert resp_bool.status_code == 422

    # Negative scan_job_id rejected with 422
    resp_neg = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"scan_job_id": -1}})
    assert resp_neg.status_code == 422

    # Zero scan_job_id rejected with 422
    resp_zero = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"scan_job_id": 0}})
    assert resp_zero.status_code == 422

    # Non-existent scan_job_id returns 404
    resp_404 = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"scan_job_id": 999999}})
    assert resp_404.status_code == 404

    # Non-completed scan_job_id returns 409 DEDUPE_SCAN_NOT_COMPLETED
    _create_completed_scan(
        workflow_test_env["SessionLocal"],
        scan_id=401,
        roots=[str(workflow_test_env["data_dir"])],
        status="running",
    )
    resp_409 = client.post(f"/api/workflows/{wf_id}/preview", json={"runtime_inputs": {"scan_job_id": 401}})
    assert resp_409.status_code == 409
    err = resp_409.json().get("error", {})
    assert err.get("code") == "DEDUPE_SCAN_NOT_COMPLETED"


# 5. Mode-specific input restrictions
def test_5_mode_specific_input_restrictions(workflow_test_env):
    client = workflow_test_env["client"]

    # Dedupe mode rejects root_ids
    wf_resp = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 5",
            "description": "test mode-specific inputs",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    )
    assert wf_resp.status_code == 201
    d_id = wf_resp.json()["id"]

    # root_ids in preview
    r_prev = client.post(f"/api/workflows/{d_id}/preview", json={"root_ids": [1]})
    assert r_prev.status_code in (400, 422)

    # root_ids in generate-plan
    r_gen = client.post(
        f"/api/workflows/{d_id}/generate-plan",
        json={"expected_compile_digest": "a" * 64, "root_ids": [1]},
    )
    assert r_gen.status_code in (400, 422)

    # File mode rejects scan_job_id
    f_wf_resp = client.post(
        "/api/workflows",
        json={
            "name": "File WF 5",
            "description": "test file wf",
            "definition": {
                "schema_version": 1,
                "mode": "file",
                "steps": [
                    {"id": "s1", "type": "scan", "root_ids": [1]},
                    {"id": "r1", "type": "rename", "pattern": "a", "replacement": "b"},
                ],
            },
        },
    )
    assert f_wf_resp.status_code == 201
    f_id = f_wf_resp.json()["id"]

    rf_prev = client.post(f"/api/workflows/{f_id}/preview", json={"runtime_inputs": {"scan_job_id": 1}})
    assert rf_prev.status_code in (400, 422)


# 6. Direct D2 <-> Workflow Dedupe parity
def test_6_direct_d2_and_workflow_dedupe_parity(workflow_test_env):
    client = workflow_test_env["client"]
    scan_id = 601
    keeper, victim = _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    config = {
        "schema_version": 1,
        "selection_mode": "weighted",
        "factors": {
            "mtime": {"mode": "newest", "weight": 100},
        },
    }

    # 1. Direct D2 preview
    d2_resp = client.post(f"/api/scans/{scan_id}/dedupe-preview", json={"scorer_config": config})
    assert d2_resp.status_code == 200
    d2_data = d2_resp.json()

    # 2. Workflow preview
    wf_resp = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 6",
            "description": "parity test",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": config}],
            },
        },
    )
    assert wf_resp.status_code == 201
    wf_id = wf_resp.json()["id"]

    wf_prev = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}, "only_changed": False},
    )
    assert wf_prev.status_code == 200
    wf_data = wf_prev.json()

    # Parity assertions
    assert wf_data["planned_operations_count"] == d2_data["summary"]["planned_quarantine_count"]
    assert wf_data["planned_operations_count"] == 1

    # Winner/keeper path parity
    row = d2_data["rows"][0]
    assert row["group_recommended_keep_path"] == str(keeper)

    items = wf_data["items"]
    keeper_item = next(it for it in items if it["source_path"] == str(keeper))
    victim_item = next(it for it in items if it["source_path"] == str(victim))

    assert keeper_item["operation"] == "keep"
    assert keeper_item["changed"] is False
    assert victim_item["operation"] == "quarantine"
    assert victim_item["changed"] is True
    assert victim_item["metadata"]["keep_path"] == str(keeper)


# 7. Pagination invariance
def test_7_preview_pagination_invariance(workflow_test_env):
    client = workflow_test_env["client"]
    scan_id = 701
    _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    wf_resp = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 7",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    )
    wf_id = wf_resp.json()["id"]

    # Page 1, size 1
    p1 = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}, "page": 1, "page_size": 1, "only_changed": False},
    ).json()

    # Page 2, size 1
    p2 = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}, "page": 2, "page_size": 1, "only_changed": False},
    ).json()

    # Page 1, size 100
    pall = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}, "page": 1, "page_size": 100, "only_changed": False},
    ).json()

    # compile_digest must be strictly invariant across pagination
    assert p1["compile_digest"] == p2["compile_digest"] == pall["compile_digest"]
    assert p1["items"][0]["source_path"] != p2["items"][0]["source_path"]
    assert len(pall["items"]) == 2


# 8. only_changed invariance
def test_8_preview_only_changed_invariance(workflow_test_env):
    client = workflow_test_env["client"]
    scan_id = 801
    keeper, victim = _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    wf_resp = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 8",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()
    wf_id = wf_resp["id"]

    res_all = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}, "only_changed": False},
    ).json()

    res_changed = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}, "only_changed": True},
    ).json()

    # compile_digest invariant
    assert res_all["compile_digest"] == res_changed["compile_digest"]

    # only_changed=True returns only quarantine
    assert len(res_changed["items"]) == 1
    assert res_changed["items"][0]["source_path"] == str(victim)
    assert res_changed["items"][0]["operation"] == "quarantine"
    assert res_changed["items"][0]["changed"] is True

    # only_changed=False returns all
    assert len(res_all["items"]) == 2
    ops = {it["operation"] for it in res_all["items"]}
    assert ops == {"keep", "quarantine"}


# 9. Compile digest sensitivity
def test_9_compile_digest_sensitivity(workflow_test_env):
    client = workflow_test_env["client"]
    scan_id = 901
    _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    # Base workflow
    wf1 = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 9-1",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()

    d1 = client.post(
        f"/api/workflows/{wf1['id']}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}},
    ).json()["compile_digest"]

    # Different workflow ID
    wf2 = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 9-2",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()

    d2 = client.post(
        f"/api/workflows/{wf2['id']}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}},
    ).json()["compile_digest"]

    assert d1 != d2  # Sensitivity to workflow_id

    # Update workflow revision
    client.put(
        f"/api/workflows/{wf1['id']}",
        json={
            "expected_current_revision": 1,
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [
                    {
                        "id": "s1",
                        "type": "dedupe",
                        "scorer_config": {"factors": {"mtime": {"mode": "oldest", "weight": 80}}},
                    }
                ],
            },
        },
    )
    d_rev2 = client.post(
        f"/api/workflows/{wf1['id']}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}},
    ).json()["compile_digest"]

    assert d1 != d_rev2  # Sensitivity to revision / definition / config


# 10. PREVIEW_CHANGED on compile digest mismatch: 409 with 0 draft plans/items
def test_10_generate_plan_mismatch_returns_409_zero_plans(workflow_test_env):
    client = workflow_test_env["client"]
    scan_id = 1001
    _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    wf = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 10",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()

    before_plans, before_items = _count_plan_state(workflow_test_env["SessionLocal"])

    wrong_digest = "e" * 64
    resp = client.post(
        f"/api/workflows/{wf['id']}/generate-plan",
        json={
            "runtime_inputs": {"scan_job_id": scan_id},
            "expected_compile_digest": wrong_digest,
        },
    )
    assert resp.status_code == 409
    err = resp.json().get("error", {})
    assert err.get("code") == "PREVIEW_CHANGED"

    # Verify zero plans and zero items created
    after_plans, after_items = _count_plan_state(workflow_test_env["SessionLocal"])
    assert after_plans == before_plans
    assert after_items == before_items


# 11-15. Generate Draft Plan, Lineage Metadata, keep_path column, pre-freeze identity, reclaim bytes
def test_11_to_15_generate_draft_plan_and_invariants(workflow_test_env):
    client = workflow_test_env["client"]
    service = workflow_test_env["service"]
    scan_id = 1101
    keeper, victim = _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    wf = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 11-15",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()
    wf_id = wf["id"]

    prev = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}},
    ).json()
    compile_digest = prev["compile_digest"]

    # 11. Generate plan with matching compile_digest
    gen_resp = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={
            "runtime_inputs": {"scan_job_id": scan_id},
            "expected_compile_digest": compile_digest,
        },
    )
    assert gen_resp.status_code == 201
    gen_data = gen_resp.json()
    plan_id = gen_data["plan_id"]
    assert gen_data["status"] == "draft"
    assert gen_data["expected_changes"] == 1

    with service.SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        assert plan is not None
        assert plan.status == "draft"

        # 12. Metadata lineage completeness
        meta = json.loads(plan.metadata_json)
        assert meta["source"] == "workflow"
        assert meta["workflow_mode"] == "dedupe"
        assert meta["workflow_id"] == wf_id
        assert meta["workflow_revision"] == 1
        assert meta["scan_job_id"] == scan_id
        assert meta["runtime_inputs"]["scan_job_id"] == scan_id
        assert meta["scan_job_id"] == meta["runtime_inputs"]["scan_job_id"]
        assert meta["compile_digest"] == compile_digest
        assert len(meta["preview_digest"]) == 64
        assert len(meta["db_lineage_digest"]) == 64
        assert "effective_safety_policy" in meta
        assert meta["effective_safety_policy"]["protect_last_file"] is True

        # 13. BatchPlanItem.keep_path persisted in database column
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)))
        assert len(items) == 1
        item = items[0]
        assert item.operation == "quarantine"
        assert item.source_path == str(victim)
        assert item.target_path is None
        assert item.keep_path == str(keeper)

        # 14. Pre-freeze zero/null Gate3 identity
        assert item.expected_device == 0
        assert item.expected_inode == 0
        assert item.expected_mtime_ns == 0
        assert item.expected_hash is None

        # 15. Expected reclaim bytes correctly recorded
        file_sz = victim.stat().st_size
        assert plan.expected_reclaim_bytes == file_sz


# 16. Phase A/B DB race detection (db_lineage_changed -> 409 PREVIEW_CHANGED)
def test_16_phase_a_b_db_race_detection(workflow_test_env, monkeypatch):
    client = workflow_test_env["client"]
    service = workflow_test_env["service"]
    scan_id = 1601
    _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    wf = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 16",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()
    wf_id = wf["id"]

    prev = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}},
    ).json()
    compile_digest = prev["compile_digest"]

    # Monkeypatch compile_workflow_definition to simulate DB mutation right after Phase A
    orig_compile = service.workflow_service.compile_workflow_definition

    def racing_compile(*args, **kwargs):
        res = orig_compile(*args, **kwargs)
        # Mutate scan status or duplicate row in DB
        with service.SessionLocal() as session:
            file_row = session.scalar(select(DuplicateFile).limit(1))
            if file_row:
                file_row.size += 1
                session.commit()
        return res

    monkeypatch.setattr(service.workflow_service, "compile_workflow_definition", racing_compile)

    before_plans, before_items = _count_plan_state(workflow_test_env["SessionLocal"])

    resp = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={
            "runtime_inputs": {"scan_job_id": scan_id},
            "expected_compile_digest": compile_digest,
        },
    )
    assert resp.status_code == 409
    err = resp.json().get("error", {})
    assert err.get("code") == "PREVIEW_CHANGED"
    assert err.get("details", {}).get("reason") == "db_lineage_changed"

    after_plans, after_items = _count_plan_state(workflow_test_env["SessionLocal"])
    assert after_plans == before_plans
    assert after_items == before_items


# 17. Archive race detection
def test_17_archive_race_detection(workflow_test_env, monkeypatch):
    client = workflow_test_env["client"]
    service = workflow_test_env["service"]
    scan_id = 1701
    _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    wf = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 17",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()
    wf_id = wf["id"]

    prev = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}},
    ).json()
    compile_digest = prev["compile_digest"]

    orig_compile = service.workflow_service.compile_workflow_definition

    def racing_archive(*args, **kwargs):
        res = orig_compile(*args, **kwargs)
        with service.SessionLocal() as session:
            wf_obj = session.get(Workflow, wf_id)
            wf_obj.archived_at = utcnow()
            session.commit()
        return res

    monkeypatch.setattr(service.workflow_service, "compile_workflow_definition", racing_archive)

    before_plans, before_items = _count_plan_state(workflow_test_env["SessionLocal"])

    resp = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={
            "runtime_inputs": {"scan_job_id": scan_id},
            "expected_compile_digest": compile_digest,
        },
    )
    assert resp.status_code == 409
    err = resp.json().get("error", {})
    assert err.get("code") == "WORKFLOW_ARCHIVED"

    after_plans, after_items = _count_plan_state(workflow_test_env["SessionLocal"])
    assert after_plans == before_plans
    assert after_items == before_items


# 18. Historical revision Preview and Generate
def test_18_historical_revision_preview_and_generate(workflow_test_env):
    client = workflow_test_env["client"]
    scan_id = 1801
    _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    # Rev 1
    wf = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 18",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()
    wf_id = wf["id"]

    # Rev 2: update scorer config
    client.put(
        f"/api/workflows/{wf_id}",
        json={
            "expected_current_revision": 1,
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [
                    {
                        "id": "s1",
                        "type": "dedupe",
                        "scorer_config": {"factors": {"mtime": {"mode": "oldest", "weight": 70}}},
                    }
                ],
            },
        },
    )

    # Preview rev 1
    p1 = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}, "revision": 1},
    ).json()
    assert p1["workflow_revision"] == 1
    d1 = p1["compile_digest"]

    # Generate plan for rev 1
    gen1 = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={
            "runtime_inputs": {"scan_job_id": scan_id},
            "revision": 1,
            "expected_compile_digest": d1,
        },
    )
    assert gen1.status_code == 201
    plan_id = gen1.json()["plan_id"]

    with workflow_test_env["service"].SessionLocal() as session:
        plan = session.get(BatchPlan, plan_id)
        meta = json.loads(plan.metadata_json)
        assert meta["workflow_revision"] == 1


# 19. Stale dedupe rebuild guard returns 409 DEDUPE_RESCAN_REQUIRED
def test_19_stale_dedupe_rebuild_guard(workflow_test_env):
    client = workflow_test_env["client"]
    scan_id = 1901
    _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    wf = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 19",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()
    wf_id = wf["id"]

    prev = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}},
    ).json()

    gen = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={
            "runtime_inputs": {"scan_job_id": scan_id},
            "expected_compile_digest": prev["compile_digest"],
        },
    ).json()
    plan_id = gen["plan_id"]

    # Mark plan as stale so it becomes eligible for rebuild consideration
    with workflow_test_env["SessionLocal"]() as session:
        p = session.get(BatchPlan, plan_id)
        p.status = "stale"
        session.commit()

    before_plans, before_items = _count_plan_state(workflow_test_env["SessionLocal"])

    # Rebuild-preview returns 409 DEDUPE_RESCAN_REQUIRED
    rp_resp = client.post(f"/api/plans/{plan_id}/rebuild-preview", json={})
    assert rp_resp.status_code == 409
    err1 = rp_resp.json().get("error", {})
    assert err1.get("code") == "DEDUPE_RESCAN_REQUIRED"

    # Rebuild returns 409 DEDUPE_RESCAN_REQUIRED
    r_resp = client.post(
        f"/api/plans/{plan_id}/rebuild",
        json={"expected_compile_digest": "a" * 64},
    )
    assert r_resp.status_code == 409
    err2 = r_resp.json().get("error", {})
    assert err2.get("code") == "DEDUPE_RESCAN_REQUIRED"

    after_plans, after_items = _count_plan_state(workflow_test_env["SessionLocal"])
    assert after_plans == before_plans
    assert after_items == before_items


# 20. ScanJob dependency deletion guard blocks scan deletion
def test_20_delete_scan_blocked_by_workflow_dedupe_plan(workflow_test_env):
    client = workflow_test_env["client"]
    service = workflow_test_env["service"]
    scan_id = 2001
    _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    wf = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 20",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()
    wf_id = wf["id"]

    prev = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}},
    ).json()

    client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={
            "runtime_inputs": {"scan_job_id": scan_id},
            "expected_compile_digest": prev["compile_digest"],
        },
    )

    # Attempting to delete scan must be blocked
    with pytest.raises(ValueError, match="关联计划"):
        service.delete_scan(scan_id)


# 21. Full Gate3 Lifecycle: Generate Draft -> Freeze -> Validate
def test_21_gate3_freeze_and_validate_lifecycle(workflow_test_env):
    client = workflow_test_env["client"]
    service = workflow_test_env["service"]
    scan_id = 2101
    keeper, victim = _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    wf = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 21",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()
    wf_id = wf["id"]

    prev = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}},
    ).json()

    gen = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={
            "runtime_inputs": {"scan_job_id": scan_id},
            "expected_compile_digest": prev["compile_digest"],
        },
    ).json()
    plan_id = gen["plan_id"]

    # Freeze plan
    frozen_plan = service.freeze_plan(plan_id)
    assert frozen_plan.status == "frozen"
    assert frozen_plan.frozen_at is not None

    with service.SessionLocal() as session:
        items = list(session.scalars(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id)))
        assert len(items) == 1
        item = items[0]
        # Gate3 physical identity must be populated
        assert item.expected_device > 0
        assert item.expected_inode > 0
        assert item.expected_mtime_ns > 0
        assert item.expected_size > 0

    # Validate plan
    val_res = service.validate_plan(plan_id)
    assert val_res["status"] in ("ready", "valid") or val_res.get("valid") is True


# 22. Modified KEEP file after freeze causes Execute to fail closed
def test_22_modified_keep_file_fails_closed(workflow_test_env):
    client = workflow_test_env["client"]
    service = workflow_test_env["service"]
    scan_id = 2201
    keeper, victim = _setup_duplicate_test_data(
        workflow_test_env["SessionLocal"],
        workflow_test_env["data_dir"],
        scan_id=scan_id,
    )

    wf = client.post(
        "/api/workflows",
        json={
            "name": "Dedupe WF 22",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [{"id": "s1", "type": "dedupe", "scorer_config": {}}],
            },
        },
    ).json()
    wf_id = wf["id"]

    prev = client.post(
        f"/api/workflows/{wf_id}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}},
    ).json()

    gen = client.post(
        f"/api/workflows/{wf_id}/generate-plan",
        json={
            "runtime_inputs": {"scan_job_id": scan_id},
            "expected_compile_digest": prev["compile_digest"],
        },
    ).json()
    plan_id = gen["plan_id"]

    # Freeze plan
    service.freeze_plan(plan_id)

    # Modify the KEEP file content to tamper with physical identity / freshness
    keeper.write_bytes(b"tampered_keep_content_12345678")

    # 1. Validation detects duplicate pair mismatch and marks item as skipped
    service.validate_plan(plan_id)
    with service.SessionLocal() as session:
        p = session.get(BatchPlan, plan_id)
        item = session.scalar(select(BatchPlanItem).where(BatchPlanItem.plan_id == plan_id))
        assert item.state == "skipped"
        assert p.status in ("partial", "stale")

    # 2. Executing plan fails closed: item is NOT quarantined, victim file is untouched
    service.execute_plan(plan_id)
    assert victim.exists()
    assert victim.read_bytes() == b"duplicate_content_data_128" * 5

