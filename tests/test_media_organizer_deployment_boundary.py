"""#403: test the rendered deployment model, not indentation in YAML.

Declaration regressions also run without Docker. Effective-mount checks use
Docker Compose's resolved JSON, never an emulated YAML merge. They neither
start containers nor mount the NAS. Real permission and ACL proof is separate.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
API_UID = "10001"
WORKER_UID = "10002"
SHARED_GID = "10000"


def _declaration(filename: str) -> dict:
    """Check supplied declarations locally; this does not emulate Compose merge."""
    return yaml.safe_load((ROOT / filename).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("filename", "api_name"),
    [("compose.cross-storage.yaml", "api"),
     ("compose.komodo.cross-storage.yaml", "nas-file-center-api")],
)
def test_cross_storage_overlay_never_grants_api_quarantine_write_access(
    filename: str, api_name: str,
) -> None:
    service = _declaration(filename)["services"][api_name]
    assert service["environment"]["QUARANTINE_ROOT"] == "/quarantine/.nas-file-center-trash"
    for mount in service["volumes"]:
        if isinstance(mount, str):
            assert mount.endswith(":ro"), "An overlay must not restore API quarantine writes"
        else:
            assert mount["read_only"] is True
            assert mount["bind"]["create_host_path"] is False


@pytest.mark.parametrize(
    ("filename", "api_name", "worker_name"),
    [("compose.archive-recovery-secrets.yaml", "api", "worker"),
     ("compose.komodo.archive-recovery-secrets.yaml", "nas-file-center-api", "nas-file-center-worker")],
)
def test_secret_overlays_preserve_shared_uid_volume_contract(
    filename: str, api_name: str, worker_name: str,
) -> None:
    model = _declaration(filename)
    sources = []
    for name in (api_name, worker_name):
        mounts = model["services"][name]["volumes"]
        selected = [mount for mount in mounts if mount.endswith(":/run/nfc-recovery-secrets")]
        assert len(selected) == 1
        sources.append(selected[0].split(":", 1)[0])
    assert sources[0] == sources[1]
    options = model["volumes"][sources[0]]["driver_opts"]["o"]
    assert "uid=${NFC_API_UID:-10001}" in options
    assert "gid=${NFC_SHARED_GID:-10000}" in options
    assert {"mode=2770", "noexec", "nosuid", "nodev"}.issubset(options.split(","))


def test_komodo_preserves_canonical_quarantine_and_masks_its_config_alias() -> None:
    model = _declaration("compose.komodo.yaml")
    for name, read_only in (("nas-file-center-api", True), ("nas-file-center-worker", False)):
        service = model["services"][name]
        assert "QUARANTINE_ROOT=/quarantine/.nas-file-center-trash" in service["environment"]
        mounts = {mount["target"]: mount for mount in service["volumes"] if isinstance(mount, dict)}
        quarantine = mounts["/quarantine/.nas-file-center-trash"]
        assert quarantine.get("read_only", False) is read_only
        assert quarantine["source"] == mounts["/config"]["source"] + "/.nas-file-center-trash"
        assert all(mount["bind"]["create_host_path"] is False for mount in mounts.values())
        assert mounts["/config"]["source"].startswith("${HOST_CONFIG_DIR:?")
        assert mounts["/data"]["source"].startswith("${HOST_DATA_DIR:?")
        if read_only:
            alias = mounts["/config/.nas-file-center-trash"]
            assert alias["source"] == quarantine["source"]
            assert alias["read_only"] is True


def test_komodo_retains_media_package_deployment_variables() -> None:
    model = _declaration("compose.komodo.yaml")
    for service in model["services"].values():
        assert "MEDIA_PACKAGE_ROOT=[[MEDIA_PACKAGE_ROOT]]" in service["environment"]
        assert "MEDIA_PACKAGE_FUSE_COMPAT_ENABLED=[[MEDIA_PACKAGE_FUSE_COMPAT_ENABLED]]" in service["environment"]


def _compose_model(path: Path, *overlays: Path, cwd: Path, extra_env: dict[str, str]) -> dict:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose CLI not installed; hosted CI checks the model")
    env = {
        **os.environ,
        "HOST_CONFIG_DIR": "/tmp/nfc-compose-test-config",
        "HOST_DATA_DIR": "/tmp/nfc-compose-test-media",
        "HOST_QUARANTINE_DIR": "/tmp/nfc-compose-test-quarantine",
        **extra_env,
    }
    command = ["docker", "compose"]
    for compose_file in (path, *overlays):
        command.extend(["-f", str(compose_file)])
    process = subprocess.run(
        [*command, "config", "--format", "json"],
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
    media = Path(_data_mount(api)["source"])
    assert _data_mount(worker)["source"] == str(media)
    for mount in api["volumes"]:
        if mount["type"] == "bind" and not mount.get("read_only", False):
            source = Path(mount["source"])
            assert not (source.is_relative_to(media) or media.is_relative_to(source)), (
                "API has writable media alias; config and media must be disjoint"
            )

    for service in (api, worker):
        assert service["read_only"] is True, "Container root filesystem must be read-only"
        assert "ALL" in service["cap_drop"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert not service.get("privileged", False)
        assert service["environment"]["MEDIA_ORGANIZER_EXECUTION_ENABLED"] == "false"
        assert service["environment"]["MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK"] == "false"


@pytest.mark.parametrize("config", ["/tmp/nfc-test-media", "/tmp", "/tmp/nfc-test-media/config"])
def test_media_model_guard_refuses_overlapping_writable_config(config: str) -> None:
    services = {}
    for name, uid in (("api", API_UID), ("worker", WORKER_UID)):
        services[name] = {
            "user": f"{uid}:{SHARED_GID}", "read_only": True,
            "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
            "environment": {"MEDIA_ORGANIZER_EXECUTION_ENABLED": "false",
                            "MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK": "false"},
            "volumes": [
                {"type": "bind", "source": "/tmp/nfc-test-media", "target": "/data", "read_only": name == "api"},
                {"type": "bind", "source": config, "target": "/config"},
            ],
        }
    with pytest.raises(AssertionError, match="API has writable media alias"):
        _assert_isolation({"services": services}, api_name="api", worker_name="worker")


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
            "HOST_DATA_DIR": str(tmp_path / "media"),
            "HOST_CONFIG_DIR": str(tmp_path / "config"),
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
    definition = model["volumes"][selected[0]]
    assert definition["driver"] == "local"
    opts = definition["driver_opts"]
    assert opts["type"] == "tmpfs" and opts["device"] == "tmpfs"
    options = set(opts["o"].split(","))
    assert {
        "size=1m", f"uid={API_UID}", f"gid={SHARED_GID}",
        "mode=2770", "noexec", "nosuid", "nodev",
    }.issubset(options)


def test_secret_model_guard_inspects_mounted_volume_not_unused_safe_definition() -> None:
    safe = {
        "driver": "local",
        "driver_opts": {"type": "tmpfs", "device": "tmpfs",
                        "o": "size=1m,uid=10001,gid=10000,mode=2770,noexec,nosuid,nodev"},
    }
    legacy = {
        "driver": "local",
        "driver_opts": {"type": "tmpfs", "device": "tmpfs", "o": "size=1m,mode=0700"},
    }
    service = {
        "volumes": [{"type": "volume", "source": "legacy-secret", "target": "/run/nfc-recovery-secrets"}],
        "environment": {"NFC_SECRET_OWNER_UID": API_UID, "NFC_SECRET_GROUP_GID": SHARED_GID},
    }
    model = {"services": {"api": service, "worker": service},
             "volumes": {"nfc-recovery-secrets": safe, "legacy-secret": legacy}}
    with pytest.raises(AssertionError):
        _assert_shared_ram_secret_volume(model, "api", "worker")


def _assert_quarantine_boundary(model: dict, api_name: str, worker_name: str) -> None:
    """Lexical bind coverage in a rendered model, not host symlink/ACL proof."""
    root = "/quarantine/.nas-file-center-trash"
    api = model["services"][api_name]
    worker = model["services"][worker_name]
    selected = []
    for service, read_only in ((api, True), (worker, False)):
        assert service["environment"]["CONFIG_DIR"] == "/config"
        assert service["environment"]["QUARANTINE_ROOT"] == root
        mounts = [mount for mount in service["volumes"] if mount["target"] == root]
        assert len(mounts) == 1 and mounts[0]["type"] == "bind"
        assert mounts[0].get("read_only", False) is read_only
        assert mounts[0].get("bind", {}).get("create_host_path", False) is False
        selected.append(Path(mounts[0]["source"]))
    assert selected[0] == selected[1], "API and Worker must refer to the same quarantine"
    for mount in api["volumes"]:
        if mount["type"] != "bind" or mount.get("read_only", False):
            continue
        source = Path(mount["source"])
        assert not source.is_relative_to(selected[0]), "Writable bind exposes quarantine subtree"
        if selected[0].is_relative_to(source):
            alias = Path(mount["target"]) / selected[0].relative_to(source)
            masks = [candidate for candidate in api["volumes"]
                     if candidate["target"] == str(alias)]
            assert len(masks) == 1, f"Uncovered writable quarantine alias: {alias}"
            assert masks[0]["source"] == str(selected[0])
            assert masks[0].get("read_only", False) is True


def test_quarantine_model_guard_refuses_writable_subtree_alias() -> None:
    source = "/tmp/nfc-test-quarantine/.nas-file-center-trash"
    canonical = "/quarantine/.nas-file-center-trash"
    environment = {"CONFIG_DIR": "/config", "QUARANTINE_ROOT": canonical}
    model = {"services": {
        "api": {"environment": environment, "volumes": [
            {"type": "bind", "source": source, "target": canonical, "read_only": True},
            {"type": "bind", "source": source + "/app-config", "target": "/config"},
        ]},
        "worker": {"environment": environment, "volumes": [
            {"type": "bind", "source": source, "target": canonical},
        ]},
    }}
    with pytest.raises(AssertionError, match="Writable bind exposes quarantine subtree"):
        _assert_quarantine_boundary(model, "api", "worker")


@pytest.mark.parametrize("komodo", [False, True])
@pytest.mark.parametrize("with_secrets", [False, True])
def test_merged_cross_storage_preserves_paths_and_security(
    tmp_path: Path, komodo: bool, with_secrets: bool,
) -> None:
    prefix = "compose.komodo" if komodo else "compose"
    (tmp_path / ".env").write_text("", encoding="utf-8")
    filenames = [f"{prefix}.yaml", f"{prefix}.cross-storage.yaml"]
    if with_secrets:
        filenames.append(f"{prefix}.archive-recovery-secrets.yaml")
    paths = []
    for name in filenames:
        target = tmp_path / name
        target.write_text((ROOT / name).read_text(encoding="utf-8"), encoding="utf-8")
        paths.append(target)
    model = _compose_model(
        *paths, cwd=tmp_path,
        extra_env={"HOST_CONFIG_DIR": str(tmp_path / "config"),
                   "HOST_DATA_DIR": str(tmp_path / "media"),
                   "HOST_QUARANTINE_DIR": str(tmp_path / "external-quarantine"),
                   "DATA_MODE": "rw", "NFC_API_UID": API_UID,
                   "NFC_WORKER_UID": WORKER_UID, "NFC_SHARED_GID": SHARED_GID},
    )
    api_name, worker_name = (("nas-file-center-api", "nas-file-center-worker")
                             if komodo else ("api", "worker"))
    _assert_isolation(model, api_name=api_name, worker_name=worker_name)
    _assert_quarantine_boundary(model, api_name, worker_name)
    _assert_shared_ram_secret_volume(model, api_name, worker_name)
    for service in model["services"].values():
        assert not any(mount["target"] == "/quarantine" for mount in service["volumes"])
        leaf = next(mount for mount in service["volumes"]
                    if mount["target"] == "/quarantine/.nas-file-center-trash")
        # Legacy HOST_QUARANTINE_DIR is still the parent, not the leaf itself.
        assert leaf["source"] == str(tmp_path / "external-quarantine" / ".nas-file-center-trash")


@pytest.mark.parametrize("quarantine_subdir", ["", "nested"])
def test_merged_komodo_checks_actual_nested_source_alias(
    tmp_path: Path, quarantine_subdir: str,
) -> None:
    config = tmp_path / "config"
    model = _compose_model(
        ROOT / "compose.komodo.yaml", ROOT / "compose.komodo.cross-storage.yaml",
        ROOT / "compose.komodo.archive-recovery-secrets.yaml", cwd=ROOT,
        extra_env={"HOST_CONFIG_DIR": str(config), "HOST_DATA_DIR": str(tmp_path / "media"),
                   "HOST_QUARANTINE_DIR": str(config / quarantine_subdir),
                   "NFC_API_UID": API_UID, "NFC_WORKER_UID": WORKER_UID,
                   "NFC_SHARED_GID": SHARED_GID},
    )
    if quarantine_subdir:
        # A mask for config/.trash cannot protect config/nested/.trash. Such
        # custom layouts still need an operator-proven mount, never a blind ACK.
        with pytest.raises(AssertionError, match="Uncovered writable quarantine alias"):
            _assert_quarantine_boundary(model, "nas-file-center-api", "nas-file-center-worker")
    else:
        _assert_quarantine_boundary(model, "nas-file-center-api", "nas-file-center-worker")


def test_local_archive_password_channel_uses_shared_memory_volume(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("", encoding="utf-8")
    local_compose = tmp_path / "compose.yaml"
    local_compose.write_text(
        (ROOT / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    model = _compose_model(
        local_compose, cwd=tmp_path,
        extra_env={"HOST_DATA_DIR": str(tmp_path / "media"), "HOST_CONFIG_DIR": str(tmp_path / "config"),
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
