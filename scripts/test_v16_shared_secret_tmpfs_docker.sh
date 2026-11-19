#!/usr/bin/env bash
# #403: Real Docker RAM volume test with distinct UIDs, fake credential only.
# CI only: no host media, Docker socket, /data, or application config bind mounts.
set -Eeuo pipefail

if [[ "${GITHUB_ACTIONS:-}" != "true" ]]; then
  echo "Refusing outside GitHub Actions; this is not an NAS command" >&2
  exit 2
fi
command -v docker >/dev/null || exit 2
: "$GITHUB_RUN_ID"
: "$GITHUB_RUN_ATTEMPT"
: "$RUNNER_TEMP"

repo="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d "$RUNNER_TEMP/nfc-v16-secret-model-XXXXXXXX")"
VOL="nfc-v16-secret-ci-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT-${scratch##*-}"
HOLDER="$VOL-holder"
IMAGE="python:3.12-slim-bookworm"
DEST="/run/nfc-recovery-secrets"

cleanup() {
  docker rm -f "$HOLDER" >/dev/null 2>&1 || true
  docker volume rm "$VOL" >/dev/null 2>&1 || true
  if [[ -n "$scratch" && "$scratch" == "$RUNNER_TEMP"/nfc-v16-secret-model-* ]]; then
    rm -rf -- "$scratch"
  fi
}
trap cleanup EXIT INT TERM

# Only render synthetic host sources; no config/media bind is mounted below.
# Test the selected volume AFTER both overlays, not an unused base definition.
mkdir -p "$scratch/config/.nas-file-center-trash" "$scratch/media"
export HOST_CONFIG_DIR="$scratch/config" HOST_DATA_DIR="$scratch/media"
export HOST_QUARANTINE_DIR="$scratch/config"
export NFC_API_UID=10001 NFC_WORKER_UID=10002 NFC_SHARED_GID=10000
docker compose -f "$repo/compose.komodo.yaml" \
  -f "$repo/compose.komodo.cross-storage.yaml" \
  -f "$repo/compose.komodo.archive-recovery-secrets.yaml" \
  config --format json > "$scratch/merged.json"
python3 - "$scratch/merged.json" "$scratch/volume.args" <<'PY'
import json, sys
from pathlib import Path
model = json.loads(Path(sys.argv[1]).read_text())
sources = []
for service_name, principal in (('nas-file-center-api', '10001:10000'),
                                ('nas-file-center-worker', '10002:10000')):
    service = model['services'][service_name]
    assert service['user'] == principal
    mounts = [v for v in service['volumes'] if v['target'] == '/run/nfc-recovery-secrets']
    assert len(mounts) == 1 and mounts[0]['type'] == 'volume'
    assert not mounts[0].get('read_only', False)
    sources.append(mounts[0]['source'])
    assert service['environment']['NFC_SECRET_OWNER_UID'] == '10001'
    assert service['environment']['NFC_SECRET_GROUP_GID'] == '10000'
assert sources[0] == sources[1], 'API and Worker must use the same RAM volume'
definition = model['volumes'][sources[0]]
assert definition['driver'] == 'local' and not definition.get('external', False)
options = definition['driver_opts']
assert set(options) == {'type', 'device', 'o'}
assert options['type'] == options['device'] == 'tmpfs'
mount_options = options['o'].split(',')
option_keys = [part.split('=', 1)[0] for part in mount_options]
assert len(option_keys) == len(set(option_keys)), 'Duplicate RAM mount options'
assert {'size=1m', 'uid=10001', 'gid=10000', 'mode=2770',
        'noexec', 'nosuid', 'nodev'}.issubset(mount_options)
arguments = ['--driver', definition['driver']]
for key, value in sorted(options.items()):
    assert isinstance(value, str) and not any(c in value for c in ('\0', '\n'))
    arguments.extend(('--opt', f'{key}={value}'))
# Docker receives these exact rendered options, with a fresh CI-only name.
# NUL-delimited argv avoids eval or shell parsing of the Compose output.
Path(sys.argv[2]).write_bytes(b''.join(arg.encode() + b'\0' for arg in arguments))
print('MERGED_COMPOSE_SELECTED_SHARED_RAM_VOLUME_OK')
PY
mapfile -d '' -t VOLUME_ARGS < "$scratch/volume.args"
docker volume create "${VOLUME_ARGS[@]}" "$VOL" >/dev/null

# Hold one attachment open so the local-driver tmpfs stays mounted.
docker run --rm -d --name "$HOLDER" --user 10001:10000 \
  --mount "type=volume,source=$VOL,target=$DEST" \
  "$IMAGE" python -c 'import time; time.sleep(240)' >/dev/null

# API UID exclusively creates a synthetic 0640 password token.
docker run --rm --user 10001:10000 \
  --mount "type=volume,source=$VOL,target=$DEST" \
  "$IMAGE" python -c '
import os, stat
root="/run/nfc-recovery-secrets"
s=os.lstat(root)
assert stat.S_ISDIR(s.st_mode)
assert (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(10001,10000,0o2770)
with open("/proc/self/mountinfo",encoding="utf-8") as stream:
    assert any(" - tmpfs " in line and " /run/nfc-recovery-secrets " in line for line in stream)
path=root+"/"+"d"*32
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o640)
try:
    os.fchmod(fd,0o640)
    os.write(fd,b"synthetic-only-test-credential")
    os.fsync(fd)
finally:
    os.close(fd)
assert os.lstat(path).st_gid==10000
print("API_NONROOT_WRITE_OK")
'

# An unrelated UID/GID cannot open that same token.
docker run --rm --user 10003:10003 \
  --mount "type=volume,source=$VOL,target=$DEST" \
  "$IMAGE" python -c '
import os
try:
    os.open("/run/nfc-recovery-secrets/"+"d"*32,os.O_RDONLY)
except PermissionError:
    print("FOREIGN_UID_DENIED")
else:
    raise SystemExit("Untrusted UID unexpectedly read token")
'

# Worker UID with the approved group can read and unlink that same inode.
docker run --rm --user 10002:10000 \
  --mount "type=volume,source=$VOL,target=$DEST" \
  "$IMAGE" python -c '
import os,stat
root="/run/nfc-recovery-secrets"
path=root+"/"+"d"*32
s=os.lstat(path)
assert (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(10001,10000,0o640)
fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
try:
    contents=os.read(fd,4097)
finally:
    os.close(fd)
assert contents==b"synthetic-only-test-credential"
os.unlink(path)
print("WORKER_NONROOT_READ_UNLINK_OK")
'

docker run --rm --user 10001:10000 \
  --mount "type=volume,source=$VOL,target=$DEST" \
  "$IMAGE" python -c '
import os
assert os.listdir("/run/nfc-recovery-secrets")==[]
print("ZERO_SECRET_RESIDUE")
'

cleanup
if docker volume inspect "$VOL" >/dev/null 2>&1; then
  echo "Temporary volume was not removed" >&2
  exit 1
fi
trap - EXIT INT TERM
echo "PASS_TWO_UID_TMPFS_ZERO_RESIDUE"
