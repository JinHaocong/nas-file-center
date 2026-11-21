#!/usr/bin/env bash
# CI-only static Compose render. No Docker up, no media writes, no NAS mounts.
set -Eeuo pipefail
command -v docker >/dev/null
command -v python3 >/dev/null

scratch="$(mktemp -d "${RUNNER_TEMP:-/tmp}/nfc-v162-compose-XXXXXXXX")"
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$scratch/config/.nas-file-center-trash" "$scratch/data"
export NFC_V162_IMAGE="nfc:v162-ci-placeholder"
export NFC_V162_SCRATCH_CONFIG_DIR="$scratch/config"
export NFC_V162_SCRATCH_DATA_DIR="$scratch/data"
export NFC_V162_SCRATCH_ADMIN_USERNAME="synthetic-admin"
export NFC_V162_SCRATCH_ADMIN_PASSWORD="synthetic-test-only-password"

docker compose -f compose.v162-nas-compat-scratch.yaml config --format json > "$scratch/model.json"
python3 - "$scratch/model.json" "$scratch" <<'PY'
import json
import pathlib
import sys

model = json.loads(pathlib.Path(sys.argv[1]).read_text())
scratch = pathlib.Path(sys.argv[2])
assert set(model["services"]) == {"api", "worker"}
api = model["services"]["api"]
worker = model["services"]["worker"]
assert api["user"] == "10001:10000"
assert worker["user"] == "0:10000"
assert worker["command"] == ["python", "-m", "app.nas_compat_launcher"]
assert set(worker["cap_add"]) == {"DAC_OVERRIDE", "SETUID", "SETGID"}
assert not api.get("cap_add")
assert model["networks"]["v162-private"]["internal"] is True

for name, service in (("api", api), ("worker", worker)):
    assert service["read_only"] is True
    assert "ALL" in service["cap_drop"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert not service.get("privileged", False)
    assert not service.get("ports")
    assert set(service["networks"]) == {"v162-private"}
    env = service["environment"]
    assert env["ALLOW_MUTATION"] == "false"
    assert env["ALLOW_DELETE"] == "false"
    assert env["MEDIA_ORGANIZER_EXECUTION_ENABLED"] == "false"
    assert env["MEDIA_ORGANIZER_EXECUTION_MODE"] == "maintenance_window"
    mounts = {m["target"]: m for m in service["volumes"]}
    assert mounts["/data"]["source"] == str(scratch / "data")
    assert mounts["/config"]["source"] == str(scratch / "config")
    assert mounts["/quarantine/.nas-file-center-trash"]["source"] == str(scratch / "config/.nas-file-center-trash")
    assert mounts["/data"].get("read_only", False) is (name == "api")
    assert all(m["source"].startswith(str(scratch)) for m in service["volumes"] if m["type"] == "bind")
assert api["environment"]["NFC_NAS_COMPAT_API_DEFERRED_SELECTION_ENABLED"] == "true"
assert worker["environment"]["NFC_NAS_COMPAT_API_DEFERRED_SELECTION_ENABLED"] == "false"
assert worker["environment"]["NFC_NAS_COMPAT_WORKER_ENABLED"] == "true"
assert api["environment"]["NFC_NAS_COMPAT_WORKER_ENABLED"] == "false"
assert worker["environment"]["NFC_NAS_COMPAT_WORKER_UID"] == "10002"
assert worker["environment"]["NFC_NAS_COMPAT_WORKER_GID"] == "10000"

print("Scratch-only V1.6.2 Compose boundary: PASS. Did not start any containers.")
PY
