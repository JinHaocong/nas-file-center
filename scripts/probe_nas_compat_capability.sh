#!/usr/bin/env bash
# CI-only Docker proof of the simple UID 0:GID 10000 + DAC_OVERRIDE profile.
# Uses only a brand-new temporary directory; never binds a NAS or user data.
set -Eeuo pipefail
command -v docker >/dev/null
command -v python3 >/dev/null
scratch="$(mktemp -d "${RUNNER_TEMP:-/tmp}/nfc-v162-root-worker-XXXXXXXX")"
cleanup() {
  case "$scratch" in
    "${RUNNER_TEMP:-/tmp}"/nfc-v162-root-worker-*) rm -rf -- "$scratch" ;;
    *) echo "Refusing to clean unexpected scratch path" >&2; return 1 ;;
  esac
}
trap cleanup EXIT
mkdir -p "$scratch/media"
printf 'synthetic-only\n' > "$scratch/media/root-private.bin"
chmod 0755 "$scratch/media"
chmod 0600 "$scratch/media/root-private.bin"
image="${NFC_ROOT_PROBE_IMAGE:-python:3.12-slim}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker pull "$image" >/dev/null
payload="$(cat <<'PY'
import errno, json, os, sys
from types import SimpleNamespace
from nas_compat_worker import verify_worker_runtime
status = {}
for line in open("/proc/self/status", encoding="ascii"):
    if ":" in line:
        key, value = line.split(":", 1)
        status[key] = value.strip()
caps = {k: int(status[k], 16) for k in ("CapInh","CapPrm","CapEff","CapBnd","CapAmb")}
caps["NoNewPrivs"] = int(status["NoNewPrivs"])
mode = os.environ.get("NFC_NAS_COMPAT_ROOT_WORKER_ENABLED") == "true"
settings = SimpleNamespace(
    nas_compat_root_worker_enabled=mode,
    media_organizer_execution_mode=os.environ.get("MEDIA_ORGANIZER_EXECUTION_MODE","strict"),
)
print(json.dumps({
    "profile_check": __import__("nas_compat_worker").is_nas_compat_root_worker(settings),
    "uid": os.getresuid(), "gid": os.getresgid(), "groups": os.getgroups(),
    "caps": {k: int(status[k], 16) for k in ("CapInh","CapPrm","CapEff","CapBnd","CapAmb")},
    "no_new_privs": status["NoNewPrivs"],
    "shared_gid": os.environ.get("NFC_SHARED_CONFIG_GID"),
    "mode": os.environ.get("MEDIA_ORGANIZER_EXECUTION_MODE"),
}, sort_keys=True), file=sys.stderr, flush=True)
verify_worker_runtime(settings)
can_read = False
read_error = None
try:
    with open("/data/root-private.bin","rb") as f:
        can_read = f.read() == b"synthetic-only\n"
except OSError as exc:
    read_error = errno.errorcode.get(exc.errno, str(exc.errno))
can_write = False
write_error = None
try:
    fd = os.open("/data/created.bin", os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    os.write(fd, b"synthetic-only\n")
    os.close(fd)
    can_write = True
    os.unlink("/data/created.bin")
except OSError as exc:
    write_error = errno.errorcode.get(exc.errno, str(exc.errno))
print(json.dumps({
    "uid": os.geteuid(), "gid": os.getegid(), "groups": os.getgroups(),
    "caps": caps, "read_root_private": can_read, "write_root_directory": can_write,
    "read_error": read_error, "write_error": write_error,
}, sort_keys=True))
PY
)"
run_case() {
  local label="$1"; shift
  docker run --rm --network none --read-only \
    --cap-drop ALL --security-opt no-new-privileges:true \
    "$@" \
    --mount "type=bind,source=$scratch/media,target=/data" \
    --mount "type=bind,source=$repo/app/nas_compat_worker.py,target=/opt/nas_compat_worker.py,readonly" \
    -e PYTHONPATH=/opt \
    -e NFC_SHARED_CONFIG_GID=10000 \
    -e MEDIA_ORGANIZER_EXECUTION_MODE=maintenance_window \
    "$image" python -c "$payload"
}
baseline="$(run_case baseline --user 10002:10000 -e NFC_NAS_COMPAT_ROOT_WORKER_ENABLED=false)"
candidate="$(run_case root_worker --user 0:10000 --cap-add DAC_OVERRIDE -e NFC_NAS_COMPAT_ROOT_WORKER_ENABLED=true)"
python3 - "$baseline" "$candidate" <<'PY'
import json, sys
baseline, candidate = (json.loads(x) for x in sys.argv[1:])
assert baseline["uid"] == 10002 and baseline["gid"] == 10000
assert not baseline["read_root_private"] and not baseline["write_root_directory"]
assert candidate["uid"] == 0 and candidate["gid"] == 10000
assert set(candidate["groups"]).issubset({10000})
assert candidate["caps"] == {
    "CapInh": 0, "CapPrm": 2, "CapEff": 2, "CapBnd": 2,
    "CapAmb": 0, "NoNewPrivs": 1,
}
assert candidate["read_root_private"] and candidate["write_root_directory"]
print("NAS_ROOT_WORKER_FEASIBILITY=PASS_CI_HOST_ONLY")
print("Baseline non-root is denied; UID 0:GID 10000 with only DAC_OVERRIDE succeeds.")
print("This proves only ordinary CI Docker behavior, not ZOS/zfuse compatibility.")
PY
