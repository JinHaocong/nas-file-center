# NAS File Center v0.3.5 — Gate5-G Final Validation Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the complete, immutable release and safety validation for NAS File Center v0.3.5 across all phases G0 through G8, verifying candidate immutability, zero regression, Docker Linux amd64 packaging, database migration resilience, synthetic filesystem safety, and real 极空间 NAS deployment.

**Architecture:** A sequential 9-phase verification protocol (G0–G8) binding one immutable candidate Git SHA to one immutable built Linux amd64 Docker image and evaluating it across clean host, containerized, and real NAS environments. Any candidate-changing repository modification invalidates the candidate and mandates a full restart from Phase G0.

**Tech Stack:** Python 3.12, FastAPI, SQLite / SQLAlchemy (WAL mode), Argon2, React 18, Vite, TypeScript, fclones 0.35.0, Docker Engine (linux/amd64), ZSpace OS / 极空间 NAS (ZFS/ext4).

**Spec:** docs/superpowers/specs/2026-09-10-gate5g-final-validation-design.md

---

## Global Constraints

- Approved Freeze Baseline HEAD: `073a69eb1e001e1738c32739f9b57820cba1b05f`.
- The Candidate Immutability Equation is strictly enforced: `One Candidate Git SHA + One Built Image Identity (Tag, Image ID & Tar Archive Digest) + Fixed G0–G7 Verification Matrix = One Gate5-G Candidate Evaluation`.
- Candidate Restart Rule: Any defect requiring changes to production code, tests, frontend, Dockerfile, compose files, package metadata, runtime configuration, or migration scripts marks the candidate as FAIL, requires a separately authorized bounded hotfix producing a new candidate Git SHA, and restarts verification from Phase G0.
- Archival Exception: Only post-verification commits modifying exclusively `docs/history/gate5g/**` may retain parent executable evidence, tracked via `VERIFIED_RUNTIME_HEAD` and `ARCHIVAL_RECORD_HEAD`.
- Target Release Version: Canonical release version is strictly `0.3.5` across all release-bearing surfaces.
- Mandatory Linux amd64 Platform: All Docker images must be built and verified for `--platform linux/amd64`.
- Real 极空间 NAS Black-Box Smoke: Verification on the target NAS is mandatory and cannot be substituted by desktop Docker.
- Production Mount Isolation: Validation must never mount committed production `CONFIG` or `DATA` paths from `compose.komodo.yaml`. All NAS tests execute on dedicated disposable directories physically outside production trees.
- Zero-Scheduler Invariant: Neither active window governance nor background polling may spawn a Task Scheduler or automated job creator.
- Single Worker Ownership: Exactly one active worker ownership lease may exist; no second worker process is permitted.
- Mutation Lifecycle Integrity: All filesystem mutations must follow `Preview -> Explicit Generate Draft -> Freeze -> Validate -> Execute`.
- Mandatory Quarantine Restore: Because the API exposes `POST /api/quarantine/{id}/restore`, quarantine restore verification is strictly mandatory.
- Release Tagging Deferred: Git tag `v0.3.5` and public image publishing to Docker Hub are prohibited until Gate5-G and milestone v0.3.5 are formally CLOSED by the project owner.

---

### Task 0: Phase G0 — Candidate Baseline & Release Metadata Preflight (Known Blocker & STOP Condition)

**Files:**
- Inspect: `pyproject.toml`
- Inspect: `app/main.py`
- Inspect: `frontend/package.json`
- Inspect: `frontend/package-lock.json`
- Inspect: `frontend/src/pages/Login/index.tsx`
- Inspect: `frontend/src/components/Sidebar.tsx`
- Inspect: `compose.yaml`
- Inspect: `compose.komodo.yaml`
- Test: `tests/test_release_version_consistency.py`

**Interfaces:**
- Consumes: Authoritative repository state at baseline commit SHA.
- Produces: Initial G0 preflight evaluation status (`PASS` or `FAIL / KNOWN BLOCKER`).

- [ ] **Step 1: Capture and verify runtime candidate Git SHA**

Run:
```bash
VERIFIED_RUNTIME_HEAD=$(git rev-parse HEAD)
echo "VERIFIED_RUNTIME_HEAD: ${VERIFIED_RUNTIME_HEAD}"
git status --short
```
Expected:
- `VERIFIED_RUNTIME_HEAD` matches the candidate under test (e.g. `073a69eb1e001e1738c32739f9b57820cba1b05f` or newly authorized candidate).
- `git status --short` output is completely empty.

- [ ] **Step 2: Inspect all eight release-bearing surfaces for canonical version `0.3.5`**

Run:
```bash
python3 -c "
import json, tomllib, sys
from pathlib import Path

errors = []
# 1. pyproject.toml
with open('pyproject.toml', 'rb') as f:
    pyproj = tomllib.load(f).get('project', {}).get('version')
    if pyproj != '0.3.5': errors.append(f'pyproject.toml version is {pyproj}')

# 2. app/main.py
with open('app/main.py', 'r') as f:
    content = f.read()
    if 'version=\"0.3.5\"' not in content: errors.append('app/main.py does not define version=\"0.3.5\"')

# 3. frontend/package.json
with open('frontend/package.json', 'r') as f:
    pkg = json.load(f).get('version')
    if pkg != '0.3.5': errors.append(f'frontend/package.json version is {pkg}')

# 4. frontend/package-lock.json
with open('frontend/package-lock.json', 'r') as f:
    lock = json.load(f)
    if lock.get('version') != '0.3.5': errors.append(f'package-lock top-level version is {lock.get(\"version\")}')
    if lock.get('packages', {}).get('', {}).get('version') != '0.3.5': errors.append('package-lock packages[\"\"] version is not 0.3.5')

# 5. Login/index.tsx
with open('frontend/src/pages/Login/index.tsx', 'r') as f:
    if 'v0.3.5' not in f.read(): errors.append('Login/index.tsx does not display v0.3.5')

# 6. Sidebar.tsx
with open('frontend/src/components/Sidebar.tsx', 'r') as f:
    if 'v0.3.5' not in f.read(): errors.append('Sidebar.tsx does not display v0.3.5')

# 7. compose.yaml
with open('compose.yaml', 'r') as f:
    if 'nas-file-center:0.3.5' not in f.read(): errors.append('compose.yaml image tag is not nas-file-center:0.3.5')

# 8. compose.komodo.yaml
with open('compose.komodo.yaml', 'r') as f:
    k_content = f.read()
    if 'kerwinjhc/nas-file-center:0.3.5' not in k_content: errors.append('compose.komodo.yaml image tag is not kerwinjhc/nas-file-center:0.3.5')
    if ':latest' in k_content: errors.append('compose.komodo.yaml contains prohibited :latest tag')

if errors:
    print('G0_INCONSISTENCIES_FOUND:')
    for e in errors: print('  -', e)
    sys.exit(1)
print('G0_ALL_SURFACES_ALIGNED: 0.3.5')
"
```

- [ ] **Step 3: Run release-version consistency contract test**

Run:
```bash
pytest tests/test_release_version_consistency.py -v
```

- [ ] **Step 4: Evaluate G0 Status & Enforce Known Blocker STOP Condition**

Evaluate:
- At baseline commit `073a69eb1e001e1738c32739f9b57820cba1b05f`, the repository contains known historical versions (`0.3.3` in python/frontend, `0.3.2` in compose.yaml, `:latest` in compose.komodo.yaml).
- Therefore, at this baseline, Steps 2 and 3 are expected to output errors and fail.
- **MANDATORY STOP CONDITION:**
  ```text
  If Step 2 or Step 3 fails:
    Mark G0 = FAIL / KNOWN RELEASE METADATA BLOCKER.
    DO NOT proceed to Phase G1 or subsequent execution phases.
    Request separate project-owner authorization for a bounded release-metadata hotfix.
    After the hotfix produces a NEW candidate Git commit SHA, RESTART verification from Task 0.
  ```
- When running against an authorized candidate commit where all 8 surfaces have been updated to `0.3.5` and `tests/test_release_version_consistency.py` passes:
  ```text
  G0_RESULT: PASS
  Proceed to Task 1 (Phase G1).
  ```

---

### Task 1: Phase G1 — Source Regression & Frontend Verification

**Files:**
- Test: `tests/test_filter_*.py`
- Test: `tests/test_gate5b_*.py`
- Test: `tests/test_gate5c_*.py`
- Test: `tests/test_gate5d_*.py`
- Test: `tests/test_gate5e_*.py`
- Test: `tests/test_gate5f_*.py`
- Test: `tests/test_worker_*.py`, `tests/test_task_*.py`, `tests/test_fclones.py`, `tests/test_indexing.py`
- Test: `tests/test_planning.py`, `tests/test_execution.py`
- Test: Full `tests/`
- Frontend: `frontend/`

**Interfaces:**
- Consumes: Validated G0 candidate source tree.
- Produces: Complete backend test metrics (passed, warnings, elapsed) and frontend typecheck/test/build validation artifacts.

- [ ] **Step 1: Execute Gate5-A ~ Gate5-F focused regression suite**

Run:
```bash
CONFIG_DIR=/tmp/test_config DATA_MOUNT=/tmp/test_data .venv/bin/pytest \
  tests/test_filter_ast.py \
  tests/test_filter_compiler.py \
  tests/test_filter_policy.py \
  tests/test_filter_preview.py \
  tests/test_filter_preview_readonly.py \
  tests/test_filter_index_freshness.py \
  tests/test_gate5b_*.py \
  tests/test_gate5c_*.py \
  tests/test_gate5d_*.py \
  tests/test_gate5e_*.py \
  tests/test_gate5f_*.py -v
```
Expected: `0 failed, 0 errors`. Capture exact passed count and execution time.
*Note:* On macOS local runs, if case-sensitive collisions in Gate5-E symlink tests are tested, mount a 10G APFS case-sensitive volume at `/Volumes/CaseSensitiveTest` and specify `--basetemp=/Volumes/CaseSensitiveTest/tmp/pytest`.

- [ ] **Step 2: Execute Task Engine, Worker, and Scanner core regression suite**

Run:
```bash
CONFIG_DIR=/tmp/test_config DATA_MOUNT=/tmp/test_data .venv/bin/pytest \
  tests/test_worker_recovery_and_claim.py \
  tests/test_task_state_machine.py \
  tests/test_task_api.py \
  tests/test_task_checkpoint.py \
  tests/test_task_pause_resume_e2e.py \
  tests/test_gate2_hotfix1_worker_fencing.py \
  tests/test_fclones.py \
  tests/test_scan_jobs.py \
  tests/test_indexing.py \
  tests/test_index_root_lifecycle.py \
  tests/test_index_root_progress_regression.py -v
```
Expected: `0 failed, 0 errors`. Capture exact passed count and execution time.

- [ ] **Step 3: Execute Planning and Execution engine suites**

Run:
```bash
CONFIG_DIR=/tmp/test_config DATA_MOUNT=/tmp/test_data .venv/bin/pytest \
  tests/test_planning.py \
  tests/test_execution.py -v
```
Expected: `0 failed, 0 errors`. Capture exact passed count and execution time.

- [ ] **Step 4: Execute Full Backend Repository Test Suite**

Run:
```bash
CONFIG_DIR=/tmp/test_config DATA_MOUNT=/tmp/test_data .venv/bin/pytest tests/
```
Expected: `0 failed, 0 errors`. Capture raw passed count, warning count, and execution time (e.g. `1149 passed, 19 warnings in 95.95s`).

- [ ] **Step 5: Execute Frontend Typecheck, Automated Tests, and Production Build**

Run:
```bash
cd frontend
npm run typecheck
TYPECHECK_EXIT=$?
npm run test
TEST_EXIT=$?
npm run build
BUILD_EXIT=$?
cd ..
echo "FRONTEND_TYPECHECK_EXIT: ${TYPECHECK_EXIT}"
echo "FRONTEND_TEST_EXIT: ${TEST_EXIT}"
echo "FRONTEND_BUILD_EXIT: ${BUILD_EXIT}"
```
Expected:
- `FRONTEND_TYPECHECK_EXIT == 0`
- `FRONTEND_TEST_EXIT == 0`
- `FRONTEND_BUILD_EXIT == 0`
- `frontend/dist/index.html` exists and is non-empty.

- [ ] **Step 6: Verify Repository Working Tree Hygiene**

Run:
```bash
git diff --check
git status --short
```
Expected:
- `git diff --check` exits with code 0 (no output).
- `git status --short` output is empty.

---

### Task 2: Phase G2 — Clean Linux amd64 Docker Build & Image Archive Transport Protocol

**Files:**
- Build context: Repository root (`Dockerfile`, `app/`, `frontend/`, `pyproject.toml`)
- Output: Image archive `/tmp/nas-file-center-0.3.5-gate5g-${SHORT_SHA}.tar`

**Interfaces:**
- Consumes: Clean, verified candidate Git commit SHA.
- Produces: Exact built Docker image tag, Image ID, archive file, and SHA256 archive checksum.

- [ ] **Step 1: Fix candidate metadata and execute clean Linux amd64 Docker build**

Run:
```bash
VERIFIED_RUNTIME_HEAD=$(git rev-parse HEAD)
SHORT_SHA=$(git rev-parse --short HEAD)
G2_IMAGE_TAG="nas-file-center:0.3.5-gate5g-${SHORT_SHA}"

echo "Building candidate image: ${G2_IMAGE_TAG} on platform linux/amd64..."
docker build --platform linux/amd64 --no-cache -t "${G2_IMAGE_TAG}" .
G2_IMAGE_ID=$(docker inspect --format='{{.Id}}' "${G2_IMAGE_TAG}")
echo "G2_IMAGE_ID: ${G2_IMAGE_ID}"
```
Expected: Docker build completes with exit code 0; `G2_IMAGE_ID` is a 64-character SHA256 hash.

- [ ] **Step 2: Inspect container internals for platform and dependencies**

Run:
```bash
echo "Verifying architecture..."
ARCH_OUT=$(docker run --rm --platform linux/amd64 "${G2_IMAGE_TAG}" uname -m)
[ "${ARCH_OUT}" = "x86_64" ] || { echo "Architecture mismatch: ${ARCH_OUT}"; exit 1; }

echo "Verifying Python version >= 3.12..."
docker run --rm --platform linux/amd64 "${G2_IMAGE_TAG}" python -c "
import sys
assert sys.version_info >= (3, 12), f'Python version must be >= 3.12, got {sys.version_info}'
print('PYTHON_VERSION_OK:', sys.version)
"

echo "Verifying fclones binary..."
FCLONES_OUT=$(docker run --rm --platform linux/amd64 "${G2_IMAGE_TAG}" /usr/local/bin/fclones --version)
echo "fclones version: ${FCLONES_OUT}"

echo "Verifying Python application package imports..."
IMPORT_OUT=$(docker run --rm --platform linux/amd64 "${G2_IMAGE_TAG}" python -c "import app; import app.main; import app.worker; print('IMPORT_OK')")
[ "${IMPORT_OUT}" = "IMPORT_OK" ] || { echo "Application import failed: ${IMPORT_OUT}"; exit 1; }

echo "Verifying frontend static distribution bundle..."
docker run --rm --platform linux/amd64 "${G2_IMAGE_TAG}" bash -c "
test -s /app/frontend/dist/index.html || { echo 'index.html is missing or empty'; exit 1; }
echo 'FRONTEND_DIST_NON_EMPTY_OK'
"
```
Expected: All assertions pass cleanly.

- [ ] **Step 3: Export image to tar archive, compute SHA256 checksum, and write transport manifest**

Run:
```bash
G2_IMAGE_ARCHIVE_PATH="/tmp/nas-file-center-0.3.5-gate5g-${SHORT_SHA}.tar"
echo "Exporting image to ${G2_IMAGE_ARCHIVE_PATH}..."
docker save "${G2_IMAGE_TAG}" -o "${G2_IMAGE_ARCHIVE_PATH}"

if command -v sha256sum >/dev/null 2>&1; then
  G2_IMAGE_ARCHIVE_SHA256=$(sha256sum "${G2_IMAGE_ARCHIVE_PATH}" | awk '{print $1}')
else
  G2_IMAGE_ARCHIVE_SHA256=$(shasum -a 256 "${G2_IMAGE_ARCHIVE_PATH}" | awk '{print $1}')
fi

echo "G2_IMAGE_ARCHIVE_SHA256: ${G2_IMAGE_ARCHIVE_SHA256}"

# Explicitly create transport manifest to hand off identity to target NAS
G2_IMAGE_MANIFEST_PATH="/tmp/gate5g-image-manifest.env"
cat <<EOF > "${G2_IMAGE_MANIFEST_PATH}"
G2_IMAGE_TAG="${G2_IMAGE_TAG}"
G2_IMAGE_ID="${G2_IMAGE_ID}"
G2_IMAGE_ARCHIVE_PATH="${G2_IMAGE_ARCHIVE_PATH}"
G2_IMAGE_ARCHIVE_SHA256="${G2_IMAGE_ARCHIVE_SHA256}"
EOF
echo "G2 Image Manifest created at ${G2_IMAGE_MANIFEST_PATH}:"
cat "${G2_IMAGE_MANIFEST_PATH}"
```
Expected: Tar file is generated; `G2_IMAGE_ARCHIVE_SHA256` is recorded; `/tmp/gate5g-image-manifest.env` is written for deterministic Phase G7 transfer.

---

### Task 3: Phase G3 — Isolated API + Worker Container Smoke & Process Ownership

**Files:**
- Runtime Directory: `/tmp/gate5g-smoke/config`, `/tmp/gate5g-smoke/data`

**Interfaces:**
- Consumes: Built Docker image `G2_IMAGE_TAG`.
- Produces: Container health logs, single worker lease assertion, RBAC response status, restart resilience evidence.

- [ ] **Step 1: Setup isolated test environment and start API container**

Run:
```bash
SMOKE_DIR="/tmp/gate5g-smoke"
rm -rf "${SMOKE_DIR}"
mkdir -p "${SMOKE_DIR}/config" "${SMOKE_DIR}/data"

echo "Starting API container..."
docker run -d --name gate5g-smoke-api \
  --platform linux/amd64 \
  -p 18080:8080 \
  -v "${SMOKE_DIR}/config:/config" \
  -v "${SMOKE_DIR}/data:/data:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  -e ALLOWED_ROOTS=/data \
  -e QUARANTINE_ROOT=/data/.quarantine \
  -e ALLOW_MUTATION=false \
  -e ALLOW_DELETE=false \
  -e PROTECT_LAST_FILE=true \
  -e INITIAL_ADMIN_USERNAME=admin \
  -e INITIAL_ADMIN_PASSWORD=AdminPassword123! \
  "${G2_IMAGE_TAG}"
```
Expected: API container starts; port `18080` bound to host.

- [ ] **Step 2: Poll API healthcheck until healthy and assert exact safety flags**

Run:
```bash
for i in {1..30}; do
  HEALTH_RESP=$(curl -s http://127.0.0.1:18080/health || true)
  if echo "${HEALTH_RESP}" | grep -q '"status":"ok"'; then
    echo "${HEALTH_RESP}" > "${SMOKE_DIR}/health.json"
    break
  fi
  sleep 1
done

python3 -c "
import json
with open('${SMOKE_DIR}/health.json') as f: data = json.load(f)
assert data.get('status') == 'ok', 'status is not ok'
assert data.get('allow_mutation') is False, 'allow_mutation must be False'
assert data.get('allow_delete') is False, 'allow_delete must be False'
assert data.get('protect_last_file') is True, 'protect_last_file must be True'
print('HEALTH_FLAGS_EXACT_MATCH_OK')
"
```
Expected: `GET /health` returns HTTP 200 with `"status":"ok"` and safety flags reflecting `allow_mutation=false`.

- [ ] **Step 3: Start Worker container and verify single worker ownership and lease**

Run:
```bash
echo "Starting Worker container..."
docker run -d --name gate5g-smoke-worker \
  --platform linux/amd64 \
  -v "${SMOKE_DIR}/config:/config" \
  -v "${SMOKE_DIR}/data:/data:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  -e ALLOWED_ROOTS=/data \
  -e QUARANTINE_ROOT=/data/.quarantine \
  -e ALLOW_MUTATION=false \
  -e ALLOW_DELETE=false \
  -e PROTECT_LAST_FILE=true \
  "${G2_IMAGE_TAG}" \
  python -m app.worker

sleep 3

# Login via real session cookie
curl -s -c "${SMOKE_DIR}/cookie.txt" -X POST http://127.0.0.1:18080/api/auth/login \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:18080" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# Query worker status and assert single ownership lease
WORKER_RESP=$(curl -s -b "${SMOKE_DIR}/cookie.txt" http://127.0.0.1:18080/api/tasks/worker)
echo "Worker Response: ${WORKER_RESP}"

python3 -c "
import json
data = json.loads('''${WORKER_RESP}''')
assert data.get('online') is True, 'Worker is not online'
worker_id = data.get('worker_id') or data.get('id')
assert worker_id is not None, 'Worker ID missing'
print(f'SINGLE_WORKER_ONLINE_OK: {worker_id}')
"

# Direct DB proof of single worker state
docker exec gate5g-smoke-api python -c "
from app.db import create_engine_and_session
from app.models import WorkerState, TaskLock
from pathlib import Path
engine, SessionLocal = create_engine_and_session(Path('/config/app.db'))
with SessionLocal() as s:
    workers = s.query(WorkerState).all()
    assert len(workers) == 1, f'Expected exactly 1 WorkerState row, got {len(workers)}'
    lock = s.get(TaskLock, 1)
    assert lock is not None and lock.owner is not None, 'TaskLock owner lease missing'
print('SINGLE_WORKER_OWNERSHIP_LEASE_PROVEN')
"
```
Expected: Worker is online, single WorkerState entry exists, TaskLock has authoritative owner lease.

- [ ] **Step 4: Verify Resource Policy RBAC & Zero-Scheduler Invariant**

Run:
```bash
# Admin query succeeds
ADMIN_POL_RESP=$(curl -s -w "\n%{http_code}" -b "${SMOKE_DIR}/cookie.txt" http://127.0.0.1:18080/api/settings/resource-policy)
HTTP_CODE=$(echo "${ADMIN_POL_RESP}" | tail -n1)
[ "${HTTP_CODE}" = "200" ] || { echo "Admin resource policy read failed: ${ADMIN_POL_RESP}"; exit 1; }

# Create non-admin user via direct DB
docker exec gate5g-smoke-api python -c "
from app.db import create_engine_and_session
from app.models import User
from app.auth.password import hash_password
from pathlib import Path
engine, SessionLocal = create_engine_and_session(Path('/config/app.db'))
with SessionLocal() as s:
    if not s.query(User).filter_by(username='regular').first():
        s.add(User(username='regular', password_hash=hash_password('RegularPassword123!'), role='user'))
        s.commit()
"

# Login as regular user
curl -s -c "${SMOKE_DIR}/cookie_regular.txt" -X POST http://127.0.0.1:18080/api/auth/login \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:18080" \
  -d '{"username":"regular","password":"RegularPassword123!"}'

# Query as regular user -> must return 403
REG_POL_RESP=$(curl -s -w "\n%{http_code}" -b "${SMOKE_DIR}/cookie_regular.txt" http://127.0.0.1:18080/api/settings/resource-policy)
REG_CODE=$(echo "${REG_POL_RESP}" | tail -n1)
[ "${REG_CODE}" = "403" ] || { echo "Non-admin resource policy access was not forbidden: ${REG_CODE}"; exit 1; }

# Verify no scheduled tasks exist in WorkJob table
docker exec gate5g-smoke-api python -c "
from app.db import create_engine_and_session
from app.models import WorkJob
from pathlib import Path
engine, SessionLocal = create_engine_and_session(Path('/config/app.db'))
with SessionLocal() as s:
    count = s.query(WorkJob).count()
    assert count == 0, f'Expected 0 work jobs spawned, found {count}'
print('ZERO_SCHEDULER_INVARIANT_VERIFIED')
"
```
Expected: Admin receives 200, regular user receives 403, 0 scheduled work jobs exist.

- [ ] **Step 5: Verify Worker Restart, API Restart, and Zero Crash-Looping**

Run:
```bash
echo "Restarting Worker container..."
docker restart gate5g-smoke-worker
sleep 3
WORKER_RESTART_RESP=$(curl -s -b "${SMOKE_DIR}/cookie.txt" http://127.0.0.1:18080/api/tasks/worker)
echo "${WORKER_RESTART_RESP}" | grep -q '"online":true' || { echo "Worker did not recover online status after restart"; exit 1; }

echo "Restarting API container..."
docker restart gate5g-smoke-api
sleep 3
HEALTH_AFTER_RESTART=$(curl -s http://127.0.0.1:18080/health)
echo "${HEALTH_AFTER_RESTART}" | grep -q '"status":"ok"' || { echo "API failed after restart"; exit 1; }

# Assert restart counts and no unhandled crash-loops
API_RESTARTS=$(docker inspect --format='{{.RestartCount}}' gate5g-smoke-api)
WORKER_RESTARTS=$(docker inspect --format='{{.RestartCount}}' gate5g-smoke-worker)
echo "API RestartCount: ${API_RESTARTS}, Worker RestartCount: ${WORKER_RESTARTS}"
[ "${API_RESTARTS}" -le 1 ] || { echo "API crash-loop detected"; exit 1; }
[ "${WORKER_RESTARTS}" -le 1 ] || { echo "Worker crash-loop detected"; exit 1; }
```
Expected: Both containers recover cleanly with no crash-looping.

- [ ] **Step 6: Tear down smoke containers**

Run:
```bash
docker stop gate5g-smoke-worker gate5g-smoke-api
docker rm gate5g-smoke-worker gate5g-smoke-api
rm -rf "${SMOKE_DIR}"
```
Expected: Clean teardown; zero lingering containers.

---

### Task 4: Phase G4 — Database Migration (Fresh Install & Upgrade from Gate5-E Baseline)

**Files:**
- Directory: `/tmp/gate5g-migration`
- Historical Git Tree: `3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9`

**Interfaces:**
- Consumes: Built Docker image `G2_IMAGE_TAG`.
- Produces: Verified SQLite databases under fresh and upgraded schemas.

- [ ] **Step 1: Fresh Installation Migration Validation via Actual Application Container**

Run:
```bash
MIG_DIR="/tmp/gate5g-migration"
rm -rf "${MIG_DIR}"
mkdir -p "${MIG_DIR}/fresh_config" "${MIG_DIR}/data"

echo "Starting fresh application container against empty CONFIG..."
docker run -d --name gate5g-mig-fresh   --platform linux/amd64   -p 18083:8080   -v "${MIG_DIR}/fresh_config:/config"   -v "${MIG_DIR}/data:/data:ro"   -e CONFIG_DIR=/config   -e DATA_MOUNT=/data   -e ALLOWED_ROOTS=/data   -e QUARANTINE_ROOT=/data/.quarantine   -e ALLOW_MUTATION=false   -e ALLOW_DELETE=false   -e PROTECT_LAST_FILE=true   "${G2_IMAGE_TAG}"

# Poll health (fail-closed)
HEALTH_OK=0
for i in {1..30}; do
  if curl -s http://127.0.0.1:18083/health | grep -q '"status":"ok"'; then
    HEALTH_OK=1
    echo "Fresh container is healthy"
    break
  fi
  sleep 1
done
[ "${HEALTH_OK}" = "1" ] || {
  docker logs gate5g-mig-fresh
  echo "Fresh container never became healthy"; exit 1;
}

# Gracefully stop container to ensure WAL truncate
docker stop gate5g-mig-fresh
docker rm gate5g-mig-fresh

# Inspect DB offline
python3 -c "
import sqlite3
conn = sqlite3.connect('${MIG_DIR}/fresh_config/app.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type="table";')
tables = {row[0] for row in cursor.fetchall()}
required_tables = {'users', 'sessions', 'work_jobs', 'batch_plans', 'batch_plan_items', 'operation_journal', 'scan_jobs', 'indexed_paths', 'resource_policy'}
missing = required_tables - tables
assert not missing, f'Missing tables in fresh DB: {missing}'
cursor.execute('SELECT id, revision, scan_threads FROM resource_policy WHERE id=1;')
row = cursor.fetchone()
assert row is not None, 'ResourcePolicy singleton id=1 missing'
assert row[1] == 1, f'Expected revision 1, got {row[1]}'
conn.close()
print('FRESH_DB_INSPECTION_SUCCESS')
"

# Restart container against the same DB to prove idempotency
docker run -d --name gate5g-mig-fresh-restart   --platform linux/amd64   -p 18083:8080   -v "${MIG_DIR}/fresh_config:/config"   -v "${MIG_DIR}/data:/data:ro"   -e CONFIG_DIR=/config   -e DATA_MOUNT=/data   "${G2_IMAGE_TAG}"

sleep 3
curl -s http://127.0.0.1:18083/health | grep -q '"status":"ok"' || { echo "Restart failed"; exit 1; }
docker stop gate5g-mig-fresh-restart
docker rm gate5g-mig-fresh-restart
echo "FRESH_DB_IDEMPOTENCY_SUCCESS"
```
Expected: Fresh application container boots, healthcheck passes, DB tables and singleton policy created, second boot is idempotent.

- [ ] **Step 2: Generate historical database from Gate5-E closed baseline (`3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9`)**

Run:
```bash
HIST_SRC_DIR="/tmp/gate5g-hist-src"
rm -rf "${HIST_SRC_DIR}"
mkdir -p "${HIST_SRC_DIR}"

echo "Exporting Gate5-E historical baseline source tree..."
git archive 3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9 app pyproject.toml | tar -x -C "${HIST_SRC_DIR}"

mkdir -p "${MIG_DIR}/historical_original_config"

# Construct and seed historical database inside candidate container (deterministic, network-independent)
docker run --rm   --platform linux/amd64   -v "${HIST_SRC_DIR}:/hist_app:ro"   -v "${MIG_DIR}/historical_original_config:/config"   -w /hist_app   "${G2_IMAGE_TAG}"   python -c "
from pathlib import Path
from app.db import create_engine_and_session, init_db
from app.models import User, Session, WorkJob, BatchPlan, BatchPlanItem, ScanJob, IndexedPath, OperationJournal, utcnow
from app.auth.password import hash_password

db_path = Path('/config/app.db')
engine, SessionLocal = create_engine_and_session(db_path)
init_db(engine, db_path=db_path)

with SessionLocal() as s:
    # 1. User + Session
    u = User(id=1, username='hist_user', password_hash=hash_password('HistPassword123!'), role='user')
    s.add(u)
    s.flush()
    sess = Session(id=1, user_id=1, token_hash='hist_token_hash_abc123', created_at=utcnow(), expires_at=utcnow(), last_seen_at=utcnow())
    s.add(sess)

    # 2. Completed WorkJob
    s.add(WorkJob(id=101, kind='batch-plan-execute', status='completed', state_json='{}', created_at=utcnow()))

    # 3. Queued WorkJob
    s.add(WorkJob(id=102, kind='fclones-scan', status='queued', state_json='{}', created_at=utcnow()))

    # 4. BatchPlan (id: int, name: str, kind: str, expected_changes: int)
    bp = BatchPlan(id=1, name='plan-hist-001', kind='dedupe', status='completed', expected_changes=1, expected_reclaim_bytes=1024, created_at=utcnow())
    s.add(bp)
    s.flush()

    # 5. BatchPlanItem (plan_id: int, sequence: int, operation: str, state: str - Note: NO created_at in historical BatchPlanItem)
    bpi = BatchPlanItem(id=1, plan_id=1, sequence=1, operation='quarantine', source_path='/data/old.txt', target_path='/quarantine/old.txt', keep_path='/data/keep.txt', state='completed')
    s.add(bpi)
    s.flush()

    # 6. ScanJob
    s.add(ScanJob(id=1, name='scan-001', mode='normal', roots_json='["/data"]', status='completed', created_at=utcnow()))

    # 7. IndexedPath (Note: NO created_at in historical IndexedPath, uses first_seen_at / last_seen_at)
    s.add(IndexedPath(id=1, root_key='/data', absolute_path='/data/old.txt', relative_path='old.txt', basename='old.txt', stem='old', suffix='.txt', scan_generation='gen1', first_seen_at=utcnow(), last_seen_at=utcnow()))

    # 8. OperationJournal (real fields: operation, sequence, plan_id, plan_item_id, task_id, user_id)
    s.add(OperationJournal(id=1, operation='quarantine', sequence=1, plan_id=1, plan_item_id=1, task_id=101, user_id=1, before_json='{}', after_json='{}', metadata_before_json='{}', metadata_after_json='{}', created_at=utcnow()))

    s.commit()
print('HISTORICAL_DB_ALL_ENTITIES_SEEDED_SUCCESS')
"
rm -rf "${HIST_SRC_DIR}"
```
Expected: Historical DB created with users, sessions, jobs, plans, plan items, scan jobs, indexed paths, and operation journals matching exact Gate5-E schema; preserved untouched in `historical_original_config/app.db`.

- [ ] **Step 3: Run candidate application container against an isolated COPY of historical database**

Run:
```bash
# Create isolated upgrade-test CONFIG directory whose tested historical COPY is named exactly app.db
mkdir -p "${MIG_DIR}/upgrade_test_config"
cp "${MIG_DIR}/historical_original_config/app.db" "${MIG_DIR}/upgrade_test_config/app.db"

# Start candidate application container against that directory (where Settings.database_path resolves to /config/app.db)
docker run -d --name gate5g-mig-upgrade   --platform linux/amd64   -p 18084:8080   -v "${MIG_DIR}/upgrade_test_config:/config"   -v "${MIG_DIR}/data:/data:ro"   -e CONFIG_DIR=/config   -e DATA_MOUNT=/data   "${G2_IMAGE_TAG}"   uvicorn app.main:app --host 0.0.0.0 --port 8080

# Poll health (fail-closed)
UPGRADE_HEALTH_OK=0
for i in {1..30}; do
  if curl -s http://127.0.0.1:18084/health | grep -q '"status":"ok"'; then
    UPGRADE_HEALTH_OK=1
    echo "Upgraded container is healthy"
    break
  fi
  sleep 1
done
[ "${UPGRADE_HEALTH_OK}" = "1" ] || {
  docker logs gate5g-mig-upgrade
  echo "Upgraded container never became healthy"; exit 1;
}

# Gracefully stop container
docker stop gate5g-mig-upgrade
docker rm gate5g-mig-upgrade

# Inspect upgraded database offline at ${MIG_DIR}/upgrade_test_config/app.db
python3 -c "
import sqlite3
conn = sqlite3.connect('${MIG_DIR}/upgrade_test_config/app.db')
cursor = conn.cursor()

# 1. Assert ResourcePolicy table added and singleton row seeded
cursor.execute('SELECT id, revision FROM resource_policy WHERE id=1;')
row = cursor.fetchone()
assert row == (1, 1), f'Expected ResourcePolicy id=1 revision=1, got {row}'

# 2. Assert pre-existing Gate5-E records completely preserved
cursor.execute('SELECT username FROM users WHERE id=1;')
assert cursor.fetchone() == ('hist_user',), 'User record lost'

cursor.execute('SELECT token_hash FROM sessions WHERE id=1;')
assert cursor.fetchone() == ('hist_token_hash_abc123',), 'Session record lost'

cursor.execute('SELECT status FROM work_jobs WHERE id=101;')
assert cursor.fetchone() == ('completed',), 'Completed WorkJob lost'

cursor.execute('SELECT status FROM work_jobs WHERE id=102;')
assert cursor.fetchone() == ('queued',), 'Queued WorkJob lost'

cursor.execute('SELECT name, expected_changes FROM batch_plans WHERE id=1;')
assert cursor.fetchone() == ('plan-hist-001', 1), 'BatchPlan lost'

cursor.execute('SELECT operation, state FROM batch_plan_items WHERE id=1;')
assert cursor.fetchone() == ('quarantine', 'completed'), 'BatchPlanItem lost'

cursor.execute('SELECT name FROM scan_jobs WHERE id=1;')
assert cursor.fetchone() == ('scan-001',), 'ScanJob lost'

cursor.execute('SELECT basename FROM indexed_paths WHERE id=1;')
assert cursor.fetchone() == ('old.txt',), 'IndexedPath lost'

cursor.execute('SELECT operation FROM operation_journal WHERE id=1;')
assert cursor.fetchone() == ('quarantine',), 'OperationJournal lost'

conn.close()
print('UPGRADE_MIGRATION_RECORDS_PRESERVED_SUCCESS')
"

# Restart candidate container against the exact same DB to prove idempotency
docker run -d --name gate5g-mig-upgrade-restart   --platform linux/amd64   -p 18084:8080   -v "${MIG_DIR}/upgrade_test_config:/config"   -v "${MIG_DIR}/data:/data:ro"   -e CONFIG_DIR=/config   -e DATA_MOUNT=/data   "${G2_IMAGE_TAG}"   uvicorn app.main:app --host 0.0.0.0 --port 8080

sleep 3
curl -s http://127.0.0.1:18084/health | grep -q '"status":"ok"' || { echo "Restart failed"; exit 1; }
docker stop gate5g-mig-upgrade-restart
docker rm gate5g-mig-upgrade-restart
echo "UPGRADE_MIGRATION_IDEMPOTENCY_SUCCESS"
```
Expected: Additive migration creates `resource_policy` table without dropping or corrupting any historical records; second container start is idempotent; untouched original historical database remains preserved in `historical_original_config/app.db`.

---

### Task 5: Phase G5 — SQLite Integrity Check & Schema / Index Constraint Verification

**Files:**
- Database: `/tmp/gate5g-migration/fresh_config/app.db` and `/tmp/gate5g-migration/upgrade_test_config/app.db`

**Interfaces:**
- Consumes: Post-migration SQLite databases after clean container shutdown.
- Produces: Raw PRAGMA integrity check, foreign key check, and schema/foreign key/index constraint verification outputs.

- [ ] **Step 1: Checkpoint WAL and run SQLite integrity & foreign key checks**

Run:
```bash
python3 -c "
import sqlite3

for name, p in [('fresh', '/tmp/gate5g-migration/fresh_config/app.db'), ('upgrade', '/tmp/gate5g-migration/upgrade_test_config/app.db')]:
    conn = sqlite3.connect(p)
    cursor = conn.cursor()
    # Checkpoint WAL
    cursor.execute('PRAGMA wal_checkpoint(TRUNCATE);')
    # Integrity check
    cursor.execute('PRAGMA integrity_check;')
    res = cursor.fetchall()
    assert res == [('ok',)], f'{name} integrity_check failed: {res}'
    # Foreign key check
    cursor.execute('PRAGMA foreign_key_check;')
    fk_res = cursor.fetchall()
    assert len(fk_res) == 0, f'{name} foreign_key_check found violations: {fk_res}'
    # Singleton check
    cursor.execute('SELECT count(*), id, revision FROM resource_policy;')
    cnt, rid, rev = cursor.fetchone()
    assert cnt == 1 and rid == 1 and rev == 1, f'{name} resource_policy singleton corrupted: count={cnt}, id={rid}, revision={rev}'
    conn.close()
    print(f'SQLITE_PRAGMA_CHECKS_PASS: {name}')
"
```
Expected: Both fresh and upgraded databases return `integrity_check = ok`, `foreign_key_check = 0 rows`, and `resource_policy` count = 1, id = 1, revision = 1.

- [ ] **Step 2: Verify expected schema, foreign keys, unique constraints, and indexes required by Freeze**

Run:
```bash
python3 -c "
import sqlite3

for name, p in [('fresh', '/tmp/gate5g-migration/fresh_config/app.db'), ('upgrade', '/tmp/gate5g-migration/upgrade_test_config/app.db')]:
    conn = sqlite3.connect(p)
    cursor = conn.cursor()

    # 1. PRAGMA table_info for resource_policy columns
    cursor.execute('PRAGMA table_info(resource_policy);')
    cols = {row[1] for row in cursor.fetchall()}
    expected_cols = {
        'id', 'scan_threads', 'hash_threads', 'io_limit', 'job_priority',
        'active_window_enabled', 'active_window_start', 'active_window_end',
        'active_window_timezone', 'outside_window_mode', 'revision'
    }
    missing_cols = expected_cols - cols
    assert not missing_cols, f'{name} resource_policy missing columns: {missing_cols}'

    # 2. PRAGMA foreign_key_list for representative critical relationships
    cursor.execute('PRAGMA foreign_key_list(batch_plan_items);')
    bpi_fks = cursor.fetchall()
    assert any(row[2] == 'batch_plans' and row[3] == 'plan_id' for row in bpi_fks), f'{name} batch_plan_items missing FK to batch_plans'

    cursor.execute('PRAGMA foreign_key_list(sessions);')
    sess_fks = cursor.fetchall()
    assert any(row[2] == 'users' and row[3] == 'user_id' for row in sess_fks), f'{name} sessions missing FK to users'

    # 3. PRAGMA index_list & PRAGMA index_info for verified unique constraints
    def assert_unique_column(table_name, expected_column):
        cursor.execute(f"PRAGMA index_list({table_name});")
        indexes = cursor.fetchall()
        for idx in indexes:
            if idx[2] == 1:  # unique index
                idx_name = idx[1]
                cursor.execute(f"PRAGMA index_info('{idx_name}');")
                cols = [col[2] for col in cursor.fetchall()]
                if expected_column in cols:
                    return
        raise AssertionError(f"{name} table {table_name} missing unique constraint on column {expected_column}")

    assert_unique_column('users', 'username')
    assert_unique_column('sessions', 'token_hash')
    assert_unique_column('quarantine_entries', 'quarantine_path')
    assert_unique_column('indexed_paths', 'absolute_path')

    # 4. Verify required named indexes exist in sqlite_master
    cursor.execute('SELECT name FROM sqlite_master WHERE type="index";')
    indexes = {row[0] for row in cursor.fetchall()}
    required_indexes = {
        'ix_work_jobs_status',
        'ix_work_jobs_kind',
        'ix_batch_plan_items_plan_state',
        'ix_operation_journal_plan_sequence',
        'ix_indexed_paths_root_relative'
    }
    missing_indexes = required_indexes - indexes
    assert not missing_indexes, f'{name} missing required indexes: {missing_indexes}'

    conn.close()
    print(f'SCHEMA_FK_UNIQUE_INDEX_CONSTRAINTS_VERIFIED: {name}')
"
```
Expected: All required columns, foreign keys, unique constraints, and indexes exist in both fresh and upgraded databases.

- [ ] **Step 3: Clean up migration temporary directory**

Run:
```bash
rm -rf "/tmp/gate5g-migration"
```
Expected: Directory removed cleanly.

---

### Task 6: Phase G6 — Synthetic Filesystem Safety & Mutation Lifecycle Black-Box

**Files:**
- Fixture: `/tmp/gate5g-safety-fixture/`

**Interfaces:**
- Consumes: Built Docker image `G2_IMAGE_TAG`.
- Produces: Verification of 5-stage lifecycle (`Preview -> Draft -> Freeze -> Validate -> Execute`), plan-derived keep/quarantine assertions, separate stale preflight rejection, reachable symlink protection, and mandatory quarantine restore.

- [ ] **Step 1: Construct deterministic synthetic filesystem fixture with reachable symlink target**

Run:
```bash
FIXTURE_DIR="/tmp/gate5g-safety-fixture"
rm -rf "${FIXTURE_DIR}"
mkdir -p "${FIXTURE_DIR}/allowed_root" "${FIXTURE_DIR}/quarantine_root" "${FIXTURE_DIR}/sentinel_dir" "${FIXTURE_DIR}/config"

# Primary group duplicates (byte-identical)
echo "GATE5G_SYNTHETIC_DUPLICATE_GROUP1_CONTENT_DATA_ABC" > "${FIXTURE_DIR}/allowed_root/group1_fileA.dat"
cp "${FIXTURE_DIR}/allowed_root/group1_fileA.dat" "${FIXTURE_DIR}/allowed_root/group1_fileB.dat"

# Solitary unique file
echo "GATE5G_SYNTHETIC_UNIQUE_SOLITARY_FILE_123" > "${FIXTURE_DIR}/allowed_root/unique_file.txt"

# External sentinel file outside allowed root
echo "GATE5G_EXTERNAL_SENTINEL_DO_NOT_ALTER_SAFETY_LOCK" > "${FIXTURE_DIR}/sentinel_dir/external_file.txt"

# Reachable symlink pointing to external sentinel via container path (/sentinel/external_file.txt)
ln -s "/sentinel/external_file.txt" "${FIXTURE_DIR}/allowed_root/symlink_to_external"

# Verify from container namespace that escape target is genuinely reachable and symlink resolves
docker run --rm \
  --platform linux/amd64 \
  -v "${FIXTURE_DIR}/allowed_root:/data:ro" \
  -v "${FIXTURE_DIR}/sentinel_dir:/sentinel:ro" \
  "${G2_IMAGE_TAG}" \
  bash -c "
test -f /sentinel/external_file.txt || { echo 'Sentinel target missing in container'; exit 1; }
test -L /data/symlink_to_external || { echo 'Symlink missing in container'; exit 1; }
test -f /data/symlink_to_external || { echo 'Symlink referent unreachable in container'; exit 1; }
echo 'REACHABLE_SYMLINK_FIXTURE_VERIFIED_IN_CONTAINER'
"

# Record baseline snapshot of entire fixture (file set, SHA256, size, mtime_ns)
python3 -c "
import hashlib, os, json
from pathlib import Path

root = Path('${FIXTURE_DIR}')
baseline = {}
for subdir in ['allowed_root', 'sentinel_dir']:
    for p in (root / subdir).rglob('*'):
        if p.is_file() and not p.is_symlink():
            rel = str(p.relative_to(root))
            st = p.stat()
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            baseline[rel] = {'sha256': h, 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}

with open('${FIXTURE_DIR}/baseline_records.json', 'w') as f:
    json.dump(baseline, f, indent=2)
print('BASELINE_RECORDS_SAVED:', len(baseline), 'files')
"
```
Expected: Fixture created; primary duplicate pair and sentinel file verified; symlink referent proven reachable inside container namespace; baseline recorded. Note: Stale duplicate pair will be created in Step 5 as a separate, independent scenario.

- [ ] **Step 2: Read-Only Safety Verification Stage (Real Worker-Backed Execution & Exact Snapshot Comparison)**

Start real API and Worker containers with safe read-only configuration (mounting sentinel outside `/data`):
```bash
docker run -d --name gate5g-safety-ro-api \
  --platform linux/amd64 \
  -p 18081:8080 \
  -v "${FIXTURE_DIR}/config:/config" \
  -v "${FIXTURE_DIR}/allowed_root:/data:ro" \
  -v "${FIXTURE_DIR}/quarantine_root:/quarantine:ro" \
  -v "${FIXTURE_DIR}/sentinel_dir:/sentinel:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  -e ALLOWED_ROOTS=/data \
  -e QUARANTINE_ROOT=/quarantine \
  -e ALLOW_MUTATION=false \
  -e ALLOW_DELETE=false \
  -e PROTECT_LAST_FILE=true \
  -e INITIAL_ADMIN_USERNAME=admin \
  -e INITIAL_ADMIN_PASSWORD=AdminPassword123! \
  "${G2_IMAGE_TAG}"

docker run -d --name gate5g-safety-ro-worker \
  --platform linux/amd64 \
  -v "${FIXTURE_DIR}/config:/config" \
  -v "${FIXTURE_DIR}/allowed_root:/data:ro" \
  -v "${FIXTURE_DIR}/quarantine_root:/quarantine:ro" \
  -v "${FIXTURE_DIR}/sentinel_dir:/sentinel:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  -e ALLOWED_ROOTS=/data \
  -e QUARANTINE_ROOT=/quarantine \
  -e ALLOW_MUTATION=false \
  -e ALLOW_DELETE=false \
  -e PROTECT_LAST_FILE=true \
  "${G2_IMAGE_TAG}" \
  python -m app.worker

sleep 3
# Login
curl -s -c "${FIXTURE_DIR}/cookie.txt" -X POST http://127.0.0.1:18081/api/auth/login \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:18081" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# 1. Trigger scan via real API with valid name and roots
SCAN_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie.txt" -X POST http://127.0.0.1:18081/api/scans \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18081" \
  -d '{"name":"safety-ro-scan","roots":["/data"]}')
echo "Scan enqueue response: ${SCAN_RESP}"
SCAN_ID=$(echo "${SCAN_RESP}" | grep -o '"scan_job_id":[0-9]*' | cut -d: -f2)
[ -n "${SCAN_ID}" ] || { echo "Failed to enqueue scan"; exit 1; }

# Poll scan job until Worker completes it
for i in {1..30}; do
  STATUS=$(curl -s -b "${FIXTURE_DIR}/cookie.txt" "http://127.0.0.1:18081/api/scans/${SCAN_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  echo "Polling scan status: ${STATUS}"
  if [ "${STATUS}" = "completed" ]; then break; fi
  if [ "${STATUS}" = "failed" ]; then echo "Scan failed in worker"; docker logs gate5g-safety-ro-worker; exit 1; fi
  sleep 1
done
[ "${STATUS}" = "completed" ] || { echo "Scan timed out waiting for worker"; exit 1; }

# 2. Trigger index via /api/indexes, capture work_job_id, and poll until completed
INDEX_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie.txt" -X POST http://127.0.0.1:18081/api/indexes \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18081" \
  -d '{"root":"/data"}')
echo "Index enqueue response: ${INDEX_RESP}"
INDEX_WORK_JOB_ID=$(echo "${INDEX_RESP}" | grep -o '"work_job_id":[0-9]*' | cut -d: -f2)
[ -n "${INDEX_WORK_JOB_ID}" ] || { echo "Failed to enqueue index task"; exit 1; }

for i in {1..30}; do
  INDEX_STATUS=$(curl -s -b "${FIXTURE_DIR}/cookie.txt" "http://127.0.0.1:18081/api/tasks/${INDEX_WORK_JOB_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  echo "Polling index WorkJob status: ${INDEX_STATUS}"
  if [ "${INDEX_STATUS}" = "completed" ]; then break; fi
  if [ "${INDEX_STATUS}" = "failed" ] || [ "${INDEX_STATUS}" = "cancelled" ]; then
    echo "Index WorkJob failed or cancelled: ${INDEX_STATUS}"; docker logs gate5g-safety-ro-worker; exit 1
  fi
  sleep 1
done
[ "${INDEX_STATUS}" = "completed" ] || { echo "Index WorkJob timed out"; exit 1; }

# 3. Trigger real dedupe preview
PREVIEW_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie.txt" -X POST "http://127.0.0.1:18081/api/scans/${SCAN_ID}/dedupe-preview" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18081" -d '{}')
echo "Preview response: ${PREVIEW_RESP}"

docker stop gate5g-safety-ro-worker gate5g-safety-ro-api
docker rm gate5g-safety-ro-worker gate5g-safety-ro-api

# Assert zero mutation: compare current file set, hashes, sizes, and mtimes with baseline
python3 -c "
import hashlib, json
from pathlib import Path

root = Path('${FIXTURE_DIR}')
current = {}
for subdir in ['allowed_root', 'sentinel_dir']:
    for p in (root / subdir).rglob('*'):
        if p.is_file() and not p.is_symlink():
            rel = str(p.relative_to(root))
            st = p.stat()
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            current[rel] = {'sha256': h, 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}

with open('${FIXTURE_DIR}/baseline_records.json') as f:
    baseline = json.load(f)

# Assert exact file set identity (unexpected creation or deletion fails)
assert set(current.keys()) == set(baseline.keys()), (
    f'File set changed! Added: {set(current.keys()) - set(baseline.keys())}, '
    f'Removed: {set(baseline.keys()) - set(current.keys())}'
)

for rel, expected in baseline.items():
    cur = current[rel]
    assert cur['size'] == expected['size'], f'Size changed for {rel}: expected {expected["size"]}, got {cur["size"]}'
    assert cur['mtime_ns'] == expected['mtime_ns'], f'Mtime changed for {rel}: expected {expected["mtime_ns"]}, got {cur["mtime_ns"]}'
    assert cur['sha256'] == expected['sha256'], f'Content hash changed for {rel}: expected {expected["sha256"]}, got {cur["sha256"]}'
print('READ_ONLY_STAGE_ZERO_MUTATION_VERIFIED_SUCCESS')
"
```
Expected: Real scan and index executed and verified completed by Worker; dedupe preview generated; zero disk mutations across file set, hashes, sizes, and mtimes.

- [ ] **Step 3: Controlled Dedupe Mutation Stage (Primary Lifecycle & Plan-Derived Schema Compliance)**

Start real API and Worker containers in controlled mutation mode:
```bash
docker run -d --name gate5g-safety-rw-api \
  --platform linux/amd64 \
  -p 18082:8080 \
  -v "${FIXTURE_DIR}/config:/config" \
  -v "${FIXTURE_DIR}/allowed_root:/data:rw" \
  -v "${FIXTURE_DIR}/quarantine_root:/quarantine:rw" \
  -v "${FIXTURE_DIR}/sentinel_dir:/sentinel:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  -e ALLOWED_ROOTS=/data \
  -e QUARANTINE_ROOT=/quarantine \
  -e ALLOW_MUTATION=true \
  -e ALLOW_DELETE=false \
  -e PROTECT_LAST_FILE=true \
  "${G2_IMAGE_TAG}"

docker run -d --name gate5g-safety-rw-worker \
  --platform linux/amd64 \
  -v "${FIXTURE_DIR}/config:/config" \
  -v "${FIXTURE_DIR}/allowed_root:/data:rw" \
  -v "${FIXTURE_DIR}/quarantine_root:/quarantine:rw" \
  -v "${FIXTURE_DIR}/sentinel_dir:/sentinel:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  -e ALLOWED_ROOTS=/data \
  -e QUARANTINE_ROOT=/quarantine \
  -e ALLOW_MUTATION=true \
  -e ALLOW_DELETE=false \
  -e PROTECT_LAST_FILE=true \
  "${G2_IMAGE_TAG}" \
  python -m app.worker

sleep 3
# Login
curl -s -c "${FIXTURE_DIR}/cookie_rw.txt" -X POST http://127.0.0.1:18082/api/auth/login \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:18082" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# 1. Enqueue scan targeting allowed_root
SCAN_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST http://127.0.0.1:18082/api/scans \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18082" \
  -d '{"name":"mutation-scan","roots":["/data"]}')
SCAN_ID=$(echo "${SCAN_RESP}" | grep -o '"scan_job_id":[0-9]*' | cut -d: -f2)

# Poll until completed
for i in {1..30}; do
  STATUS=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" "http://127.0.0.1:18082/api/scans/${SCAN_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  if [ "${STATUS}" = "completed" ]; then break; fi
  sleep 1
done

# 2. Preview
PREVIEW_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/scans/${SCAN_ID}/dedupe-preview" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18082" -d '{}')
echo "Preview response: ${PREVIEW_RESP}"

# 3. Explicit Generate Draft Plan through real dedupe endpoint
PLAN_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/scans/${SCAN_ID}/dedupe-plan" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18082" \
  -d '{"policy":"newest"}')
echo "Draft plan response: ${PLAN_RESP}"
PLAN_ID=$(echo "${PLAN_RESP}" | grep -o '"id":[0-9]*' | cut -d: -f2)
[ -n "${PLAN_ID}" ] || { echo "Failed to create dedupe plan"; exit 1; }

# 4. Freeze
FREEZE_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${PLAN_ID}/freeze" \
  -H "Origin: http://127.0.0.1:18082")
echo "Freeze response: ${FREEZE_RESP}"

# 5. Inspect Frozen Plan: extract plan-derived paths using exact API schema (source, keep)
PLAN_ITEMS=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" "http://127.0.0.1:18082/api/plans/${PLAN_ID}/items")
echo "Frozen Plan Items: ${PLAN_ITEMS}"

python3 -c "
import json
data = json.loads('''${PLAN_ITEMS}''')
items = data.get('items', [])
assert len(items) >= 1, 'No items in frozen plan'
target_item = None
for it in items:
    if 'group1' in it['source']:
        target_item = it
        break
assert target_item is not None, 'group1 item not found in plan'

with open('${FIXTURE_DIR}/plan_paths.json', 'w') as f:
    json.dump({
        'keep_path': target_item['keep'],
        'mutation_source': target_item['source'],
        'item_id': target_item['id']
    }, f)
print('PLAN_DERIVED_PATHS_EXTRACTED:', target_item['keep'], '->', target_item['source'])
"

ACTUAL_KEEP_PATH=$(python3 -c "import json; print(json.load(open('${FIXTURE_DIR}/plan_paths.json'))['keep_path'])")
ACTUAL_MUTATION_SOURCE=$(python3 -c "import json; print(json.load(open('${FIXTURE_DIR}/plan_paths.json'))['mutation_source'])")

# 6. Validate
VAL_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${PLAN_ID}/validate" \
  -H "Origin: http://127.0.0.1:18082")
echo "Validate Response: ${VAL_RESP}"

# 7. Execute (asynchronous via Worker)
EXEC_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${PLAN_ID}/execute" \
  -H "Origin: http://127.0.0.1:18082")
echo "Execute Response: ${EXEC_RESP}"
WORK_JOB_ID=$(echo "${EXEC_RESP}" | grep -o '"work_job_id":[0-9]*' | cut -d: -f2)

# Poll WorkJob until terminal completion
for i in {1..30}; do
  JOB_STATUS=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" "http://127.0.0.1:18082/api/tasks/${WORK_JOB_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  echo "Polling plan execution WorkJob status: ${JOB_STATUS}"
  if [ "${JOB_STATUS}" = "completed" ]; then break; fi
  if [ "${JOB_STATUS}" = "failed" ]; then echo "Execution failed in worker"; docker logs gate5g-safety-rw-worker; exit 1; fi
  sleep 1
done
[ "${JOB_STATUS}" = "completed" ] || { echo "Execution timed out"; exit 1; }

# Map container path to host fixture path
HOST_KEEP_PATH="${FIXTURE_DIR}/allowed_root/$(basename ${ACTUAL_KEEP_PATH})"
HOST_MUTATION_SOURCE="${FIXTURE_DIR}/allowed_root/$(basename ${ACTUAL_MUTATION_SOURCE})"

# Verify plan-derived postconditions
[ -f "${HOST_KEEP_PATH}" ] || { echo "Protected keep copy missing: ${HOST_KEEP_PATH}"; exit 1; }
[ ! -f "${HOST_MUTATION_SOURCE}" ] || { echo "Quarantined source still in allowed root: ${HOST_MUTATION_SOURCE}"; exit 1; }

# Query QuarantineEntry associated with actual executed item and verify state == 'active'
Q_LIST=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" http://127.0.0.1:18082/api/quarantine)
python3 -c "
import json, os
data = json.loads('''${Q_LIST}''')
entries = data.get('items', [])
match = None
for e in entries:
    if e['original_path'] == '${ACTUAL_MUTATION_SOURCE}':
        match = e
        break
assert match is not None, f'No quarantine entry found for ${ACTUAL_MUTATION_SOURCE}'
assert match['state'] == 'active', f'Expected state active, got {match["state"]}'

# Map quarantine_path to host path using relative path from /quarantine to handle nested structures
rel_qpath = os.path.relpath(match['quarantine_path'], '/quarantine')
host_qpath = os.path.join('${FIXTURE_DIR}/quarantine_root', rel_qpath)
assert os.path.isfile(host_qpath), f'Quarantined file missing at mapped host path: {host_qpath}'

with open('${FIXTURE_DIR}/quarantine_entry.json', 'w') as f:
    json.dump({
        'id': match['id'],
        'quarantine_path': match['quarantine_path'],
        'host_qpath': host_qpath
    }, f)
print('QUARANTINE_ENTRY_ASSOCIATED_AND_ACTIVE:', match['id'], 'target:', host_qpath)
"
```
Expected: Real dedupe chain executed; keep path preserved; planned mutation source moved to quarantine root and associated with QuarantineEntry with `state == 'active'`.

- [ ] **Step 4: Mandatory Quarantine Restore Stage**

Run:
```bash
# Load associated quarantine entry id and mapped host quarantine path from Step 3
QUARANTINE_ENTRY_ID=$(python3 -c "import json; print(json.load(open('${FIXTURE_DIR}/quarantine_entry.json'))['id'])")
HOST_QUARANTINE_FILE=$(python3 -c "import json; print(json.load(open('${FIXTURE_DIR}/quarantine_entry.json'))['host_qpath'])")

echo "Restoring QuarantineEntry ID: ${QUARANTINE_ENTRY_ID}..."

# Call POST /api/quarantine/{id}/restore through real API
RESTORE_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/quarantine/${QUARANTINE_ENTRY_ID}/restore" \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:18082" \
  -d '{}')
echo "Restore Response: ${RESTORE_RESP}"

# Verify returned state == restored
python3 -c "
import json
data = json.loads('''${RESTORE_RESP}''')
assert data.get('state') == 'restored', f'Expected state restored, got {data.get("state")}'
print('RESTORE_RESPONSE_STATE_OK')
"

# Verify original destination file recovered with byte-for-byte hash equality against baseline
[ -f "${HOST_MUTATION_SOURCE}" ] || { echo "Restored file missing from original destination"; exit 1; }
python3 -c "
import hashlib, json
records = json.load(open('${FIXTURE_DIR}/baseline_records.json'))
baseline_entry = records['allowed_root/$(basename ${HOST_MUTATION_SOURCE})']
restored_data = open('${HOST_MUTATION_SOURCE}', 'rb').read()
restored_hash = hashlib.sha256(restored_data).hexdigest()
assert restored_hash == baseline_entry['sha256'], f'Restored hash mismatch: expected {baseline_entry["sha256"]}, got {restored_hash}'
assert len(restored_data) == baseline_entry['size'], f'Restored size mismatch: expected {baseline_entry["size"]}, got {len(restored_data)}'
print('RESTORED_BYTE_FOR_BYTE_EQUALITY_OK')
"

# Verify quarantine source no longer exists
[ ! -f "${HOST_QUARANTINE_FILE}" ] || { echo "Quarantined source still exists in quarantine root: ${HOST_QUARANTINE_FILE}"; exit 1; }

echo "MANDATORY_QUARANTINE_RESTORE_SUCCESS"
```
Expected: Specific QuarantineEntry restored; state transitions to `restored`; original file recovered with byte-for-byte identical SHA256 and size; quarantine source cleaned up.

- [ ] **Step 5: Real Dedupe Stale Preflight Protection Stage (Separate Independent Duplicate Scenario)**

Run:
```bash
# Construct a separate, fresh duplicate pair strictly after primary lifecycle completion
echo "GATE5G_SYNTHETIC_STALE_DUPLICATE_GROUP_INDEPENDENT_AAA" > "${FIXTURE_DIR}/allowed_root/stale_fileA.dat"
cp "${FIXTURE_DIR}/allowed_root/stale_fileA.dat" "${FIXTURE_DIR}/allowed_root/stale_fileB.dat"

# Trigger a separate fresh scan for the stale scenario
SCAN_STALE_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST http://127.0.0.1:18082/api/scans \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18082" \
  -d '{"name":"stale-scan","roots":["/data"]}')
STALE_SCAN_ID=$(echo "${SCAN_STALE_RESP}" | grep -o '"scan_job_id":[0-9]*' | cut -d: -f2)

for i in {1..30}; do
  STATUS=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" "http://127.0.0.1:18082/api/scans/${STALE_SCAN_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  if [ "${STATUS}" = "completed" ]; then break; fi
  sleep 1
done

# Preview -> Draft Plan -> Freeze
curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/scans/${STALE_SCAN_ID}/dedupe-preview" -H "Origin: http://127.0.0.1:18082" -d '{}'
STALE_PLAN_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/scans/${STALE_SCAN_ID}/dedupe-plan" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18082" -d '{"policy":"newest"}')
STALE_PLAN_ID=$(echo "${STALE_PLAN_RESP}" | grep -o '"id":[0-9]*' | cut -d: -f2)

curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/freeze" -H "Origin: http://127.0.0.1:18082"

# Inspect frozen items using correct schema (source, keep) to find actual mutation source
STALE_ITEMS=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/items")
python3 -c "
import json
data = json.loads('''${STALE_ITEMS}''')
items = data.get('items', [])
target = None
for it in items:
    if 'stale_file' in it['source']:
        target = it
        break
assert target is not None, 'stale item not found in frozen plan'
with open('${FIXTURE_DIR}/stale_source.txt', 'w') as f:
    f.write(target['source'])
print('STALE_ACTUAL_SOURCE:', target['source'])
"
ACTUAL_STALE_SOURCE=$(cat "${FIXTURE_DIR}/stale_source.txt")
HOST_STALE_SOURCE="${FIXTURE_DIR}/allowed_root/$(basename ${ACTUAL_STALE_SOURCE})"

# Externally modify THAT exact source file after Freeze
echo "TAMPERED_MODIFIED_PAYLOAD_AFTER_FREEZE" >> "${HOST_STALE_SOURCE}"

# Validate -> MUST detect stale state
STALE_VAL_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/validate" -H "Origin: http://127.0.0.1:18082")
echo "Stale Validate Response: ${STALE_VAL_RESP}"
echo "${STALE_VAL_RESP}" | grep -E "stale|STALE" || { echo "Validate did not detect stale state"; exit 1; }

# Attempt Execute -> MUST BE REFUSED with HTTP 409 and JSON error.code == PLAN_STALE
STALE_EXEC_RESP=$(curl -s -w "\n%{http_code}" -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/execute" -H "Origin: http://127.0.0.1:18082")
STALE_EXEC_CODE=$(echo "${STALE_EXEC_RESP}" | tail -n1)
STALE_EXEC_BODY=$(echo "${STALE_EXEC_RESP}" | sed '$d')
echo "Stale Execute Status Code: ${STALE_EXEC_CODE}, Body: ${STALE_EXEC_BODY}"
[ "${STALE_EXEC_CODE}" = "409" ] || { echo "Expected 409 for stale execution, got ${STALE_EXEC_CODE}"; exit 1; }
python3 -c "
import json
body = json.loads('''${STALE_EXEC_BODY}''')
err = body.get('error') or {}
err_code = err.get('code') if isinstance(err, dict) else None
assert err_code == 'PLAN_STALE', f'Expected error.code == PLAN_STALE, got: {body}'
print('G6_PLAN_STALE_CODE_VERIFIED_OK: HTTP 409 and error.code == PLAN_STALE')
"

# Verify source remains intact on disk and clean up stale test pair
[ -f "${HOST_STALE_SOURCE}" ] || { echo "Modified file was erroneously removed!"; exit 1; }
rm -f "${FIXTURE_DIR}/allowed_root/stale_fileA.dat" "${FIXTURE_DIR}/allowed_root/stale_fileB.dat"
echo "STALE_PROTECTION_SUCCESS"
```
Expected: Validate explicitly reports stale; Execute refused with 409; modified file remains untouched; stale test files cleaned up.

- [ ] **Step 6: Verify Reachable Sentinel and Symlink Traversal Protection**

Run:
```bash
python3 -c "
import hashlib, json, os
records = json.load(open('${FIXTURE_DIR}/baseline_records.json'))
sentinel_expected = records['sentinel_dir/external_file.txt']
sentinel_path = '${FIXTURE_DIR}/sentinel_dir/external_file.txt'

st = open(sentinel_path, 'rb').read()
stat_info = os.stat(sentinel_path)
current_h = hashlib.sha256(st).hexdigest()
assert current_h == sentinel_expected['sha256'], 'Sentinel SHA256 was modified!'
assert len(st) == sentinel_expected['size'], 'Sentinel content size was modified!'
assert stat_info.st_size == sentinel_expected['size'], 'Sentinel stat size was modified!'
assert stat_info.st_mtime_ns == sentinel_expected['mtime_ns'], 'Sentinel mtime_ns was modified!'
print('SENTINEL_INTEGRITY_VERIFIED_OK: Sentinel SHA256, size, and mtime_ns completely untouched')
"
```
Expected: External sentinel file content, size, and hash remain completely unmodified.

- [ ] **Step 7: Clean up safety containers and fixture**

Run:
```bash
docker stop gate5g-safety-rw-worker gate5g-safety-rw-api
docker rm gate5g-safety-rw-worker gate5g-safety-rw-api
rm -rf "${FIXTURE_DIR}"
```
Expected: Clean teardown.

---

### Task 7: Phase G7 — Target 极空间 NAS Isolated Black-Box Validation

**Files:**
- Host Filesystem: Target 极空间 NAS filesystem
- Transient Compose File: `/tmp/nas-gate5g-transient-compose.yaml` (outside git worktree)
- Transport Manifest: `/tmp/gate5g-image-manifest.env`

**Interfaces:**
- Consumes: Transferred image tar archive `/tmp/nas-file-center-candidate.tar` and explicit manifest `/tmp/gate5g-image-manifest.env`.
- Produces: Target NAS environment metrics, exact Image ID equality verification, completed RO matrix, completed RW mutation & restore matrix, and restart persistence logs.

- [ ] **Step 1: Transfer image archive and manifest to target 极空间 NAS**

Run:
```bash
# On verifier host:
# scp "${G2_IMAGE_ARCHIVE_PATH}" user@nas:/tmp/nas-file-center-candidate.tar
# scp "${G2_IMAGE_MANIFEST_PATH}" user@nas:/tmp/gate5g-image-manifest.env

# On NAS:
echo "Checking transferred files on NAS..."
[ -f /tmp/nas-file-center-candidate.tar ] || { echo "Image archive missing on NAS"; exit 1; }
[ -f /tmp/gate5g-image-manifest.env ] || { echo "Image manifest missing on NAS"; exit 1; }

# Source manifest to explicitly load G2_IMAGE_TAG, G2_IMAGE_ID, and G2_IMAGE_ARCHIVE_SHA256
source /tmp/gate5g-image-manifest.env
echo "Loaded Manifest: TAG=${G2_IMAGE_TAG}, ID=${G2_IMAGE_ID}, SHA256=${G2_IMAGE_ARCHIVE_SHA256}"

echo "Verifying transferred image archive SHA256 checksum on NAS..."
NAS_ARCHIVE_SHA256=$(sha256sum /tmp/nas-file-center-candidate.tar | awk '{print $1}')
echo "NAS_ARCHIVE_SHA256: ${NAS_ARCHIVE_SHA256}"
echo "G2_IMAGE_ARCHIVE_SHA256: ${G2_IMAGE_ARCHIVE_SHA256}"
[ "${NAS_ARCHIVE_SHA256}" = "${G2_IMAGE_ARCHIVE_SHA256}" ] || { echo "Image archive SHA256 mismatch on NAS!"; exit 1; }

# Produce authoritative G7_IMAGE_ARCHIVE_SHA256 variable for G8 evidence audit
G7_IMAGE_ARCHIVE_SHA256="${NAS_ARCHIVE_SHA256}"
[ "${G7_IMAGE_ARCHIVE_SHA256}" = "${G2_IMAGE_ARCHIVE_SHA256}" ] || { echo "G7_IMAGE_ARCHIVE_SHA256 mismatch!"; exit 1; }
echo "G7_IMAGE_ARCHIVE_SHA256=${G7_IMAGE_ARCHIVE_SHA256}"
```
Expected: SHA256 checksum on the NAS matches `G2_IMAGE_ARCHIVE_SHA256` bit-for-bit; manifest variables explicitly loaded.

- [ ] **Step 2: Load Docker image on NAS and verify Image ID equality**

Run (on NAS):
```bash
docker load -i /tmp/nas-file-center-candidate.tar
G7_LOADED_IMAGE_ID=$(docker inspect --format='{{.Id}}' "${G2_IMAGE_TAG}")
echo "G7_LOADED_IMAGE_ID: ${G7_LOADED_IMAGE_ID}"
echo "G2_IMAGE_ID: ${G2_IMAGE_ID}"
[ "${G7_LOADED_IMAGE_ID}" = "${G2_IMAGE_ID}" ] || { echo "Image ID mismatch between G2 and G7!"; exit 1; }

NAS_ARCH=$(docker run --rm --platform linux/amd64 "${G2_IMAGE_TAG}" uname -m)
[ "${NAS_ARCH}" = "x86_64" ] || { echo "Loaded image architecture is not x86_64: ${NAS_ARCH}"; exit 1; }
echo "IMAGE_BYTE_IDENTITY_VERIFIED: YES"
```
Expected: `G7_LOADED_IMAGE_ID == G2_IMAGE_ID`; architecture is `linux/amd64`. Zero rebuilding or compose building on the NAS.

- [ ] **Step 3: Assert Absolute Host Mount Isolation & Ancestry-Overlap Rejection**

Run (on NAS):
```bash
# Production paths from committed compose.komodo.yaml
PRODUCTION_DATA_PATH="/tmp/zfsv3/sata11/15246330601/data"
PRODUCTION_CONFIG_PATH="/tmp/zfsv3/nvme13/15246330601/data/NasFileCenter"

# Dedicated disposable Gate5-G paths (physically outside both production trees)
GATE5G_TEST_ROOT="/tmp/zfsv3/sata11/gate5g_isolated_testbed"
GATE5G_TEST_DATA_PATH="${GATE5G_TEST_ROOT}/data"
GATE5G_TEST_CONFIG_PATH="${GATE5G_TEST_ROOT}/config"
GATE5G_TEST_QUARANTINE_PATH="${GATE5G_TEST_ROOT}/quarantine"
GATE5G_TEST_SENTINEL_PATH="${GATE5G_TEST_ROOT}/sentinel"

mkdir -p "${GATE5G_TEST_DATA_PATH}" "${GATE5G_TEST_CONFIG_PATH}" "${GATE5G_TEST_QUARANTINE_PATH}" "${GATE5G_TEST_SENTINEL_PATH}"

python3 -c "
import sys
from pathlib import Path

def assert_no_overlap(name1, p1, name2, p2):
    r1 = Path(p1).resolve()
    r2 = Path(p2).resolve()
    if r1 == r2:
        print(f'FATAL: {name1} equals {name2}: {r1}')
        sys.exit(1)
    if r1 in r2.parents:
        print(f'FATAL: {name1} is an ancestor of {name2}: {r1} contains {r2}')
        sys.exit(1)
    if r2 in r1.parents:
        print(f'FATAL: {name2} is an ancestor of {name1}: {r2} contains {r1}')
        sys.exit(1)

prod_data = '${PRODUCTION_DATA_PATH}'
prod_config = '${PRODUCTION_CONFIG_PATH}'
test_root = '${GATE5G_TEST_ROOT}'
test_data = '${GATE5G_TEST_DATA_PATH}'
test_config = '${GATE5G_TEST_CONFIG_PATH}'

assert_no_overlap('PROD_DATA', prod_data, 'TEST_ROOT', test_root)
assert_no_overlap('PROD_CONFIG', prod_config, 'TEST_ROOT', test_root)
assert_no_overlap('PROD_DATA', prod_data, 'TEST_DATA', test_data)
assert_no_overlap('PROD_CONFIG', prod_config, 'TEST_CONFIG', test_config)
print('ABSOLUTE_MOUNT_ISOLATION_AND_ANCESTRY_REJECTION_VERIFIED_OK')
"
```
Expected: All path comparisons pass; zero ancestry overlap between testbed and production paths.

- [ ] **Step 4: Record Environmental Context on target 极空间 NAS**

Run (on NAS):
```bash
echo "=== TARGET NAS ENVIRONMENT INFO ==="
uname -a
docker --version
df -T "${GATE5G_TEST_ROOT}"
echo "==================================="
```
Record: NAS model/firmware, CPU arch, Docker engine version, filesystem type of test mount.

- [ ] **Step 5: Stage 1 — Mandatory Read-Only Matrix Verification on NAS (`/data:ro`, `ALLOW_MUTATION=false`)**

Generate transient compose file outside git worktree at `/tmp/nas-gate5g-transient-compose.yaml`:
Run (on NAS):
```bash
cat <<EOF > /tmp/nas-gate5g-transient-compose.yaml
services:
  api:
    image: ${G2_IMAGE_TAG}
    container_name: gate5g-nas-api
    ports:
      - "28080:8080"
    environment:
      - CONFIG_DIR=/config
      - DATA_MOUNT=/data
      - ALLOWED_ROOTS=/data
      - QUARANTINE_ROOT=/quarantine
      - ALLOW_MUTATION=false
      - ALLOW_DELETE=false
      - PROTECT_LAST_FILE=true
      - INITIAL_ADMIN_USERNAME=admin
      - INITIAL_ADMIN_PASSWORD=AdminPassword123!
    volumes:
      - ${GATE5G_TEST_CONFIG_PATH}:/config
      - ${GATE5G_TEST_DATA_PATH}:/data:ro
      - ${GATE5G_TEST_QUARANTINE_PATH}:/quarantine:ro
      - ${GATE5G_TEST_SENTINEL_PATH}:/sentinel:ro
    restart: "no"

  worker:
    image: ${G2_IMAGE_TAG}
    container_name: gate5g-nas-worker
    command: ["python", "-m", "app.worker"]
    environment:
      - CONFIG_DIR=/config
      - DATA_MOUNT=/data
      - ALLOWED_ROOTS=/data
      - QUARANTINE_ROOT=/quarantine
      - ALLOW_MUTATION=false
      - ALLOW_DELETE=false
      - PROTECT_LAST_FILE=true
    volumes:
      - ${GATE5G_TEST_CONFIG_PATH}:/config
      - ${GATE5G_TEST_DATA_PATH}:/data:ro
      - ${GATE5G_TEST_QUARANTINE_PATH}:/quarantine:ro
      - ${GATE5G_TEST_SENTINEL_PATH}:/sentinel:ro
    restart: "no"
EOF

docker compose -f /tmp/nas-gate5g-transient-compose.yaml up -d
sleep 5

# 1. API Health Check and exact safety flags
NAS_HEALTH=$(curl -s http://127.0.0.1:28080/health)
echo "NAS Health: ${NAS_HEALTH}"
python3 -c "
import json
data = json.loads('''${NAS_HEALTH}''')
assert data.get('status') == 'ok', 'status is not ok'
assert data.get('allow_mutation') is False, 'allow_mutation must be False'
assert data.get('allow_delete') is False, 'allow_delete must be False'
assert data.get('protect_last_file') is True, 'protect_last_file must be True'
print('NAS_RO_HEALTH_FLAGS_OK')
"

# 2. Login admin
curl -s -c /tmp/nas_cookie.txt -X POST http://127.0.0.1:28080/api/auth/login \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# 3. Verify worker online and single ownership lease
NAS_WORKER=$(curl -s -b /tmp/nas_cookie.txt http://127.0.0.1:28080/api/tasks/worker)
python3 -c "
import json
data = json.loads('''${NAS_WORKER}''')
assert data.get('online') is True, 'NAS worker is not online'
print('NAS_WORKER_ONLINE_OK')
"

# Executable DB proof of single Worker ownership (WorkerState count==1, TaskLock locked==true, owner==worker_id)
docker exec gate5g-nas-api python -c "
from app.db import create_engine_and_session
from app.models import WorkerState, TaskLock
from pathlib import Path
engine, SessionLocal = create_engine_and_session(Path('/config/app.db'))
with SessionLocal() as s:
    workers = s.query(WorkerState).all()
    assert len(workers) == 1, f'Expected exactly 1 WorkerState, found {len(workers)}'
    w = workers[0]
    lock = s.query(TaskLock).filter(TaskLock.id == 1).first()
    assert lock is not None, 'TaskLock id=1 missing'
    assert lock.locked is True, f'TaskLock is not locked: {lock.locked}'
    assert lock.owner == w.worker_id, f'TaskLock owner {lock.owner} != worker_id {w.worker_id}'
print('NAS_WORKER_SINGLE_OWNERSHIP_DB_PROOF_OK: exactly 1 worker owning TaskLock id=1')
"

# 4. Real Worker-backed scan on NAS volume
NAS_RO_SCAN_RESP=$(curl -s -b /tmp/nas_cookie.txt -X POST http://127.0.0.1:28080/api/scans \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{"name":"nas-ro-scan","roots":["/data"]}')
NAS_RO_SCAN_ID=$(echo "${NAS_RO_SCAN_RESP}" | grep -o '"scan_job_id":[0-9]*' | cut -d: -f2)
for i in {1..30}; do
  STATUS=$(curl -s -b /tmp/nas_cookie.txt "http://127.0.0.1:28080/api/scans/${NAS_RO_SCAN_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  if [ "${STATUS}" = "completed" ]; then break; fi
  sleep 1
done
[ "${STATUS}" = "completed" ] || { echo "NAS RO Scan timed out"; exit 1; }

# 5. Real /api/indexes WorkJob on NAS volume
NAS_RO_IDX_RESP=$(curl -s -b /tmp/nas_cookie.txt -X POST http://127.0.0.1:28080/api/indexes \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{"root":"/data"}')
NAS_RO_IDX_WORK_ID=$(echo "${NAS_RO_IDX_RESP}" | grep -o '"work_job_id":[0-9]*' | cut -d: -f2)
for i in {1..30}; do
  STATUS=$(curl -s -b /tmp/nas_cookie.txt "http://127.0.0.1:28080/api/tasks/${NAS_RO_IDX_WORK_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  if [ "${STATUS}" = "completed" ]; then break; fi
  sleep 1
done
[ "${STATUS}" = "completed" ] || { echo "NAS RO Index WorkJob timed out"; exit 1; }

# 6. Verify fclones executes inside container on NAS filesystem
docker exec gate5g-nas-api fclones --version
docker exec gate5g-nas-api fclones group /data > /dev/null

# Capture WorkJob stats before policy update (Zero-Scheduler proof baseline)
read -r G7_WORKJOB_COUNT_BEFORE_POLICY G7_WORKJOB_MAX_ID_BEFORE_POLICY < <(docker exec gate5g-nas-api python -c "
from app.db import create_engine_and_session
from app.models import WorkJob
from pathlib import Path
from sqlalchemy import func
engine, SessionLocal = create_engine_and_session(Path('/config/app.db'))
with SessionLocal() as s:
    cnt = s.query(func.count(WorkJob.id)).scalar() or 0
    max_id = s.query(func.max(WorkJob.id)).scalar() or 0
    print(f'{cnt} {max_id}')
")
echo "G7_WORKJOB_COUNT_BEFORE_POLICY: ${G7_WORKJOB_COUNT_BEFORE_POLICY}"
echo "G7_WORKJOB_MAX_ID_BEFORE_POLICY: ${G7_WORKJOB_MAX_ID_BEFORE_POLICY}"

# 7. Admin ResourcePolicy GET
POL_GET=$(curl -s -b /tmp/nas_cookie.txt http://127.0.0.1:28080/api/settings/resource-policy)
echo "Resource Policy GET: ${POL_GET}"
OLD_REV=$(python3 -c "
import json
data = json.loads('''${POL_GET}''')
assert data.get('scan_threads') is not None, 'scan_threads missing'
assert data.get('revision') == 1, 'initial revision must be 1'
print(data['revision'])
")
echo "Initial Policy Revision: ${OLD_REV}"

# 8. Admin ResourcePolicy PUT and readback verification (full replacement payload, extra forbidden)
POL_PUT_RESP=$(curl -s -w "\n%{http_code}" -b /tmp/nas_cookie.txt -X PUT http://127.0.0.1:28080/api/settings/resource-policy \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{
    "scan_threads": 2,
    "hash_threads": 2,
    "io_limit": "normal",
    "job_priority": "normal",
    "active_window_enabled": true,
    "active_window_start": "00:00",
    "active_window_end": "23:59",
    "active_window_timezone": "UTC",
    "outside_window_mode": "limited"
  }')
POL_PUT_CODE=$(echo "${POL_PUT_RESP}" | tail -n1)
POL_PUT_BODY=$(echo "${POL_PUT_RESP}" | sed '$d')
echo "Resource Policy PUT Code: ${POL_PUT_CODE}, Body: ${POL_PUT_BODY}"
[ "${POL_PUT_CODE}" = "200" ] || { echo "PUT resource policy failed with ${POL_PUT_CODE}"; exit 1; }
python3 -c "
import json
data = json.loads('''${POL_PUT_BODY}''')
assert data.get('revision') == int('${OLD_REV}') + 1, 'revision not incremented by 1'
print('NAS_RESOURCE_POLICY_PUT_OK')
"

# Fresh GET readback verifying all persisted fields
POL_GET_FRESH=$(curl -s -b /tmp/nas_cookie.txt http://127.0.0.1:28080/api/settings/resource-policy)
python3 -c "
import json
data = json.loads('''${POL_GET_FRESH}''')
assert data.get('scan_threads') == 2, 'scan_threads mismatch'
assert data.get('hash_threads') == 2, 'hash_threads mismatch'
assert data.get('io_limit') == 'normal', 'io_limit mismatch'
assert data.get('job_priority') == 'normal', 'job_priority mismatch'
assert data.get('active_window_enabled') is True, 'active_window_enabled mismatch'
assert data.get('active_window_start') == '00:00', 'active_window_start mismatch'
assert data.get('active_window_end') == '23:59', 'active_window_end mismatch'
assert data.get('active_window_timezone') == 'UTC', 'active_window_timezone mismatch'
assert data.get('outside_window_mode') == 'limited', 'outside_window_mode mismatch'
assert data.get('revision') == int('${OLD_REV}') + 1, 'revision mismatch'
print('NAS_RESOURCE_POLICY_FRESH_GET_READBACK_OK')
"

# 9. Verify ordinary user is forbidden on ResourcePolicy
docker exec gate5g-nas-api python -c "
from app.db import create_engine_and_session
from app.models import User
from app.auth.password import hash_password
from pathlib import Path
engine, SessionLocal = create_engine_and_session(Path('/config/app.db'))
with SessionLocal() as s:
    if not s.query(User).filter_by(username='ordinary_user').first():
        s.add(User(username='ordinary_user', password_hash=hash_password('UserPass123!'), role='user'))
        s.commit()
"
curl -s -c /tmp/nas_user_cookie.txt -X POST http://127.0.0.1:28080/api/auth/login \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{"username":"ordinary_user","password":"UserPass123!"}'

USER_POL_CODE=$(curl -s -o /dev/null -w "%{http_code}" -b /tmp/nas_user_cookie.txt http://127.0.0.1:28080/api/settings/resource-policy)
[ "${USER_POL_CODE}" = "403" ] || { echo "Ordinary user was not forbidden: ${USER_POL_CODE}"; exit 1; }
echo "NAS_ORDINARY_USER_RBAC_FORBIDDEN_OK"

# 10. Prove Zero-Scheduler Invariant: wait across multiple worker polling iterations and assert zero automatic jobs created
sleep 6

read -r G7_WORKJOB_COUNT_AFTER_POLICY G7_WORKJOB_MAX_ID_AFTER_POLICY < <(docker exec gate5g-nas-api python -c "
from app.db import create_engine_and_session
from app.models import WorkJob
from pathlib import Path
from sqlalchemy import func
engine, SessionLocal = create_engine_and_session(Path('/config/app.db'))
with SessionLocal() as s:
    cnt = s.query(func.count(WorkJob.id)).scalar() or 0
    max_id = s.query(func.max(WorkJob.id)).scalar() or 0
    print(f'{cnt} {max_id}')
")
echo "G7_WORKJOB_COUNT_AFTER_POLICY: ${G7_WORKJOB_COUNT_AFTER_POLICY}"
echo "G7_WORKJOB_MAX_ID_AFTER_POLICY: ${G7_WORKJOB_MAX_ID_AFTER_POLICY}"
[ "${G7_WORKJOB_COUNT_AFTER_POLICY}" = "${G7_WORKJOB_COUNT_BEFORE_POLICY}" ] || { echo "WorkJob count changed after policy update!"; exit 1; }
[ "${G7_WORKJOB_MAX_ID_AFTER_POLICY}" = "${G7_WORKJOB_MAX_ID_BEFORE_POLICY}" ] || { echo "WorkJob max(id) changed after policy update!"; exit 1; }
AUTOMATIC_JOBS_CREATED=0
echo "AUTOMATIC_JOBS_CREATED=${AUTOMATIC_JOBS_CREATED}"
echo "NAS_ZERO_SCHEDULER_INVARIANT_OK"

# 11. Put complete known-safe ResourcePolicy before mutation stage and capture G7_SAFE_POLICY_REVISION
SAFE_POL_RESP=$(curl -s -b /tmp/nas_cookie.txt -X PUT http://127.0.0.1:28080/api/settings/resource-policy \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{
    "scan_threads": 2,
    "hash_threads": 2,
    "io_limit": "normal",
    "job_priority": "normal",
    "active_window_enabled": false,
    "active_window_start": null,
    "active_window_end": null,
    "active_window_timezone": null,
    "outside_window_mode": "limited"
  }')
G7_SAFE_POLICY_REVISION=$(python3 -c "
import json
data = json.loads('''${SAFE_POL_RESP}''')
assert data.get('active_window_enabled') is False, 'safe policy active_window_enabled not False'
print(data['revision'])
")
echo "G7_SAFE_POLICY_REVISION=${G7_SAFE_POLICY_REVISION}"

docker compose -f /tmp/nas-gate5g-transient-compose.yaml down
echo "NAS_STAGE1_READ_ONLY_SUCCESS"
```
Expected: Stage 1 read-only mandatory matrix passes cleanly on target NAS.

- [ ] **Step 6: Stage 2 — Controlled Mutation, Stale Defense, Reachable Symlink, & Mandatory Restore Verification on NAS**

Update `/tmp/nas-gate5g-transient-compose.yaml` for RW mode:
```bash
sed -i 's/:ro/:rw/g' /tmp/nas-gate5g-transient-compose.yaml
# Keep sentinel mount strictly read-only
sed -i 's/sentinel:rw/sentinel:ro/g' /tmp/nas-gate5g-transient-compose.yaml
sed -i 's/ALLOW_MUTATION=false/ALLOW_MUTATION=true/g' /tmp/nas-gate5g-transient-compose.yaml

docker compose -f /tmp/nas-gate5g-transient-compose.yaml up -d
sleep 5

# 1. Setup primary duplicate pair on NAS test data
echo "NAS_PRIMARY_DUP_DATA_ALPHA" > "${GATE5G_TEST_DATA_PATH}/nas_fileA.dat"
cp "${GATE5G_TEST_DATA_PATH}/nas_fileA.dat" "${GATE5G_TEST_DATA_PATH}/nas_fileB.dat"

# Setup sentinel and reachable symlink
echo "NAS_EXTERNAL_SENTINEL_PAYLOAD_SAFE" > "${GATE5G_TEST_SENTINEL_PATH}/external_file.txt"
ln -sf "/sentinel/external_file.txt" "${GATE5G_TEST_DATA_PATH}/symlink_to_external"

# Record NAS Sentinel baseline (SHA256, size, mtime_ns)
read -r NAS_SENTINEL_HASH_ORIG NAS_SENTINEL_SIZE_ORIG NAS_SENTINEL_MTIME_ORIG < <(python3 -c "
import os, hashlib
p = '${GATE5G_TEST_SENTINEL_PATH}/external_file.txt'
st = os.stat(p)
h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
print(f'{h} {st.st_size} {st.st_mtime_ns}')
")
echo "NAS Sentinel Baseline: hash=${NAS_SENTINEL_HASH_ORIG} size=${NAS_SENTINEL_SIZE_ORIG} mtime_ns=${NAS_SENTINEL_MTIME_ORIG}"

# Login admin
curl -s -c /tmp/nas_rw_cookie.txt -X POST http://127.0.0.1:28080/api/auth/login \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# 2. Trigger primary scan on NAS
NAS_SCAN_RESP=$(curl -s -b /tmp/nas_rw_cookie.txt -X POST http://127.0.0.1:28080/api/scans \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{"name":"nas-mutation-scan","roots":["/data"]}')
NAS_SCAN_ID=$(echo "${NAS_SCAN_RESP}" | grep -o '"scan_job_id":[0-9]*' | cut -d: -f2)

for i in {1..30}; do
  STATUS=$(curl -s -b /tmp/nas_rw_cookie.txt "http://127.0.0.1:28080/api/scans/${NAS_SCAN_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  if [ "${STATUS}" = "completed" ]; then break; fi
  sleep 1
done

# 3. Dedupe Preview -> Draft Plan -> Freeze Plan
curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/scans/${NAS_SCAN_ID}/dedupe-preview" -H "Origin: http://127.0.0.1:28080" -d '{}'
NAS_PLAN_RESP=$(curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/scans/${NAS_SCAN_ID}/dedupe-plan" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" -d '{"policy":"newest"}')
NAS_PLAN_ID=$(echo "${NAS_PLAN_RESP}" | grep -o '"id":[0-9]*' | cut -d: -f2)

curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/plans/${NAS_PLAN_ID}/freeze" -H "Origin: http://127.0.0.1:28080"

# Inspect frozen items: extract plan-derived paths using correct API schema (source, keep)
NAS_ITEMS=$(curl -s -b /tmp/nas_rw_cookie.txt "http://127.0.0.1:28080/api/plans/${NAS_PLAN_ID}/items")
python3 -c "
import json
data = json.loads('''${NAS_ITEMS}''')
items = data.get('items', [])
assert len(items) >= 1, 'No items in NAS frozen plan'
item = items[0]
with open('/tmp/nas_plan_paths.json', 'w') as f:
    json.dump({'keep': item['keep'], 'source': item['source']}, f)
print('NAS_PLAN_DERIVED_PATHS:', item['keep'], '->', item['source'])
"
NAS_KEEP=$(python3 -c "import json; print(json.load(open('/tmp/nas_plan_paths.json'))['keep'])")
NAS_SOURCE=$(python3 -c "import json; print(json.load(open('/tmp/nas_plan_paths.json'))['source'])")
NAS_ORIG_HASH=$(sha256sum "${GATE5G_TEST_DATA_PATH}/$(basename ${NAS_SOURCE})" | awk '{print $1}')

# Validate & Execute primary plan
curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/plans/${NAS_PLAN_ID}/validate" -H "Origin: http://127.0.0.1:28080"
EXEC_OUT=$(curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/plans/${NAS_PLAN_ID}/execute" -H "Origin: http://127.0.0.1:28080")
NAS_WORK_ID=$(echo "${EXEC_OUT}" | grep -o '"work_job_id":[0-9]*' | cut -d: -f2)

for i in {1..30}; do
  STATUS=$(curl -s -b /tmp/nas_rw_cookie.txt "http://127.0.0.1:28080/api/tasks/${NAS_WORK_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  if [ "${STATUS}" = "completed" ]; then break; fi
  sleep 1
done

# Postconditions on NAS filesystem
[ -f "${GATE5G_TEST_DATA_PATH}/$(basename ${NAS_KEEP})" ] || { echo "NAS keep file missing"; exit 1; }
[ ! -f "${GATE5G_TEST_DATA_PATH}/$(basename ${NAS_SOURCE})" ] || { echo "NAS quarantined file still in data"; exit 1; }

# Find QuarantineEntry ID and verify state == 'active'
NAS_Q_LIST=$(curl -s -b /tmp/nas_rw_cookie.txt http://127.0.0.1:28080/api/quarantine)
python3 -c "
import json, os
data = json.loads('''${NAS_Q_LIST}''')
entries = data.get('items', [])
match = None
for e in entries:
    if e['original_path'] == '${NAS_SOURCE}':
        match = e
        break
assert match is not None, f'No quarantine entry on NAS for ${NAS_SOURCE}'
assert match['state'] == 'active', f'Expected active state, got {match["state"]}'

rel_qpath = os.path.relpath(match['quarantine_path'], '/quarantine')
host_qpath = os.path.join('${GATE5G_TEST_QUARANTINE_PATH}', rel_qpath)
assert os.path.isfile(host_qpath), f'Quarantined file missing on NAS host: {host_qpath}'

with open('/tmp/nas_q_entry.json', 'w') as f:
    json.dump({'id': match['id'], 'host_qpath': host_qpath}, f)
print('NAS_QUARANTINE_ENTRY_ACTIVE:', match['id'])
"
NAS_Q_ID=$(python3 -c "import json; print(json.load(open('/tmp/nas_q_entry.json'))['id'])")
NAS_HOST_Q_FILE=$(python3 -c "import json; print(json.load(open('/tmp/nas_q_entry.json'))['host_qpath'])")

# 4. Mandatory Quarantine Restore on NAS
RESTORE_RESP=$(curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/quarantine/${NAS_Q_ID}/restore" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" -d '{}')
python3 -c "
import json
data = json.loads('''${RESTORE_RESP}''')
assert data.get('state') == 'restored', f'NAS restore state not restored: {data.get("state")}'
print('NAS_RESTORE_STATE_OK')
"
[ -f "${GATE5G_TEST_DATA_PATH}/$(basename ${NAS_SOURCE})" ] || { echo "Restored file missing on NAS"; exit 1; }
NAS_RESTORED_HASH=$(sha256sum "${GATE5G_TEST_DATA_PATH}/$(basename ${NAS_SOURCE})" | awk '{print $1}')
[ "${NAS_RESTORED_HASH}" = "${NAS_ORIG_HASH}" ] || { echo "NAS restore SHA256 mismatch!"; exit 1; }
[ ! -f "${NAS_HOST_Q_FILE}" ] || { echo "Quarantine source file still exists on NAS after restore"; exit 1; }
echo "NAS_MANDATORY_RESTORE_SHA256_VERIFIED_OK"

# 5. Separate Independent Stale Lifecycle on NAS
echo "NAS_STALE_DUP_DATA_AAA" > "${GATE5G_TEST_DATA_PATH}/nas_staleA.dat"
cp "${GATE5G_TEST_DATA_PATH}/nas_staleA.dat" "${GATE5G_TEST_DATA_PATH}/nas_staleB.dat"

NAS_STALE_SCAN_RESP=$(curl -s -b /tmp/nas_rw_cookie.txt -X POST http://127.0.0.1:28080/api/scans \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{"name":"nas-stale-scan","roots":["/data"]}')
NAS_STALE_SCAN_ID=$(echo "${NAS_STALE_SCAN_RESP}" | grep -o '"scan_job_id":[0-9]*' | cut -d: -f2)
for i in {1..30}; do
  STATUS=$(curl -s -b /tmp/nas_rw_cookie.txt "http://127.0.0.1:28080/api/scans/${NAS_STALE_SCAN_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  if [ "${STATUS}" = "completed" ]; then break; fi
  sleep 1
done

curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/scans/${NAS_STALE_SCAN_ID}/dedupe-preview" -H "Origin: http://127.0.0.1:28080" -d '{}'
NAS_STALE_PLAN_RESP=$(curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/scans/${NAS_STALE_SCAN_ID}/dedupe-plan" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" -d '{"policy":"newest"}')
NAS_STALE_PLAN_ID=$(echo "${NAS_STALE_PLAN_RESP}" | grep -o '"id":[0-9]*' | cut -d: -f2)

curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/plans/${NAS_STALE_PLAN_ID}/freeze" -H "Origin: http://127.0.0.1:28080"

# Inspect items and extract actual stale mutation source
NAS_STALE_ITEMS=$(curl -s -b /tmp/nas_rw_cookie.txt "http://127.0.0.1:28080/api/plans/${NAS_STALE_PLAN_ID}/items")
python3 -c "
import json
data = json.loads('''${NAS_STALE_ITEMS}''')
items = data.get('items', [])
target = None
for it in items:
    if 'nas_stale' in it['source']:
        target = it
        break
assert target is not None, 'NAS stale item not found in plan'
with open('/tmp/nas_stale_source.txt', 'w') as f:
    f.write(target['source'])
print('NAS_STALE_SOURCE:', target['source'])
"
NAS_STALE_SOURCE=$(cat /tmp/nas_stale_source.txt)
NAS_HOST_STALE_SOURCE="${GATE5G_TEST_DATA_PATH}/$(basename ${NAS_STALE_SOURCE})"

# Modify source file after freeze
echo "MODIFIED_ON_NAS_AFTER_FREEZE" >> "${NAS_HOST_STALE_SOURCE}"

# Validate fails
NAS_STALE_VAL=$(curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/plans/${NAS_STALE_PLAN_ID}/validate" -H "Origin: http://127.0.0.1:28080")
echo "${NAS_STALE_VAL}" | grep -E "stale|STALE" || { echo "NAS validate did not detect stale"; exit 1; }

# Execute rejected with HTTP 409 and JSON error.code == PLAN_STALE
NAS_STALE_EXEC_RESP=$(curl -s -w "\n%{http_code}" -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/plans/${NAS_STALE_PLAN_ID}/execute" -H "Origin: http://127.0.0.1:28080")
NAS_STALE_EXEC_CODE=$(echo "${NAS_STALE_EXEC_RESP}" | tail -n1)
NAS_STALE_EXEC_BODY=$(echo "${NAS_STALE_EXEC_RESP}" | sed '$d')
echo "NAS Stale Execute Code: ${NAS_STALE_EXEC_CODE}, Body: ${NAS_STALE_EXEC_BODY}"
[ "${NAS_STALE_EXEC_CODE}" = "409" ] || { echo "Expected 409 on NAS stale execute, got ${NAS_STALE_EXEC_CODE}"; exit 1; }
python3 -c "
import json
body = json.loads('''${NAS_STALE_EXEC_BODY}''')
err = body.get('error') or {}
err_code = err.get('code') if isinstance(err, dict) else None
assert err_code == 'PLAN_STALE', f'Expected error.code == PLAN_STALE on NAS, got: {body}'
print('NAS_PLAN_STALE_CODE_VERIFIED_OK: HTTP 409 and error.code == PLAN_STALE')
"
[ -f "${NAS_HOST_STALE_SOURCE}" ] || { echo "Stale source was deleted on NAS"; exit 1; }
rm -f "${GATE5G_TEST_DATA_PATH}/nas_staleA.dat" "${GATE5G_TEST_DATA_PATH}/nas_staleB.dat"
echo "NAS_STALE_DEFENSE_VERIFIED_OK"

# 6. Verify Reachable Sentinel and Zero Filesystem Escape outside test root
python3 -c "
import os, hashlib
p = '${GATE5G_TEST_SENTINEL_PATH}/external_file.txt'
st = os.stat(p)
h = hashlib.sha256(open(p, 'rb').read()).hexdigest()
assert h == '${NAS_SENTINEL_HASH_ORIG}', f'NAS sentinel SHA256 mismatch: {h} != ${NAS_SENTINEL_HASH_ORIG}'
assert st.st_size == int('${NAS_SENTINEL_SIZE_ORIG}'), f'NAS sentinel size mismatch: {st.st_size} != ${NAS_SENTINEL_SIZE_ORIG}'
assert st.st_mtime_ns == int('${NAS_SENTINEL_MTIME_ORIG}'), f'NAS sentinel mtime_ns mismatch: {st.st_mtime_ns} != ${NAS_SENTINEL_MTIME_ORIG}'
print('NAS_SENTINEL_INTEGRITY_VERIFIED_OK: SHA256, size, and mtime_ns unchanged')
"
```
Expected: Real G6 lifecycle, plan-derived quarantine, byte-identical restore, separate stale rejection with 409, and reachable sentinel protection verified on target NAS.

- [ ] **Step 7: Verify Restart Resilience, Ownership Recovery, & Database Persistence on NAS**

Run (on NAS):
```bash
echo "Verifying restart resilience and state persistence on NAS..."

# 1. Restart Worker container and verify heartbeat/ownership recovery
docker restart gate5g-nas-worker
sleep 3
NAS_WORKER_AFTER_RESTART=$(curl -s -b /tmp/nas_rw_cookie.txt http://127.0.0.1:28080/api/tasks/worker)
python3 -c "
import json
data = json.loads('''${NAS_WORKER_AFTER_RESTART}''')
assert data.get('online') is True, 'Worker not online after restart'
print('NAS_WORKER_RESTART_RECOVERY_OK')
"

# 2. Restart API container and verify health recovery
docker restart gate5g-nas-api
sleep 3
NAS_HEALTH_AFTER_RESTART=$(curl -s http://127.0.0.1:28080/health)
echo "${NAS_HEALTH_AFTER_RESTART}" | grep -q '"status":"ok"' || { echo "API unhealthy after restart"; exit 1; }

# Re-login admin
curl -s -c /tmp/nas_rw_cookie.txt -X POST http://127.0.0.1:28080/api/auth/login \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# 3. Verify SQLite DB exists, passes integrity check, and ResourcePolicy fully persisted across restarts
docker exec gate5g-nas-api python -c "
import sqlite3
conn = sqlite3.connect('/config/app.db')
cursor = conn.cursor()
cursor.execute('PRAGMA integrity_check;')
res = cursor.fetchall()
assert res == [('ok',)], f'NAS DB integrity check failed after restart: {res}'
conn.close()
print('NAS_DB_INTEGRITY_POST_RESTART_OK')
"

PERSISTED_POL=$(curl -s -b /tmp/nas_rw_cookie.txt http://127.0.0.1:28080/api/settings/resource-policy)
echo "Persisted Policy after restart: ${PERSISTED_POL}"
python3 -c "
import json
data = json.loads('''${PERSISTED_POL}''')
assert data.get('scan_threads') == 2, 'scan_threads not persisted'
assert data.get('hash_threads') == 2, 'hash_threads not persisted'
assert data.get('io_limit') == 'normal', 'io_limit not persisted'
assert data.get('job_priority') == 'normal', 'job_priority not persisted'
assert data.get('active_window_enabled') is False, 'active_window_enabled not persisted'
assert data.get('active_window_start') is None, 'active_window_start not persisted'
assert data.get('active_window_end') is None, 'active_window_end not persisted'
assert data.get('active_window_timezone') is None, 'active_window_timezone not persisted'
assert data.get('outside_window_mode') == 'limited', 'outside_window_mode not persisted'
assert data.get('revision') == int('${G7_SAFE_POLICY_REVISION}'), f'Expected revision {${G7_SAFE_POLICY_REVISION}}, got {data.get("revision")}'
print('NAS_RESOURCE_POLICY_ALL_FIELDS_PERSISTED_OK: all 10 fields match G7_SAFE_POLICY_REVISION')
"

# 4. Verify container restart counts and absence of crash loops
API_RESTARTS=$(docker inspect --format='{{.RestartCount}}' gate5g-nas-api)
WORKER_RESTARTS=$(docker inspect --format='{{.RestartCount}}' gate5g-nas-worker)
echo "NAS API Restarts: ${API_RESTARTS}, Worker Restarts: ${WORKER_RESTARTS}"
[ "${API_RESTARTS}" -le 1 ] || { echo "NAS API crash-loop detected"; exit 1; }
[ "${WORKER_RESTARTS}" -le 1 ] || { echo "NAS Worker crash-loop detected"; exit 1; }
echo "NAS_RESTART_AND_PERSISTENCE_VERIFIED_OK"
```
Expected: API and Worker recover cleanly; DB and ResourcePolicy persist across restarts; restart counts `<= 1`; zero crash-loops.

- [ ] **Step 8: Teardown transient NAS testbed**

Run (on NAS):
```bash
docker compose -f /tmp/nas-gate5g-transient-compose.yaml down -v
rm -f /tmp/nas-gate5g-transient-compose.yaml /tmp/nas_cookie.txt /tmp/nas_rw_cookie.txt /tmp/nas_user_cookie.txt
rm -f /tmp/nas_plan_paths.json /tmp/nas_q_entry.json /tmp/nas_stale_source.txt
rm -f /tmp/nas-file-center-candidate.tar /tmp/gate5g-image-manifest.env
rm -rf "${GATE5G_TEST_ROOT}"
```
Expected: Clean teardown on NAS with zero lingering files or containers.

---

### Task 8: Phase G8 — Final Evidence & Immutable Release-Candidate Audit

**Files:**
- Documentation: `docs/history/gate5g/gate5g-final-verification-walkthrough.md`

**Interfaces:**
- Consumes: Execution outputs from all phases G0 through G7.
- Produces: Audited final release evidence report binding the exact candidate SHA and image identity.

- [ ] **Step 1: Compile unified final evidence report**

Fill and verify the following complete evidence template:
```text
GATE5-G FINAL RELEASE VERIFICATION AUDIT REPORT

CANDIDATE_GIT_SHA: <full 40-char SHA>
VERIFIED_RUNTIME_HEAD: <full 40-char SHA>
REMOTE_BRANCH_SHA: <full 40-char SHA>

PHASE_G0_RESULT: PASS (all 8 release surfaces identify 0.3.5 and test passes)
PHASE_G1_RESULT: PASS (0 failed, 0 errors in backend; frontend typecheck, test, build exit 0)
PHASE_G2_RESULT: PASS (Clean linux/amd64 Docker build, internal inspection verified)
PHASE_G3_RESULT: PASS (Isolated API + Worker container smoke, single worker ownership, crash-loop free)
PHASE_G4_RESULT: PASS (Fresh install + Gate5-E upgrade migration clean, additive, idempotent)
PHASE_G5_RESULT: PASS (SQLite integrity_check=ok, foreign_key_check=0, singleton count=1 id=1, PRAGMAs & schema/indexes/unique verified)
PHASE_G6_RESULT: PASS (Synthetic safety lifecycle verified: preview/draft/freeze/validate/execute, plan-derived quarantine, stale rejection, reachable symlink protection, mandatory restore passed)
PHASE_G7_RESULT: PASS (Real 极空间 NAS smoke passed: RO matrix complete, RW lifecycle, stale rejection, reachable symlink protection, restore byte equality, restart persistence verified)

G2_IMAGE_TAG: nas-file-center:0.3.5-gate5g-<shortSHA>
G2_IMAGE_ID: <SHA256>
G2_IMAGE_ARCHIVE_SHA256: <SHA256>

G7_LOADED_IMAGE_ID: <SHA256>
G7_IMAGE_ARCHIVE_SHA256: <SHA256>
IMAGE_IDENTITY_MATCH: YES

BACKEND_RAW_SUMMARY: <exact pytest summary>
FRONTEND_RAW_SUMMARY: <typecheck=0, test=0, build=0>

API_HEALTH_RESULT: HTTP 200 OK {"status":"ok", "allow_mutation": false, "allow_delete": false, "protect_last_file": true}
WORKER_ONLINE_RESULT: online=true, single ownership lease proven
WORKER_RESTART_RESULT: recovered cleanly, restart count <= 1
API_RESTART_RESULT: recovered cleanly, restart count <= 1

FRESH_MIGRATION_RESULT: schema created, singleton policy id=1, revision=1, idempotent
UPGRADE_MIGRATION_RESULT: additive migration, Gate5-E records preserved, singleton added, idempotent

SQLITE_INTEGRITY_RESULT: integrity_check=ok
SQLITE_FK_RESULT: foreign_key_check=0 rows
SCHEMA_CONSTRAINTS_RESULT: columns and indexes verified

SYNTHETIC_SAFETY_RESULT: lifecycle verified, plan-derived quarantine passed
QUARANTINE_STATE_RESULT: active upon quarantine, restored upon restore, relative path host mapping verified
STALE_PREFLIGHT_RESULT: validate rejected, execute refused with 409 PLAN_STALE, zero file corruption
RESTORE_RESULT: mandatory restore passed, byte-identical recovery verified
NAS_RESTART_PERSISTENCE_RESULT: API + Worker recovered cleanly, DB/policy persisted, restart counts <= 1

TARGET_NAS_MODEL: <captured from NAS environment>
TARGET_NAS_OS: <captured from NAS environment>
TARGET_NAS_ARCH: x86_64
TARGET_NAS_DOCKER_VERSION: <captured from NAS environment>
TARGET_NAS_FS_TYPE: <captured from NAS environment>

GIT_DIFF_CHECK: clean
WORKTREE_BEFORE: clean
WORKTREE_AFTER: clean

KNOWN_WARNINGS: <captured raw deprecation warnings from pytest>
KNOWN_LIMITATIONS: <captured actual limitations identified during verification, if any; otherwise None identified>
```

- [ ] **Step 2: Verify candidate immutability and provenance rules**

Assert:
- Zero skipped phases (`G0` through `G7` all `PASS`).
- `VERIFIED_RUNTIME_HEAD == CANDIDATE_GIT_SHA == REMOTE_BRANCH_SHA`.
- `G7_LOADED_IMAGE_ID == G2_IMAGE_ID`.
- `G7_IMAGE_ARCHIVE_SHA256 == G2_IMAGE_ARCHIVE_SHA256`.
- If an archival documentation commit is subsequently created in `docs/history/gate5g/**`, verify it touches zero code/test/deployment files and record its SHA as `ARCHIVAL_RECORD_HEAD`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-10-gate5g-final-validation-execution-plan.md`. Two execution options:

1. **Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
