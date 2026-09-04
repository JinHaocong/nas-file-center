from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.sessions import create_session
from app.config import Settings
from app.db import create_engine_and_session, init_db
from app.main import create_app
from app.models import (
    AuditEvent,
    BatchPlan,
    BatchPlanItem,
    DuplicateFile,
    DuplicateGroup,
    Plan,
    PlanItem,
    ScanJob,
    User,
    WorkJob,
    utcnow,
)


@pytest.fixture
def plan_cleanup_setup(tmp_path: Path):
    settings = Settings(config_dir=tmp_path)
    engine, SessionLocal = create_engine_and_session(settings.database_path)
    init_db(
        engine,
        db_path=settings.database_path,
        backups_dir=settings.backups_dir,
        initial_admin_username="admin",
        initial_admin_password="Password123!",
    )
    app = create_app(settings)
    client = TestClient(app)
    client.headers.update({"Origin": "http://testserver"})

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        _, token = create_session(session, user_id=user.id, max_age_seconds=86400)
        session.commit()
    client.cookies.set(settings.session_cookie_name, token)

    return {
        "settings": settings,
        "engine": engine,
        "SessionLocal": SessionLocal,
        "client": client,
        "service": app.state.service,
        "app": app,
    }


def test_red_current_batch_plan_delete_endpoint(plan_cleanup_setup):
    """RED test: In fixed7 baseline, DELETE /api/plans/{id} endpoint does not exist.
    Attempting to delete a BatchPlan returns 405 Method Not Allowed.
    In fixed8, it must succeed with 200 and return {'deleted': True, 'id': plan_id}.
    """
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        bp = BatchPlan(
            name="Test Draft Plan",
            kind="dedupe",
            status="draft",
        )
        session.add(bp)
        session.commit()
        plan_id = bp.id

    resp = client.delete(f"/api/plans/{plan_id}")
    assert resp.status_code == 200, f"Expected 200 OK, got {resp.status_code}"
    assert resp.json() == {"deleted": True, "id": plan_id}


def test_red_legacy_plan_cleanup_endpoints(plan_cleanup_setup):
    """RED test: In fixed7 baseline, /api/plans/legacy/summary and /api/plans/legacy/clear
    do not exist (404 Not Found).
    In fixed8, summary returns legacy Plan/PlanItem counts, and clear safely purges them.
    """
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        scan = ScanJob(name="Scan for Legacy Plan", status="completed", roots_json=json.dumps(["/data"]))
        session.add(scan)
        session.flush()
        scan_id = scan.id

        grp = DuplicateGroup(scan_job_id=scan_id, content_hash="hash1", file_size=100, member_count=2)
        session.add(grp)
        session.flush()
        grp_id = grp.id

        lp = Plan(scan_job_id=scan_id, policy="balanced-roots", status="draft")
        session.add(lp)
        session.flush()
        l_item = PlanItem(
            plan_id=lp.id,
            group_id=grp_id,
            keep_path="/data/keep.txt",
            delete_path="/data/del.txt",
            expected_size=100,
            discovery_hash="hash1",
        )
        session.add(l_item)
        session.commit()

    # GET /api/plans/legacy/summary
    resp_sum = client.get("/api/plans/legacy/summary")
    assert resp_sum.status_code == 200, f"Expected 200, got {resp_sum.status_code}"
    sum_data = resp_sum.json()
    assert sum_data["plan_count"] == 1
    assert sum_data["item_count"] == 1
    assert sum_data["affected_scan_count"] == 1

    # POST /api/plans/legacy/clear
    resp_clear = client.post("/api/plans/legacy/clear", json={})
    assert resp_clear.status_code == 200, f"Expected 200, got {resp_clear.status_code}"
    clear_data = resp_clear.json()
    assert clear_data["deleted_count"] == 1
    assert clear_data["deleted_item_count"] == 1
    assert clear_data["affected_scan_count"] == 1


def test_red_clear_history_endpoint(plan_cleanup_setup):
    """RED test: In fixed7 baseline, POST /api/plans/clear-history does not exist (404 Not Found).
    In fixed8, it accepts {'statuses': ['completed', 'failed']} and returns {'deleted_count': N}.
    """
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        p_comp = BatchPlan(name="Completed Plan", kind="dedupe", status="completed")
        p_fail = BatchPlan(name="Failed Plan", kind="dedupe", status="failed")
        session.add_all([p_comp, p_fail])
        session.commit()

    resp = client.post("/api/plans/clear-history", json={"statuses": ["completed", "failed"]})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert resp.json()["deleted_count"] == 2


# =========================================================================
# Cases A ~ I: Single Delete Allowed & Blocked Status Matrix
# =========================================================================

@pytest.mark.parametrize("status", ["draft", "frozen", "ready", "partial", "completed", "failed"])
def test_delete_plan_allowed_statuses(plan_cleanup_setup, status: str):
    """Cases A~F: Single delete allowed for draft, frozen, ready, partial, completed, failed."""
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        p = BatchPlan(name=f"Plan {status}", kind="dedupe", status=status)
        session.add(p)
        session.commit()
        plan_id = p.id

    resp = client.delete(f"/api/plans/{plan_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "id": plan_id}

    with SessionLocal() as session:
        assert session.get(BatchPlan, plan_id) is None


@pytest.mark.parametrize("blocked_status", ["validating", "executing", "unknown_status"])
def test_delete_plan_blocked_statuses(plan_cleanup_setup, blocked_status: str):
    """Cases G~I: Single delete strictly blocked (409 Conflict) for validating, executing, and unknown statuses."""
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        p = BatchPlan(name=f"Plan {blocked_status}", kind="dedupe", status=blocked_status)
        session.add(p)
        session.commit()
        plan_id = p.id

    resp = client.delete(f"/api/plans/{plan_id}")
    assert resp.status_code == 409
    assert f"Plan with status '{blocked_status}' cannot be deleted" in resp.json()["detail"]

    # Verify plan is preserved
    with SessionLocal() as session:
        assert session.get(BatchPlan, plan_id) is not None


def test_delete_plan_nonexistent_returns_404(plan_cleanup_setup):
    """Case J: Deleting a non-existent plan returns 404."""
    client = plan_cleanup_setup["client"]
    resp = client.delete("/api/plans/999999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Plan not found"


# =========================================================================
# Cases K ~ O: Cascade, Preservations, and Delete != Undo
# =========================================================================

def test_delete_plan_cascades_items_and_preserves_audit_scan_files_workjob(plan_cleanup_setup, tmp_path: Path):
    """Cases K, L, M, N, O: Deleting a plan cascades BatchPlanItem,
    preserves AuditEvent, ScanJob, WorkJob, and does NOT touch real files (Delete != Undo).
    """
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    # Create real NAS file to verify Delete != Undo
    nas_file = tmp_path / "nas_data.txt"
    nas_file.write_text("important content before and after delete")
    file_mtime = nas_file.stat().st_mtime_ns

    with SessionLocal() as session:
        scan = ScanJob(name="Parent Scan", status="completed", roots_json=json.dumps([str(tmp_path)]))
        session.add(scan)
        session.flush()
        s_id = scan.id

        plan = BatchPlan(
            name="Plan with Items",
            kind="dedupe",
            status="completed",
            metadata_json=json.dumps({"scan_job_id": s_id}),
        )
        session.add(plan)
        session.flush()
        p_id = plan.id

        item = BatchPlanItem(
            plan_id=p_id,
            sequence=1,
            operation="rename",
            source_path=str(nas_file),
            target_path=str(tmp_path / "target.txt"),
            expected_size=100,
            state="completed",
        )
        audit = AuditEvent(
            operation="rename",
            path=str(nas_file),
            result="completed",
            details_json=json.dumps({"plan_id": p_id, "item_id": 1}),
        )
        work = WorkJob(
            kind="plan-execute",
            status="completed",
            state_json=json.dumps({"plan_id": p_id}),
        )
        session.add_all([item, audit, work])
        session.commit()
        item_id = item.id
        audit_id = audit.id
        work_id = work.id

    resp = client.delete(f"/api/plans/{p_id}")
    assert resp.status_code == 200

    # Verify database states
    with SessionLocal() as session:
        # Case K: Plan and PlanItem removed
        assert session.get(BatchPlan, p_id) is None
        assert session.get(BatchPlanItem, item_id) is None

        # Case L: AuditEvent preserved
        assert session.get(AuditEvent, audit_id) is not None

        # Case M: ScanJob preserved
        assert session.get(ScanJob, s_id) is not None

        # Case O: WorkJob preserved
        assert session.get(WorkJob, work_id) is not None

    # Case N: Real NAS file untouched on disk (Delete != Undo)
    assert nas_file.exists()
    assert nas_file.read_text() == "important content before and after delete"
    assert nas_file.stat().st_mtime_ns == file_mtime


# =========================================================================
# Cases P ~ R: Scan Dependency Unlocking
# =========================================================================

def test_scan_dependency_unlock_single_batch_plan(plan_cleanup_setup):
    """Case P: Scan with single BatchPlan -> deleting plan unlocks Scan for deletion."""
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        scan = ScanJob(name="Scan P", status="completed", roots_json=json.dumps(["/data"]))
        session.add(scan)
        session.flush()
        s_id = scan.id

        bp = BatchPlan(
            name="Plan for Scan P",
            kind="dedupe",
            status="ready",
            metadata_json=json.dumps({"scan_job_id": s_id}),
        )
        session.add(bp)
        session.commit()
        p_id = bp.id

    # Prior to delete, scan has dependent plan
    assert client.get(f"/api/scans/{s_id}").json()["has_dependent_plan"] is True
    assert client.delete(f"/api/scans/{s_id}").status_code == 409

    # Delete BatchPlan
    assert client.delete(f"/api/plans/{p_id}").status_code == 200

    # Now scan has NO dependent plan
    assert client.get(f"/api/scans/{s_id}").json()["has_dependent_plan"] is False

    # Scan can now be safely deleted
    assert client.delete(f"/api/scans/{s_id}").status_code == 200


def test_scan_dependency_multiple_batch_plans(plan_cleanup_setup):
    """Case Q: Scan with 2 BatchPlans -> deleting first plan keeps dependency,
    deleting second plan unlocks Scan.
    """
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        scan = ScanJob(name="Scan Q", status="completed", roots_json=json.dumps(["/data"]))
        session.add(scan)
        session.flush()
        s_id = scan.id

        bp1 = BatchPlan(name="P1", kind="dedupe", status="ready", metadata_json=json.dumps({"scan_job_id": s_id}))
        bp2 = BatchPlan(name="P2", kind="dedupe", status="draft", metadata_json=json.dumps({"scan_job_id": s_id}))
        session.add_all([bp1, bp2])
        session.commit()
        p1_id = bp1.id
        p2_id = bp2.id

    # Delete first plan
    assert client.delete(f"/api/plans/{p1_id}").status_code == 200
    # Still blocked by bp2
    assert client.get(f"/api/scans/{s_id}").json()["has_dependent_plan"] is True
    assert client.delete(f"/api/scans/{s_id}").status_code == 409

    # Delete second plan
    assert client.delete(f"/api/plans/{p2_id}").status_code == 200
    # Now unlocked
    assert client.get(f"/api/scans/{s_id}").json()["has_dependent_plan"] is False
    assert client.delete(f"/api/scans/{s_id}").status_code == 200


def test_scan_dependency_mixed_batch_and_legacy_plan(plan_cleanup_setup):
    """Case R: Scan with BatchPlan + legacy Plan -> deleting BatchPlan leaves dependency True
    due to legacy Plan.
    """
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        scan = ScanJob(name="Scan R", status="completed", roots_json=json.dumps(["/data"]))
        session.add(scan)
        session.flush()
        s_id = scan.id

        bp = BatchPlan(name="Batch Plan R", kind="dedupe", status="ready", metadata_json=json.dumps({"scan_job_id": s_id}))
        lp = Plan(scan_job_id=s_id, policy="keep-first", status="draft")
        session.add_all([bp, lp])
        session.commit()
        bp_id = bp.id

    # Delete BatchPlan
    assert client.delete(f"/api/plans/{bp_id}").status_code == 200

    # Still blocked by legacy Plan
    assert client.get(f"/api/scans/{s_id}").json()["has_dependent_plan"] is True
    assert client.delete(f"/api/scans/{s_id}").status_code == 409


# =========================================================================
# Cases S ~ Y: Legacy Plan Compatibility Cleanup
# =========================================================================

def test_legacy_plan_summary_and_clear_flow(plan_cleanup_setup):
    """Cases S~Y: Legacy summary counts correctly, clear purges legacy Plan/PlanItem,
    preserves BatchPlan/ScanJob/AuditEvent, and unlocks Scan dependency.
    """
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        scan1 = ScanJob(name="Scan 1", status="completed", roots_json=json.dumps(["/data"]))
        scan2 = ScanJob(name="Scan 2", status="completed", roots_json=json.dumps(["/data"]))
        session.add_all([scan1, scan2])
        session.flush()
        s1_id = scan1.id
        s2_id = scan2.id

        grp = DuplicateGroup(scan_job_id=s1_id, content_hash="h1", file_size=10, member_count=2)
        session.add(grp)
        session.flush()

        lp1 = Plan(scan_job_id=s1_id, policy="balanced-roots", status="draft")
        lp2 = Plan(scan_job_id=s2_id, policy="balanced-roots", status="draft")
        session.add_all([lp1, lp2])
        session.flush()

        item1 = PlanItem(plan_id=lp1.id, group_id=grp.id, keep_path="/a", delete_path="/b", expected_size=10, discovery_hash="h1")
        item2 = PlanItem(plan_id=lp1.id, group_id=grp.id, keep_path="/c", delete_path="/d", expected_size=10, discovery_hash="h1")
        item3 = PlanItem(plan_id=lp2.id, group_id=grp.id, keep_path="/e", delete_path="/f", expected_size=10, discovery_hash="h1")
        session.add_all([item1, item2, item3])

        # Concurrent current BatchPlan (must be preserved)
        bp = BatchPlan(name="Current BP", kind="dedupe", status="draft")
        audit = AuditEvent(operation="legacy.test", path="/test", result="ok", details_json="{}")
        session.add_all([bp, audit])
        session.commit()
        bp_id = bp.id
        audit_id = audit.id

    # Case S: legacy summary counts correct
    resp_sum = client.get("/api/plans/legacy/summary")
    assert resp_sum.status_code == 200
    sum_data = resp_sum.json()
    assert sum_data["plan_count"] == 2
    assert sum_data["item_count"] == 3
    assert sum_data["affected_scan_count"] == 2

    # Prior to clear: scans are blocked
    assert client.get(f"/api/scans/{s1_id}").json()["has_dependent_plan"] is True
    assert client.get(f"/api/scans/{s2_id}").json()["has_dependent_plan"] is True

    # Execute clear legacy plans
    resp_clear = client.post("/api/plans/legacy/clear")
    assert resp_clear.status_code == 200
    clear_data = resp_clear.json()
    assert clear_data["deleted_count"] == 2
    assert clear_data["deleted_item_count"] == 3
    assert clear_data["affected_scan_count"] == 2

    # Cases T, U: legacy Plan and PlanItem removed
    with SessionLocal() as session:
        assert session.scalars(select(Plan)).all() == []
        assert session.scalars(select(PlanItem)).all() == []

        # Case V: ScanJobs preserved
        assert session.get(ScanJob, s1_id) is not None
        assert session.get(ScanJob, s2_id) is not None

        # Case W: AuditEvent preserved
        assert session.get(AuditEvent, audit_id) is not None

        # Case X: BatchPlan preserved
        assert session.get(BatchPlan, bp_id) is not None

    # Case Y: legacy clear unlocks Scan dependency
    assert client.get(f"/api/scans/{s1_id}").json()["has_dependent_plan"] is False
    assert client.get(f"/api/scans/{s2_id}").json()["has_dependent_plan"] is False
    assert client.delete(f"/api/scans/{s1_id}").status_code == 200
    assert client.delete(f"/api/scans/{s2_id}").status_code == 200


# =========================================================================
# Cases Z ~ AI: Clear Plan History Matrix & Validation
# =========================================================================

def test_clear_plan_history_statuses_validation_and_safety(plan_cleanup_setup):
    """Cases Z~AI: Clear history only allows completed/failed,
    rejects empty/missing/invalid statuses with 400 and zero deletion,
    cascades items, preserves Audit, and updates scan dependencies.
    """
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        scan = ScanJob(name="Scan Hist", status="completed", roots_json=json.dumps(["/data"]))
        session.add(scan)
        session.flush()
        s_id = scan.id

        p1 = BatchPlan(name="C1", kind="dedupe", status="completed", metadata_json=json.dumps({"scan_job_id": s_id}))
        p2 = BatchPlan(name="F1", kind="dedupe", status="failed")
        p3 = BatchPlan(name="Draft1", kind="dedupe", status="draft")
        p4 = BatchPlan(name="Partial1", kind="dedupe", status="partial")
        session.add_all([p1, p2, p3, p4])
        session.flush()

        item1 = BatchPlanItem(plan_id=p1.id, sequence=1, operation="rename", source_path="/p1", expected_size=10, state="completed")
        audit = AuditEvent(operation="plan.cleanup", path="/p1", result="completed", details_json="{}")
        session.add_all([item1, audit])
        session.commit()
        p1_id = p1.id
        p2_id = p2.id
        p3_id = p3.id
        p4_id = p4.id
        item1_id = item1.id
        audit_id = audit.id

    # Case AC: statuses=[] -> 400 Bad Request, zero deletion
    resp_empty = client.post("/api/plans/clear-history", json={"statuses": []})
    assert resp_empty.status_code == 400
    assert "At least one terminal status is required" in resp_empty.json()["detail"]

    # Case AD: statuses missing / None -> 400 Bad Request
    resp_none = client.post("/api/plans/clear-history", json={})
    assert resp_none.status_code == 400
    assert "At least one terminal status is required" in resp_none.json()["detail"]

    # Case AE: statuses=["partial"] -> 400 Bad Request
    resp_partial = client.post("/api/plans/clear-history", json={"statuses": ["partial"]})
    assert resp_partial.status_code == 400
    assert "Cannot clear non-history status" in resp_partial.json()["detail"]

    # Case AF: mixed ["completed", "partial"] -> 400 Bad Request, atomic zero deletion
    resp_mixed = client.post("/api/plans/clear-history", json={"statuses": ["completed", "partial"]})
    assert resp_mixed.status_code == 400

    # Verify zero deletion after all invalid attempts
    with SessionLocal() as session:
        assert session.get(BatchPlan, p1_id) is not None
        assert session.get(BatchPlan, p2_id) is not None
        assert session.get(BatchPlan, p3_id) is not None
        assert session.get(BatchPlan, p4_id) is not None

    # Case AA: clear only failed
    resp_fail = client.post("/api/plans/clear-history", json={"statuses": ["failed"]})
    assert resp_fail.status_code == 200
    assert resp_fail.json() == {"deleted_count": 1}

    with SessionLocal() as session:
        assert session.get(BatchPlan, p2_id) is None
        assert session.get(BatchPlan, p1_id) is not None
        assert session.get(BatchPlan, p3_id) is not None
        assert session.get(BatchPlan, p4_id) is not None

    # Case Z: clear only completed (also tests AG cascade items, AH Audit preserved, AI updates scan dep)
    resp_comp = client.post("/api/plans/clear-history", json={"statuses": ["completed"]})
    assert resp_comp.status_code == 200
    assert resp_comp.json() == {"deleted_count": 1}

    with SessionLocal() as session:
        assert session.get(BatchPlan, p1_id) is None
        # Case AG: item cascaded
        assert session.get(BatchPlanItem, item1_id) is None
        # Case AH: AuditEvent preserved
        assert session.get(AuditEvent, audit_id) is not None
        # Draft and Partial still preserved
        assert session.get(BatchPlan, p3_id) is not None
        assert session.get(BatchPlan, p4_id) is not None

    # Case AI: scan dependency unlocked
    assert client.get(f"/api/scans/{s_id}").json()["has_dependent_plan"] is False


def test_clear_plan_history_both_completed_and_failed(plan_cleanup_setup):
    """Case AB: statuses=['completed', 'failed'] clears both in single batch."""
    client = plan_cleanup_setup["client"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]

    with SessionLocal() as session:
        p1 = BatchPlan(name="C1", kind="dedupe", status="completed")
        p2 = BatchPlan(name="C2", kind="dedupe", status="completed")
        p3 = BatchPlan(name="F1", kind="dedupe", status="failed")
        session.add_all([p1, p2, p3])
        session.commit()

    resp = client.post("/api/plans/clear-history", json={"statuses": ["completed", "failed"]})
    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 3}


# =========================================================================
# Cases AJ ~ AN: Authentication and CSRF / Origin Security
# =========================================================================

def test_plan_cleanup_auth_and_csrf_security(plan_cleanup_setup):
    """Cases AJ~AN: Unauthenticated calls return 401; authenticated without Origin returns 403;
    valid Origin succeeds.
    """
    app = plan_cleanup_setup["app"]
    SessionLocal = plan_cleanup_setup["SessionLocal"]
    settings = plan_cleanup_setup["settings"]

    with SessionLocal() as session:
        plan = BatchPlan(name="Security Plan", kind="dedupe", status="draft")
        session.add(plan)
        session.commit()
        p_id = plan.id

    # Unauthenticated client (no cookie)
    unauth = TestClient(app)
    unauth.headers.update({"Origin": "http://testserver"})

    # Case AJ: unauth single delete -> 401
    assert unauth.delete(f"/api/plans/{p_id}").status_code == 401
    # Case AK: unauth clear history -> 401
    assert unauth.post("/api/plans/clear-history", json={"statuses": ["completed"]}).status_code == 401
    # Case AL: unauth legacy clear -> 401
    assert unauth.post("/api/plans/legacy/clear", json={}).status_code == 401

    # Authenticated client without Origin
    auth_no_origin = TestClient(app)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        _, token = create_session(session, user_id=user.id, max_age_seconds=86400)
        session.commit()
    auth_no_origin.cookies.set(settings.session_cookie_name, token)

    # Case AM: missing Origin on state-changing request -> 403
    assert auth_no_origin.delete(f"/api/plans/{p_id}").status_code == 403
    assert auth_no_origin.post("/api/plans/clear-history", json={"statuses": ["completed"]}).status_code == 403
    assert auth_no_origin.post("/api/plans/legacy/clear", json={}).status_code == 403

    # Case AN: valid Origin -> normal response
    auth_valid = TestClient(app)
    auth_valid.headers.update({"Origin": "http://testserver"})
    auth_valid.cookies.set(settings.session_cookie_name, token)
    assert auth_valid.delete(f"/api/plans/{p_id}").status_code == 200

