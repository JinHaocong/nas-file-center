#!/usr/bin/env bash
# Validate the fresh-install Compose model using only disposable local paths.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT

mkdir -p "$TMP/config/.nas-file-center-trash" "$TMP/data"
export NFC_V16_IMAGE='nas-file-center:v16-candidate-test'
export NFC_V16_CONFIG_DIR="$TMP/config"
export NFC_V16_DATA_DIR="$TMP/data"
export NFC_V16_API_UID=10001
export NFC_V16_WORKER_UID=10002
export NFC_V16_SHARED_GID=10000
export NFC_V16_ADMIN_USERNAME='candidate-admin'
export NFC_V16_ADMIN_PASSWORD='disposable-only-password'
export NFC_V16_WEB_PORT=18080

docker compose -f "$ROOT/compose.komodo.v16-fresh-install.yaml" \
  config --format json > "$TMP/model.json"

python3 - "$TMP/model.json" "$TMP" <<'PY'
import json
import sys
from pathlib import Path

model = json.loads(Path(sys.argv[1]).read_text())
tmp = Path(sys.argv[2]).resolve(strict=True)
services = model["services"]
api_name = "nas-file-center-v16-api"
worker_name = "nas-file-center-v16-worker"
assert set(services) == {api_name, worker_name}
api, worker = services[api_name], services[worker_name]

assert api["container_name"] == api_name
assert worker["container_name"] == worker_name
assert api["container_name"] != "nas-file-center-api"
assert worker["container_name"] != "nas-file-center-worker"
assert api["user"] == "10001:10000"
assert worker["user"] == "10002:10000"
assert api["image"] == worker["image"] == "nas-file-center:v16-candidate-test"

def mounts(service):
    return {item["target"]: item for item in service["volumes"]}

am, wm = mounts(api), mounts(worker)
assert set(am) == {
    "/config", "/data", "/quarantine/.nas-file-center-trash",
    "/config/.nas-file-center-trash", "/run/nfc-recovery-secrets",
}
assert set(wm) == {
    "/config", "/data", "/quarantine/.nas-file-center-trash",
    "/run/nfc-recovery-secrets",
}
config = (tmp / "config").resolve(strict=True)
data = (tmp / "data").resolve(strict=True)
trash = (config / ".nas-file-center-trash").resolve(strict=True)
assert config.is_relative_to(tmp) and data.is_relative_to(tmp)
assert not (config == data or config in data.parents or data in config.parents)

for service_mounts in (am, wm):
    assert Path(service_mounts["/config"]["source"]).resolve(strict=True) == config
    assert Path(service_mounts["/data"]["source"]).resolve(strict=True) == data
    assert service_mounts["/data"].get("read_only") is True
    assert service_mounts["/config"].get("read_only", False) is False
    assert service_mounts["/run/nfc-recovery-secrets"]["type"] == "volume"

for target in ("/quarantine/.nas-file-center-trash", "/config/.nas-file-center-trash"):
    assert Path(am[target]["source"]).resolve(strict=True) == trash
    assert am[target].get("read_only") is True
assert Path(wm["/quarantine/.nas-file-center-trash"]["source"]).resolve(strict=True) == trash
assert wm["/quarantine/.nas-file-center-trash"].get("read_only", False) is False

for service in (api, worker):
    assert service["read_only"] is True
    assert "ALL" in service["cap_drop"]
    assert "no-new-privileges:true" in service["security_opt"]
    env = service["environment"]
    assert env["ALLOW_MUTATION"] == "false"
    assert env["ALLOW_DELETE"] == "false"
    assert env["MEDIA_ORGANIZER_EXECUTION_ENABLED"] == "false"
    assert env["MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK"] == "false"

assert api["ports"][0]["host_ip"] == "127.0.0.1"
assert api["ports"][0]["published"] == "18080"
assert set(api["networks"]) == {"v16-private"}
assert set(worker["networks"]) == {"v16-private"}
network = model["networks"]["v16-private"]
assert network["internal"] is True
assert not network.get("external", False)
assert model["volumes"]["nfc-v16-recovery-secrets"]["name"] == (
    "nas-file-center-v16-candidate-recovery-secrets"
)
assert model["volumes"]["nfc-v16-recovery-secrets"]["driver_opts"]["o"] == (
    "size=1m,uid=10001,gid=10000,mode=2770,noexec,nosuid,nodev"
)
assert api["depends_on"] == {} if "depends_on" in api else True
assert worker["depends_on"][api_name]["condition"] == "service_healthy"
print("FRESH_V16_COMPOSE_ISOLATION_MODEL_OK")
PY
