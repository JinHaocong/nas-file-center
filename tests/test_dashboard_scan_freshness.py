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
from app.models import DuplicateFile, DuplicateGroup, ScanJob, User, utcnow


@pytest.fixture
def dashboard_setup(tmp_path: Path):
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
    }


def test_dashboard_uses_latest_completed_scan_not_all_historical_groups(dashboard_setup):
    """RED test: In fixed6 baseline, duplicate_group_count is COUNT(DuplicateGroup.id)
    which accumulates across all historical scans (10 + 12 = 22).
    In fixed7, duplicate_group_count must reflect the latest completed scan (12 groups),
    and provide latest_scan_id, latest_scan_name, latest_scan_finished_at.
    """
    client = dashboard_setup["client"]
    SessionLocal = dashboard_setup["SessionLocal"]
    service = dashboard_setup["service"]

    with SessionLocal() as session:
        # Scan 1: completed, 10 groups, reclaimable = 1000
        scan1 = ScanJob(
            name="Scan #1",
            status="completed",
            roots_json=json.dumps(["/data"]),
            total_groups=10,
            reclaimable_bytes=1000,
            finished_at=utcnow(),
        )
        session.add(scan1)
        session.flush()

        for i in range(10):
            grp = DuplicateGroup(
                scan_job_id=scan1.id,
                content_hash=f"hash1_{i}",
                file_size=100,
                member_count=2,
            )
            session.add(grp)

        # Scan 2: completed, 12 groups, reclaimable = 2500
        scan2 = ScanJob(
            name="Scan #2",
            status="completed",
            roots_json=json.dumps(["/data"]),
            total_groups=12,
            reclaimable_bytes=2500,
            finished_at=utcnow(),
        )
        session.add(scan2)
        session.flush()

        for i in range(12):
            grp = DuplicateGroup(
                scan_job_id=scan2.id,
                content_hash=f"hash2_{i}",
                file_size=200,
                member_count=2,
            )
            session.add(grp)

        session.commit()
        scan2_id = scan2.id

    # Check via direct service call
    summary = service.dashboard_summary()

    # In fixed6: summary["duplicate_group_count"] == 22 (FAIL)
    # In fixed7: summary["duplicate_group_count"] == 12 (PASS)
    assert summary["duplicate_group_count"] == 12, (
        f"Expected latest scan group count (12), but got historical accumulated {summary['duplicate_group_count']}"
    )
    assert summary["latest_reclaimable_bytes"] == 2500
    assert summary["latest_scan_id"] == scan2_id
    assert summary["latest_scan_name"] == "Scan #2"
    assert summary["latest_scan_finished_at"] is not None

    # Check via HTTP GET /api/dashboard/summary
    resp = client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    api_summary = resp.json()
    assert api_summary["duplicate_group_count"] == 12
    assert api_summary["latest_reclaimable_bytes"] == 2500
    assert api_summary["latest_scan_id"] == scan2_id
    assert api_summary["latest_scan_name"] == "Scan #2"
    assert api_summary["latest_scan_finished_at"] is not None


def test_dashboard_zero_completed_scans(dashboard_setup):
    """When no scans or no completed scans exist, return 0s and Nones."""
    client = dashboard_setup["client"]
    service = dashboard_setup["service"]

    summary = service.dashboard_summary()
    assert summary["duplicate_group_count"] == 0
    assert summary["latest_reclaimable_bytes"] == 0
    assert summary["latest_scan_id"] is None
    assert summary["latest_scan_name"] is None
    assert summary["latest_scan_finished_at"] is None

    resp = client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["duplicate_group_count"] == 0
    assert data["latest_reclaimable_bytes"] == 0
    assert data["latest_scan_id"] is None
    assert data["latest_scan_name"] is None
    assert data["latest_scan_finished_at"] is None


def test_dashboard_ignores_failed_or_running_newer_scans(dashboard_setup):
    """If a newer scan is running or failed, dashboard snapshot stays on the latest COMPLETED scan."""
    client = dashboard_setup["client"]
    SessionLocal = dashboard_setup["SessionLocal"]
    service = dashboard_setup["service"]

    with SessionLocal() as session:
        completed_scan = ScanJob(
            name="Good Scan",
            status="completed",
            roots_json=json.dumps(["/data"]),
            total_groups=5,
            reclaimable_bytes=500,
            finished_at=utcnow(),
        )
        session.add(completed_scan)
        session.flush()

        failed_scan = ScanJob(
            name="Failed Scan",
            status="failed",
            roots_json=json.dumps(["/data"]),
            total_groups=99,
            reclaimable_bytes=9999,
            finished_at=utcnow(),
        )
        session.add(failed_scan)

        running_scan = ScanJob(
            name="Running Scan",
            status="running",
            roots_json=json.dumps(["/data"]),
            total_groups=88,
            reclaimable_bytes=8888,
        )
        session.add(running_scan)
        session.commit()
        good_id = completed_scan.id

    summary = service.dashboard_summary()
    assert summary["duplicate_group_count"] == 5
    assert summary["latest_reclaimable_bytes"] == 500
    assert summary["latest_scan_id"] == good_id
    assert summary["latest_scan_name"] == "Good Scan"

    resp = client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["duplicate_group_count"] == 5
    assert data["latest_reclaimable_bytes"] == 500
    assert data["latest_scan_id"] == good_id


def test_dashboard_fallback_when_latest_scan_deleted(dashboard_setup):
    """When latest completed scan is deleted, dashboard falls back to previous completed scan."""
    client = dashboard_setup["client"]
    SessionLocal = dashboard_setup["SessionLocal"]
    service = dashboard_setup["service"]

    with SessionLocal() as session:
        scan1 = ScanJob(
            name="Old Scan",
            status="completed",
            roots_json=json.dumps(["/data"]),
            total_groups=3,
            reclaimable_bytes=300,
            finished_at=utcnow(),
        )
        session.add(scan1)
        session.flush()

        scan2 = ScanJob(
            name="New Scan",
            status="completed",
            roots_json=json.dumps(["/data"]),
            total_groups=8,
            reclaimable_bytes=800,
            finished_at=utcnow(),
        )
        session.add(scan2)
        session.commit()
        s1_id = scan1.id
        s2_id = scan2.id

    # Currently pointing to scan2
    assert service.dashboard_summary()["latest_scan_id"] == s2_id

    # Delete scan2
    del_resp = client.delete(f"/api/scans/{s2_id}")
    assert del_resp.status_code == 200

    # Now falls back to scan1
    summary = service.dashboard_summary()
    assert summary["duplicate_group_count"] == 3
    assert summary["latest_reclaimable_bytes"] == 300
    assert summary["latest_scan_id"] == s1_id
    assert summary["latest_scan_name"] == "Old Scan"

    # Delete scan1
    del_resp2 = client.delete(f"/api/scans/{s1_id}")
    assert del_resp2.status_code == 200

    # Now falls back to 0/None
    summary_empty = service.dashboard_summary()
    assert summary_empty["duplicate_group_count"] == 0
    assert summary_empty["latest_reclaimable_bytes"] == 0
    assert summary_empty["latest_scan_id"] is None

