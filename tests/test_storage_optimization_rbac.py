from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth.password import hash_password
from app.config import Settings
from app.main import create_app
from app.models import DuplicateFile, DuplicateGroup, ScanJob, User, utcnow


def _api_env(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    settings = Settings(
        config_dir=config,
        data_mount=data,
        quarantine_root=quarantine,
        allowed_roots_raw=str(data),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
        allow_mutation=True,
    )
    app = create_app(settings)
    service = app.state.service
    with service.SessionLocal() as session:
        session.add(User(
            username="member",
            password_hash=hash_password("MemberPassword123!"),
            role="user",
            is_active=True,
        ))
        session.commit()

    left = data / "left.bin"
    right = data / "right.bin"
    left.write_bytes(b"same" * 256)
    right.write_bytes(b"same" * 256)
    with service.SessionLocal() as session:
        scan = ScanJob(
            id=950,
            name="storage-rbac",
            mode="normal",
            roots_json=json.dumps([str(data)]),
            status="completed",
            started_at=utcnow(),
            finished_at=utcnow(),
            total_groups=1,
            total_files_in_groups=2,
            reclaimable_bytes=1024,
        )
        session.add(scan)
        group = DuplicateGroup(
            scan_job_id=950,
            content_hash="discovery-hash",
            file_size=1024,
            member_count=2,
        )
        session.add(group)
        session.flush()
        for path, mtime in ((left, 1000), (right, 2000)):
            session.add(DuplicateFile(
                group_id=group.id,
                root_id=0,
                absolute_path=str(path),
                relative_path=path.name,
                top_level_dir=str(data),
                size=1024,
                mtime_ns=mtime,
                device=0,
                inode=0,
            ))
        session.commit()

    return TestClient(app), service


def _login(client: TestClient, username: str, password: str):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 200


def test_member_can_preview_but_cannot_generate_hardlink_plan(tmp_path: Path):
    client, _ = _api_env(tmp_path)
    _login(client, "member", "MemberPassword123!")

    preview = client.post(
        "/api/scans/950/dedupe-preview",
        json={"scorer_config": {}, "storage_action": "hardlink"},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200
    digest = preview.json()["preview_digest"]

    generate = client.post(
        "/api/scans/950/dedupe-plan",
        json={
            "scorer_config": {},
            "expected_preview_digest": digest,
            "storage_action": "hardlink",
        },
        headers={"Origin": "http://testserver"},
    )
    assert generate.status_code == 403


def test_admin_can_generate_hardlink_plan(tmp_path: Path):
    client, _ = _api_env(tmp_path)
    _login(client, "admin", "AdminPassword123!")

    preview = client.post(
        "/api/scans/950/dedupe-preview",
        json={"scorer_config": {}, "storage_action": "hardlink"},
        headers={"Origin": "http://testserver"},
    )
    assert preview.status_code == 200

    generate = client.post(
        "/api/scans/950/dedupe-plan",
        json={
            "scorer_config": {},
            "expected_preview_digest": preview.json()["preview_digest"],
            "storage_action": "hardlink",
        },
        headers={"Origin": "http://testserver"},
    )
    assert generate.status_code == 200
    assert generate.json()["status"] == "draft"


def test_non_advanced_hardlink_request_is_rejected(tmp_path: Path):
    client, _ = _api_env(tmp_path)
    _login(client, "admin", "AdminPassword123!")

    response = client.post(
        "/api/scans/950/dedupe-plan",
        json={"policy": "balanced-roots", "storage_action": "hardlink"},
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 422


def test_member_cannot_freeze_restricted_optimization_plan(tmp_path: Path):
    client, service = _api_env(tmp_path)
    _login(client, "admin", "AdminPassword123!")
    preview = client.post(
        "/api/scans/950/dedupe-preview",
        json={"scorer_config": {}, "storage_action": "hardlink"},
        headers={"Origin": "http://testserver"},
    ).json()
    generated = client.post(
        "/api/scans/950/dedupe-plan",
        json={
            "scorer_config": {},
            "expected_preview_digest": preview["preview_digest"],
            "storage_action": "hardlink",
        },
        headers={"Origin": "http://testserver"},
    ).json()

    _login(client, "member", "MemberPassword123!")
    response = client.post(
        f"/api/plans/{generated['id']}/freeze",
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 403
