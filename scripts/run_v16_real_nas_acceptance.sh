#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-compose.v16-real-nas-acceptance.yaml}"
ACCEPTANCE_ROOT="${V16_ACCEPTANCE_HOST_ROOT:?Set V16_ACCEPTANCE_HOST_ROOT to the existing SATA acceptance root}"
EVIDENCE_DIR="${V16_EVIDENCE_HOST_DIR:-./v16-nas-evidence}"
CANDIDATE_SHA="${CANDIDATE_SHA:-$(git rev-parse HEAD)}"

require_dir() {
  local path="$1"
  test -d "$path"
  test ! -L "$path"
}

ACCEPTANCE_ROOT="$(realpath -e -- "$ACCEPTANCE_ROOT")"
test "$(basename "$ACCEPTANCE_ROOT")" = "nas-file-center-v1.6-acceptance"

ORGANIZER_ROOT="$ACCEPTANCE_ROOT/nfc-organizer-c5-acceptance"
SCHEDULER_ROOT="$ACCEPTANCE_ROOT/nfc-scheduler-s5-acceptance"
require_dir "$ORGANIZER_ROOT"
require_dir "$SCHEDULER_ROOT"

test "$(stat -c %d "$ACCEPTANCE_ROOT")" = "$(stat -c %d "$ORGANIZER_ROOT")"

mapfile -t ROOT_CHILDREN < <(
  find "$ACCEPTANCE_ROOT" -mindepth 1 -maxdepth 1 -printf '%f\n' | sort
)
test "${#ROOT_CHILDREN[@]}" -eq 2
test "${ROOT_CHILDREN[0]}" = "nfc-organizer-c5-acceptance"
test "${ROOT_CHILDREN[1]}" = "nfc-scheduler-s5-acceptance"

# Scheduler is reserved and must be empty.
test -z "$(find "$SCHEDULER_ROOT" -mindepth 1 -maxdepth 1 -print -quit)"

# Never delete an existing run. Only our own uniquely named evidence runs are allowed.
while IFS= read -r entry; do
  test -d "$entry"
  test ! -L "$entry"
  case "$(basename "$entry")" in
    .nfc-v16-run-*) ;;
    *) echo "Unexpected organizer-root entry: $entry" >&2; exit 1 ;;
  esac
done < <(find "$ORGANIZER_ROOT" -mindepth 1 -maxdepth 1 -print)

mkdir -p "$EVIDENCE_DIR"
export V16_ACCEPTANCE_HOST_ROOT="$ACCEPTANCE_ROOT"
export V16_EVIDENCE_HOST_DIR="$EVIDENCE_DIR"
export CANDIDATE_SHA

docker compose -f "$COMPOSE_FILE" config -q
docker compose -f "$COMPOSE_FILE" run --rm --build v16-real-nas-acceptance
