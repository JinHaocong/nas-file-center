from __future__ import annotations

import json
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app
from app.models import AuditEvent, DuplicateFile, DuplicateGroup, ScanJob


def make_authenticated_client(tmp_path: Path, *, allow_mutation: bool = True):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        quarantine_root=data / ".trash",
        allow_mutation=allow_mutation,
        allow_delete=False,
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    client = TestClient(create_app(settings))
    client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "AdminPassword123!"},
        headers={"Origin": "http://testserver"},
    )
    return client, data, settings


def test_server_side_pagination_endpoints(tmp_path: Path):
    client, data, settings = make_authenticated_client(tmp_path)

    # 1. Create multiple index entries
    for i in range(5):
        dir_path = data / f"folder_{i}"
        dir_path.mkdir()
        (dir_path / f"file_{i}.txt").write_text(f"content {i}")
        client.app.state.service.reindex_root(str(dir_path))

    # 2. Test /api/indexes pagination
    p1 = client.get("/api/indexes?page=1&page_size=2").json()
    assert p1["total"] == 5
    assert len(p1["items"]) == 2
    assert p1["page"] == 1
    assert p1["page_size"] == 2

    p2 = client.get("/api/indexes?page=2&page_size=2").json()
    assert len(p2["items"]) == 2
    assert p2["page"] == 2

    p3 = client.get("/api/indexes?page=3&page_size=2").json()
    assert len(p3["items"]) == 1

    # 3. Create multiple plans
    for i in range(5):
        f = data / f"plan_src_{i}.txt"
        f.write_text("touch")
        client.post(
            "/api/plans",
            json={
                "name": f"plan_{i}",
                "kind": "touch",
                "items": [{"operation": "touch", "source": str(f)}],
            },
            headers={"Origin": "http://testserver"},
        )

    # Test /api/plans pagination
    plans_p1 = client.get("/api/plans?page=1&page_size=3").json()
    assert plans_p1["total"] == 5
    assert len(plans_p1["items"]) == 3
    assert plans_p1["page"] == 1

    plans_p2 = client.get("/api/plans?page=2&page_size=3").json()
    assert len(plans_p2["items"]) == 2
    assert plans_p2["page"] == 2


def test_plan_lifecycle_and_api_contract(tmp_path: Path):
    client, data, settings = make_authenticated_client(tmp_path, allow_mutation=True)

    # Prepare identical test files for deduplication verification
    f_keep = data / "original.jpg"
    f_dup = data / "duplicate.jpg"
    content = b"IDENTICAL_PHOTO_DATA_FOR_VERIFICATION"
    f_keep.write_bytes(content)
    f_dup.write_bytes(content)

    # 1. Create Dedupe Plan (Draft)
    create_resp = client.post(
        "/api/plans",
        json={
            "name": "Dedupe Photos Test",
            "kind": "dedupe",
            "items": [
                {
                    "operation": "quarantine",
                    "source": str(f_dup),
                    "keep": str(f_keep),
                    "expected_size": len(content),
                }
            ],
        },
        headers={"Origin": "http://testserver"},
    )
    assert create_resp.status_code == 200
    plan_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "draft"

    # Verify initial plan detail schema
    detail = client.get(f"/api/plans/{plan_id}").json()
    assert detail["id"] == plan_id
    assert detail["name"] == "Dedupe Photos Test"
    assert detail["kind"] == "dedupe"
    assert detail["status"] == "draft"
    assert detail["expected_changes"] == 1
    assert detail["total_items"] == 1
    assert len(detail["items"]) == 1
    item = detail["items"][0]
    assert item["operation"] == "quarantine"
    assert item["source"] == str(f_dup)
    assert item["keep"] == str(f_keep)
    assert item["expected_size"] == len(content)
    assert item["state"] == "planned"

    # 2. Freeze Plan
    freeze_resp = client.post(f"/api/plans/{plan_id}/freeze", headers={"Origin": "http://testserver"})
    assert freeze_resp.status_code == 200
    assert freeze_resp.json()["status"] == "frozen"

    # 3. Validate Plan (streaming SHA256 verification)
    validate_resp = client.post(f"/api/plans/{plan_id}/validate", headers={"Origin": "http://testserver"})
    assert validate_resp.status_code == 200
    val_data = validate_resp.json()
    # Contract: status must be 'ready'
    assert val_data["status"] == "ready"
    assert val_data["items"][0]["state"] == "validated"
    assert val_data["items"][0]["reason"] == "SHA256 verified"
    assert val_data["items"][0]["expected_hash"] is not None

    # Test /api/plans/{id}/items pagination endpoint
    items_page = client.get(f"/api/plans/{plan_id}/items?page=1&page_size=10").json()
    assert items_page["total"] == 1
    assert items_page["page"] == 1
    assert len(items_page["items"]) == 1
    assert items_page["items"][0]["state"] == "validated"

    # 4. Execute Plan on 'ready' status
    exec_resp = client.post(f"/api/plans/{plan_id}/execute", headers={"Origin": "http://testserver"})
    assert exec_resp.status_code == 200
    exec_data = exec_resp.json()
    assert exec_data["status"] == "queued"
    assert "work_job_id" in exec_data
    from app.worker import process_work_job
    process_work_job(settings, exec_data["work_job_id"])
    plan_after = client.get(f"/api/plans/{plan_id}").json()
    assert plan_after["status"] == "completed"
    assert plan_after["items"][0]["state"] == "completed"

    # Verify f_dup was safely quarantined and f_keep still exists
    assert f_keep.exists()
    assert not f_dup.exists()
