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



def test_real_nas_acceptance_pulls_the_verified_candidate_without_building_on_nas():
    root = Path(__file__).resolve().parent.parent
    compose = yaml.safe_load(
        (root / "compose.v16-real-nas-acceptance.yaml").read_text(encoding="utf-8")
    )
    runner = (root / "scripts/run_v16_real_nas_acceptance.sh").read_text(encoding="utf-8")
    service = compose["services"]["v16-real-nas-acceptance"]

    assert "build" not in service
    assert service["image"] == (
        "kerwinjhc/nas-file-center@sha256:"
        "c5ceaf32813ddc1b3955b661c91c9ca923040ec34d58961003d47e17642d0d32"
    )
    assert service["read_only"] is True
    assert service["network_mode"] == "none"
    assert service.get("user") is None  # image's verified 10001:10000 default
    mounts = {item["target"]: item for item in service["volumes"]}
    assert mounts["/nas/v16-acceptance"]["read_only"] is False
    assert mounts["/tmp/media_organizer_v16_real_nas_acceptance.py"]["read_only"] is True
    assert mounts["/evidence"]["read_only"] is False
    assert mounts["/evidence"]["bind"]["create_host_path"] is False
    assert "--build" not in runner
    assert 'docker compose -f "$COMPOSE_FILE" pull v16-real-nas-acceptance' in runner
    assert 'docker compose -f "$COMPOSE_FILE" run --rm v16-real-nas-acceptance' in runner
