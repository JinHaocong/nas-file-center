from __future__ import annotations

import json
from pathlib import Path
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import create_engine_and_session
from app.main import create_app
from app.models import ScanJob, WorkJob
from app.worker import process_work_job


def test_scan_detail_and_worker_timestamps(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    # Create dummy files
    (data / "file1.txt").write_text("content 1")
    (data / "file2.txt").write_text("content 2")

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})

    # 1. Enqueue index job
    idx_resp = client.post("/api/indexes", json={"root": str(data)})
    assert idx_resp.status_code == 200
    work_id = idx_resp.json()["work_job_id"]

    # Process index job with worker
    process_work_job(settings, work_id)

    # Verify work job timestamps
    job_resp = client.get(f"/api/work-jobs/{work_id}")
    assert job_resp.status_code == 200
    job_data = job_resp.json()
    assert job_data["status"] == "completed"
    assert job_data["created_at"] is not None
    assert job_data["started_at"] is not None
    assert job_data["finished_at"] is not None

    # 2. Enqueue scan job
    scan_resp = client.post(
        "/api/scans",
        json={"name": "Timestamp Test Scan", "roots": [str(data)]},
    )
    assert scan_resp.status_code == 200
    scan_id = scan_resp.json()["scan_job_id"]
    scan_work_id = scan_resp.json()["work_job_id"]

    # Check scan detail in queued state
    scan_detail_queued = client.get(f"/api/scans/{scan_id}").json()
    assert scan_detail_queued["status"] == "queued"
    assert scan_detail_queued["created_at"] is not None
    assert scan_detail_queued["started_at"] is None
    assert scan_detail_queued["finished_at"] is None

    # Process scan job with worker (or simulate fclones failure if binary not present)
    try:
        process_work_job(settings, scan_work_id)
    except Exception:
        pass

    # Check scan detail and work job after execution
    scan_detail_after = client.get(f"/api/scans/{scan_id}").json()
    assert scan_detail_after["created_at"] is not None
    assert scan_detail_after["started_at"] is not None
    assert scan_detail_after["finished_at"] is not None

    scan_work_after = client.get(f"/api/work-jobs/{scan_work_id}").json()
    assert scan_work_after["created_at"] is not None
    assert scan_work_after["started_at"] is not None
    assert scan_work_after["finished_at"] is not None
