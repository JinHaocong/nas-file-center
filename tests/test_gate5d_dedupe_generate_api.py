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
    service = FileCenterService(settings)
    with service.SessionLocal() as session:
        session.add(User(
            username="normaluser",
            password_hash=hash_password("UserPassword123!"),
            is_active=True,
            role="user",
        ))
        session.commit()

    app = create_app(settings)
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


def test_unknown_dedupe_plan_field_uses_structured_error(api_test_env):
    resp = api_test_env["client"].post(
        "/api/scans/1/dedupe-plan",
        json={"policy": "balanced-roots", "unexpected": True},
    )
    _assert_structured_dedupe_error(resp, status=422, code="DEDUPE_INVALID_CONFIG")
