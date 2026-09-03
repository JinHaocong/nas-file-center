from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


def test_pathmatch_api_contract_and_plan_generation(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    dir_a = data / "DiskA"
    dir_b = data / "DiskB"
    dir_a.mkdir()
    dir_b.mkdir()

    # Create matching duplicate files in both roots
    content = b"IDENTICAL_VIDEO_DATA_12345"
    (dir_a / "movie.mkv").write_bytes(content)
    (dir_b / "movie.mkv").write_bytes(content)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=data / ".trash",
        allow_mutation=True,
        allow_delete=False,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})

    # 1. Test /api/path-match/preview
    resp = client.post(
        "/api/path-match/preview",
        json={"roots": [str(dir_a), str(dir_b)], "mode": "relative-path"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "groups" in body
    assert len(body["groups"]) == 1

    group = body["groups"][0]
    assert group["key"] == "movie.mkv"
    assert "members" in group
    assert len(group["members"]) == 2

    # Verify each member has exact contract fields
    member_a = group["members"][0]
    assert member_a["root"] == "root-0"
    assert member_a["path"] == str(dir_a / "movie.mkv")
    assert member_a["relative_path"] == "movie.mkv"
    assert member_a["size"] == len(content)
    assert "mtime_ns" in member_a

    member_b = group["members"][1]
    assert member_b["root"] == "root-1"
    assert member_b["path"] == str(dir_b / "movie.mkv")
    assert member_b["relative_path"] == "movie.mkv"
    assert member_b["size"] == len(content)

    # 2. Test Plan creation using members[].path (React UI behavior)
    keep_path = member_a["path"]
    dup_path = member_b["path"]
    plan_resp = client.post(
        "/api/plans",
        json={
            "name": "PathMatch Dedupe Plan",
            "kind": "path-match-dedupe",
            "items": [
                {
                    "operation": "quarantine",
                    "source": dup_path,
                    "keep": keep_path,
                    "expected_size": member_b["size"],
                }
            ],
        },
    )
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["id"]

    # 3. Freeze -> Validate -> Execute
    client.post(f"/api/plans/{plan_id}/freeze")
    val_resp = client.post(f"/api/plans/{plan_id}/validate")
    assert val_resp.status_code == 200
    assert val_resp.json()["status"] == "ready"

    exec_resp = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_resp.status_code == 200
    assert exec_resp.json()["status"] == "completed"

    assert (dir_a / "movie.mkv").exists()
    assert not (dir_b / "movie.mkv").exists()
