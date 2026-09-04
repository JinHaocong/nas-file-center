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
from app.models import BatchPlan, DuplicateFile, DuplicateGroup, Plan, ScanJob, User, utcnow


@pytest.fixture
def scan_lifecycle_setup(tmp_path: Path):
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


def test_red_scan_delete_plan_dependency_safety_blocks_cascade(scan_lifecycle_setup):
    """RED test: Deleting a ScanJob that has an associated Plan or BatchPlan
    must be blocked with 409 Conflict to prevent cascade deletion or dangling plans.
    In fixed6 baseline, DELETE /api/scans/{id} endpoint does not exist (405 Method Not Allowed),
    and service.delete_scan does not exist.
    """
    client = scan_lifecycle_setup["client"]
    SessionLocal = scan_lifecycle_setup["SessionLocal"]

    with SessionLocal() as session:
        scan = ScanJob(
            name="Scan with Plan",
            status="completed",
            roots_json=json.dumps(["/data"]),
            total_groups=1,
            reclaimable_bytes=100,
            finished_at=utcnow(),
        )
        session.add(scan)
        session.flush()
        scan_id = scan.id

        # Associate a legacy Plan
        plan = Plan(scan_job_id=scan_id, policy="balanced-roots", status="draft")
        session.add(plan)

        # Associate a BatchPlan with scan_job_id in metadata_json
        bplan = BatchPlan(
            name=f"scan-{scan_id}-balanced-roots",
            kind="dedupe",
            status="draft",
            metadata_json=json.dumps({"scan_job_id": scan_id, "policy": "balanced-roots"}),
        )
        session.add(bplan)
        session.commit()
        plan_id = plan.id
        bplan_id = bplan.id

    resp = client.delete(f"/api/scans/{scan_id}")
    assert resp.status_code == 409, f"Expected 409 Conflict, got {resp.status_code}"
    assert "该扫描已生成关联计划，请先处理相关计划后再删除扫描记录。" in resp.json()["detail"]

    # Verify both plans and scan are preserved
    with SessionLocal() as session:
        assert session.get(ScanJob, scan_id) is not None
        assert session.get(Plan, plan_id) is not None
        assert session.get(BatchPlan, bplan_id) is not None


def test_delete_completed_scan_success_and_cleans_groups_and_files(scan_lifecycle_setup):
    """Deleting a completed scan cleans ScanJob, DuplicateGroup, and DuplicateFile without leaving orphans."""
    client = scan_lifecycle_setup["client"]
    SessionLocal = scan_lifecycle_setup["SessionLocal"]

    with SessionLocal() as session:
        scan = ScanJob(
            name="Orphan-free Scan",
            status="completed",
            roots_json=json.dumps(["/data"]),
            total_groups=1,
            reclaimable_bytes=500,
            finished_at=utcnow(),
        )
        session.add(scan)
        session.flush()
        s_id = scan.id

        grp = DuplicateGroup(
            scan_job_id=s_id,
            content_hash="clean_hash",
            file_size=250,
            member_count=2,
        )
        session.add(grp)
        session.flush()
        g_id = grp.id

        f1 = DuplicateFile(
            group_id=g_id,
            root_id=1,
            absolute_path="/data/a.txt",
            relative_path="a.txt",
            top_level_dir="data",
            size=250,
        )
        f2 = DuplicateFile(
            group_id=g_id,
            root_id=1,
            absolute_path="/data/b.txt",
            relative_path="b.txt",
            top_level_dir="data",
            size=250,
        )
        session.add_all([f1, f2])
        session.commit()

    resp = client.delete(f"/api/scans/{s_id}")
    assert resp.status_code == 200
    assert resp.json() == {"deleted": True, "id": s_id}

    with SessionLocal() as session:
        assert session.get(ScanJob, s_id) is None
        assert session.get(DuplicateGroup, g_id) is None
        assert session.scalars(select(DuplicateFile).where(DuplicateFile.group_id == g_id)).all() == []


def test_delete_failed_and_cancelled_scans(scan_lifecycle_setup):
    """Terminal scans (failed, cancelled) can be safely deleted."""
    client = scan_lifecycle_setup["client"]
    SessionLocal = scan_lifecycle_setup["SessionLocal"]

    with SessionLocal() as session:
        scan_failed = ScanJob(
            name="Failed Scan",
            status="failed",
            roots_json=json.dumps(["/data"]),
        )
        scan_cancelled = ScanJob(
            name="Cancelled Scan",
            status="cancelled",
            roots_json=json.dumps(["/data"]),
        )
        session.add_all([scan_failed, scan_cancelled])
        session.commit()
        failed_id = scan_failed.id
        cancelled_id = scan_cancelled.id

    assert client.delete(f"/api/scans/{failed_id}").status_code == 200
    assert client.delete(f"/api/scans/{cancelled_id}").status_code == 200

    with SessionLocal() as session:
        assert session.get(ScanJob, failed_id) is None
        assert session.get(ScanJob, cancelled_id) is None


def test_delete_active_scans_rejected(scan_lifecycle_setup):
    """Active scans (queued, running) cannot be deleted."""
    client = scan_lifecycle_setup["client"]
    SessionLocal = scan_lifecycle_setup["SessionLocal"]

    with SessionLocal() as session:
        scan_queued = ScanJob(name="Queued Scan", status="queued", roots_json=json.dumps(["/data"]))
        scan_running = ScanJob(name="Running Scan", status="running", roots_json=json.dumps(["/data"]))
        session.add_all([scan_queued, scan_running])
        session.commit()
        q_id = scan_queued.id
        r_id = scan_running.id

    resp_q = client.delete(f"/api/scans/{q_id}")
    assert resp_q.status_code == 409
    assert "Only terminal scans can be deleted" in resp_q.json()["detail"]

    resp_r = client.delete(f"/api/scans/{r_id}")
    assert resp_r.status_code == 409
    assert "Only terminal scans can be deleted" in resp_r.json()["detail"]

    with SessionLocal() as session:
        assert session.get(ScanJob, q_id) is not None
        assert session.get(ScanJob, r_id) is not None


def test_delete_nonexistent_scan_returns_404(scan_lifecycle_setup):
    """Deleting a non-existent scan returns 404."""
    client = scan_lifecycle_setup["client"]
    resp = client.delete("/api/scans/999999")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Scan not found"


def test_delete_scan_preserves_workjob_and_audit(scan_lifecycle_setup):
    """Deleting a scan must NOT delete background WorkJob or AuditEvent records."""
    client = scan_lifecycle_setup["client"]
    SessionLocal = scan_lifecycle_setup["SessionLocal"]
    from app.models import AuditEvent, WorkJob

    with SessionLocal() as session:
        scan = ScanJob(name="Scan With Task", status="completed", roots_json=json.dumps(["/data"]))
        session.add(scan)
        session.flush()
        s_id = scan.id

        wj = WorkJob(
            kind="fclones-scan",
            status="completed",
            state_json=json.dumps({"scan_job_id": s_id}),
        )
        audit = AuditEvent(
            operation="scan.create",
            path="/data",
            result="success",
            details_json=json.dumps({"name": "Scan With Task"}),
        )
        session.add_all([wj, audit])
        session.commit()
        wj_id = wj.id
        audit_id = audit.id

    resp = client.delete(f"/api/scans/{s_id}")
    assert resp.status_code == 200

    with SessionLocal() as session:
        assert session.get(ScanJob, s_id) is None
        assert session.get(WorkJob, wj_id) is not None
        assert session.get(AuditEvent, audit_id) is not None


def test_delete_scan_auth_and_csrf_protection(scan_lifecycle_setup):
    """Scan deletion requires valid auth and CSRF/Origin."""
    app = scan_lifecycle_setup["app"]
    SessionLocal = scan_lifecycle_setup["SessionLocal"]
    settings = scan_lifecycle_setup["settings"]

    with SessionLocal() as session:
        scan = ScanJob(name="Protected Scan", status="completed", roots_json=json.dumps(["/data"]))
        session.add(scan)
        session.commit()
        s_id = scan.id

    # Unauthenticated client
    unauth_client = TestClient(app)
    unauth_client.headers.update({"Origin": "http://testserver"})
    resp_unauth = unauth_client.delete(f"/api/scans/{s_id}")
    assert resp_unauth.status_code == 401

    # Authenticated but missing / invalid Origin
    auth_client = TestClient(app)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == "admin"))
        _, token = create_session(session, user_id=user.id, max_age_seconds=86400)
        session.commit()
    auth_client.cookies.set(settings.session_cookie_name, token)

    # Missing Origin header on state-changing request
    resp_no_origin = auth_client.delete(f"/api/scans/{s_id}")
    assert resp_no_origin.status_code == 403


def test_list_scans_and_scan_detail_has_dependent_plan(scan_lifecycle_setup):
    """list_scans and scan_detail accurately expose has_dependent_plan."""
    client = scan_lifecycle_setup["client"]
    SessionLocal = scan_lifecycle_setup["SessionLocal"]

    with SessionLocal() as session:
        # Scan 1 has no plan
        scan_free = ScanJob(name="Free Scan", status="completed", roots_json=json.dumps(["/data"]))
        session.add(scan_free)
        session.flush()
        free_id = scan_free.id

        # Scan 2 has legacy plan
        scan_legacy = ScanJob(name="Legacy Plan Scan", status="completed", roots_json=json.dumps(["/data"]))
        session.add(scan_legacy)
        session.flush()
        legacy_id = scan_legacy.id
        p1 = Plan(scan_job_id=legacy_id, policy="keep-first", status="draft")
        session.add(p1)

        # Scan 3 has batch plan
        scan_batch = ScanJob(name="Batch Plan Scan", status="completed", roots_json=json.dumps(["/data"]))
        session.add(scan_batch)
        session.flush()
        batch_id = scan_batch.id
        bp = BatchPlan(
            name="bp-scan3",
            kind="dedupe",
            status="draft",
            metadata_json=json.dumps({"scan_job_id": batch_id}),
        )
        session.add(bp)
        session.commit()

    # Test list_scans
    resp_list = client.get("/api/scans")
    assert resp_list.status_code == 200
    items = {item["id"]: item for item in resp_list.json()["items"]}
    assert items[free_id]["has_dependent_plan"] is False
    assert items[legacy_id]["has_dependent_plan"] is True
    assert items[batch_id]["has_dependent_plan"] is True

    # Test scan_detail
    detail_free = client.get(f"/api/scans/{free_id}").json()
    assert detail_free["has_dependent_plan"] is False

    detail_legacy = client.get(f"/api/scans/{legacy_id}").json()
    assert detail_legacy["has_dependent_plan"] is True

    detail_batch = client.get(f"/api/scans/{batch_id}").json()
    assert detail_batch["has_dependent_plan"] is True


