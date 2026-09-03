from __future__ import annotations

from pathlib import Path
import yaml
import pytest


def test_komodo_compose_and_readme_deployment_consistency():
    root = Path(__file__).resolve().parent.parent
    komodo_compose = root / "compose.komodo.yaml"
    readme = root / "README.md"
    config_env = root / "config.example.env"

    assert komodo_compose.exists()
    assert readme.exists()
    assert config_env.exists()

    komodo_text = komodo_compose.read_text(encoding="utf-8")
    readme_text = readme.read_text(encoding="utf-8")
    env_text = config_env.read_text(encoding="utf-8")

    # 1. Ensure NO host port 8089 or "ports:" mapping in compose.komodo.yaml
    parsed_komodo = yaml.safe_load(komodo_text)
    api_service = parsed_komodo["services"]["nas-file-center-api"]
    assert "ports" not in api_service, "compose.komodo.yaml must NOT expose host ports"
    assert "8089" not in komodo_text

    # 2. Ensure NO hardcoded admin password in compose.komodo.yaml
    assert "admin123456" not in komodo_text
    assert "admin123456" not in readme_text

    # 3. Ensure SESSION_COOKIE_SECURE=true is set in compose.komodo.yaml and mentioned in docs
    assert "SESSION_COOKIE_SECURE=true" in komodo_text
    assert "SESSION_COOKIE_SECURE=true" in readme_text
    assert "SESSION_COOKIE_SECURE=true" in env_text

    # 4. Ensure Zoraxy and nginx_network deployment architecture is documented
    assert "file.kerwin.cloud" in readme_text
    assert "Zoraxy" in readme_text
    assert "nginx_network" in readme_text
    assert parsed_komodo["networks"]["nginx_network"]["external"] is True
