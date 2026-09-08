from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth.password import hash_password
from app.config import Settings
from app.main import create_app
from app.models import Base, BatchPlan, BatchPlanItem, DuplicateFile, DuplicateGroup, QuarantineEntry, ScanJob, User, WorkJob, utcnow
from app.service import FileCenterService


@pytest.fixture
def api_test_env(tmp_path: Path):
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
        session.add(User(
            username="normaluser",
            password_hash=hash_password("UserPassword123!"),
            is_active=True,
            role="user",
        ))
        session.commit()

    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    login = client.post(
        "/api/auth/login",
        json={"username": "normaluser", "password": "UserPassword123!"},
    )
    assert login.status_code == 200
    return {
        "client": client,
        "service": service,
        "SessionLocal": service.SessionLocal,
        "settings": settings,
        "data_dir": data_dir,
        "quarantine_dir": quarantine_dir,
    }


def _create_completed_scan(SessionLocal, *, scan_id: int, roots: list[str]) -> None:
    with SessionLocal() as session:
        session.add(ScanJob(
            id=scan_id,
            name=f"scan-{scan_id}",
            mode="normal",
            roots_json=json.dumps(roots),
            status="completed",
            started_at=utcnow(),
            finished_at=utcnow(),
            total_groups=0,
            total_files_in_groups=0,
            reclaimable_bytes=0,
        ))
        session.commit()


def _setup_duplicate_test_data(SessionLocal, root: Path, *, scan_id: int) -> None:
    _create_completed_scan(SessionLocal, scan_id=scan_id, roots=[str(root)])
    first = root / f"dup-{scan_id}-a.bin"
    second = root / f"dup-{scan_id}-b.bin"
    first.write_bytes(b"x" * 128)
    second.write_bytes(b"x" * 128)
    with SessionLocal() as session:
        group = DuplicateGroup(
            id=scan_id * 10 + 1,
            scan_job_id=scan_id,
            content_hash=f"group-hash-{scan_id}",
            file_size=128,
            member_count=2,
        )
        session.add(group)
        session.flush()
        session.add_all([
            DuplicateFile(
                group_id=group.id, root_id=0, absolute_path=str(first),
                relative_path=first.name, top_level_dir=str(root),
                size=128, mtime_ns=1000, device=0, inode=0,
            ),
            DuplicateFile(
                group_id=group.id, root_id=0, absolute_path=str(second),
                relative_path=second.name, top_level_dir=str(root),
                size=128, mtime_ns=2000, device=0, inode=0,
            ),
        ])
        session.commit()


def _count_plan_state(SessionLocal) -> tuple[int, int, int, int]:
    with SessionLocal() as session:
        return (
            session.scalar(select(func.count(BatchPlan.id))) or 0,
            session.scalar(select(func.count(BatchPlanItem.id))) or 0,
            session.scalar(select(func.count(WorkJob.id))) or 0,
            session.scalar(select(func.count(QuarantineEntry.id))) or 0,
        )


def _assert_structured_dedupe_error(resp, *, status: int, code: str):
    assert resp.status_code == status, resp.text
    body = resp.json()
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert isinstance(body["error"]["details"], (dict, list))


@pytest.mark.parametrize("payload", [
    {"scorer_config": {}},
    {"scorer_config": {}, "expected_preview_digest": None},
    {"scorer_config": {}, "expected_preview_digest": "0" * 63},
    {"scorer_config": {}, "expected_preview_digest": "g" * 64},
    {"scorer_config": {}, "expected_preview_digest": 123},
])
def test_advanced_generate_requires_strict_64hex_digest(api_test_env, payload):
    resp = api_test_env["client"].post("/api/scans/1/dedupe-plan", json=payload)
    _assert_structured_dedupe_error(resp, status=422, code="DEDUPE_INVALID_CONFIG")


@pytest.mark.parametrize("legacy_field, legacy_value", [
    ("policy", "balanced-roots"),
    ("path_priority_patterns", ["/preferred"]),
    ("relative_path_priority_patterns", ["preferred"]),
])
def test_advanced_generate_rejects_mixed_legacy_fields(api_test_env, legacy_field, legacy_value):
    payload = {
        "scorer_config": {},
        "expected_preview_digest": "a" * 64,
        legacy_field: legacy_value,
    }
    resp = api_test_env["client"].post("/api/scans/1/dedupe-plan", json=payload)
    _assert_structured_dedupe_error(resp, status=422, code="DEDUPE_INVALID_CONFIG")


def test_digest_without_scorer_config_is_rejected_not_treated_as_legacy(api_test_env):
    resp = api_test_env["client"].post(
        "/api/scans/1/dedupe-plan",
        json={"expected_preview_digest": "a" * 64},
    )
    _assert_structured_dedupe_error(resp, status=422, code="DEDUPE_INVALID_CONFIG")


def test_advanced_unknown_extra_field_rejected(api_test_env):
    resp = api_test_env["client"].post(
        "/api/scans/1/dedupe-plan",
        json={
            "scorer_config": {},
            "expected_preview_digest": "a" * 64,
            "unexpected": True,
        },
    )
    _assert_structured_dedupe_error(resp, status=422, code="DEDUPE_INVALID_CONFIG")


def test_advanced_invalid_scorer_config_selection_mode_returns_422_structured(api_test_env):
    scan_id = 230
    _setup_duplicate_test_data(api_test_env["SessionLocal"], api_test_env["data_dir"], scan_id=scan_id)
    before = _count_plan_state(api_test_env["SessionLocal"])
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={
            "scorer_config": {"selection_mode": "bogus"},
            "expected_preview_digest": "a" * 64,
        },
    )
    _assert_structured_dedupe_error(resp, status=422, code="DEDUPE_INVALID_CONFIG")
    assert _count_plan_state(api_test_env["SessionLocal"]) == before


def test_advanced_reserved_factor_returns_422_factor_unavailable(api_test_env):
    scan_id = 231
    _setup_duplicate_test_data(api_test_env["SessionLocal"], api_test_env["data_dir"], scan_id=scan_id)
    before = _count_plan_state(api_test_env["SessionLocal"])
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={
            "scorer_config": {"factors": {"resolution": {"weight": 1}}},
            "expected_preview_digest": "a" * 64,
        },
    )
    _assert_structured_dedupe_error(resp, status=422, code="DEDUPE_FACTOR_UNAVAILABLE")
    assert _count_plan_state(api_test_env["SessionLocal"]) == before


def test_advanced_factors_null_returns_422_structured(api_test_env):
    scan_id = 232
    _setup_duplicate_test_data(api_test_env["SessionLocal"], api_test_env["data_dir"], scan_id=scan_id)
    before = _count_plan_state(api_test_env["SessionLocal"])
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={
            "scorer_config": {"factors": None},
            "expected_preview_digest": "a" * 64,
        },
    )
    _assert_structured_dedupe_error(resp, status=422, code="DEDUPE_INVALID_CONFIG")
    assert _count_plan_state(api_test_env["SessionLocal"]) == before


def test_legacy_policy_null_returns_422_validation_error_and_does_not_call_service(api_test_env, monkeypatch):
    service = api_test_env["service"]
    called = []
    monkeypatch.setattr(service, "create_dedupe_plan", lambda *a, **kw: called.append(1))
    monkeypatch.setattr(service, "create_advanced_dedupe_plan", lambda *a, **kw: called.append(1))
    resp = api_test_env["client"].post(
        "/api/scans/1/dedupe-plan",
        json={"policy": None},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    assert "error" not in body  # standard Pydantic validation error envelope, not structured DedupeError
    assert called == []


def test_legacy_unknown_extra_field_ignored_and_calls_service(api_test_env, monkeypatch):
    service = api_test_env["service"]
    calls = []

    def fake_legacy(scan_job_id, *, policy, path_priority_patterns=None, relative_path_priority_patterns=None):
        calls.append((scan_job_id, policy, path_priority_patterns, relative_path_priority_patterns))
        return {"id": 99, "status": "draft", "items": 0, "delete_counts": {}}

    monkeypatch.setattr(service, "create_dedupe_plan", fake_legacy)
    resp = api_test_env["client"].post(
        "/api/scans/777/dedupe-plan",
        json={"policy": "balanced-roots", "unexpected": True},
    )
    assert resp.status_code == 200
    assert calls == [(777, "balanced-roots", None, None)]



def test_http_matching_digest_creates_draft(api_test_env):
    scan_id = 200
    _setup_duplicate_test_data(api_test_env["SessionLocal"], api_test_env["data_dir"], scan_id=scan_id)
    config = {"selection_mode": "weighted"}
    preview = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": config},
    ).json()
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={
            "scorer_config": config,
            "expected_preview_digest": preview["preview_digest"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == body["plan_id"]
    assert body["status"] == "draft"
    assert body["items"] == preview["planned_quarantine_count"]
    assert body["expected_changes"] == preview["planned_quarantine_count"]
    assert body["expected_reclaim_bytes"] == preview["expected_reclaim_bytes"]
    assert body["preview_digest"] == preview["preview_digest"]


def test_http_bad_digest_returns_409_and_zero_draft(api_test_env):
    scan_id = 201
    _setup_duplicate_test_data(api_test_env["SessionLocal"], api_test_env["data_dir"], scan_id=scan_id)
    before = _count_plan_state(api_test_env["SessionLocal"])
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={"scorer_config": {}, "expected_preview_digest": "0" * 64},
    )
    _assert_structured_dedupe_error(resp, status=409, code="PREVIEW_CHANGED")
    assert _count_plan_state(api_test_env["SessionLocal"]) == before
    details = resp.json()["error"]["details"]
    assert details["expected_preview_digest"] == "0" * 64
    assert len(details["actual_preview_digest"]) == 64
    assert details["actual_preview_digest"] != details["expected_preview_digest"]


def test_http_empty_advanced_generate_returns_422_zero_draft(api_test_env):
    scan_id = 202
    _create_completed_scan(api_test_env["SessionLocal"], scan_id=scan_id, roots=[str(api_test_env["data_dir"])])
    preview = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": {}},
    ).json()
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={"scorer_config": {}, "expected_preview_digest": preview["preview_digest"]},
    )
    _assert_structured_dedupe_error(resp, status=422, code="DEDUPE_EMPTY_PLAN")


@pytest.mark.parametrize("policy", [
    "keep-first-root",
    "keep-newest",
    "keep-oldest",
    "balanced-roots",
    "path-priority",
    "relative-path-preference",
])
def test_legacy_policy_request_still_calls_legacy_service(api_test_env, monkeypatch, policy):
    service = api_test_env["service"]
    calls = []

    def fake_legacy(scan_job_id, *, policy, path_priority_patterns=None, relative_path_priority_patterns=None):
        calls.append((scan_job_id, policy, path_priority_patterns, relative_path_priority_patterns))
        return {"id": 99, "status": "draft", "items": 0, "delete_counts": {}}

    monkeypatch.setattr(service, "create_dedupe_plan", fake_legacy)
    resp = api_test_env["client"].post(
        "/api/scans/777/dedupe-plan",
        json={"policy": policy},
    )
    assert resp.status_code == 200
    assert calls == [(777, policy, None, None)]


def test_scorer_change_after_preview_returns_preview_changed(api_test_env):
    scan_id = 210
    _setup_duplicate_test_data(api_test_env["SessionLocal"], api_test_env["data_dir"], scan_id=scan_id)
    config_a = {"selection_mode": "weighted"}
    config_b = {
        "selection_mode": "weighted",
        "factors": {"mtime": {"mode": "newest", "weight": 10}},
    }
    preview = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": config_a},
    ).json()
    before = _count_plan_state(api_test_env["SessionLocal"])
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={
            "scorer_config": config_b,
            "expected_preview_digest": preview["preview_digest"],
        },
    )
    _assert_structured_dedupe_error(resp, status=409, code="PREVIEW_CHANGED")
    assert _count_plan_state(api_test_env["SessionLocal"]) == before


def test_scan_provenance_change_after_preview_returns_preview_changed(api_test_env):
    scan_id = 211
    _setup_duplicate_test_data(api_test_env["SessionLocal"], api_test_env["data_dir"], scan_id=scan_id)
    preview = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": {}},
    ).json()
    with api_test_env["SessionLocal"]() as session:
        scan = session.get(ScanJob, scan_id)
        assert scan is not None
        scan.name = "changed-after-preview"
        session.commit()
    before = _count_plan_state(api_test_env["SessionLocal"])
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={"scorer_config": {}, "expected_preview_digest": preview["preview_digest"]},
    )
    _assert_structured_dedupe_error(resp, status=409, code="PREVIEW_CHANGED")
    assert _count_plan_state(api_test_env["SessionLocal"]) == before


def test_filesystem_safety_change_after_preview_returns_preview_changed(api_test_env):
    scan_id = 212
    _setup_duplicate_test_data(api_test_env["SessionLocal"], api_test_env["data_dir"], scan_id=scan_id)
    preview = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": {}},
    ).json()
    with api_test_env["SessionLocal"]() as session:
        victim = session.scalar(
            select(DuplicateFile)
            .join(DuplicateGroup)
            .where(DuplicateGroup.scan_job_id == scan_id)
            .order_by(DuplicateFile.id)
        )
        assert victim is not None
        victim_path = Path(victim.absolute_path)
    victim_path.unlink()
    before = _count_plan_state(api_test_env["SessionLocal"])
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={"scorer_config": {}, "expected_preview_digest": preview["preview_digest"]},
    )
    _assert_structured_dedupe_error(resp, status=409, code="PREVIEW_CHANGED")
    assert _count_plan_state(api_test_env["SessionLocal"]) == before


def test_effective_safety_authority_change_after_preview_returns_preview_changed(api_test_env, tmp_path: Path):
    scan_id = 213
    _setup_duplicate_test_data(api_test_env["SessionLocal"], api_test_env["data_dir"], scan_id=scan_id)
    preview = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": {}},
    ).json()
    new_quarantine = tmp_path / "new-quarantine"
    new_quarantine.mkdir()
    api_test_env["service"].settings.quarantine_root = new_quarantine
    before = _count_plan_state(api_test_env["SessionLocal"])
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={"scorer_config": {}, "expected_preview_digest": preview["preview_digest"]},
    )
    _assert_structured_dedupe_error(resp, status=409, code="PREVIEW_CHANGED")
    assert _count_plan_state(api_test_env["SessionLocal"]) == before


def test_protected_directory_count_change_after_preview_returns_preview_changed(api_test_env):
    scan_id = 214
    _setup_duplicate_test_data(api_test_env["SessionLocal"], api_test_env["data_dir"], scan_id=scan_id)
    preview = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": {}},
    ).json()
    extra = api_test_env["data_dir"] / "unrelated-file.bin"
    extra.write_bytes(b"extra")
    before = _count_plan_state(api_test_env["SessionLocal"])
    resp = api_test_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={"scorer_config": {}, "expected_preview_digest": preview["preview_digest"]},
    )
    _assert_structured_dedupe_error(resp, status=409, code="PREVIEW_CHANGED")
    assert _count_plan_state(api_test_env["SessionLocal"]) == before


