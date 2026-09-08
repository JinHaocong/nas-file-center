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
# 5. GLOBAL SUMMARY & TRUTH MARKERS CONTRACT
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

    # Released bytes by scan root: string keys for all scan roots
    assert body["released_bytes_by_scan_root"] == {"0": 450}

    # Effective safety policy
    assert body["effective_safety_policy"]["protect_last_file"] is True
    assert str(data_dir) in body["effective_safety_policy"]["allowed_roots"]
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
# 6. PAGE-LOCAL GROUP EXPLAIN ON EVERY ROW
# =========================================================================

def test_page_local_group_explain_on_every_row(api_test_env):
    """Every member row (even with page_size=1 on a quarantine row) must explain its group."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=11)

    # Fetch with page_size=1
    p1 = client.post("/api/scans/11/dedupe-preview", json={"page": 1, "page_size": 1}).json()
    assert len(p1["rows"]) == 1
    row = p1["rows"][0]

    # Must contain group-level decision context
    assert "group_recommended_keep_path" in row
    assert "group_reclaimable_bytes" in row
    assert "group_selection_reason" in row
    assert "group_balance_info" in row

    # Group 1 has 3 files, size 100, 2 quarantine -> 200 reclaimable bytes
    assert row["group_reclaimable_bytes"] > 0
    assert row["group_recommended_keep_path"] is not None
    assert row["group_selection_reason"] is not None


# =========================================================================
# 7. EFFECTIVE SAFETY CONTEXT IN PREVIEW DIGEST
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


def test_preview_digest_sensitivity_to_db_snapshot(api_test_env):
    """Changing raw DB snapshot (e.g. root_id 99 -> 100, both invalid) must change source_snapshot_digest and preview_digest."""
    client = api_test_env["client"]
    SessionLocal = api_test_env["SessionLocal"]
    data_dir = api_test_env["data_dir"]

    with SessionLocal() as session:
        _setup_duplicate_test_data(session, data_dir, scan_id=22)

    res1 = client.post("/api/scans/22/dedupe-preview", json={}).json()

    # Modify raw DB root_id
    with SessionLocal() as session:
        f = session.scalars(select(DuplicateFile).limit(1)).first()
        f.root_id = 99
        session.commit()

    res2 = client.post("/api/scans/22/dedupe-preview", json={}).json()

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
# 8. EMPTY PREVIEW & ALL SKIPPED SCENARIOS
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
# 9. EXPLAIN DETAIL & PROTECT LAST FILE API TESTS
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


# =========================================================================
# 10. REAL QUERY ORDER DETERMINISM
# =========================================================================

def test_real_db_query_order_determinism(api_test_env, monkeypatch):
    """Inverting incidental DB query order must produce strictly identical digests and row sequences."""
    client = api_test_env["client"]
    service = api_test_env["service"]
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
        # Reverse the order returned from the DB query
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
# 11. NO-MUTATION GUARANTEE
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
# 12. LIMIT EXCEEDED (422)
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
