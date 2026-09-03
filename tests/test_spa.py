from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app


def test_spa_hosting_and_fallback(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config"
    config.mkdir()

    dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    has_real_dist = (dist_dir / "index.html").exists()

    settings = Settings(
        config_dir=config,
        data_mount=data,
        allowed_roots_raw=str(data),
        initial_admin_username="admin",
        initial_admin_password="test-password-123",
    )
    client = TestClient(create_app(settings))

    # 1. GET /health -> FastAPI handled (200 JSON)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    # 2. GET /api/unknown -> 404 JSON, NEVER swallowed by SPA fallback!
    api_404 = client.get("/api/unknown-endpoint-xyz")
    assert api_404.status_code == 404
    assert api_404.headers.get("content-type", "").startswith("application/json")

    # 3. GET /favicon.ico -> 200 image/x-icon
    fav_ico = client.get("/favicon.ico")
    assert fav_ico.status_code == 200
    assert "image/x-icon" in fav_ico.headers.get("content-type", "") or "image/vnd.microsoft.icon" in fav_ico.headers.get("content-type", "")

    # 4. GET /favicon.svg -> 200 image/svg+xml
    fav_svg = client.get("/favicon.svg")
    assert fav_svg.status_code == 200
    assert "image/svg+xml" in fav_svg.headers.get("content-type", "")

    # 5. GET /apple-touch-icon.png -> 200 image/png
    fav_png = client.get("/apple-touch-icon.png")
    assert fav_png.status_code == 200
    assert "image/png" in fav_png.headers.get("content-type", "")

    # 6. If dist exists, check SPA routes return HTML index
    if has_real_dist:
        for path in ["/", "/dashboard", "/scans", "/duplicates", "/tasks", "/settings", "/login"]:
            resp = client.get(path)
            assert resp.status_code == 200
            assert "text/html" in resp.headers.get("content-type", "")
            assert '<div id="root">' in resp.text
