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
    """Invalid scorer config (unknown factor, boolean weight, typo fields) returns 422 with DEDUPE_INVALID_CONFIG."""
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

    # Top-level typo
    resp3 = client.post(
        "/api/scans/4/dedupe-preview",
        json={"scorer_config": {"selection_mod": "weighted"}},
    )
    assert resp3.status_code == 422
    assert resp3.json()["error"]["code"] == "DEDUPE_INVALID_CONFIG"

    # Inner factor field typo (e.g. weigth instead of weight)
    resp4 = client.post(
        "/api/scans/4/dedupe-preview",
        json={"scorer_config": {"factors": {"path_priority": {"enabled": True, "weigth": 10}}}},
    )
    assert resp4.status_code == 422
    assert resp4.json()["error"]["code"] == "DEDUPE_INVALID_CONFIG"


# =========================================================================
# 4. STRICT PAGINATION PARAMETER VALIDATION (422)
# =========================================================================

def test_strict_pagination_validation_returns_422(api_test_env):
    """Strict integer validation for page and page_size, rejecting 0, negative, bool, str, float, >500."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=5, roots=[str(data_dir)])

    invalid_cases = [
        {"page": 0},
        {"page": -1},
        {"page": True},
        {"page": "1"},
        {"page": 1.5},
        {"page_size": 0},
        {"page_size": -5},
        {"page_size": True},
        {"page_size": "50"},
        {"page_size": 50.0},
        {"page_size": 501},
    ]
    for case in invalid_cases:
        resp = client.post("/api/scans/5/dedupe-preview", json=case)
        assert resp.status_code == 422, f"Expected 422 for case {case}, got {resp.status_code}"
        assert resp.json()["error"]["code"] == "DEDUPE_INVALID_CONFIG", f"Failed error code for case {case}"

    # page_size=500 must be accepted
    resp_500 = client.post("/api/scans/5/dedupe-preview", json={"page_size": 500})
    assert resp_500.status_code == 200


# =========================================================================
# 5. PAGINATION SERVER CONTRACT & PARTITION SEQUENCE
# =========================================================================

def test_preview_pagination_server_contract(api_test_env):
    """Verify default page/size, member row required fields, 3+3+1 partition, and beyond-end 200 response."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=10)

    # 1. Default page=1, default page_size=50
    resp_def = client.post("/api/scans/10/dedupe-preview", json={})
    assert resp_def.status_code == 200
    body_def = resp_def.json()
    assert body_def["page"] == 1
    assert body_def["page_size"] == 50
    assert body_def["total_rows"] == 7
    assert len(body_def["rows"]) == 7

    # Verify all member row required fields
    required_row_fields = [
        "group_provenance_id", "group_status", "group_skip_reason", "group_file_size",
        "group_recommended_keep_path", "group_reclaimable_bytes", "group_selection_reason", "group_balance_info",
        "absolute_path", "relative_path", "scan_root_index", "scan_root_path",
        "eligible_as_keep", "safety_reasons", "total_score", "contributions",
        "is_top_candidate", "recommended_keep", "member_decision", "selection_reason", "balance_info",
    ]
    for row in body_def["rows"]:
        for field in required_row_fields:
            assert field in row, f"Missing required field {field} in row"

    # 2. Partition 3 + 3 + 1
    p1 = client.post("/api/scans/10/dedupe-preview", json={"page": 1, "page_size": 3}).json()
    assert p1["total_rows"] == 7
    assert p1["total_pages"] == 3
    assert p1["page"] == 1
    assert len(p1["rows"]) == 3

    p2 = client.post("/api/scans/10/dedupe-preview", json={"page": 2, "page_size": 3}).json()
    assert p2["total_rows"] == 7
    assert p2["total_pages"] == 3
    assert p2["page"] == 2
    assert len(p2["rows"]) == 3

    p3 = client.post("/api/scans/10/dedupe-preview", json={"page": 3, "page_size": 3}).json()
    assert p3["total_rows"] == 7
    assert p3["total_pages"] == 3
    assert p3["page"] == 3
    assert len(p3["rows"]) == 1

    # Concatenated rows match full fetch sequence deterministically
    concat_paths = [r["absolute_path"] for r in p1["rows"] + p2["rows"] + p3["rows"]]
    full_paths = [r["absolute_path"] for r in body_def["rows"]]
    assert concat_paths == full_paths

    # 3. Out of bounds page: returns 200, rows=[]
    p4 = client.post("/api/scans/10/dedupe-preview", json={"page": 4, "page_size": 3})
    assert p4.status_code == 200
    p4_body = p4.json()
    assert p4_body["rows"] == []
    assert p4_body["total_rows"] == 7
    assert p4_body["total_pages"] == 3
    assert p4_body["page"] == 4


# =========================================================================
# 6. GLOBAL SUMMARY & TRUTH MARKERS CONTRACT
# =========================================================================

def test_global_summary_and_truth_markers_contract(api_test_env):
    """Response must expose scan_roots, candidate_member_count, group_count, released_bytes_by_scan_root, truth markers."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=10)

    resp = client.post("/api/scans/10/dedupe-preview", json={})
    assert resp.status_code == 200
    body = resp.json()

    # Authoritative scan_roots
    assert body["scan_roots"] == [str(data_dir)]

    # Global counts
    assert body["group_count"] == 3
    assert body["candidate_member_count"] == 7
    assert body["actionable_group_count"] == 3
    assert body["skipped_group_count"] == 0
    assert body["planned_quarantine_count"] == 4
    assert body["expected_reclaim_bytes"] == 450

    # Truth markers
    assert body["preview_source"] == "completed-scan-readonly-safety"
    assert body["live_filesystem_verified"] is False
    assert body["dedupe_engine_version"] == 1

    # Released bytes by scan root: scan_root_index string keys for all scan roots
    assert body["released_bytes_by_scan_root"] == {"0": 450}

    # Effective safety policy
    assert body["effective_safety_policy"]["protect_last_file"] is True
    assert str(data_dir.resolve()) in body["effective_safety_policy"]["allowed_roots"]
    assert "quarantine_root" in body["effective_safety_policy"]

    # Summary object contract
    summary = body["summary"]
    assert summary["group_count"] == 3
    assert summary["candidate_member_count"] == 7
    assert summary["actionable_group_count"] == 3
    assert summary["skipped_group_count"] == 0
    assert summary["planned_quarantine_count"] == 4
    assert summary["expected_reclaim_bytes"] == 450
    assert summary["released_bytes_by_scan_root"] == {"0": 450}


# =========================================================================
# 7. PAGE-LOCAL GROUP EXPLAIN & QUARANTINE EXPLAIN
# =========================================================================

def test_page_local_group_explain_on_every_row(api_test_env):
    """Every member row (even with page_size=1) must explain its group."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=11)

    p1 = client.post("/api/scans/11/dedupe-preview", json={"page": 1, "page_size": 1}).json()
    assert len(p1["rows"]) == 1
    row = p1["rows"][0]

    assert "group_recommended_keep_path" in row
    assert "group_reclaimable_bytes" in row
    assert "group_selection_reason" in row
    assert "group_balance_info" in row

    assert row["group_reclaimable_bytes"] > 0
    assert row["group_recommended_keep_path"] is not None
    assert row["group_selection_reason"] is not None


def test_page_local_quarantine_explain(api_test_env):
    """In an actionable group, a QUARANTINE member row on its own isolated page must explain its group."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=12)

    # Fetch with page_size=1 and iterate until finding the QUARANTINE row
    quarantine_page = None
    for p in range(1, 8):
        resp = client.post("/api/scans/12/dedupe-preview", json={"page": p, "page_size": 1}).json()
        assert len(resp["rows"]) == 1
        if resp["rows"][0]["member_decision"] == "QUARANTINE":
            quarantine_page = resp
            break

    assert quarantine_page is not None, "Could not find a QUARANTINE row across pages"
    q_row = quarantine_page["rows"][0]

    # Verify self-contained explanation on this isolated page
    assert q_row["group_status"] == "actionable"
    assert q_row["group_recommended_keep_path"] is not None
    assert q_row["group_recommended_keep_path"] != q_row["absolute_path"]
    assert q_row["group_reclaimable_bytes"] > 0
    assert q_row["group_selection_reason"] is not None


def test_balanced_by_bytes_page_local_explain(api_test_env, tmp_path: Path):
    """With selection_mode=balanced_by_bytes, balancer tie-breaking is recorded in group context on QUARANTINE row."""
    client = api_test_env["client"]
    service = api_test_env["service"]
    SessionLocal = api_test_env["SessionLocal"]

    root0 = tmp_path / "root0"
    root1 = tmp_path / "root1"
    root0.mkdir()
    root1.mkdir()

    # Add extra files in both roots so protect_last_file allows either candidate to be quarantined
    for i in range(5):
        (root0 / f"extra_{i}.txt").write_text("extra")
        (root1 / f"extra_{i}.txt").write_text("extra")

    orig_allowed = service.settings.allowed_roots_raw
    service.settings.allowed_roots_raw = f"{orig_allowed},{root0},{root1}"

    # Group 1: 2 files in root0 (1000 bytes each). Keeping one releases 1000 bytes in root0.
    f1_a = root0 / "g1_a.bin"
    f1_b = root0 / "g1_b.bin"
    f1_a.write_bytes(b"1" * 1000)
    f1_b.write_bytes(b"1" * 1000)

    # Group 2: 1 file in root0, 1 file in root1 (1000 bytes each).
    # Since root0 has already released 1000 bytes, keeping f2_root0 causes f2_root1 to be deleted,
    # releasing 1000 in root1 -> spread becomes |1000 - 1000| = 0.
    # If f2_root1 was kept, root0 would release another 1000 -> root0 released = 2000, root1 = 0 -> spread = 2000.
    # Therefore, balancer chooses f2_root0 as keeper! f2_root1 is QUARANTINE with group_selection_reason="balanced_by_bytes".
    f2_root0 = root0 / "g2_r0.bin"
    f2_root1 = root1 / "g2_r1.bin"
    f2_root0.write_bytes(b"2" * 1000)
    f2_root1.write_bytes(b"2" * 1000)

    scan_id = 15
    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=scan_id, roots=[str(root0), str(root1)])

        # Group 1 (file_size=1000)
        g1 = DuplicateGroup(id=151, scan_job_id=scan_id, content_hash="hash_b1", file_size=1000, member_count=2)
        session.add(g1)
        session.flush()
        session.add(DuplicateFile(group_id=g1.id, root_id=0, absolute_path=str(f1_a), relative_path=f1_a.name, top_level_dir=str(root0), size=1000, mtime_ns=1000))
        session.add(DuplicateFile(group_id=g1.id, root_id=0, absolute_path=str(f1_b), relative_path=f1_b.name, top_level_dir=str(root0), size=1000, mtime_ns=2000))

        # Group 2 (file_size=1000)
        g2 = DuplicateGroup(id=152, scan_job_id=scan_id, content_hash="hash_b2", file_size=1000, member_count=2)
        session.add(g2)
        session.flush()
        session.add(DuplicateFile(group_id=g2.id, root_id=0, absolute_path=str(f2_root0), relative_path=f2_root0.name, top_level_dir=str(root0), size=1000, mtime_ns=3000))
        session.add(DuplicateFile(group_id=g2.id, root_id=1, absolute_path=str(f2_root1), relative_path=f2_root1.name, top_level_dir=str(root1), size=1000, mtime_ns=4000))

        session.commit()

    cfg = {"scorer_config": {"selection_mode": "balanced_by_bytes"}}

    # Fetch all rows with page_size=1 to find the QUARANTINE row of Group 2 (f2_root1)
    target_row = None
    for p in range(1, 5):
        resp = client.post(f"/api/scans/{scan_id}/dedupe-preview", json={**cfg, "page": p, "page_size": 1}).json()
        assert len(resp["rows"]) == 1
        r = resp["rows"][0]
        if r["absolute_path"] == str(f2_root1):
            target_row = r
            break

    assert target_row is not None, "Target quarantine row f2_root1 not found"
    assert target_row["member_decision"] == "QUARANTINE"
    assert target_row["group_selection_reason"] == "balanced_by_bytes"
    assert target_row["group_balance_info"] is not None
    assert "spread_before" in target_row["group_balance_info"]
    assert "spread_after" in target_row["group_balance_info"]
    assert target_row["group_balance_info"]["spread_after"] < target_row["group_balance_info"]["spread_before"]

    # Verify balancer info is group context, NOT in contributions
    contrib_factors = [c["factor"] for c in target_row["contributions"]]
    assert "balanced_by_bytes" not in contrib_factors
    assert "balance" not in contrib_factors


# =========================================================================
# 8. MISSING MEMBER API EXPLAIN
# =========================================================================

def test_missing_member_api_explain(api_test_env):
    """API response for a missing file must mark eligible_as_keep=False, member_decision=SKIPPED, safety_reasons with SOURCE_NOT_FOUND."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    # Create 1 existing file, 1 missing file
    f_real = data_dir / "real_file.txt"
    f_real.write_text("existing")
    f_missing = data_dir / "nonexistent_file.txt"

    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=82, roots=[str(data_dir)])
        g = DuplicateGroup(id=821, scan_job_id=82, content_hash="hash_missing_mem", file_size=8, member_count=2)
        session.add(g)
        session.flush()
        session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_real), relative_path=f_real.name, top_level_dir=str(data_dir), size=8, mtime_ns=1000))
        session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_missing), relative_path=f_missing.name, top_level_dir=str(data_dir), size=8, mtime_ns=2000))
        session.commit()

    resp = client.post("/api/scans/82/dedupe-preview", json={})
    assert resp.status_code == 200
    body = resp.json()

    assert body["skipped_group_count"] == 1
    assert body["actionable_group_count"] == 0

    missing_row = next(r for r in body["rows"] if r["absolute_path"] == str(f_missing))
    assert missing_row["eligible_as_keep"] is False
    assert missing_row["member_decision"] == "SKIPPED"
    assert "SOURCE_NOT_FOUND" in missing_row["safety_reasons"]
    assert missing_row["group_status"] == "skipped"
    assert missing_row["group_skip_reason"] == "SOURCE_SNAPSHOT_STALE"


# =========================================================================
# 9. PREVIEW DIGEST INVARIANCE & SENSITIVITY
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


def test_preview_digest_sensitivity_to_safety_context(api_test_env, tmp_path: Path):
    """Changing server safety policy (protect_last_file, allowed_roots, quarantine_root) must change preview_digest."""
    client = api_test_env["client"]
    service = api_test_env["service"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=21)

    base_res = client.post("/api/scans/21/dedupe-preview", json={}).json()
    base_digest = base_res["preview_digest"]

    # 1. Change protect_last_file True -> False
    service.settings.protect_last_file = False
    res_plf = client.post("/api/scans/21/dedupe-preview", json={}).json()
    assert res_plf["preview_digest"] != base_digest
    service.settings.protect_last_file = True

    # 2. Change allowed_roots by adding an unused root
    extra_root = tmp_path / "extra_root"
    extra_root.mkdir(exist_ok=True)
    orig_raw = service.settings.allowed_roots_raw
    service.settings.allowed_roots_raw = f"{orig_raw},{extra_root}"
    res_ar = client.post("/api/scans/21/dedupe-preview", json={}).json()
    assert res_ar["preview_digest"] != base_digest
    service.settings.allowed_roots_raw = orig_raw

    # 3. Change quarantine_root
    orig_q = service.settings.quarantine_root
    service.settings.quarantine_root = tmp_path / "new_quarantine"
    res_q = client.post("/api/scans/21/dedupe-preview", json={}).json()
    assert res_q["preview_digest"] != base_digest
    service.settings.quarantine_root = orig_q


def test_quarantine_canonical_equivalent_alias_invariance(api_test_env, tmp_path: Path):
    """Equivalent quarantine path (real dir vs symlink alias) must produce identical effective policy and preview_digest."""
    client = api_test_env["client"]
    service = api_test_env["service"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=23)

    qreal = tmp_path / "qreal_alias_test"
    qreal.mkdir(parents=True, exist_ok=True)
    qalias = tmp_path / "qalias_test"
    if qalias.exists() or qalias.is_symlink():
        qalias.unlink()
    qalias.symlink_to(qreal)

    # 1. Preview using qreal
    service.settings.quarantine_root = qreal
    res_real = client.post("/api/scans/23/dedupe-preview", json={}).json()

    # 2. Preview using qalias
    service.settings.quarantine_root = qalias
    res_alias = client.post("/api/scans/23/dedupe-preview", json={}).json()

    assert res_real["effective_safety_policy"]["quarantine_root"] == str(qreal.resolve())
    assert res_alias["effective_safety_policy"]["quarantine_root"] == str(qreal.resolve())
    assert res_real["effective_safety_policy"] == res_alias["effective_safety_policy"]
    assert res_real["preview_digest"] == res_alias["preview_digest"]


def test_quarantine_canonical_symlink_retarget_sensitivity(api_test_env, tmp_path: Path):
    """Retargeting quarantine symlink must change effective_safety_policy and preview_digest even when candidates are outside."""
    client = api_test_env["client"]
    service = api_test_env["service"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=24)

    q1 = tmp_path / "q1_target"
    q2 = tmp_path / "q2_target"
    q1.mkdir(parents=True, exist_ok=True)
    q2.mkdir(parents=True, exist_ok=True)

    qalias = tmp_path / "q_retarget_alias"
    if qalias.exists() or qalias.is_symlink():
        qalias.unlink()
    qalias.symlink_to(q1)

    # Preview A: qalias -> q1
    service.settings.quarantine_root = qalias
    res_a = client.post("/api/scans/24/dedupe-preview", json={}).json()

    # Retarget qalias -> q2
    qalias.unlink()
    qalias.symlink_to(q2)

    # Preview B: qalias -> q2
    res_b = client.post("/api/scans/24/dedupe-preview", json={}).json()

    # Neither candidate files nor group decisions change
    assert res_a["source_snapshot_digest"] == res_b["source_snapshot_digest"]
    assert res_a["decision_digest"] == res_b["decision_digest"]

    # But quarantine authority changes -> effective_safety_policy changes -> preview_digest changes!
    assert res_a["effective_safety_policy"]["quarantine_root"] == str(q1.resolve())
    assert res_b["effective_safety_policy"]["quarantine_root"] == str(q2.resolve())
    assert res_a["effective_safety_policy"] != res_b["effective_safety_policy"]
    assert res_a["preview_digest"] != res_b["preview_digest"]


def test_quarantine_canonical_relative_absolute_equivalence(api_test_env, tmp_path: Path):
    """Relative quarantine path and its resolved absolute path must produce identical effective policy and preview_digest."""
    client = api_test_env["client"]
    service = api_test_env["service"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=25)

    qreal = tmp_path / "qreal_rel_test"
    qreal.mkdir(parents=True, exist_ok=True)

    rel_q = os.path.relpath(qreal, os.getcwd())

    service.settings.quarantine_root = qreal
    res_abs = client.post("/api/scans/25/dedupe-preview", json={}).json()

    service.settings.quarantine_root = Path(rel_q)
    res_rel = client.post("/api/scans/25/dedupe-preview", json={}).json()

    assert res_abs["effective_safety_policy"] == res_rel["effective_safety_policy"]
    assert res_abs["preview_digest"] == res_rel["preview_digest"]


def test_preview_digest_sensitivity_to_db_snapshot(api_test_env):
    """Changing raw DB snapshot (root_id 99 -> 100, both invalid) must change source_snapshot_digest and preview_digest."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=22)

    # Set root_id to 99 for a file in DB (invalid root_id for 1 scan_root)
    with SessionLocal() as session:
        f = session.scalars(select(DuplicateFile).where(DuplicateFile.group_id == 221).limit(1)).first()
        f.root_id = 99
        session.commit()

    res1 = client.post("/api/scans/22/dedupe-preview", json={}).json()
    assert res1["skipped_group_count"] >= 1

    # Now change root_id from 99 to 100 (both invalid)
    with SessionLocal() as session:
        f = session.scalars(select(DuplicateFile).where(DuplicateFile.group_id == 221).limit(1)).first()
        f.root_id = 100
        session.commit()

    res2 = client.post("/api/scans/22/dedupe-preview", json={}).json()
    assert res2["skipped_group_count"] >= 1

    assert res1["source_snapshot_digest"] != res2["source_snapshot_digest"]
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
    assert res2["skipped_group_count"] == 1


# =========================================================================
# 10. EMPTY PREVIEW & ALL SKIPPED SCENARIOS
# =========================================================================

def test_empty_scan_zero_duplicate_groups(api_test_env):
    """Completed scan with 0 duplicate groups must return HTTP 200 and clean 0 counts."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=80, roots=[str(data_dir)])

    resp = client.post("/api/scans/80/dedupe-preview", json={})
    assert resp.status_code == 200
    body = resp.json()

    assert body["scan_roots"] == [str(data_dir)]
    assert body["group_count"] == 0
    assert body["candidate_member_count"] == 0
    assert body["planned_quarantine_count"] == 0
    assert body["expected_reclaim_bytes"] == 0
    assert body["total_rows"] == 0
    assert body["total_pages"] == 0
    assert body["rows"] == []


def test_preview_all_groups_skipped(api_test_env):
    """Scan where all groups are skipped must return HTTP 200 with planned_quarantine=0 and explain rows."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=81, roots=[str(data_dir)])
        # Group with missing files -> skipped
        g = DuplicateGroup(id=811, scan_job_id=81, content_hash="hash_skipped", file_size=100, member_count=2)
        session.add(g)
        session.flush()
        session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(data_dir / "missing1.txt"), relative_path="missing1.txt", top_level_dir=str(data_dir), size=100, mtime_ns=1))
        session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(data_dir / "missing2.txt"), relative_path="missing2.txt", top_level_dir=str(data_dir), size=100, mtime_ns=2))
        session.commit()

    resp = client.post("/api/scans/81/dedupe-preview", json={})
    assert resp.status_code == 200
    body = resp.json()

    assert body["group_count"] == 1
    assert body["actionable_group_count"] == 0
    assert body["skipped_group_count"] == 1
    assert body["planned_quarantine_count"] == 0
    assert body["expected_reclaim_bytes"] == 0
    assert len(body["rows"]) == 2
    for r in body["rows"]:
        assert r["member_decision"] == "SKIPPED"
        assert r["group_status"] == "skipped"
        assert r["group_skip_reason"] in {"SOURCE_SNAPSHOT_STALE", "FILESYSTEM_SAFETY_CHECK_FAILED"}


# =========================================================================
# 11. EXPLAIN DETAIL & PROTECT LAST FILE API TESTS
# =========================================================================

def test_explain_protect_last_file_api(api_test_env):
    """Protect last file triggered: row shows PROTECT_LAST_FILE and PROTECT_LAST_FILE_NO_SAFE_SELECTION if no safe keep."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    # Subdir A has only 1 file. Subdir B has only 1 file.
    dir_a = data_dir / "subA"
    dir_b = data_dir / "subB"
    dir_a.mkdir()
    dir_b.mkdir()

    f_a = dir_a / "dup.txt"
    f_b = dir_b / "dup.txt"
    f_a.write_text("content")
    f_b.write_text("content")

    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=90, roots=[str(data_dir)])
        g = DuplicateGroup(id=901, scan_job_id=90, content_hash="hash_plf", file_size=7, member_count=2)
        session.add(g)
        session.flush()
        session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_a), relative_path="subA/dup.txt", top_level_dir=str(dir_a), size=7, mtime_ns=1))
        session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_b), relative_path="subB/dup.txt", top_level_dir=str(dir_b), size=7, mtime_ns=2))
        session.commit()

    resp = client.post("/api/scans/90/dedupe-preview", json={})
    assert resp.status_code == 200
    body = resp.json()

    assert body["skipped_group_count"] == 1
    assert body["planned_quarantine_count"] == 0
    row = body["rows"][0]
    assert row["group_status"] == "skipped"
    assert row["group_skip_reason"] == "PROTECT_LAST_FILE_NO_SAFE_SELECTION"
    assert "PROTECT_LAST_FILE" in row["safety_reasons"]


def test_explain_serialization_breakdown(api_test_env):
    """Contributions list in rows must be properly serialized with factor, configured_weight, actual_contribution, reason."""
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

    jpg_row = next(r for r in body["rows"] if r["absolute_path"].endswith(".jpg"))
    assert len(jpg_row["contributions"]) > 0
    c = jpg_row["contributions"][0]
    assert "factor" in c
    assert "configured_weight" in c
    assert "actual_contribution" in c
    assert "reason" in c


# =========================================================================
# 12. REAL QUERY ORDER DETERMINISM
# =========================================================================

def test_real_db_query_order_determinism(api_test_env, monkeypatch):
    """Inverting incidental DB query order must produce strictly identical digests and row sequences."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=95)

    # 1. Normal run
    res_normal = client.post("/api/scans/95/dedupe-preview", json={}).json()

    # 2. Mock Session.scalars to reverse query results on DuplicateGroup / DuplicateFile queries
    orig_scalars = Session.scalars

    def mock_scalars(self, statement, *args, **kwargs):
        res = orig_scalars(self, statement, *args, **kwargs)
        all_items = list(res)
        all_items.reverse()
        return all_items

    monkeypatch.setattr(Session, "scalars", mock_scalars)

    res_reversed = client.post("/api/scans/95/dedupe-preview", json={}).json()

    # Assert complete determinism
    assert res_normal["source_snapshot_digest"] == res_reversed["source_snapshot_digest"]
    assert res_normal["decision_digest"] == res_reversed["decision_digest"]
    assert res_normal["preview_digest"] == res_reversed["preview_digest"]
    assert res_normal["rows"] == res_reversed["rows"]


# =========================================================================
# 13. NO-MUTATION GUARANTEE
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
# 14. LIMIT EXCEEDED (422)
# =========================================================================

def test_limit_exceeded_returns_422(api_test_env, monkeypatch):
    """Exceeding MAX_DEDUPE_CANDIDATES must return 422 with DEDUPE_LIMIT_EXCEEDED."""
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


def test_planned_quarantine_limit_exceeded_returns_422(api_test_env, monkeypatch):
    """Exceeding MAX_PLANNED_QUARANTINE must return 422 with DEDUPE_LIMIT_EXCEEDED and create zero records."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=71)
        init_plans = session.scalar(select(func.count(BatchPlan.id)))
        init_items = session.scalar(select(func.count(BatchPlanItem.id)))
        init_jobs = session.scalar(select(func.count(WorkJob.id)))
        init_quarantine = session.scalar(select(func.count(QuarantineEntry.id)))

    # In scan 71, there are 4 planned quarantine items. Monkeypatch limit to 1.
    monkeypatch.setattr(dp_mod, "MAX_PLANNED_QUARANTINE", 1)

    resp = client.post("/api/scans/71/dedupe-preview", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "DEDUPE_LIMIT_EXCEEDED"

    with SessionLocal() as session:
        assert session.scalar(select(func.count(BatchPlan.id))) == init_plans
        assert session.scalar(select(func.count(BatchPlanItem.id))) == init_items
        assert session.scalar(select(func.count(WorkJob.id))) == init_jobs
        assert session.scalar(select(func.count(QuarantineEntry.id))) == init_quarantine


# =========================================================================
# 15. ADVERSARIAL PER-REQUEST SAFETY SNAPSHOT IMMUNITY
# =========================================================================

def test_per_request_safety_snapshot_immune_to_mid_request_quarantine_retarget(api_test_env, tmp_path: Path, monkeypatch):
    """Retargeting quarantine symlink during compilation must NOT bleed into the response or effective safety policy."""
    client = api_test_env["client"]
    service = api_test_env["service"]
    SessionLocal = api_test_env["SessionLocal"]

    q1 = tmp_path / "race_q1"
    q2 = tmp_path / "race_q2"
    q1.mkdir(parents=True, exist_ok=True)
    q2.mkdir(parents=True, exist_ok=True)

    qalias = tmp_path / "race_qalias"
    if qalias.exists() or qalias.is_symlink():
        qalias.unlink()
    qalias.symlink_to(q1)

    service.settings.quarantine_root = qalias
    service.settings.protect_last_file = False
    orig_allowed = service.settings.allowed_roots_raw
    service.settings.allowed_roots_raw = f"{orig_allowed},{q1},{q2}"

    # Files located in q1
    f_a = q1 / "a.bin"
    f_b = q1 / "b.bin"
    f_a.write_bytes(b"x" * 100)
    f_b.write_bytes(b"x" * 100)

    scan_id = 100
    with SessionLocal() as session:
        _create_completed_scan(session, scan_id=scan_id, roots=[str(q1)])
        g = DuplicateGroup(id=1001, scan_job_id=scan_id, content_hash="hash_race_q1", file_size=100, member_count=2)
        session.add(g)
        session.flush()
        session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_a), relative_path=f_a.name, top_level_dir=str(q1), size=100, mtime_ns=1000))
        session.add(DuplicateFile(group_id=g.id, root_id=0, absolute_path=str(f_b), relative_path=f_b.name, top_level_dir=str(q1), size=100, mtime_ns=2000))
        session.commit()

    # Intercept compile_advanced_dedupe_preview in app.service to simulate external retarget right after compilation
    orig_compile = dp_mod.compile_advanced_dedupe_preview

    def retarget_on_compile(*args, **kwargs):
        comp = orig_compile(*args, **kwargs)
        # Retarget symlink from q1 -> q2 during request execution
        qalias.unlink()
        qalias.symlink_to(q2)
        return comp

    monkeypatch.setattr("app.service.compile_advanced_dedupe_preview", retarget_on_compile)

    resp = client.post(f"/api/scans/{scan_id}/dedupe-preview", json={})
    assert resp.status_code == 200
    body = resp.json()

    # The entire response MUST be bound to q1, not q2
    assert body["effective_safety_policy"]["quarantine_root"] == str(q1.resolve())
    assert body["effective_safety_policy"]["quarantine_root"] != str(q2.resolve())

    # Because files are inside q1 (the snapshot quarantine root), they must be flagged RESERVED_QUARANTINE_PATH
    assert body["group_count"] == 1
    assert body["skipped_group_count"] == 1
    assert len(body["rows"]) == 2
    for r in body["rows"]:
        assert "RESERVED_QUARANTINE_PATH" in r["safety_reasons"]
        assert r["member_decision"] == "SKIPPED"
        assert r["group_status"] == "skipped"
        assert r["group_skip_reason"] == "FILESYSTEM_SAFETY_CHECK_FAILED"


def test_per_request_safety_snapshot_successive_requests_atomic_transition(api_test_env, tmp_path: Path, monkeypatch):
    """Successive requests each capture their own atomic safety snapshot without leaking previous state."""
    client = api_test_env["client"]
    service = api_test_env["service"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    q1 = tmp_path / "atom_q1"
    q2 = tmp_path / "atom_q2"
    q1.mkdir(parents=True, exist_ok=True)
    q2.mkdir(parents=True, exist_ok=True)

    qalias = tmp_path / "atom_qalias"
    if qalias.exists() or qalias.is_symlink():
        qalias.unlink()
    qalias.symlink_to(q1)

    service.settings.quarantine_root = qalias
    scan_id = 101
    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=scan_id)

    # Monkeypatch to retarget qalias during Request A
    orig_compile = dp_mod.compile_advanced_dedupe_preview

    def retarget_during_req_a(*args, **kwargs):
        comp = orig_compile(*args, **kwargs)
        qalias.unlink()
        qalias.symlink_to(q2)
        return comp

    monkeypatch.setattr("app.service.compile_advanced_dedupe_preview", retarget_during_req_a)

    # Request A: Captured q1 at start
    res_a = client.post(f"/api/scans/{scan_id}/dedupe-preview", json={}).json()
    assert res_a["effective_safety_policy"]["quarantine_root"] == str(q1.resolve())

    # Undo monkeypatch for Request B
    monkeypatch.undo()

    # Request B: Captures q2 at start
    res_b = client.post(f"/api/scans/{scan_id}/dedupe-preview", json={}).json()
    assert res_b["effective_safety_policy"]["quarantine_root"] == str(q2.resolve())

    # Candidate data files are in data_dir (outside q1 and q2), so snapshot and decision digests remain equal
    assert res_a["source_snapshot_digest"] == res_b["source_snapshot_digest"]
    assert res_a["decision_digest"] == res_b["decision_digest"]

    # But quarantine authority changed between requests -> effective_safety_policy and preview_digest change atomically!
    assert res_a["effective_safety_policy"] != res_b["effective_safety_policy"]
    assert res_a["preview_digest"] != res_b["preview_digest"]

