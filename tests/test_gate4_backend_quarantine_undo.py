from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.exceptions import StateConflictError
from app.main import create_app
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    OperationJournal,
    QuarantineEntry,
    TaskLock,
    User,
    WorkJob,
    utcnow,
)
from app.quarantine.paths import safe_quarantine_hash
from app.service import FileCenterService
from app.tasks.context import JobContext
from app.tasks.handlers import get_handler


def _setup_gate4_env(tmp_path: Path, allow_delete: bool = True, allow_mutation: bool = True):
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    trash = data / ".nas-file-center-trash"
    trash.mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=trash,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=allow_mutation,
        allow_delete=allow_delete,
    )
    service = FileCenterService(settings)
    app = create_app(settings)
    client = TestClient(app)

    # Login as admin
    resp = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    assert resp.status_code == 200

    # Create regular user
    with service.SessionLocal() as session:
        from app.auth.password import hash_password
        regular_user = User(
            username="regular_user",
            password_hash=hash_password("RegularPass123!"),
            role="user",
        )
        session.add(regular_user)
        session.commit()

    regular_client = TestClient(app)
    resp_reg = regular_client.post(
        "/api/auth/login",
        json={"username": "regular_user", "password": "RegularPass123!"},
        headers={"Origin": "http://testserver"},
    )
    assert resp_reg.status_code == 200

    client.headers.update({"Origin": "http://testserver"})
    regular_client.headers.update({"Origin": "http://testserver"})

    return {
        "admin_client": client,
        "regular_client": regular_client,
        "service": service,
        "settings": settings,
        "data": data,
        "trash": trash,
    }


def _acquire_lease(service: FileCenterService, worker_id: str):
    with service.SessionLocal() as session:
        lock = session.get(TaskLock, 1)
        if not lock:
            lock = TaskLock(id=1, locked=True, owner=worker_id, acquired_at=utcnow())
            session.add(lock)
        else:
            lock.locked = True
            lock.owner = worker_id
            lock.acquired_at = utcnow()
        session.commit()


def _execute_job(service: FileCenterService, settings: Settings, job_id: int, worker_id: str = "worker-gate4"):
    handler = get_handler("batch-plan-execute")
    _acquire_lease(service, worker_id)
    with service.SessionLocal() as session:
        job = session.get(WorkJob, job_id)
        assert job is not None
        job.status = "running"
        session.commit()
        context = JobContext(service.engine, service.SessionLocal, job.id, worker_id=worker_id)
        handler.run(job, context, settings)
        job.status = "completed"
        session.commit()


# ==============================================================================
# 1. Restore Target Conflict Policies: skip, rename, manual
# ==============================================================================

def test_restore_conflict_policy_skip(tmp_path: Path):
    """When target already exists and policy='skip', restore skips and preserves both files."""
    env = _setup_gate4_env(tmp_path)
    client = env["admin_client"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    original_file = data / "conflict_doc.txt"
    original_file.write_text("existing content in place", encoding="utf-8")

    quarantine_file = trash / "conflict_doc.q-101.txt"
    quarantine_file.write_text("quarantined content", encoding="utf-8")
    sha = safe_quarantine_hash(quarantine_file)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original_file),
            quarantine_path=str(quarantine_file),
            state="active",
            size=len("quarantined content"),
            content_hash=sha,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # Restore with skip
    resp = client.post(
        f"/api/quarantine/{entry_id}/restore",
        json={"conflict_policy": "skip"},
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["state"] == "skipped"
    assert res_data["status"] == "skipped"
    assert "Destination already exists" in res_data["reason"]

    # Both files must remain intact
    assert original_file.exists()
    assert original_file.read_text(encoding="utf-8") == "existing content in place"
    assert quarantine_file.exists()
    assert quarantine_file.read_text(encoding="utf-8") == "quarantined content"

    # DB state remains active
    with service.SessionLocal() as session:
        e = session.get(QuarantineEntry, entry_id)
        assert e.state == "active"


def test_restore_conflict_policy_rename(tmp_path: Path):
    """When target already exists and policy='rename', restore creates renamed target."""
    env = _setup_gate4_env(tmp_path)
    client = env["admin_client"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    original_file = data / "doc_rename.txt"
    original_file.write_text("existing original content", encoding="utf-8")

    quarantine_file = trash / "doc_rename.q-102.txt"
    quarantine_file.write_text("quarantined content to rename", encoding="utf-8")
    sha = safe_quarantine_hash(quarantine_file)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original_file),
            quarantine_path=str(quarantine_file),
            state="active",
            size=len("quarantined content to rename"),
            content_hash=sha,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # Restore with rename
    resp = client.post(
        f"/api/quarantine/{entry_id}/restore",
        json={"conflict_policy": "rename"},
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["state"] == "restored"
    assert res_data["conflict_resolved"] is True
    restored_path = Path(res_data["restored_to_path"])

    assert original_file.exists()
    assert original_file.read_text(encoding="utf-8") == "existing original content"

    assert restored_path.exists()
    assert restored_path != original_file
    assert restored_path.read_text(encoding="utf-8") == "quarantined content to rename"
    assert not quarantine_file.exists()


def test_restore_conflict_policy_manual(tmp_path: Path):
    """Manual destination: fails if destination exists, succeeds if custom_target is non-existent."""
    env = _setup_gate4_env(tmp_path)
    client = env["admin_client"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    original_file = data / "doc_manual.txt"
    original_file.write_text("existing file", encoding="utf-8")

    quarantine_file = trash / "doc_manual.q-103.txt"
    quarantine_file.write_text("quarantined content manual", encoding="utf-8")
    sha = safe_quarantine_hash(quarantine_file)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(original_file),
            quarantine_path=str(quarantine_file),
            state="active",
            size=len("quarantined content manual"),
            content_hash=sha,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # 1. Manual without custom target when original exists -> fails
    resp_conflict = client.post(
        f"/api/quarantine/{entry_id}/restore",
        json={"conflict_policy": "manual"},
    )
    assert resp_conflict.status_code == 400

    # 2. Manual with custom target that already exists -> fails
    resp_custom_conflict = client.post(
        f"/api/quarantine/{entry_id}/restore",
        json={"conflict_policy": "manual", "custom_target": str(original_file)},
    )
    assert resp_custom_conflict.status_code == 400

    # 3. Manual with custom target that does not exist -> succeeds
    custom_target = data / "subfolder" / "custom_restored.txt"
    resp_success = client.post(
        f"/api/quarantine/{entry_id}/restore",
        json={"conflict_policy": "manual", "custom_target": str(custom_target)},
    )
    assert resp_success.status_code == 200
    assert resp_success.json()["state"] == "restored"
    assert custom_target.exists()
    assert custom_target.read_text(encoding="utf-8") == "quarantined content manual"
    assert not quarantine_file.exists()


# ==============================================================================
# 2. Purge Guard: Admin required, ALLOW_DELETE=true, confirmation token
# ==============================================================================

def test_purge_guard_rules(tmp_path: Path):
    """Purge verifies non-admin rejection, bad token rejection, and ALLOW_DELETE enforcement."""
    env = _setup_gate4_env(tmp_path, allow_delete=True)
    admin_client = env["admin_client"]
    reg_client = env["regular_client"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    purge_file = trash / "to_purge.q-201.txt"
    purge_file.write_text("data to purge", encoding="utf-8")
    sha = safe_quarantine_hash(purge_file)

    with service.SessionLocal() as session:
        entry = QuarantineEntry(
            original_path=str(data / "to_purge.txt"),
            quarantine_path=str(purge_file),
            state="active",
            size=len("data to purge"),
            content_hash=sha,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry)
        session.commit()
        entry_id = entry.id

    # 1. Non-admin forbidden
    resp_reg = reg_client.post(
        f"/api/quarantine/{entry_id}/purge",
        json={"confirmation": "DELETE"},
    )
    assert resp_reg.status_code == 403

    # 2. Bad confirmation token
    for bad_token in ["delete", "Delete", "CONFIRM", "YES", "", "DELETE ", " DELETE", "  DELETE  ", "DELETE\n", "DELETE\t"]:
        resp_bad = admin_client.post(
            f"/api/quarantine/{entry_id}/purge",
            json={"confirmation": bad_token},
        )
        assert resp_bad.status_code == 400

    # 3. Environment with ALLOW_DELETE=False
    env_nodelete = _setup_gate4_env(tmp_path / "nodelete_env", allow_delete=False)
    admin_nd = env_nodelete["admin_client"]
    serv_nd = env_nodelete["service"]
    trash_nd = env_nodelete["trash"]
    data_nd = env_nodelete["data"]

    target_nd = trash_nd / "nodelete.q-202.txt"
    target_nd.write_text("cannot delete", encoding="utf-8")
    sha_nd = safe_quarantine_hash(target_nd)
    with serv_nd.SessionLocal() as session:
        entry_nd = QuarantineEntry(
            original_path=str(data_nd / "nodelete.txt"),
            quarantine_path=str(target_nd),
            state="active",
            size=len("cannot delete"),
            content_hash=sha_nd,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(entry_nd)
        session.commit()
        entry_nd_id = entry_nd.id

    resp_nd = admin_nd.post(
        f"/api/quarantine/{entry_nd_id}/purge",
        json={"confirmation": "DELETE"},
    )
    assert resp_nd.status_code == 400
    assert "Permanent deletion is disabled" in resp_nd.text
    assert target_nd.exists()

    # 4. Valid Admin + DELETE + ALLOW_DELETE=True -> Success
    resp_ok = admin_client.post(
        f"/api/quarantine/{entry_id}/purge",
        json={"confirmation": "DELETE"},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["state"] == "purged"
    assert not purge_file.exists()

    # 5. Purging non-active entry -> 409 StateConflictError
    resp_again = admin_client.post(
        f"/api/quarantine/{entry_id}/purge",
        json={"confirmation": "DELETE"},
    )
    assert resp_again.status_code == 409


# ==============================================================================
# 3. Undo Plan: Rejection on illegal states, 0 journal items, & Full Lifecycle
# ==============================================================================

def test_create_undo_plan_invalid_states_and_empty_journal(tmp_path: Path):
    """Cannot create undo plan for non-completed/partial plans (409) or completed plans with 0 operations (400)."""
    env = _setup_gate4_env(tmp_path)
    client = env["admin_client"]
    service = env["service"]
    data = env["data"]

    f1 = data / "test_undo_state.txt"
    f1.write_text("content", encoding="utf-8")
    target1 = data / "test_undo_state_moved.txt"

    # 1. Plan in draft status -> 409 StateConflictError
    plan = service.create_plan(
        name="Draft Plan",
        kind="organize",
        items=[{"source": str(f1), "target": str(target1), "operation": "rename"}],
    )

    resp_draft = client.post(f"/api/plans/{plan.id}/undo-plan")
    assert resp_draft.status_code == 409
    assert "must be 'completed' or 'partial'" in resp_draft.text

    # 2. Plan in ready status -> 409 StateConflictError
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    resp_ready = client.post(f"/api/plans/{plan.id}/undo-plan")
    assert resp_ready.status_code == 409
    assert "must be 'completed' or 'partial'" in resp_ready.text

    # 3. Non-terminal / illegal statuses rejected even if journal entries exist in DB
    with service.SessionLocal() as session:
        fake_journal = OperationJournal(
            plan_id=plan.id,
            plan_item_id=None,
            operation="rename",
            before_json=json.dumps({"path": str(f1), "size": 7}),
            after_json=json.dumps({"path": str(target1), "size": 7}),
            sequence=1,
            created_at=utcnow(),
        )
        session.add(fake_journal)
        session.commit()

    for invalid_status in ["draft", "pending", "ready", "running", "failed", "cancelled", "stale"]:
        with service.SessionLocal() as session:
            p = session.get(BatchPlan, plan.id)
            assert p is not None
            p.status = invalid_status
            session.commit()

        resp_inv = client.post(f"/api/plans/{plan.id}/undo-plan")
        assert resp_inv.status_code == 409
        assert f"status is '{invalid_status}', must be 'completed' or 'partial'" in resp_inv.text

    # 4. Plan in completed status but 0 journal entries -> 400 Bad Request
    empty_completed_plan = service.create_plan(
        name="Empty Completed Plan",
        kind="organize",
        items=[],
    )
    with service.SessionLocal() as session:
        ecp = session.get(BatchPlan, empty_completed_plan.id)
        assert ecp is not None
        ecp.status = "completed"
        session.commit()

    resp_empty = client.post(f"/api/plans/{empty_completed_plan.id}/undo-plan")
    assert resp_empty.status_code == 400
    assert "no completed operations to undo" in resp_empty.text


def test_undo_plan_full_lifecycle_and_reflexivity(tmp_path: Path):
    """
    Validates complete lifecycle of Undo Plan:
    1. Executing Original Plan -> Completed
    2. Creating Undo Plan -> Draft with metadata (undo_of_plan_id)
    3. Cannot direct execute draft undo plan (requires Freeze -> Validate -> Execute)
    4. Freezing, Validating, Executing Undo Plan -> Restores original filesystem state
    5. Reflexive Undo: Creating Undo Plan from executed Undo Plan works and links correctly!
    """
    env = _setup_gate4_env(tmp_path)
    client = env["admin_client"]
    service = env["service"]
    settings = env["settings"]
    data = env["data"]

    src_file = data / "initial_doc.txt"
    src_file.write_text("original text content", encoding="utf-8")
    renamed_file = data / "renamed_doc.txt"

    # 1. Create and execute original plan
    plan = service.create_plan(
        name="Original Organize Plan",
        kind="organize",
        items=[{"source": str(src_file), "target": str(renamed_file), "operation": "rename"}],
    )
    service.freeze_plan(plan.id)
    service.validate_plan(plan.id)

    exec_res = client.post(f"/api/plans/{plan.id}/execute")
    assert exec_res.status_code == 200
    job_id = exec_res.json()["work_job_id"]
    _execute_job(service, settings, job_id, "worker-orig")

    assert not src_file.exists()
    assert renamed_file.exists()
    assert renamed_file.read_text(encoding="utf-8") == "original text content"

    # Check original plan detail returns metadata
    detail_res = client.get(f"/api/plans/{plan.id}")
    assert detail_res.status_code == 200
    assert "metadata" in detail_res.json()

    # 2. Create Undo Plan
    undo_res = client.post(f"/api/plans/{plan.id}/undo-plan")
    assert undo_res.status_code == 200
    undo_data = undo_res.json()
    undo_id = undo_data["id"]

    assert undo_data["kind"] == "undo"
    assert undo_data["status"] == "draft"

    # Query undo plan detail from API to verify metadata contract
    undo_detail = client.get(f"/api/plans/{undo_id}").json()
    assert undo_detail["metadata"]["is_undo"] is True
    assert undo_detail["metadata"]["undo_of_plan_id"] == plan.id

    # 3. Direct execution of draft undo plan is forbidden
    direct_exec = client.post(f"/api/plans/{undo_id}/execute")
    assert direct_exec.status_code == 409  # must be validated first

    # 4. Follow strict lifecycle: Freeze -> Validate -> Execute
    freeze_res = client.post(f"/api/plans/{undo_id}/freeze")
    assert freeze_res.status_code == 200
    assert freeze_res.json()["status"] == "frozen"

    validate_res = client.post(f"/api/plans/{undo_id}/validate")
    assert validate_res.status_code == 200
    assert validate_res.json()["status"] == "ready"

    exec_undo_res = client.post(f"/api/plans/{undo_id}/execute")
    assert exec_undo_res.status_code == 200
    undo_job_id = exec_undo_res.json()["work_job_id"]
    _execute_job(service, settings, undo_job_id, "worker-undo")

    # Verify original file restored and renamed file gone
    assert src_file.exists()
    assert src_file.read_text(encoding="utf-8") == "original text content"
    assert not renamed_file.exists()

    # 5. Reflexive Undo: Create an Undo Plan for the Undo Plan!
    reflexive_res = client.post(f"/api/plans/{undo_id}/undo-plan")
    assert reflexive_res.status_code == 200
    reflexive_data = reflexive_res.json()
    reflexive_id = reflexive_data["id"]

    assert reflexive_data["kind"] == "undo"
    assert reflexive_data["status"] == "draft"

    ref_detail = client.get(f"/api/plans/{reflexive_id}").json()
    assert ref_detail["metadata"]["is_undo"] is True
    assert ref_detail["metadata"]["undo_of_plan_id"] == undo_id

    # Freeze -> Validate -> Execute the reflexive undo plan
    client.post(f"/api/plans/{reflexive_id}/freeze")
    client.post(f"/api/plans/{reflexive_id}/validate")
    ref_exec = client.post(f"/api/plans/{reflexive_id}/execute")
    assert ref_exec.status_code == 200
    ref_job_id = ref_exec.json()["work_job_id"]
    _execute_job(service, settings, ref_job_id, "worker-ref-undo")

    # Filesystem state is back to renamed!
    assert not src_file.exists()
    assert renamed_file.exists()
    assert renamed_file.read_text(encoding="utf-8") == "original text content"


def test_quarantine_list_search_and_query_parameters(tmp_path: Path):
    """Test that /api/quarantine works seamlessly with both ?query= and ?search= parameters."""
    env = _setup_gate4_env(tmp_path)
    client = env["admin_client"]
    service = env["service"]
    data = env["data"]
    trash = env["trash"]

    f1 = trash / "target_alpha.q-301.txt"
    f1.write_text("alpha content", encoding="utf-8")
    f2 = trash / "target_beta.q-302.txt"
    f2.write_text("beta content", encoding="utf-8")

    with service.SessionLocal() as session:
        entry1 = QuarantineEntry(
            original_path=str(data / "alpha_doc.txt"),
            quarantine_path=str(f1),
            state="active",
            size=len("alpha content"),
            content_hash=safe_quarantine_hash(f1),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        entry2 = QuarantineEntry(
            original_path=str(data / "beta_file.pdf"),
            quarantine_path=str(f2),
            state="active",
            size=len("beta content"),
            content_hash=safe_quarantine_hash(f2),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add_all([entry1, entry2])
        session.commit()

    # 1. Search using ?query=
    resp_query = client.get("/api/quarantine?query=alpha")
    assert resp_query.status_code == 200
    assert resp_query.json()["total"] == 1
    assert "alpha" in resp_query.json()["items"][0]["original_path"]

    # 2. Search using ?search= (backwards-compatibility)
    resp_search = client.get("/api/quarantine?search=beta")
    assert resp_search.status_code == 200
    assert resp_search.json()["total"] == 1
    assert "beta" in resp_search.json()["items"][0]["original_path"]

    # 3. Search with no match
    resp_nomatch = client.get("/api/quarantine?query=nonexistent_xyz")
    assert resp_nomatch.status_code == 200
    assert resp_nomatch.json()["total"] == 0

