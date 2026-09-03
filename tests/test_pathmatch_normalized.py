from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


def test_pathmatch_normalized_mode_contract(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    dir_a = data / "FolderA"
    dir_b = data / "FolderB"
    dir_a.mkdir()
    dir_b.mkdir()

    # Create files with varied suffix annotations that normalize to the same key
    (dir_a / "Album_001 [20P 1GB].zip").write_bytes(b"DATA_A")
    (dir_b / "Album_001 [50P 2GB].zip").write_bytes(b"DATA_B")

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

    resp = client.post(
        "/api/path-match/preview",
        json={
            "roots": [str(dir_a), str(dir_b)],
            "mode": "normalized",
            "normalize_pattern": r"\[\d+P.*?\]",
            "normalize_replacement": "",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "groups" in body
    assert len(body["groups"]) == 1

    group = body["groups"][0]
    # Key should have the pattern stripped
    assert "Album_001" in group["key"]
    assert len(group["members"]) == 2
    paths = [m["path"] for m in group["members"]]
    assert str(dir_a / "Album_001 [20P 1GB].zip") in paths
    assert str(dir_b / "Album_001 [50P 2GB].zip") in paths
