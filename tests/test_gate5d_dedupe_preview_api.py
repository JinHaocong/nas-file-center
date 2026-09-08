from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, sessionmaker

from app.auth.password import hash_password
from app.config import Settings
from app.main import create_app
from app.models import (
    Base,
    DuplicateFile,
    DuplicateGroup,
    ScanJob,
    BatchPlan,
    BatchPlanItem,
    WorkJob,
    QuarantineEntry,
    User,
    utcnow,
)
from app.service import FileCenterService
import app.planning.dedupe_preview as dp_mod


@pytest.fixture
def api_test_env(tmp_path: Path):
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
        protect_last_file=True,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    service = FileCenterService(settings)

    # Add regular user
    with service.SessionLocal() as session:
        reg_user = User(
            username="normaluser",
            password_hash=hash_password("UserPassword123!"),
            is_active=True,
            role="user",
        )
        session.add(reg_user)
        session.commit()

    app = create_app(settings)
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"

    # Login as normal user
    login_resp = client.post(
        "/api/auth/login",
        json={"username": "normaluser", "password": "UserPassword123!"},
    )
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"

    return {
        "client": client,
        "settings": settings,
        "service": service,
        "SessionLocal": service.SessionLocal,
        "data_dir": data_dir,
        "quarantine_dir": quarantine_dir,
    }


def _create_completed_scan(
    session: Session,
    scan_id: int,
    roots: list[str],
    status: str = "completed",
) -> ScanJob:
    scan = ScanJob(
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
    session.add(scan)
    session.commit()
    return scan


# =========================================================================
# 1. AUTHENTICATION AND AUTHORIZATION
# =========================================================================

def test_preview_auth_required(api_test_env):
    """Calling dedupe-preview without auth must return 401."""
    settings = api_test_env["settings"]
    app = create_app(settings)
    unauth_client = TestClient(app)
    unauth_client.headers["Origin"] = "http://testserver"

    resp = unauth_client.post("/api/scans/1/dedupe-preview", json={})
    assert resp.status_code == 401


def test_preview_accessible_by_normal_user(api_test_env):
    """Normal authenticated user can access dedupe-preview (not admin-restricted)."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=1, roots=[str(data_dir)])

    resp = client.post("/api/scans/1/dedupe-preview", json={})
    assert resp.status_code == 200


# =========================================================================
# 2. SCAN AUTHORITY & STATUS ERRORS
# =========================================================================

def test_scan_not_found_returns_404(api_test_env):
    """Non-existent scan job must return 404 with DEDUPE_SCAN_NOT_FOUND."""
    client = api_test_env["client"]
    resp = client.post("/api/scans/99999/dedupe-preview", json={})
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "DEDUPE_SCAN_NOT_FOUND"


def test_scan_not_completed_returns_409(api_test_env):
    """Scan job not in completed status must return 409 with DEDUPE_SCAN_NOT_COMPLETED."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=2, roots=[str(data_dir)], status="running")

    resp = client.post("/api/scans/2/dedupe-preview", json={})
    assert resp.status_code == 409
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "DEDUPE_SCAN_NOT_COMPLETED"


# =========================================================================
# 3. SCORER CONFIG VALIDATION & RESERVED FACTORS (422)
# =========================================================================

def test_reserved_factor_unavailable_returns_422(api_test_env):
    """Reserved factors like resolution/bitrate must return 422 with DEDUPE_FACTOR_UNAVAILABLE."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=3, roots=[str(data_dir)])

    for factor in ["resolution", "bitrate", "codec", "audio_channels"]:
        resp = client.post(
            "/api/scans/3/dedupe-preview",
            json={"scorer_config": {"factors": {factor: {"weight": 10}}}},
        )
        assert resp.status_code == 422
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "DEDUPE_FACTOR_UNAVAILABLE"


def test_invalid_scorer_config_returns_422(api_test_env):
    """Invalid scorer config (unknown factor, boolean weight, extra fields) returns 422 with DEDUPE_INVALID_CONFIG."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=4, roots=[str(data_dir)])

    # Unknown factor
    resp1 = client.post(
        "/api/scans/4/dedupe-preview",
        json={"scorer_config": {"factors": {"non_existent_factor": {"weight": 10}}}},
    )
    assert resp1.status_code == 422
    assert resp1.json()["error"]["code"] == "DEDUPE_INVALID_CONFIG"

    # Boolean weight
    resp2 = client.post(
        "/api/scans/4/dedupe-preview",
        json={"scorer_config": {"factors": {"path_priority": {"enabled": True, "weight": True}}}},
    )
    assert resp2.status_code == 422
    assert resp2.json()["error"]["code"] == "DEDUPE_INVALID_CONFIG"

    # Invalid selection_mode
    resp3 = client.post(
        "/api/scans/4/dedupe-preview",
        json={"scorer_config": {"selection_mode": "invalid_mode"}},
    )
    assert resp3.status_code == 422
    assert resp3.json()["error"]["code"] == "DEDUPE_INVALID_CONFIG"


# =========================================================================
# 4. PAGINATION PARAMETER VALIDATION (422)
# =========================================================================

def test_pagination_validation_returns_422(api_test_env):
    """Invalid pagination parameters (<=0, >500, boolean) must return 422."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=5, roots=[str(data_dir)])

    # page <= 0
    resp = client.post("/api/scans/5/dedupe-preview", json={"page": 0})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] in {"DEDUPE_INVALID_CONFIG", "VALIDATION_ERROR"}

    resp = client.post("/api/scans/5/dedupe-preview", json={"page": -1})
    assert resp.status_code == 422

    # page is boolean
    resp = client.post("/api/scans/5/dedupe-preview", json={"page": True})
    assert resp.status_code == 422

    # page_size <= 0
    resp = client.post("/api/scans/5/dedupe-preview", json={"page_size": 0})
    assert resp.status_code == 422

    # page_size > 500
    resp = client.post("/api/scans/5/dedupe-preview", json={"page_size": 501})
    assert resp.status_code == 422

    # page_size is boolean
    resp = client.post("/api/scans/5/dedupe-preview", json={"page_size": True})
    assert resp.status_code == 422


# =========================================================================
# 5. PAGINATION FUNCTIONALITY & ROW STRUCTURE
# =========================================================================

def _setup_duplicate_test_data(session: Session, root: Path, scan_id: int):
    _create_completed_scan(session, scan_id=scan_id, roots=[str(root)])

    # Group 1: 3 files (100 bytes)
    g1 = DuplicateGroup(id=scan_id * 10 + 1, scan_job_id=scan_id, content_hash=f"hash_{scan_id}_1", file_size=100, member_count=3)
    session.add(g1)
    session.flush()
    f1_1 = root / f"g1_a_{scan_id}.jpg"
    f1_2 = root / f"g1_b_{scan_id}.jpg"
    f1_3 = root / f"g1_c_{scan_id}.jpg"
    for f in [f1_1, f1_2, f1_3]:
        f.write_bytes(b"x" * 100)
    session.add(DuplicateFile(group_id=g1.id, root_id=0, absolute_path=str(f1_1), relative_path=f1_1.name, top_level_dir=str(root), size=100, mtime_ns=1000))
    session.add(DuplicateFile(group_id=g1.id, root_id=0, absolute_path=str(f1_2), relative_path=f1_2.name, top_level_dir=str(root), size=100, mtime_ns=2000))
    session.add(DuplicateFile(group_id=g1.id, root_id=0, absolute_path=str(f1_3), relative_path=f1_3.name, top_level_dir=str(root), size=100, mtime_ns=3000))

    # Group 2: 2 files (200 bytes)
    g2 = DuplicateGroup(id=scan_id * 10 + 2, scan_job_id=scan_id, content_hash=f"hash_{scan_id}_2", file_size=200, member_count=2)
    session.add(g2)
    session.flush()
    f2_1 = root / f"g2_a_{scan_id}.png"
    f2_2 = root / f"g2_b_{scan_id}.png"
    for f in [f2_1, f2_2]:
        f.write_bytes(b"y" * 200)
    session.add(DuplicateFile(group_id=g2.id, root_id=0, absolute_path=str(f2_1), relative_path=f2_1.name, top_level_dir=str(root), size=200, mtime_ns=4000))
    session.add(DuplicateFile(group_id=g2.id, root_id=0, absolute_path=str(f2_2), relative_path=f2_2.name, top_level_dir=str(root), size=200, mtime_ns=5000))

    # Group 3: 2 files (50 bytes)
    g3 = DuplicateGroup(id=scan_id * 10 + 3, scan_job_id=scan_id, content_hash=f"hash_{scan_id}_3", file_size=50, member_count=2)
    session.add(g3)
    session.flush()
    f3_1 = root / f"g3_a_{scan_id}.txt"
    f3_2 = root / f"g3_b_{scan_id}.txt"
    for f in [f3_1, f3_2]:
        f.write_bytes(b"z" * 50)
    session.add(DuplicateFile(group_id=g3.id, root_id=0, absolute_path=str(f3_1), relative_path=f3_1.name, top_level_dir=str(root), size=50, mtime_ns=6000))
    session.add(DuplicateFile(group_id=g3.id, root_id=0, absolute_path=str(f3_2), relative_path=f3_2.name, top_level_dir=str(root), size=50, mtime_ns=7000))

    session.commit()


def test_pagination_and_member_row_structure(api_test_env):
    """Verify pagination math and complete member row structure."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=10)

    # 1. Full page fetch (default page=1, page_size=50)
    resp = client.post("/api/scans/10/dedupe-preview", json={})
    assert resp.status_code == 200
    body = resp.json()

    assert body["scan_job_id"] == 10
    assert body["total_rows"] == 7
    assert body["total_pages"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert len(body["rows"]) == 7

    # Check top-level summary
    summary = body["summary"]
    assert summary["actionable_group_count"] == 3
    assert summary["skipped_group_count"] == 0
    assert summary["planned_quarantine_count"] == 4  # (3-1) + (2-1) + (2-1) = 4
    assert summary["expected_reclaim_bytes"] == (2 * 100) + (1 * 200) + (1 * 50)

    # Verify first row structure
    row = body["rows"][0]
    required_keys = {
        "group_provenance_id",
        "group_status",
        "group_skip_reason",
        "group_file_size",
        "absolute_path",
        "relative_path",
        "scan_root_index",
        "scan_root_path",
        "eligible_as_keep",
        "safety_reasons",
        "total_score",
        "contributions",
        "is_top_candidate",
        "recommended_keep",
        "member_decision",
        "selection_reason",
        "balance_info",
    }
    assert required_keys.issubset(row.keys()), f"Missing keys: {required_keys - set(row.keys())}"
    assert row["member_decision"] in {"KEEP", "QUARANTINE", "SKIPPED"}

    # 2. Paging with page_size=3 (7 rows -> 3 pages: 3, 3, 1)
    p1 = client.post("/api/scans/10/dedupe-preview", json={"page": 1, "page_size": 3}).json()
    assert p1["page"] == 1
    assert p1["page_size"] == 3
    assert p1["total_rows"] == 7
    assert p1["total_pages"] == 3
    assert len(p1["rows"]) == 3

    p2 = client.post("/api/scans/10/dedupe-preview", json={"page": 2, "page_size": 3}).json()
    assert p2["page"] == 2
    assert len(p2["rows"]) == 3

    p3 = client.post("/api/scans/10/dedupe-preview", json={"page": 3, "page_size": 3}).json()
    assert p3["page"] == 3
    assert len(p3["rows"]) == 1

    # Verify concatenated rows match full fetch
    concatenated_paths = [r["absolute_path"] for r in p1["rows"] + p2["rows"] + p3["rows"]]
    full_paths = [r["absolute_path"] for r in body["rows"]]
    assert concatenated_paths == full_paths

    # 3. Out of bounds page: returns 200, rows=[]
    p4 = client.post("/api/scans/10/dedupe-preview", json={"page": 4, "page_size": 3})
    assert p4.status_code == 200
    p4_body = p4.json()
    assert p4_body["rows"] == []
    assert p4_body["total_rows"] == 7
    assert p4_body["total_pages"] == 3
    assert p4_body["page"] == 4


# =========================================================================
# 6. PREVIEW DIGEST INVARIANCE & SENSITIVITY
# =========================================================================

def test_preview_digest_invariance_across_pagination(api_test_env):
    """preview_digest must be strictly identical regardless of page or page_size."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=20)

    res_p1 = client.post("/api/scans/20/dedupe-preview", json={"page": 1, "page_size": 2}).json()
    res_p2 = client.post("/api/scans/20/dedupe-preview", json={"page": 2, "page_size": 2}).json()
    res_p3 = client.post("/api/scans/20/dedupe-preview", json={"page": 1, "page_size": 50}).json()
    res_out = client.post("/api/scans/20/dedupe-preview", json={"page": 99, "page_size": 50}).json()

    # All digests must be identical across pages
    assert res_p1["preview_digest"] == res_p2["preview_digest"] == res_p3["preview_digest"] == res_out["preview_digest"]
    assert res_p1["scorer_config_digest"] == res_p2["scorer_config_digest"] == res_p3["scorer_config_digest"]
    assert res_p1["source_snapshot_digest"] == res_p2["source_snapshot_digest"] == res_p3["source_snapshot_digest"]
    assert res_p1["decision_digest"] == res_p2["decision_digest"] == res_p3["decision_digest"]


def test_preview_digest_sensitivity_to_config(api_test_env):
    """Changing scorer config must change scorer_config_digest and preview_digest."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=30)

    cfg1 = {"scorer_config": {"factors": {"preferred_extension": {"enabled": True, "weight": 10, "extensions": ["jpg"]}}}}
    cfg2 = {"scorer_config": {"factors": {"preferred_extension": {"enabled": True, "weight": 20, "extensions": ["jpg"]}}}}

    res1 = client.post("/api/scans/30/dedupe-preview", json=cfg1).json()
    res2 = client.post("/api/scans/30/dedupe-preview", json=cfg2).json()

    assert res1["scorer_config_digest"] != res2["scorer_config_digest"]
    assert res1["preview_digest"] != res2["preview_digest"]


def test_preview_digest_sensitivity_to_filesystem_changes(api_test_env):
    """Modifying file on disk changes source_snapshot_digest and preview_digest."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=40)

    res1 = client.post("/api/scans/40/dedupe-preview", json={}).json()

    # Remove one duplicate file from disk -> triggers SOURCE_SNAPSHOT_STALE
    f_to_remove = data_dir / "g1_c_40.jpg"
    f_to_remove.unlink()

    res2 = client.post("/api/scans/40/dedupe-preview", json={}).json()

    assert res1["source_snapshot_digest"] != res2["source_snapshot_digest"]
    assert res1["preview_digest"] != res2["preview_digest"]
    # Group 1 should now be skipped
    assert res2["summary"]["skipped_group_count"] == 1


# =========================================================================
# 7. EXPLAIN SERIALIZATION & FACTOR BREAKDOWN
# =========================================================================

def test_explain_serialization_breakdown(api_test_env):
    """Contributions list in rows must be properly serialized with all fields."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=50)

    cfg = {
        "scorer_config": {
            "factors": {
                "preferred_extension": {"enabled": True, "weight": 50, "extensions": ["jpg"]},
                "mtime": {"mode": "newest", "weight": 30},
            }
        }
    }
    resp = client.post("/api/scans/50/dedupe-preview", json=cfg)
    assert resp.status_code == 200
    body = resp.json()

    # Find a jpg member row in group 1
    jpg_row = next(r for r in body["rows"] if r["absolute_path"].endswith(".jpg"))
    assert len(jpg_row["contributions"]) > 0
    c = jpg_row["contributions"][0]
    assert "factor" in c
    assert "configured_weight" in c
    assert "actual_contribution" in c
    assert "reason" in c


# =========================================================================
# 8. NO-MUTATION GUARANTEE
# =========================================================================

def test_zero_mutation_guarantee(api_test_env):
    """dedupe-preview must NEVER create BatchPlan, BatchPlanItem, WorkJob, QuarantineEntry or modify files."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=60)
        initial_plans = session.scalar(select(func.count(BatchPlan.id)))
        initial_items = session.scalar(select(func.count(BatchPlanItem.id)))
        initial_jobs = session.scalar(select(func.count(WorkJob.id)))
        initial_quarantine = session.scalar(select(func.count(QuarantineEntry.id)))

    # Record files on disk
    files_before = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in data_dir.glob("*")}

    # Call preview multiple times
    for _ in range(3):
        resp = client.post("/api/scans/60/dedupe-preview", json={"page": 1, "page_size": 2})
        assert resp.status_code == 200

    # Verify zero mutations
    with SessionLocal() as session:
        assert session.scalar(select(func.count(BatchPlan.id))) == initial_plans
        assert session.scalar(select(func.count(BatchPlanItem.id))) == initial_items
        assert session.scalar(select(func.count(WorkJob.id))) == initial_jobs
        assert session.scalar(select(func.count(QuarantineEntry.id))) == initial_quarantine

    files_after = {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in data_dir.glob("*")}
    assert files_before == files_after


# =========================================================================
# 9. LIMIT EXCEEDED (422)
# =========================================================================

def test_limit_exceeded_returns_422(api_test_env, monkeypatch):
    """Exceeding MAX_DEDUPE_CANDIDATES or MAX_PLANNED_QUARANTINE must return 422 with DEDUPE_LIMIT_EXCEEDED."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=70)

    # Monkeypatch candidate limit to 2 (we have 7 candidates)
    monkeypatch.setattr(dp_mod, "MAX_DEDUPE_CANDIDATES", 2)

    resp = client.post("/api/scans/70/dedupe-preview", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "DEDUPE_LIMIT_EXCEEDED"
