from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import BatchPlan, DuplicateFile, DuplicateGroup, ScanJob, utcnow


RECURSIVE_MODE = "recursive_directory_balanced_by_bytes"


@pytest.fixture
def api_env(tmp_path: Path):
    data_dir = tmp_path / "data"
    quarantine_dir = tmp_path / "quarantine"
    config_dir = tmp_path / "config"
    data_dir.mkdir()
    quarantine_dir.mkdir()
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
    client = TestClient(app)
    client.headers["Origin"] = "http://testserver"
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
    )
    assert login.status_code == 200, login.text

    return {
        "client": client,
        "service": app.state.service,
        "SessionLocal": app.state.service.SessionLocal,
        "data_dir": data_dir,
    }


def _recursive_config(selection_mode: str = RECURSIVE_MODE) -> dict:
    return {
        "schema_version": 1,
        "selection_mode": selection_mode,
        "factors": {},
    }


def _create_recursive_fixture(env, *, scan_id: int) -> tuple[Path, Path]:
    root = env["data_dir"]
    left_dir = root / f"A-{scan_id}" / "deep"
    right_dir = root / f"B-{scan_id}" / "deep"
    left_dir.mkdir(parents=True)
    right_dir.mkdir(parents=True)

    left = left_dir / "dup.bin"
    right = right_dir / "dup.bin"
    payload = b"gate6b-api-recursive"
    left.write_bytes(payload)
    right.write_bytes(payload)
    # Keep both recursive branches safely non-empty after one duplicate is quarantined.
    (left_dir / "extra.bin").write_bytes(b"left-extra")
    (right_dir / "extra.bin").write_bytes(b"right-extra")

    with env["SessionLocal"]() as session:
        session.add(
            ScanJob(
                id=scan_id,
                name=f"scan-{scan_id}",
                mode="normal",
                roots_json=json.dumps([str(root)]),
                status="completed",
                started_at=utcnow(),
                finished_at=utcnow(),
                total_groups=1,
                total_files_in_groups=2,
                reclaimable_bytes=len(payload),
            )
        )
        group = DuplicateGroup(
            id=scan_id * 10 + 1,
            scan_job_id=scan_id,
            content_hash=f"gate6b-api-{scan_id}",
            file_size=len(payload),
            member_count=2,
        )
        session.add(group)
        session.flush()
        for path in (left, right):
            stat_result = os.lstat(path)
            relative = path.relative_to(root)
            session.add(
                DuplicateFile(
                    group_id=group.id,
                    root_id=0,
                    absolute_path=str(path),
                    relative_path=relative.as_posix(),
                    top_level_dir=str(root / relative.parts[0]),
                    size=stat_result.st_size,
                    mtime_ns=stat_result.st_mtime_ns,
                    device=stat_result.st_dev,
                    inode=stat_result.st_ino,
                )
            )
        session.commit()
    return left, right


def _batch_plan_count(env) -> int:
    with env["SessionLocal"]() as session:
        return session.scalar(select(func.count(BatchPlan.id))) or 0


def test_recursive_mode_api_accepts_token_returns_explain_and_preview_is_read_only(api_env):
    scan_id = 1001
    _create_recursive_fixture(api_env, scan_id=scan_id)
    before = _batch_plan_count(api_env)

    response = api_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": _recursive_config()},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selection_mode"] == RECURSIVE_MODE
    assert body["preview_source"] == "completed-scan-readonly-safety"
    assert body["live_filesystem_verified"] is False
    assert len(body["rows"]) == 2
    for row in body["rows"]:
        assert "candidate_balance_bucket" in row
        assert row["candidate_balance_bucket"] is not None
        assert "recursive_last_file_protection_reason" in row
        assert "group_balance_info" in row
        assert "selection_reason" in row
        assert "contributions" in row
    assert _batch_plan_count(api_env) == before


@pytest.mark.parametrize("selection_mode", ["weighted", "balanced_by_bytes"])
def test_historical_selection_mode_tokens_remain_valid_over_api(api_env, selection_mode: str):
    scan_id = 1002 if selection_mode == "weighted" else 1003
    _create_recursive_fixture(api_env, scan_id=scan_id)

    response = api_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": _recursive_config(selection_mode)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["selection_mode"] == selection_mode


def test_recursive_mandatory_last_file_protection_cannot_be_disabled_by_api(api_env):
    scan_id = 1004
    _create_recursive_fixture(api_env, scan_id=scan_id)
    config = _recursive_config()
    config["recursive_last_file_protection_enabled"] = False

    response = api_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": config},
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"]["code"] == "DEDUPE_INVALID_CONFIG"


def test_recursive_generate_stale_is_explicit_and_creates_zero_draft(api_env):
    scan_id = 1005
    left, _right = _create_recursive_fixture(api_env, scan_id=scan_id)
    config = _recursive_config()
    preview = api_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": config},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    before = _batch_plan_count(api_env)

    # Recursive directory file counts are digest-bound; this makes the Preview stale.
    (left.parent / "appeared-after-preview.bin").write_bytes(b"third-party")
    response = api_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-plan",
        json={
            "scorer_config": config,
            "expected_preview_digest": preview_body["preview_digest"],
        },
    )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["error"]["code"] == "PREVIEW_CHANGED"
    assert body["error"]["details"]["expected_preview_digest"] == preview_body["preview_digest"]
    assert body["error"]["details"]["actual_preview_digest"] != preview_body["preview_digest"]
    assert _batch_plan_count(api_env) == before


def test_recursive_dedupe_workflow_preserves_config_and_explain_transport(api_env):
    scan_id = 1006
    _create_recursive_fixture(api_env, scan_id=scan_id)
    config = _recursive_config()

    direct = api_env["client"].post(
        f"/api/scans/{scan_id}/dedupe-preview",
        json={"scorer_config": config},
    )
    assert direct.status_code == 200, direct.text
    direct_rows = {row["absolute_path"]: row for row in direct.json()["rows"]}

    create = api_env["client"].post(
        "/api/workflows",
        json={
            "name": "Gate6-B recursive transport",
            "description": "Task 10 transport regression",
            "definition": {
                "schema_version": 1,
                "mode": "dedupe",
                "steps": [
                    {
                        "id": "dedupe-1",
                        "type": "dedupe",
                        "scorer_config": config,
                    }
                ],
            },
        },
    )
    assert create.status_code == 201, create.text
    workflow = create.json()
    stored_config = workflow["definition"]["steps"][0]["scorer_config"]
    assert stored_config["schema_version"] == 1
    assert stored_config["selection_mode"] == RECURSIVE_MODE
    # Workflow storage may canonicalize omitted factor defaults; the new mode token must survive.
    assert set(stored_config["factors"]) == {"path_priority", "preferred_extension", "mtime"}

    preview = api_env["client"].post(
        f"/api/workflows/{workflow['id']}/preview",
        json={"runtime_inputs": {"scan_job_id": scan_id}, "page_size": 50},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["workflow_mode"] == "dedupe"
    assert body["dedupe_summary"]["selection_mode"] == RECURSIVE_MODE
    assert len(body["items"]) == 2

    for item in body["items"]:
        direct_row = direct_rows[item["source_path"]]
        metadata = item["metadata"]
        assert "candidate_balance_bucket" in metadata
        assert metadata["candidate_balance_bucket"] == direct_row["candidate_balance_bucket"]
        assert "recursive_last_file_protection_reason" in metadata
        assert (
            metadata["recursive_last_file_protection_reason"]
            == direct_row["recursive_last_file_protection_reason"]
        )
