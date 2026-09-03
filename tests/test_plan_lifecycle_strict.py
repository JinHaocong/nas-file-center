from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


def test_strict_plan_lifecycle_draft_frozen_ready_execution(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    f = data / "test_file.txt"
    f.write_text("sample content")

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

    # 1. Create Plan -> status: draft
    create_resp = client.post(
        "/api/plans",
        json={
            "name": "Strict Lifecycle Plan",
            "kind": "touch",
            "items": [{"operation": "touch", "source": str(f)}],
        },
    )
    assert create_resp.status_code == 200
    plan_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "draft"

    # 2. Attempt to execute DRAFT plan -> MUST BE REJECTED (409)
    exec_draft = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_draft.status_code == 409
    assert "Plan must be validated before execution" in exec_draft.json()["detail"]

    # 3. Freeze Plan -> status: frozen
    freeze_resp = client.post(f"/api/plans/{plan_id}/freeze")
    assert freeze_resp.status_code == 200
    assert freeze_resp.json()["status"] == "frozen"

    # 4. Attempt to execute FROZEN plan without validation -> MUST BE REJECTED (409)
    exec_frozen = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_frozen.status_code == 409
    assert "Plan must be validated before execution" in exec_frozen.json()["detail"]

    # 5. Validate Plan -> status: ready
    val_resp = client.post(f"/api/plans/{plan_id}/validate")
    assert val_resp.status_code == 200
    assert val_resp.json()["status"] == "ready"

    # 6. Execute READY plan -> MUST SUCCEED (200)
    exec_ready = client.post(f"/api/plans/{plan_id}/execute")
    assert exec_ready.status_code == 200
    assert exec_ready.json()["status"] == "completed"
    assert exec_ready.json()["items"][0]["state"] == "completed"
