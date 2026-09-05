from __future__ import annotations

import json
from pathlib import Path
import tomllib
import pytest

from app.main import create_app

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_fastapi_backend_version():
    app = create_app()
    assert app.version == "0.3.3", f"FastAPI app.version must be '0.3.3', got '{app.version}'"


def test_pyproject_version():
    pyproject_path = ROOT_DIR / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)
    version = data.get("project", {}).get("version")
    assert version == "0.3.3", f"pyproject.toml version must be '0.3.3', got '{version}'"


def test_frontend_package_json_version():
    package_path = ROOT_DIR / "frontend" / "package.json"
    with open(package_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    version = data.get("version")
    assert version == "0.3.3", f"frontend/package.json version must be '0.3.3', got '{version}'"


def test_frontend_package_lock_version():
    lock_path = ROOT_DIR / "frontend" / "package-lock.json"
    with open(lock_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("version") == "0.3.3", f"package-lock.json top-level version must be '0.3.3', got '{data.get('version')}'"
    root_pkg_version = data.get("packages", {}).get("", {}).get("version")
    assert root_pkg_version == "0.3.3", f"package-lock.json packages['']['version'] must be '0.3.3', got '{root_pkg_version}'"


def test_login_page_version():
    login_path = ROOT_DIR / "frontend" / "src" / "pages" / "Login" / "index.tsx"
    content = login_path.read_text(encoding="utf-8")
    assert "v0.3.3" in content, "Login page must display 'v0.3.3'"
    assert "v0.3.2" not in content, "Login page must not contain legacy 'v0.3.2'"


def test_sidebar_component_version():
    sidebar_path = ROOT_DIR / "frontend" / "src" / "components" / "Sidebar.tsx"
    content = sidebar_path.read_text(encoding="utf-8")
    assert "v0.3.3" in content, "Sidebar must display 'v0.3.3'"
    assert "v0.3.2" not in content, "Sidebar must not contain legacy 'v0.3.2'"
