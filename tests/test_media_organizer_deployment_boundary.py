"""#403: test the rendered deployment model, not indentation in YAML.

These tests inspect Docker Compose's resolved JSON only.  They neither start
containers nor mount the NAS.  Real permission and ACL proof remains separate.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
API_UID = "10001"
WORKER_UID = "10002"
SHARED_GID = "10000"


def _compose_model(path: Path, *, cwd: Path, extra_env: dict[str, str]) -> dict:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose CLI not installed; hosted CI checks the model")
    env = {**os.environ, **extra_env}
    process = subprocess.run(
        ["docker", "compose", "-f", str(path), "config", "--format", "json"],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def _data_mount(service: dict) -> dict:
    matches = [volume for volume in service["volumes"] if volume["target"] == "/data"]
    assert len(matches) == 1, "Each service must have one explicit /data mount"
    assert matches[0]["type"] == "bind"
    return matches[0]


def _assert_isolation(model: dict, *, api_name: str, worker_name: str) -> None:
    api = model["services"][api_name]
    worker = model["services"][worker_name]

    assert api["user"] == f"{API_UID}:{SHARED_GID}"
    assert worker["user"] == f"{WORKER_UID}:{SHARED_GID}"
    assert API_UID != WORKER_UID
    assert _data_mount(api)["read_only"] is True
    # Compose JSON omits read_only for a normal writable bind.
    assert _data_mount(worker).get("read_only", False) is False

    for service in (api, worker):
        assert service["read_only"] is True, "Container root filesystem must be read-only"
        assert "ALL" in service["cap_drop"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert not service.get("privileged", False)
        assert service["environment"]["MEDIA_ORGANIZER_EXECUTION_ENABLED"] == "false"
        assert service["environment"]["MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK"] == "false"


def test_komodo_deployment_separates_media_mutation_principals() -> None:
    model = _compose_model(
        ROOT / "compose.komodo.yaml",
        cwd=ROOT,
        extra_env={
            "NFC_API_UID": API_UID,
            "NFC_WORKER_UID": WORKER_UID,
            "NFC_SHARED_GID": SHARED_GID,
        },
    )
    _assert_isolation(
        model, api_name="nas-file-center-api", worker_name="nas-file-center-worker"
    )


def test_local_compose_separates_media_mutation_principals(tmp_path: Path) -> None:
    # An isolated test .env is necessary because the project does not commit
    # local deploy secrets. docker compose config does NOT start containers.
    (tmp_path / ".env").write_text("", encoding="utf-8")
    local_compose = tmp_path / "compose.yaml"
    local_compose.write_text(
        (ROOT / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    model = _compose_model(
        local_compose,
        cwd=tmp_path,
        extra_env={
            "HOST_DATA_DIR": str(tmp_path),
            "HOST_CONFIG_DIR": str(tmp_path),
            "DATA_MODE": "rw",
            "NFC_API_UID": API_UID,
            "NFC_WORKER_UID": WORKER_UID,
            "NFC_SHARED_GID": SHARED_GID,
        },
    )
    _assert_isolation(model, api_name="api", worker_name="worker")


def test_dockerfile_final_stage_has_unprivileged_default_user() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = dockerfile.split("FROM python:3.12-slim-bookworm", maxsplit=1)[1]
    user_directives = [
        line.split(maxsplit=1)[1].strip()
        for line in runtime.splitlines()
        if line.startswith("USER ")
    ]
    assert user_directives == [f"{API_UID}:{SHARED_GID}"]


def _assert_shared_ram_secret_volume(model: dict, api_name: str, worker_name: str) -> None:
    """Both distinct principals must mount ONE shared tmpfs-backed Docker volume."""
    services = model["services"]
    selected = []
    for service_name in (api_name, worker_name):
        service = services[service_name]
        mounts = [
            v for v in service["volumes"]
            if v["target"] == "/run/nfc-recovery-secrets"
        ]
        assert len(mounts) == 1
        assert mounts[0]["type"] == "volume"
        assert not mounts[0].get("read_only", False)
        selected.append(mounts[0]["source"])
        assert service["environment"]["NFC_SECRET_OWNER_UID"] == API_UID
        assert service["environment"]["NFC_SECRET_GROUP_GID"] == SHARED_GID
    assert selected[0] == selected[1]
    definition = model["volumes"]["nfc-recovery-secrets"]
    assert definition["driver"] == "local"
    opts = definition["driver_opts"]
    assert opts["type"] == "tmpfs" and opts["device"] == "tmpfs"
    options = set(opts["o"].split(","))
    assert {
        "size=1m", f"uid={API_UID}", f"gid={SHARED_GID}",
        "mode=2770", "noexec", "nosuid", "nodev",
    }.issubset(options)


def test_local_archive_password_channel_uses_shared_memory_volume(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("", encoding="utf-8")
    local_compose = tmp_path / "compose.yaml"
    local_compose.write_text(
        (ROOT / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    model = _compose_model(
        local_compose, cwd=tmp_path,
        extra_env={"HOST_DATA_DIR": str(tmp_path), "HOST_CONFIG_DIR": str(tmp_path),
                   "NFC_API_UID": API_UID, "NFC_WORKER_UID": WORKER_UID,
                   "NFC_SHARED_GID": SHARED_GID},
    )
    _assert_shared_ram_secret_volume(model, "api", "worker")


def test_komodo_archive_password_channel_uses_shared_memory_volume() -> None:
    model = _compose_model(
        ROOT / "compose.komodo.yaml", cwd=ROOT,
        extra_env={"NFC_API_UID": API_UID, "NFC_WORKER_UID": WORKER_UID,
                   "NFC_SHARED_GID": SHARED_GID},
    )
    _assert_shared_ram_secret_volume(model, "nas-file-center-api", "nas-file-center-worker")
