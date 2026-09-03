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
    return client, data, config


def test_builtin_profile_cannot_be_deleted_or_directly_mutated(tmp_path: Path):
    from app.models import OrganizerProfile
    client, data, config = _get_client(tmp_path)

    # Create a profile and mark it is_builtin in DB
    create_resp = client.post("/api/organizer-profiles", json={"name": "内置方案测试"})
    assert create_resp.status_code == 200
    builtin_id = create_resp.json()["id"]

    # Directly set is_builtin=True in DB to test protection
    SessionLocal = client.app.state.service.SessionLocal
    with SessionLocal() as session:
        p = session.get(OrganizerProfile, builtin_id)
        p.is_builtin = True
        session.commit()

    # Delete -> 400
    del_resp = client.delete(f"/api/organizer-profiles/{builtin_id}")
    assert del_resp.status_code == 400
    assert "系统内置方案禁止删除" in del_resp.json()["detail"]

    # Put direct mutation -> 400
    put_resp = client.put(f"/api/organizer-profiles/{builtin_id}", json={"name": "篡改名称"})
    assert put_resp.status_code == 400
    assert "系统内置方案禁止直接修改" in put_resp.json()["detail"]


def test_organizer_profile_root_pathguard_security(tmp_path: Path):
    client, data, _ = _get_client(tmp_path)

    # Creating profile with root outside allowed_roots -> 400
    bad_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "越界方案",
            "root": "/etc/shadow",
            "rename_template": "{name} {statistics}",
            "statistics_template": "[{images}P {size}]",
        },
    )
    assert bad_resp.status_code == 400
    assert "outside" in bad_resp.json()["detail"].lower()


def test_preview_is_strictly_read_only(tmp_path: Path):
    client, data, _ = _get_client(tmp_path)
    root = data / "测试目录"
    root.mkdir()
    sub1 = root / "001 A"
    sub1.mkdir()
    (sub1 / "img.jpg").write_bytes(b"123")
    original_mtime = sub1.stat().st_mtime_ns

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "只读测试方案",
            "rename_template": "{name} {statistics}",
            "statistics_template": "[{images}P {videos}V {size}]",
        },
    )
    profile_id = create_resp.json()["id"]

    # Preview
    prev_resp = client.post(
        f"/api/organizer-profiles/{profile_id}/preview",
        json={"root": str(root)},
    )
    assert prev_resp.status_code == 200
    proposals = prev_resp.json()["proposals"]
    assert len(proposals) == 1
    assert proposals[0]["changed"] is True

    # Assert directory name is STILL unchanged and mtime is untouched!
    assert sub1.exists()
    assert sub1.stat().st_mtime_ns == original_mtime
    assert not (root / "001 A [1P 0.0MB]").exists()


def test_conflict_detection_prevents_plan_creation(tmp_path: Path):
    client, data, _ = _get_client(tmp_path)
    root = data / "冲突测试"
    root.mkdir()

    # Two directories that would clean to the same target name
    d1 = root / "Item [10P 1MB]"
    d2 = root / "Item [20P 2MB]"
    d1.mkdir()
    d2.mkdir()
    (d1 / "a.jpg").write_bytes(b"a")
    (d2 / "b.jpg").write_bytes(b"b")

    create_resp = client.post(
        "/api/organizer-profiles",
        json={
            "name": "冲突测试方案",
            "rename_template": "{name} {statistics}",
            "statistics_template": "[{images}P {videos}V {size}]",
            "cleanup_patterns": [r"\s+\[\d+P\s+\d+MB\]$"],
        },
    )
    profile_id = create_resp.json()["id"]

    # Preview should detect collision
    prev_resp = client.post(
        f"/api/organizer-profiles/{profile_id}/preview",
        json={"root": str(root)},
    )
    assert prev_resp.status_code == 200
    summary = prev_resp.json()["summary"]
    assert summary["conflicts"] >= 1

    # Plan creation must be blocked
    plan_resp = client.post(
        f"/api/organizer-profiles/{profile_id}/plan",
        json={"root": str(root)},
    )
    assert plan_resp.status_code == 400
    assert "冲突项" in plan_resp.json()["detail"]
