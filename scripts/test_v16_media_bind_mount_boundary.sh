#!/usr/bin/env bash
# #403: synthetic-only POSIX/Docker runtime permission acceptance.
# Never run on NAS, never mount actual media/config, never modify host ACLs.
set -Eeuo pipefail

if [[ "$GITHUB_ACTIONS" != "true" ]]; then
  echo "This acceptance is restricted to isolated GitHub Actions runners" >&2
  exit 2
fi
: "$RUNNER_TEMP"
command -v docker >/dev/null

repo="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d "$RUNNER_TEMP/nfc-v16-media-boundary-XXXXXXXX")"
cleanup() {
  if [[ -n "$scratch" && "$scratch" == "$RUNNER_TEMP"/nfc-v16-media-boundary-* ]]; then
    sudo rm -rf -- "$scratch"
  fi
}
trap cleanup EXIT INT TERM

# Validate the intended production model but never mount its NAS host paths.
docker compose -f "$repo/compose.komodo.yaml" config --format json > "$scratch/komodo.json"
python3 - "$scratch/komodo.json" <<'PY'
import json, sys
from pathlib import Path
model = json.loads(Path(sys.argv[1]).read_text())
api = model['services']['nas-file-center-api']
worker = model['services']['nas-file-center-worker']
def media_mount(service):
    mounts = [v for v in service['volumes'] if v['target'] == '/data']
    assert len(mounts) == 1 and mounts[0]['type'] == 'bind'
    return mounts[0]
assert api['user'] == '10001:10000' and worker['user'] == '10002:10000'
assert media_mount(api)['read_only'] is True
assert media_mount(worker).get('read_only', False) is False
for service in (api, worker):
    assert service['read_only'] is True
    assert 'ALL' in service['cap_drop']
    assert 'no-new-privileges:true' in service['security_opt']
    assert service['environment']['MEDIA_ORGANIZER_EXECUTION_ENABLED'] == 'false'
    assert service['environment']['MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK'] == 'false'
print('REAL_COMPOSE_BOUNDARY_MODEL_OK')
PY

mkdir "$scratch/media"
sudo chown 10002:10000 "$scratch/media"
sudo chmod 2770 "$scratch/media"
printf 'synthetic-original-unchanged\n' | sudo tee "$scratch/media/original.bin" >/dev/null
sudo chown 10002:10000 "$scratch/media/original.bin"
sudo chmod 0660 "$scratch/media/original.bin"
before="$(sudo sha256sum "$scratch/media/original.bin" | cut -d ' ' -f1)"

IMAGE='python:3.12-slim-bookworm'
# The API shares the writable group, so only its readonly mount prevents writes.
docker run --rm --network none --user 10001:10000 --read-only \
  --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  --mount "type=bind,source=$scratch/media,target=/data,readonly" \
  "$IMAGE" python -c '
import errno, os
assert os.geteuid() == 10001 and os.getegid() == 10000
assert os.stat("/data/original.bin").st_size > 0
assert os.stat("/data").st_mode & 0o020
def refused(operation):
    try:
        operation()
    except OSError as error:
        assert error.errno == errno.EROFS, error
    else:
        raise AssertionError("API unexpectedly mutated media")
refused(lambda: os.open("/data/new.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
refused(lambda: os.open("/data/original.bin", os.O_WRONLY | os.O_TRUNC))
refused(lambda: os.rename("/data/original.bin", "/data/renamed.bin"))
refused(lambda: os.unlink("/data/original.bin"))
refused(lambda: os.mkdir("/data/new-directory"))
print("API_NONROOT_MEDIA_READONLY_DENIAL_OK")
'

docker run --rm --network none --user 10002:10000 --read-only \
  --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  --mount "type=bind,source=$scratch/media,target=/data" \
  "$IMAGE" python -c '
import os
assert os.geteuid() == 10002 and os.getegid() == 10000
assert os.stat("/data/original.bin").st_size > 0
fd = os.open("/data/worker-new.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    os.write(fd, b"synthetic-worker")
    os.fsync(fd)
finally:
    os.close(fd)
os.rename("/data/worker-new.bin", "/data/worker-renamed.bin")
assert open("/data/worker-renamed.bin", "rb").read() == b"synthetic-worker"
os.unlink("/data/worker-renamed.bin")
print("WORKER_NONROOT_MEDIA_RW_OK")
'

docker run --rm --network none --user 10003:10003 --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --mount "type=bind,source=$scratch/media,target=/data" \
  "$IMAGE" python -c '
import errno, os
try:
    os.open("/data/foreign.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except PermissionError as error:
    assert error.errno == errno.EACCES, error
    print("UNTRUSTED_UID_MEDIA_DENIED")
else:
    raise AssertionError("Untrusted UID unexpectedly wrote media")
'

after="$(sudo sha256sum "$scratch/media/original.bin" | cut -d ' ' -f1)"
[[ "$before" == "$after" ]] || { echo 'Original fixture changed' >&2; exit 1; }
[[ "$(sudo find "$scratch/media" -mindepth 1 -maxdepth 1 -printf '%f\n')" == 'original.bin' ]] || {
  echo 'Unexpected scratch residue' >&2
  exit 1
}
echo 'PASS_API_READONLY_WORKER_NONROOT_RW_ORIGINAL_UNCHANGED'
