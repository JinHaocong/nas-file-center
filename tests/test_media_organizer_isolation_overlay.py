"""Opt-in deployment boundary must keep API read-only and Worker non-root.

Static Compose template checks only; real NAS ACLs and same-mount acceptance
are separate prerequisites. These tests never chmod/chown user storage.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("overlay", "api", "worker", "media_source"),
    [
        ("compose.v16-isolation.yaml", "api", "worker", "${HOST_DATA_DIR:"),
        (
            "compose.komodo.v16-isolation.yaml",
            "nas-file-center-api",
            "nas-file-center-worker",
            "${NFC_KOMODO_DATA_DIR:",
        ),
    ],
)
def test_v16_isolation_overlay_is_explicit_nonroot_and_worker_only_writable(
    overlay: str, api: str, worker: str, media_source: str,
):
    path = REPO_ROOT / overlay
    template = yaml.safe_load(path.read_text(encoding="utf-8"))
    services = template["services"]
    assert set(services) == {api, worker}

    api_service = services[api]
    worker_service = services[worker]
    assert api_service["user"].startswith("${NFC_API_UID:?")
    assert worker_service["user"].startswith("${NFC_WORKER_UID:?")
    assert "${NFC_SHARED_GID:?" in api_service["user"]
    assert "${NFC_SHARED_GID:?" in worker_service["user"]

    for service in (api_service, worker_service):
        assert "ALL" in service["cap_drop"]
        assert "no-new-privileges:true" in service["security_opt"]
        env = service["environment"]
        assert env["MEDIA_ORGANIZER_EXECUTION_ENABLED"] == "false"
        assert env["MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK"] == "false"

    assert len(api_service["volumes"]) == 1
    assert len(worker_service["volumes"]) == 1
    api_media = api_service["volumes"][0]
    worker_media = worker_service["volumes"][0]
    assert api_media.startswith(media_source)
    assert worker_media.startswith(media_source)
    assert api_media.endswith(":/data:ro")
    assert worker_media.endswith(":/data:rw")
    assert api_media.removesuffix("ro") == worker_media.removesuffix("rw")


def test_overlays_do_not_modify_base_production_compose_or_auto_enable_v16():
    for base in ("compose.yaml", "compose.komodo.yaml"):
        text = (REPO_ROOT / base).read_text(encoding="utf-8")
        assert "compose.v16-isolation.yaml" not in text
        assert "compose.komodo.v16-isolation.yaml" not in text
    assert "MEDIA_ORGANIZER_EXECUTION_ENABLED" in (
        REPO_ROOT / "app/config.py"
    ).read_text(encoding="utf-8")
