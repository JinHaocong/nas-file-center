#!/usr/bin/env bash
# Actual API/Worker UIDs on disposable CI files; never run against NAS media.
set -Eeuo pipefail
if [[ "${GITHUB_ACTIONS:-}" != "true" ]]; then
  echo "CI-only synthetic cleanup lifecycle; do not run on NAS" >&2
  exit 2
fi
command -v setpriv >/dev/null
command -v sudo >/dev/null
sudo -n true
repo="$(cd "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d /tmp/nfc-v16-cleanup-crossuid-XXXXXXXX)"
cleanup() {
  if [[ "$scratch" == /tmp/nfc-v16-cleanup-crossuid-* ]]; then
    sudo -n rm -rf -- "$scratch"
  fi
}
trap cleanup EXIT INT TERM
chmod 0755 "$scratch"
cp -a "$repo/app" "$scratch/app"
cp "$repo/scripts/media_organizer_cross_uid_lifecycle.py" "$scratch/lifecycle.py"
mkdir "$scratch/config" "$scratch/data"
sudo -n chown 10001:10000 "$scratch/config"
sudo -n chmod 2770 "$scratch/config"
sudo -n chown 10002:10000 "$scratch/data"
sudo -n chmod 0750 "$scratch/data"
printf '{}\n' > "$scratch/control.json"
sudo -n chown 10001:10000 "$scratch/control.json"
sudo -n chmod 0660 "$scratch/control.json"
# Group publication verifies every media ancestor owner. The test parent is
# trusted root-owned scratch, never the runner-owned checkout/home directory.
sudo -n chown 0:0 "$scratch"
py="$(command -v python)"
cd "$scratch"

run_phase() {
  local phase_uid="$1"
  shift
  sudo -n env "GITHUB_ACTIONS=$GITHUB_ACTIONS" "NFC_SHARED_CONFIG_GID=10000" "PYTHONPATH=$scratch" \
    "PYTHONDONTWRITEBYTECODE=1" "NFC_SYNTH_ROOT=$scratch" \
    "CONFIG_DIR=$scratch/config" "DATA_MOUNT=$scratch/data" \
    "ALLOWED_ROOTS=$scratch/data" "QUARANTINE_ROOT=$scratch/data/.trash" \
    setpriv --reuid="$phase_uid" --regid=10000 --clear-groups \
    "$py" "$scratch/lifecycle.py" "$@"
}

run_phase 10002 fixtures
for fixture_kind in flat grouped reused flat-stage-recovery grouped-publish-recovery \
  reused-published-recovery grouped-handoff-recovery; do
  run_phase 10001 queue-preview "$fixture_kind"
  run_phase 10002 preview "$fixture_kind"
  run_phase 10001 queue-execution "$fixture_kind"
  if [[ "$fixture_kind" == *-recovery ]]; then
    run_phase 10002 interrupt-execution "$fixture_kind"
    run_phase 10002 mark-execution-interrupted "$fixture_kind"
    run_phase 10001 queue-execution-recovery "$fixture_kind"
    run_phase 10002 recover-execution "$fixture_kind"
  else
    run_phase 10002 execute "$fixture_kind"
  fi
  run_phase 10001 review-and-queue "$fixture_kind"
  run_phase 10002 interrupt-cleanup "$fixture_kind"
  run_phase 10002 mark-interrupted "$fixture_kind"
  run_phase 10001 queue-recovery "$fixture_kind"
  run_phase 10002 recover "$fixture_kind"
  run_phase 10001 final-read "$fixture_kind"
done
run_phase 10003 foreign-denied
echo "PASS_REAL_DISTINCT_UID_EXECUTION_CLEANUP_RECOVERY_NO_NAS"
