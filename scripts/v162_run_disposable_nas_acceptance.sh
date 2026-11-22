#!/usr/bin/env bash
# Pull-only NAS acceptance. The candidate image is built and published by GitHub Actions.
# This script never builds images, installs a Komodo stack, changes ACLs or scans existing media.
set -Eeuo pipefail
umask 077

usage() {
  cat <<'HELP'
One-time NAS V1.6.2 acceptance (no image build on the NAS):
  sudo bash scripts/v162_run_disposable_nas_acceptance.sh \
    --data-root "/absolute/host/SATA/data" \
    --candidate-sha "<exact-40-character-PR-head-SHA>" \
    --image-ref "kerwinjhc/nas-file-center@sha256:<64-character-digest>"

Pulls the immutable candidate image published by GitHub Actions, verifies its
source SHA and linux/amd64 identity, then runs real API/Worker execution,
recovery and cleanup ONLY in a new random scratch child. Existing media,
Komodo and ACLs are untouched. The synthetic fixture and evidence are retained.
HELP
}
if [[ "$#" -eq 1 && "$1" == "--help" ]]; then usage; exit 0; fi
if [[ "$#" -ne 6 || "$1" != "--data-root" || "$3" != "--candidate-sha" || "$5" != "--image-ref" ]]; then
  usage >&2; exit 2
fi
DATA_ROOT="$2"; SHA="$4"; IMAGE_REF="$6"
if [[ "$EUID" -ne 0 ]]; then
  echo "Use sudo (only for the disposable scratch test)." >&2; exit 2
fi
if [[ ! "$SHA" =~ ^[a-f0-9]{40}$ ]]; then
  echo "Invalid exact candidate SHA." >&2; exit 2
fi
if [[ ! "$IMAGE_REF" =~ ^kerwinjhc/nas-file-center@sha256:[a-f0-9]{64}$ ]]; then
  echo "Image must be the immutable kerwinjhc/nas-file-center@sha256 digest from the candidate workflow." >&2
  exit 2
fi
if [[ "$DATA_ROOT" != /* || "$DATA_ROOT" == "/" || "$DATA_ROOT" == *"/../"* ||
      "$DATA_ROOT" == *"//"* || "$DATA_ROOT" == */ || "$DATA_ROOT" == *","* ||
      "$DATA_ROOT" == *'"'* || "$DATA_ROOT" == *".." ||
      ! -d "$DATA_ROOT" || -L "$DATA_ROOT" ]]; then
  echo "Unsafe, missing or noncanonical existing SATA root." >&2; exit 2
fi
for cmd in git docker python3 mktemp; do
  command -v "$cmd" >/dev/null || { echo "Missing required command: $cmd" >&2; exit 2; }
done
python3 - "$DATA_ROOT" <<'PY'
import os, stat, sys
root = sys.argv[1]
if (os.path.abspath(root) != root or not stat.S_ISDIR(os.lstat(root).st_mode)
        or os.statvfs(root).f_flag & os.ST_RDONLY):
    raise SystemExit("Approved scratch parent unavailable or read-only")
print("SATA scratch parent: verified read-only.")
PY

WORK="$(mktemp -d /tmp/nfc-v162-exact-candidate-XXXXXXXX)"
cleanup_work() {
  # Remove only this unique /tmp checkout. The new SATA fixture and report
  # remain preserved for review even when any acceptance step fails.
  case "$WORK" in
    /tmp/nfc-v162-exact-candidate-*) rm -rf -- "$WORK" ;;
    *) echo "Refusing to remove unknown checkout path" >&2 ;;
  esac
}
trap cleanup_work EXIT

echo "Fetching exact PR acceptance driver $SHA (no Komodo changes)."
git -C "$WORK" init -q
git -C "$WORK" remote add origin https://github.com/JinHaocong/nas-file-center.git
git -C "$WORK" -c protocol.version=2 fetch -q --depth=1 origin "$SHA"
git -C "$WORK" -c advice.detachedHead=false checkout -q FETCH_HEAD
[[ "$(git -C "$WORK" rev-parse HEAD)" == "$SHA" ]] || {
  echo "Git revision mismatch. Stopping." >&2; exit 2;
}

echo "Pulling immutable GitHub-built candidate image: $IMAGE_REF"
docker pull "$IMAGE_REF"
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_REF")"
LABEL_SHA="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE_REF")"
PLATFORM="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE_REF")"
[[ "$LABEL_SHA" == "$SHA" && "$IMAGE_ID" == sha256:* && "$PLATFORM" == "linux/amd64" ]] || {
  echo "Candidate image provenance/platform check failed." >&2; exit 2;
}

echo "Starting full lifecycle ONLY within a new random SATA scratch folder."
RESULT="$WORK/acceptance-result.json"
rc=0
python3 "$WORK/scripts/v16_nas_maintenance_acceptance.py" \
  --data-root "$DATA_ROOT" \
  --image "$IMAGE_REF" \
  --candidate-sha "$SHA" \
  --nas-root-worker > "$RESULT" || rc=$?

python3 - "$RESULT" "$rc" <<'PY'
import json, sys
from pathlib import Path
path, rc = Path(sys.argv[1]), int(sys.argv[2])
try:
    report = json.loads(path.read_text())
except (OSError, ValueError) as exc:
    print(f"ACCEPTANCE_RESULT_UNAVAILABLE: {type(exc).__name__}; exit={rc}")
    raise SystemExit(rc or 2)
print("=" * 55)
print("RESULT:", report.get("status", "UNKNOWN"))
print("Candidate:", report.get("candidate_sha"))
print("Image:", report.get("requested_image"))
print("Root Worker:", report.get("nas_root_worker"))
print("Fixture:", report.get("fixture", report.get("requested_fixture", "not created")))
for case, result in (report.get("cases") or {}).items():
    print(f"Case {case}:", "PASS" if result.get("complete") else "NOT COMPLETE")
print("Release ready:", report.get("release_ready", False))
if report.get("failure"):
    print("Failure reason:", report["failure"])
print("Synthetic test evidence is retained inside the fixture for review.")
print("=" * 55)
PY
exit "$rc"
