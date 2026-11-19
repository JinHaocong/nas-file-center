#!/usr/bin/env bash
# #403: synthetic-only POSIX/Docker runtime permission acceptance.
# Never run on NAS, never mount actual media/config, never modify host ACLs.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ]]; then
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

# Render only disposable sources. The cross-storage variable keeps its legacy
# parent meaning, so its trash leaf is the same nested config child here.
mkdir -p "$scratch/config/.nas-file-center-trash" "$scratch/media"
export HOST_CONFIG_DIR="$scratch/config" HOST_DATA_DIR="$scratch/media"
export HOST_QUARANTINE_DIR="$scratch/config"
export NFC_API_UID=10001 NFC_WORKER_UID=10002 NFC_SHARED_GID=10000
docker compose -f "$repo/compose.komodo.yaml" \
  -f "$repo/compose.komodo.cross-storage.yaml" \
  -f "$repo/compose.komodo.archive-recovery-secrets.yaml" \
  config --format json > "$scratch/komodo.json"
python3 - "$scratch/komodo.json" "$scratch" <<'PY'
import json, sys
from pathlib import Path
model = json.loads(Path(sys.argv[1]).read_text())
scratch = Path(sys.argv[2]).resolve(strict=True)
api = model['services']['nas-file-center-api']
worker = model['services']['nas-file-center-worker']
canonical = '/quarantine/.nas-file-center-trash'
alias = '/config/.nas-file-center-trash'
expected_sources = {
    '/config': scratch / 'config', '/data': scratch / 'media',
    canonical: scratch / 'config/.nas-file-center-trash',
    alias: scratch / 'config/.nas-file-center-trash',
}

def mount(service, target):
    mounts = [v for v in service['volumes'] if v['target'] == target]
    assert len(mounts) == 1 and mounts[0]['type'] == 'bind'
    return mounts[0]

def write_mount_args(service, name, *, omit_alias=False):
    arguments = []
    binds = [v for v in service['volumes'] if v['type'] == 'bind']
    for volume in sorted(binds, key=lambda v: (len(Path(v['target']).parts), v['target'])):
        target, source = volume['target'], volume['source']
        assert target in expected_sources, 'Unexpected bind in disposable acceptance'
        assert Path(source).resolve(strict=True) == expected_sources[target]
        assert Path(source).resolve(strict=True).is_relative_to(scratch)
        assert not any(c in source + target for c in (',', '\0', '\n'))
        if omit_alias and target == alias:
            continue
        option = f'type=bind,source={source},target={target}'
        if volume.get('read_only', False):
            option += ',readonly'
        arguments.extend(('--mount', option))
    # NUL-delimited argv: never evaluate or shell-interpolate model contents.
    (scratch / name).write_bytes(b''.join(arg.encode() + b'\0' for arg in arguments))

assert api['user'] == '10001:10000' and worker['user'] == '10002:10000'
assert mount(api, '/data')['read_only'] is True
assert mount(worker, '/data').get('read_only', False) is False
assert mount(api, canonical)['read_only'] is True
assert mount(api, alias)['read_only'] is True
assert mount(worker, canonical).get('read_only', False) is False
for service in (api, worker):
    assert mount(service, '/config').get('read_only', False) is False
    assert service['environment']['CONFIG_DIR'] == '/config'
    assert service['environment']['QUARANTINE_ROOT'] == canonical
    assert service['read_only'] is True
    assert 'ALL' in service['cap_drop']
    assert 'no-new-privileges:true' in service['security_opt']
    assert service['environment']['MEDIA_ORGANIZER_EXECUTION_ENABLED'] == 'false'
    assert service['environment']['MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK'] == 'false'
write_mount_args(api, 'api.mounts')
write_mount_args(api, 'api-negative.mounts', omit_alias=True)
write_mount_args(worker, 'worker.mounts')
print('REAL_COMPOSE_BOUNDARY_MODEL_OK')
PY

mapfile -d '' -t API_MOUNTS < "$scratch/api.mounts"
mapfile -d '' -t API_NEGATIVE_MOUNTS < "$scratch/api-negative.mounts"
mapfile -d '' -t WORKER_MOUNTS < "$scratch/worker.mounts"

# Group write permissions deliberately allow the API to mutate through an
# unprotected alias; only the rendered readonly mounts close that boundary.
sudo chown 10001:10000 "$scratch/config"
sudo chmod 2770 "$scratch/config"
sudo chown 10002:10000 "$scratch/media" "$scratch/config/.nas-file-center-trash"
sudo chmod 2770 "$scratch/media" "$scratch/config/.nas-file-center-trash"
printf 'synthetic-original-unchanged\n' | sudo tee "$scratch/media/original.bin" >/dev/null
printf 'synthetic-quarantine-original-unchanged\n' | sudo tee "$scratch/config/.nas-file-center-trash/original.bin" >/dev/null
sudo chown 10002:10000 "$scratch/media/original.bin" "$scratch/config/.nas-file-center-trash/original.bin"
sudo chmod 0660 "$scratch/media/original.bin" "$scratch/config/.nas-file-center-trash/original.bin"
before_media="$(sudo sha256sum "$scratch/media/original.bin" | cut -d ' ' -f1)"
before_quarantine="$(sudo sha256sum "$scratch/config/.nas-file-center-trash/original.bin" | cut -d ' ' -f1)"

IMAGE='python:3.12-slim-bookworm'
# Negative control removes ONLY the alias mask from the rendered model.
# Canonical RO still denies writes, while config RW exposes the same subtree.
docker run --rm --network none --user 10001:10000 --read-only \
  --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  "${API_NEGATIVE_MOUNTS[@]}" \
  "$IMAGE" python -c '
import errno, os
canonical = "/quarantine/.nas-file-center-trash"
alias = "/config/.nas-file-center-trash"
assert os.geteuid() == 10001 and os.getegid() == 10000
assert os.stat(canonical + "/original.bin").st_ino == os.stat(alias + "/original.bin").st_ino
try:
    os.open(canonical + "/negative-control.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except OSError as error:
    assert error.errno == errno.EROFS, error
else:
    raise AssertionError("Canonical quarantine mount unexpectedly writable")
path = alias + "/negative-control.bin"
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    os.write(fd, b"disposable-alias-control")
    os.fsync(fd)
finally:
    os.close(fd)
assert open(canonical + "/negative-control.bin", "rb").read() == b"disposable-alias-control"
os.unlink(path)
print("QUARANTINE_WRITABLE_CONFIG_ALIAS_NEGATIVE_CONTROL_CONFIRMED")
'

# Positive control uses every rendered bind, including the nested RO mask.
docker run --rm --network none --user 10001:10000 --read-only \
  --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  "${API_MOUNTS[@]}" \
  "$IMAGE" python -c '
import errno, os, sqlite3, stat
assert os.geteuid() == 10001 and os.getegid() == 10000
def refused(operation):
    try:
        operation()
    except OSError as error:
        assert error.errno == errno.EROFS, error
    else:
        raise AssertionError("API unexpectedly mutated protected media/quarantine")
for root in ("/data", "/quarantine/.nas-file-center-trash", "/config/.nas-file-center-trash"):
    assert os.stat(root + "/original.bin").st_size > 0
    assert os.stat(root).st_mode & 0o020
    refused(lambda: os.open(root + "/new.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    refused(lambda: os.open(root + "/original.bin", os.O_WRONLY | os.O_TRUNC))
    refused(lambda: os.rename(root + "/original.bin", root + "/renamed.bin"))
    refused(lambda: os.unlink(root + "/original.bin"))
    refused(lambda: os.mkdir(root + "/new-directory"))
print("API_NONROOT_MEDIA_READONLY_DENIAL_OK")
print("API_QUARANTINE_CANONICAL_AND_CONFIG_ALIAS_READONLY_OK")
# Preserve the existing /config/app.db path and writable SQLite/WAL contract.
os.umask(0o007)
with open("/config/config-probe.txt", "x") as stream:
    stream.write("api\n")
database = sqlite3.connect("/config/app.db")
try:
    assert database.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    database.execute("CREATE TABLE principal (name TEXT PRIMARY KEY)")
    database.execute("INSERT INTO principal VALUES (?)", ("api",))
    database.commit()
    for suffix in ("", "-wal", "-shm"):
        info = os.stat("/config/app.db" + suffix)
        assert info.st_gid == 10000 and stat.S_IMODE(info.st_mode) == 0o660
finally:
    database.close()
print("API_CONFIG_AND_EXISTING_DATABASE_PATH_WRITABLE_OK")
'

docker run --rm --network none --user 10002:10000 --read-only \
  --cap-drop ALL --security-opt no-new-privileges --tmpfs /tmp:rw,nosuid,nodev \
  "${WORKER_MOUNTS[@]}" \
  "$IMAGE" python -c '
import os, sqlite3
assert os.geteuid() == 10002 and os.getegid() == 10000
for root in ("/data", "/quarantine/.nas-file-center-trash"):
    assert os.stat(root + "/original.bin").st_size > 0
    fd = os.open(root + "/worker-new.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, b"synthetic-worker")
        os.fsync(fd)
    finally:
        os.close(fd)
    os.rename(root + "/worker-new.bin", root + "/worker-renamed.bin")
    assert open(root + "/worker-renamed.bin", "rb").read() == b"synthetic-worker"
    fd = os.open(root + "/worker-renamed.bin", os.O_WRONLY | os.O_TRUNC)
    os.close(fd)
    os.unlink(root + "/worker-renamed.bin")
    os.mkdir(root + "/worker-directory")
    os.rmdir(root + "/worker-directory")
with open("/config/config-probe.txt", "a") as stream:
    stream.write("worker\n")
assert open("/config/config-probe.txt").read() == "api\nworker\n"
database = sqlite3.connect("/config/app.db")
try:
    assert database.execute("SELECT name FROM principal").fetchall() == [("api",)]
    database.execute("INSERT INTO principal VALUES (?)", ("worker",))
    database.commit()
    assert database.execute("SELECT name FROM principal ORDER BY name").fetchall() == [("api",), ("worker",)]
finally:
    database.close()
print("WORKER_NONROOT_MEDIA_RW_OK")
print("WORKER_QUARANTINE_AND_SHARED_DATABASE_RW_OK")
'

docker run --rm --network none --user 10003:10003 --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  "${WORKER_MOUNTS[@]}" \
  "$IMAGE" python -c '
import errno, os
for root in ("/data", "/quarantine/.nas-file-center-trash"):
    try:
        os.open(root + "/foreign.bin", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except PermissionError as error:
        assert error.errno == errno.EACCES, error
    else:
        raise AssertionError("Untrusted UID unexpectedly wrote media/quarantine")
print("UNTRUSTED_UID_MEDIA_DENIED")
'

after_media="$(sudo sha256sum "$scratch/media/original.bin" | cut -d ' ' -f1)"
after_quarantine="$(sudo sha256sum "$scratch/config/.nas-file-center-trash/original.bin" | cut -d ' ' -f1)"
[[ "$before_media" == "$after_media" && "$before_quarantine" == "$after_quarantine" ]] || {
  echo 'Original media/quarantine fixture changed' >&2; exit 1;
}
sudo python3 - "$scratch" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for path in (root / 'media', root / 'config/.nas-file-center-trash'):
    assert sorted(child.name for child in path.iterdir()) == ['original.bin'], path
PY
echo 'PASS_CANONICAL_QUARANTINE_AND_CONFIG_ALIAS_READONLY_DATABASE_PRESERVED'
echo 'PASS_API_READONLY_WORKER_NONROOT_RW_ORIGINAL_UNCHANGED'
