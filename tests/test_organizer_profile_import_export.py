from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


def _get_client(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    config = tmp_path / "config"
    config.mkdir(exist_ok=True)

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        allow_mutation=True,
        allow_delete=False,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    client = TestClient(create_app(settings))
    client.headers.update({"Origin": "http://testserver"})
    client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})
    return client, data


def test_export_and_import_roundtrip(tmp_path: Path):
    client, data = _get_client(tmp_path)

    # 1. Create a profile
    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "导出导入测试方案",
            "rename_template": "{name} {statistics}",
            "statistics_template": "[{images}P {videos}V {size}]",
        },
    )
    profile_id = create_resp.json()["id"]

    # 2. Export profile
    export_resp = client.get(f"/api/organizer-profiles/{profile_id}/export")
    assert export_resp.status_code == 200
    exported_data = export_resp.json()
    assert exported_data["schema_version"] == 1
    assert "profile" in exported_data
    assert exported_data["profile"]["name"] == "导出导入测试方案"

    # 3. Import exported JSON
    import_resp = client.post("/api/organizer-profiles/import", json=exported_data)
    assert import_resp.status_code == 200
    imported = import_resp.json()
    assert imported["is_builtin"] is False  # Must NEVER create builtin profile via import
    assert "导出导入测试方案" in imported["name"]


def test_import_validation_and_security(tmp_path: Path):
    client, data = _get_client(tmp_path)

    # 1. Reject invalid schema_version
    bad_ver = {
        "schema_version": 999,
        "profile": {"name": "Test"},
    }
    resp1 = client.post("/api/organizer-profiles/import", json=bad_ver)
    assert resp1.status_code in {400, 422}

    # 2. Reject forbidden fields (e.g. attempting to set is_builtin=True or user_id)
    forbidden_payload = {
        "schema_version": 1,
        "profile": {
            "name": "恶意方案",
            "is_builtin": True,
            "user_id": 9999,
        },
    }
    resp2 = client.post("/api/organizer-profiles/import", json=forbidden_payload)
    assert resp2.status_code == 400
    assert "禁止字段" in resp2.json()["detail"]

    # 3. Reject unknown profile fields
    unknown_payload = {
        "schema_version": 1,
        "profile": {
            "name": "未知字段方案",
            "random_unknown_field": "val",
        },
    }
    resp3 = client.post("/api/organizer-profiles/import", json=unknown_payload)
    assert resp3.status_code == 400
    assert "未知字段" in resp3.json()["detail"]

    # 4. Reject unknown top-level fields (Blocker 10)
    unknown_top_level = {
        "schema_version": 1,
        "profile": {
            "name": "正常方案",
        },
        "evil": 123,
    }
    resp4 = client.post("/api/organizer-profiles/import", json=unknown_top_level)
    assert resp4.status_code in {400, 422}
