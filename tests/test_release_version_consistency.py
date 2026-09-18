from __future__ import annotations

import json
from pathlib import Path
import tomllib

from app.main import create_app

ROOT_DIR = Path(__file__).resolve().parent.parent
RELEASE_VERSION = "0.4.0"
KOMODO_IMAGE_VERSION = "0.4.0.1"


def test_fastapi_backend_version():
    app = create_app()
    assert app.version == RELEASE_VERSION, (
        f"FastAPI app.version must be '{RELEASE_VERSION}', got '{app.version}'"
    )


def test_pyproject_version():
    pyproject_path = ROOT_DIR / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    version = data.get("project", {}).get("version")
    assert version == RELEASE_VERSION


def test_frontend_package_json_version():
    package_path = ROOT_DIR / "frontend" / "package.json"
    with open(package_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("version") == RELEASE_VERSION


def test_frontend_package_lock_version():
    lock_path = ROOT_DIR / "frontend" / "package-lock.json"
    with open(lock_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("version") == RELEASE_VERSION
    assert data.get("packages", {}).get("", {}).get("version") == RELEASE_VERSION


def test_login_page_version():
    content = (ROOT_DIR / "frontend" / "src" / "pages" / "Login" / "index.tsx").read_text(
        encoding="utf-8"
    )
    assert f"v{RELEASE_VERSION}" in content


def test_sidebar_component_version():
    content = (ROOT_DIR / "frontend" / "src" / "components" / "Sidebar.tsx").read_text(
        encoding="utf-8"
    )
    assert f"v{RELEASE_VERSION}" in content


def test_compose_yaml_version():
    content = (ROOT_DIR / "compose.yaml").read_text(encoding="utf-8")
    assert f"nas-file-center:{RELEASE_VERSION}" in content


def test_compose_komodo_yaml_version():
    content = (ROOT_DIR / "compose.komodo.yaml").read_text(encoding="utf-8")
    assert f"kerwinjhc/nas-file-center:{KOMODO_IMAGE_VERSION}" in content
    assert ":latest" not in content
