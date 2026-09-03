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


def test_organizer_profile_crud_and_pagination(tmp_path: Path):
    client, data = _get_client(tmp_path)

    # 1. Initially profile list should be completely empty (count = 0)
    resp = client.get("/api/organizer-profiles")
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["total"] == 0
    assert res_data["items"] == []

    # 2. Create custom profile
    create_payload = {
        "name": "壁纸整理方案",
        "description": "专用于 4K 壁纸自动归档与重命名",
        "root": str(data),
        "recursive": False,
        "image_extensions": ["jpg", "png", "webp"],
        "video_extensions": ["mp4"],
        "rename_template": "{index} 壁纸 {name} {statistics}",
        "statistics_template": "[{images}P {size}]",
        "numbering_mode": "sequential",
        "numbering_start": 1,
        "numbering_padding": 4,
    }
    create_resp = client.post("/api/organizer-profiles", json=create_payload)
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["name"] == "壁纸整理方案"
    assert created["is_builtin"] is False
    profile_id = created["id"]

    # 3. Get single profile
    get_resp = client.get(f"/api/organizer-profiles/{profile_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "壁纸整理方案"

    # 4. Update custom profile
    update_payload = dict(create_payload, description="更新后的描述")
    update_resp = client.put(f"/api/organizer-profiles/{profile_id}", json=update_payload)
    assert update_resp.status_code == 200
    assert update_resp.json()["description"] == "更新后的描述"

    # 5. Search profiles
    search_resp = client.get("/api/organizer-profiles?search=壁纸")
    assert search_resp.status_code == 200
    assert search_resp.json()["total"] == 1
    assert search_resp.json()["items"][0]["id"] == profile_id

    # 6. Delete custom profile
    del_resp = client.delete(f"/api/organizer-profiles/{profile_id}")
    assert del_resp.status_code == 200

    # Verify deleted
    get_after = client.get(f"/api/organizer-profiles/{profile_id}")
    assert get_after.status_code == 404


def test_clone_user_profile(tmp_path: Path):
    client, _ = _get_client(tmp_path)

    # Create profile first
    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "相册整理方案",
            "rename_template": "{name} {statistics}",
            "statistics_template": "[{images}P {videos}V {size}]",
        },
    )
    assert create_resp.status_code == 200
    orig_id = create_resp.json()["id"]

    # Clone profile -> should create "相册整理方案 - 副本"
    clone1_resp = client.post(f"/api/organizer-profiles/{orig_id}/clone")
    assert clone1_resp.status_code == 200
    cloned1 = clone1_resp.json()
    assert cloned1["name"] == "相册整理方案 - 副本"
    assert cloned1["is_builtin"] is False

    # Clone again -> should create "相册整理方案 - 副本 2"
    clone2_resp = client.post(f"/api/organizer-profiles/{orig_id}/clone")
    assert clone2_resp.status_code == 200
    cloned2 = clone2_resp.json()
    assert cloned2["name"] == "相册整理方案 - 副本 2"
    assert cloned2["is_builtin"] is False


def test_frontend_organizer_profile_source_contracts():
    fe_dir = Path(__file__).resolve().parent.parent / "frontend" / "src" / "pages" / "Organizer"
    list_code = (fe_dir / "ProfileList.tsx").read_text(encoding="utf-8")
    modal_code = (fe_dir / "ProfileFormModal.tsx").read_text(encoding="utf-8")
    preview_code = (fe_dir / "ProfilePreview.tsx").read_text(encoding="utf-8")

    assert "DirectoryPicker" in modal_code
    assert "DirectoryPicker" in preview_code
    assert "formatDateTime" in list_code
    assert "organizerProfilesApi" in list_code
    assert "organizerProfilesApi" in preview_code
