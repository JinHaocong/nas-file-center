#!/usr/bin/env bash
# #403: Real Docker RAM volume test with distinct UIDs, fake credential only.
# CI only: no host media, Docker socket, /data, or application config bind mounts.
set -Eeuo pipefail

if [[ "$GITHUB_ACTIONS" != "true" ]]; then
  echo "Refusing outside GitHub Actions; this is not an NAS command" >&2
  exit 2
fi
command -v docker >/dev/null || exit 2
: "$GITHUB_RUN_ID"
: "$GITHUB_RUN_ATTEMPT"

VOL="nfc-v16-secret-ci-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
HOLDER="$VOL-holder"
IMAGE="python:3.12-slim-bookworm"
DEST="/run/nfc-recovery-secrets"

cleanup() {
  docker rm -f "$HOLDER" >/dev/null 2>&1 || true
  docker volume rm "$VOL" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker volume create \
  --driver local \
  --opt type=tmpfs \
  --opt device=tmpfs \
  --opt 'o=size=1m,uid=10001,gid=10000,mode=2770,noexec,nosuid,nodev' \
  "$VOL" >/dev/null

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
