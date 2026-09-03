from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FORBIDDEN_CDN_PATTERNS = [
    "cdn.jsdelivr.net",
    "fastapi.tiangolo.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "unpkg.com",
    "cdnjs.cloudflare.com",
    "cdn.bootcdn.net",
    "ajax.googleapis.com",
]


def test_no_runtime_public_cdn_in_responses(tmp_path: Path):
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

    dist_dir = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    has_real_dist = (dist_dir / "index.html").exists()

    # 1. Check Root SPA HTML if dist exists
    if has_real_dist:
        root_resp = client.get("/")
        assert root_resp.status_code == 200
        root_text = root_resp.text
        for cdn in FORBIDDEN_CDN_PATTERNS:
            assert cdn not in root_text, f"Found public CDN pattern {cdn} in root HTML"

    # 2. Check /docs and /redoc are disabled (404)
    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 404

    redoc_resp = client.get("/redoc")
    assert redoc_resp.status_code == 404

    # 3. Check /openapi.json
    client.headers.update({"Origin": "http://testserver"})
    client.post("/api/auth/login", json={"username": "admin", "password": "AdminPassword123!"})
    openapi_resp = client.get("/openapi.json")
    assert openapi_resp.status_code == 200
    openapi_text = openapi_resp.text
    for cdn in FORBIDDEN_CDN_PATTERNS:
        assert cdn not in openapi_text, f"Found public CDN pattern {cdn} in openapi.json"


def test_frontend_source_contains_no_external_cdn_scripts_or_styles():
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    index_html = frontend_dir / "index.html"
    assert index_html.exists()

    content = index_html.read_text(encoding="utf-8")
    for cdn in FORBIDDEN_CDN_PATTERNS:
        assert cdn not in content, f"Found public CDN pattern {cdn} in frontend/index.html"
