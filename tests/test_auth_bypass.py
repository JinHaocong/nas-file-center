from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


def test_unauthenticated_cannot_access_legacy_ui_or_execute_actions(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        initial_admin_username="admin",
        initial_admin_password="AdminPassword123!",
    )
    client = TestClient(create_app(settings))

    # 1. Verify all legacy /ui/* routes are removed / return 404
    legacy_routes = [
        "/ui",
        "/ui/dashboard",
        "/ui/scans",
        "/ui/scans/1",
        "/ui/plans",
        "/ui/plans/1",
        "/ui/jobs",
        "/ui/audit",
        "/ui/settings",
        "/ui/indexes",
    ]
    for route in legacy_routes:
        resp = client.get(route)
        assert resp.status_code == 404, f"Route {route} should return 404"

    # 2. Verify legacy mutation routes return 404
    legacy_mutations = [
        ("/ui/plans/1/execute", "POST"),
        ("/ui/plans/1/freeze", "POST"),
        ("/ui/scans", "POST"),
        ("/ui/rename", "POST"),
        ("/ui/organizer", "POST"),
    ]
    for route, method in legacy_mutations:
        resp = client.request(method, route, data={"x": "y"})
        assert resp.status_code == 404, f"Legacy mutation {route} should return 404"

    # 3. Verify unauthenticated API mutations are strictly 401 Unauthorized
    api_mutations = [
        ("/api/plans/1/execute", "POST", {}),
        ("/api/plans/1/freeze", "POST", {}),
        ("/api/plans/1/validate", "POST", {}),
        ("/api/plans", "POST", {"name": "test", "kind": "touch", "items": [{"operation": "touch", "source": "/data/a"}]}),
        ("/api/scans", "POST", {"name": "test", "roots": ["/data"]}),
        ("/api/indexes", "POST", {"root": "/data"}),
        ("/api/auth/change-password", "POST", {"old_password": "x", "new_password": "y"}),
    ]
    for route, method, payload in api_mutations:
        resp = client.request(method, route, json=payload)
        assert resp.status_code == 401, f"API mutation {route} should return 401"

    # 4. Verify unauthenticated API queries are strictly 401 Unauthorized
    api_queries = [
        "/api/dashboard/summary",
        "/api/scans",
        "/api/scans/1",
        "/api/scans/1/groups",
        "/api/plans",
        "/api/plans/1",
        "/api/work-jobs",
        "/api/audit",
        "/api/settings",
        "/api/indexes",
        "/api/auth/me",
        "/api/auth/sessions",
    ]
    for route in api_queries:
        resp = client.get(route)
        assert resp.status_code == 401, f"API query {route} should return 401"

    # 5. Verify /docs and /redoc are disabled (404), /openapi.json requires authentication (401)
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 401

    # 6. Verify /health remains public
    health_resp = client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "ok"
