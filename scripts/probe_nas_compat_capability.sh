#!/usr/bin/env bash
# Isolated CI-only Docker capability feasibility probe for V1.6.2.
# Never bind user-controlled data or real NAS storage.
set -Eeuo pipefail
command -v docker >/dev/null
command -v python3 >/dev/null
command -v sudo >/dev/null

scratch="$(mktemp -d "${RUNNER_TEMP:-/tmp}/nfc-v162-capability-XXXXXXXX")"
cleanup() {
  case "$scratch" in
    "${RUNNER_TEMP:-/tmp}"/nfc-v162-capability-*) sudo rm -rf -- "$scratch" ;;
    *) echo "Refusing to clean unexpected scratch location" >&2; return 1 ;;
  esac
}
trap cleanup EXIT

mkdir -p "$scratch/media"
printf 'synthetic-only\n' > "$scratch/media/root-private.bin"
sudo chown 0:0 "$scratch/media" "$scratch/media/root-private.bin"
sudo chmod 0755 "$scratch/media"
sudo chmod 0600 "$scratch/media/root-private.bin"

image="${NFC_CAP_PROBE_IMAGE:-python:3.12-slim}"
docker pull "$image" >/dev/null

read -r -d '' payload <<'PY' || true
import errno, json, os
with open("/proc/self/status", encoding="utf-8") as stream:
    fields = dict(line.split(":", 1) for line in stream if ":" in line)
caps = int(fields["CapEff"].strip(), 16)
cap_dac_override_effective = bool(caps & (1 << 1))
can_read = False
read_error = None
try:
    with open("/data/root-private.bin", "rb") as stream:
        can_read = stream.read() == b"synthetic-only\n"
except OSError as exc:
    read_error = errno.errorcode.get(exc.errno, str(exc.errno))
can_write = False
write_error = None
try:
    fd = os.open("/data/probe-created.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, b"synthetic-only\n")
    finally:
        os.close(fd)
    can_write = True
    os.unlink("/data/probe-created.bin")
except OSError as exc:
    write_error = errno.errorcode.get(exc.errno, str(exc.errno))
dir_fd = os.open("/data", os.O_RDONLY | os.O_DIRECTORY)
try:
    effective_write_search_access = os.access(".", os.W_OK | os.X_OK,
                                              dir_fd=dir_fd, effective_ids=True)
finally:
    os.close(dir_fd)
print(json.dumps({
    "uid": os.geteuid(), "gid": os.getegid(),
    "effective_write_search_access": effective_write_search_access,
    "no_new_privs": fields.get("NoNewPrivs", "").strip(),
    "effective_caps_hex": f"{caps:x}",
    "effective_dac_override": cap_dac_override_effective,
    "effective_dac_read_search": bool(caps & (1 << 2)),
    "root_owned_private_read": can_read,
    "root_owned_directory_write": can_write,
    "read_errno": read_error, "write_errno": write_error,
}, sort_keys=True))
PY

run_case() {
  docker run --rm --network none --read-only \
    --user 10002:10000 \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    "$@" \
    --mount "type=bind,source=$scratch/media,target=/data,readonly=false" \
    "$image" python -c "$payload"
}
baseline="$(run_case)"
candidate="$(run_case --cap-add DAC_OVERRIDE)"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scoped="$(docker run --rm --network none --read-only \
  --user 0:10000 \
  --cap-drop ALL \
  --cap-add DAC_OVERRIDE --cap-add SETUID --cap-add SETGID \
  --security-opt no-new-privileges:true \
  --mount "type=bind,source=$scratch/media,target=/data" \
  --mount "type=bind,source=$repo/scripts/probe_nas_compat_ambient.py,target=/probe.py,readonly" \
  --mount "type=bind,source=$repo/app,target=/opt/nfc/app,readonly" \
  -e PYTHONPATH=/opt/nfc \
  -e NFC_NAS_COMPAT_WORKER_ENABLED=true \
  -e NFC_NAS_COMPAT_WORKER_UID=10002 \
  -e NFC_NAS_COMPAT_WORKER_GID=10000 \
  -e MEDIA_ORGANIZER_EXECUTION_MODE=maintenance_window \
  "$image" python /probe.py "$payload")"
python3 - "$baseline" "$candidate" "$scoped" <<'PY'
import json, sys
baseline, candidate, scoped = (json.loads(raw) for raw in sys.argv[1:])
for label, row in (("baseline", baseline), ("dac_override_candidate", candidate), ("scoped_candidate", scoped)):
    print(f"{label}={json.dumps(row, sort_keys=True)}")
    assert row["uid"] == 10002 and row["gid"] == 10000, "Unexpected Worker identity"
    assert row["no_new_privs"] == "1", "no-new-privileges is disabled"
if (baseline["root_owned_private_read"] or baseline["root_owned_directory_write"]
        or baseline["effective_write_search_access"]):
    raise SystemExit("INVALID_PROBE: unprivileged Worker unexpectedly accessed root-owned fixture")
viable = (candidate["effective_dac_override"] and
          candidate["root_owned_private_read"] and
          candidate["root_owned_directory_write"] and
          candidate["effective_write_search_access"])
print("ROOTLESS_DAC_OVERRIDE_FEASIBILITY=" + ("PASS_CI_HOST_ONLY" if viable else "UNSUPPORTED_AS_CONFIGURED"))
scoped_viable = (scoped["effective_caps_hex"] == "2" and
                 scoped["effective_dac_override"] and
                 scoped["root_owned_private_read"] and
                 scoped["root_owned_directory_write"] and
                 scoped["effective_write_search_access"])
print("SCOPED_NONROOT_DAC_OVERRIDE_FEASIBILITY=" + ("PASS_CI_HOST_ONLY" if scoped_viable else "UNSUPPORTED_AS_CONFIGURED"))
print("CI-only result: not NAS/FUSE compatibility or release authorization.")
PY
