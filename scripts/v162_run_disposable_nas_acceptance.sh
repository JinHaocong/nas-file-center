#!/usr/bin/env bash
# Run only on the owner's NAS after approval for a new random SATA scratch.
# Does not install/update Komodo, touch media or change any existing ACL.
set -Eeuo pipefail
umask 077

usage() {
  cat <<'HELP'
One-time NAS V1.6.2 acceptance:
  sudo bash scripts/v162_run_disposable_nas_acceptance.sh \
    --data-root "/absolute/host/SATA/data" \
    --candidate-sha "<exact-40-character-PR-head-SHA>"
Fetches exactly the commit, builds an isolated candidate Docker image, then
runs real API/Worker execution, recovery and cleanup ONLY in a new random
scratch child. Existing media is never scanned or changed.
HELP
}
if [[ "$#" -eq 1 && "$1" == "--help" ]]; then usage; exit 0; fi
if [[ "$#" -ne 4 || "$1" != "--data-root" || "$3" != "--candidate-sha" ]]; then
  usage >&2; exit 2
fi
DATA_ROOT="$2"; SHA="$4"
if [[ "$EUID" -ne 0 ]]; then
  echo "Use sudo (only for the disposable scratch test)." >&2; exit 2
fi
if [[ ! "$SHA" =~ ^[a-f0-9]{40}$ ]]; then
  echo "Invalid exact candidate SHA." >&2; exit 2
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

echo "Fetching exact PR candidate $SHA (no Komodo changes)."
git -C "$WORK" init -q
git -C "$WORK" remote add origin https://github.com/JinHaocong/nas-file-center.git
git -C "$WORK" -c protocol.version=2 fetch -q --depth=1 origin "$SHA"
git -C "$WORK" -c advice.detachedHead=false checkout -q FETCH_HEAD
[[ "$(git -C "$WORK" rev-parse HEAD)" == "$SHA" ]] || {
  echo "Git revision mismatch. Stopping." >&2; exit 2;
}

TAG="nfc-v162-disposable-test:$(printf %.12s "$SHA")"
echo "Building independent test image $TAG; production containers remain untouched."
# Build RUN steps on the NAS host network: ZOS Docker bridge DNS may not resolve external hosts.
# This affects build-time downloads only; test containers still run with --network none.
docker build --network=host \
  --label "org.opencontainers.image.revision=$SHA" \
  --tag "$TAG" "$WORK"
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$TAG")"
LABEL_SHA="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$TAG")"
[[ "$LABEL_SHA" == "$SHA" && "$IMAGE_ID" == sha256:* ]] || {
  echo "Candidate image provenance check failed." >&2; exit 2;
}

echo "Starting full lifecycle ONLY within a new random SATA scratch folder."
RESULT="$WORK/acceptance-result.json"
rc=0
python3 "$WORK/scripts/v16_nas_maintenance_acceptance.py" \
  --data-root "$DATA_ROOT" \
  --image "$IMAGE_ID" \
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
