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

- [ ] **Step 3: Export image to tar archive and compute SHA256 checksum**

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
```
Expected: Tar file is generated; `G2_IMAGE_ARCHIVE_SHA256` is recorded for Phase G7 identity transfer.

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
docker run -d --name gate5g-mig-fresh \
  --platform linux/amd64 \
  -p 18083:8080 \
  -v "${MIG_DIR}/fresh_config:/config" \
  -v "${MIG_DIR}/data:/data:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  -e ALLOWED_ROOTS=/data \
  -e QUARANTINE_ROOT=/data/.quarantine \
  -e ALLOW_MUTATION=false \
  -e ALLOW_DELETE=false \
  -e PROTECT_LAST_FILE=true \
  "${G2_IMAGE_TAG}"

# Poll health
for i in {1..30}; do
  if curl -s http://127.0.0.1:18083/health | grep -q '"status":"ok"'; then
    echo "Fresh container is healthy"
    break
  fi
  sleep 1
done

# Gracefully stop container to ensure WAL truncate
docker stop gate5g-mig-fresh
docker rm gate5g-mig-fresh

# Inspect DB offline
python3 -c "
import sqlite3
conn = sqlite3.connect('${MIG_DIR}/fresh_config/app.db')
cursor = conn.cursor()
cursor.execute('SELECT name FROM sqlite_master WHERE type=\"table\";')
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
docker run -d --name gate5g-mig-fresh-restart \
  --platform linux/amd64 \
  -p 18083:8080 \
  -v "${MIG_DIR}/fresh_config:/config" \
  -v "${MIG_DIR}/data:/data:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  "${G2_IMAGE_TAG}"

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

mkdir -p "${MIG_DIR}/upgrade_config"

# Construct and seed historical database inside candidate container (deterministic, network-independent)
docker run --rm \
  --platform linux/amd64 \
  -v "${HIST_SRC_DIR}:/hist_app:ro" \
  -v "${MIG_DIR}/upgrade_config:/config" \
  -w /hist_app \
  "${G2_IMAGE_TAG}" \
  python -c "
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
    sess = Session(id=1, user_id=1, token_hash='hist_token_hash_abc123', created_at=utcnow(), expires_at=utcnow())
    s.add(sess)

    # 2. Completed WorkJob
    s.add(WorkJob(id=101, kind='batch-plan-execute', status='completed', state_json='{}', created_at=utcnow()))

    # 3. Queued WorkJob
    s.add(WorkJob(id=102, kind='fclones-scan', status='queued', state_json='{}', created_at=utcnow()))

    # 4. BatchPlan (id: int, name: str, kind: str, expected_changes: int)
    bp = BatchPlan(id=1, name='plan-hist-001', kind='dedupe', status='completed', expected_changes=1, expected_reclaim_bytes=1024, created_at=utcnow())
    s.add(bp)
    s.flush()

    # 5. BatchPlanItem (plan_id: int, sequence: int, operation: str, state: str)
    bpi = BatchPlanItem(id=1, plan_id=1, sequence=1, operation='quarantine', source_path='/data/old.txt', target_path='/quarantine/old.txt', keep_path='/data/keep.txt', state='completed', created_at=utcnow())
    s.add(bpi)
    s.flush()

    # 6. ScanJob
    s.add(ScanJob(id=1, name='scan-001', mode='normal', roots_json='[\"/data\"]', status='completed', created_at=utcnow()))

    # 7. IndexedPath
    s.add(IndexedPath(id=1, root_key='/data', absolute_path='/data/old.txt', relative_path='old.txt', basename='old.txt', stem='old', suffix='.txt', scan_generation='gen1', created_at=utcnow()))

    # 8. OperationJournal (real fields: operation, sequence, plan_id, plan_item_id, task_id, user_id)
    s.add(OperationJournal(id=1, operation='quarantine', sequence=1, plan_id=1, plan_item_id=1, task_id=101, user_id=1, before_json='{}', after_json='{}', metadata_before_json='{}', metadata_after_json='{}', created_at=utcnow()))

    s.commit()
print('HISTORICAL_DB_ALL_ENTITIES_SEEDED_SUCCESS')
"
rm -rf "${HIST_SRC_DIR}"
```
Expected: Historical DB created with users, sessions, jobs, plans, plan items, scan jobs, indexed paths, and operation journals matching Gate5-E schema.

- [ ] **Step 3: Run candidate application container against a COPY of historical database**

Run:
```bash
# Make an explicit copy for testing upgrade
cp "${MIG_DIR}/upgrade_config/app.db" "${MIG_DIR}/upgrade_config/app_copy.db"

# Start candidate application container against copy
docker run -d --name gate5g-mig-upgrade \
  --platform linux/amd64 \
  -p 18084:8080 \
  -v "${MIG_DIR}/upgrade_config:/config" \
  -v "${MIG_DIR}/data:/data:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  "${G2_IMAGE_TAG}" \
  uvicorn app.main:app --host 0.0.0.0 --port 8080

# Poll health
for i in {1..30}; do
  if curl -s http://127.0.0.1:18084/health | grep -q '"status":"ok"'; then
    echo "Upgraded container is healthy"
    break
  fi
  sleep 1
done

# Gracefully stop container
docker stop gate5g-mig-upgrade
docker rm gate5g-mig-upgrade

# Inspect upgraded database offline
python3 -c "
import sqlite3
conn = sqlite3.connect('${MIG_DIR}/upgrade_config/app_copy.db')
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

# Restart candidate container to prove idempotency
docker run -d --name gate5g-mig-upgrade-restart \
  --platform linux/amd64 \
  -p 18084:8080 \
  -v "${MIG_DIR}/upgrade_config:/config" \
  -v "${MIG_DIR}/data:/data:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  "${G2_IMAGE_TAG}" \
  uvicorn app.main:app --host 0.0.0.0 --port 8080

sleep 3
curl -s http://127.0.0.1:18084/health | grep -q '"status":"ok"' || { echo "Restart failed"; exit 1; }
docker stop gate5g-mig-upgrade-restart
docker rm gate5g-mig-upgrade-restart
echo "UPGRADE_MIGRATION_IDEMPOTENCY_SUCCESS"
```
Expected: Additive migration creates `resource_policy` table without dropping or corrupting any historical records; second container start is idempotent.

---

### Task 5: Phase G5 — SQLite Integrity Check & Schema / Index Constraint Verification

**Files:**
- Database: `/tmp/gate5g-migration/fresh_config/app.db` and `/tmp/gate5g-migration/upgrade_config/app_copy.db`

**Interfaces:**
- Consumes: Post-migration SQLite databases after clean container shutdown.
- Produces: Raw PRAGMA integrity check, foreign key check, and schema constraint verification outputs.

- [ ] **Step 1: Checkpoint WAL and run SQLite integrity checks**

Run:
```bash
python3 -c "
import sqlite3

for name, p in [('fresh', '/tmp/gate5g-migration/fresh_config/app.db'), ('upgrade', '/tmp/gate5g-migration/upgrade_config/app_copy.db')]:
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
    cursor.execute('SELECT count(*), id FROM resource_policy;')
    cnt, rid = cursor.fetchone()
    assert cnt == 1 and rid == 1, f'{name} resource_policy singleton corrupted: count={cnt}, id={rid}'
    conn.close()
    print(f'SQLITE_PRAGMA_CHECKS_PASS: {name}')
"
```
Expected: Both fresh and upgraded databases return `integrity_check = ok`, `foreign_key_check = 0 rows`, and `resource_policy` count = 1, id = 1.

- [ ] **Step 2: Verify expected schema, indexes, and unique constraints required by Freeze**

Run:
```bash
python3 -c "
import sqlite3

for name, p in [('fresh', '/tmp/gate5g-migration/fresh_config/app.db'), ('upgrade', '/tmp/gate5g-migration/upgrade_config/app_copy.db')]:
    conn = sqlite3.connect(p)
    cursor = conn.cursor()

    # Verify resource_policy columns
    cursor.execute('PRAGMA table_info(resource_policy);')
    cols = {row[1] for row in cursor.fetchall()}
    expected_cols = {
        'id', 'scan_threads', 'hash_threads', 'io_limit', 'job_priority',
        'active_window_enabled', 'active_window_start', 'active_window_end',
        'active_window_timezone', 'outside_window_mode', 'revision'
    }
    missing_cols = expected_cols - cols
    assert not missing_cols, f'{name} resource_policy missing columns: {missing_cols}'

    # Verify indexes exist in sqlite_master
    cursor.execute('SELECT name FROM sqlite_master WHERE type=\"index\";')
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
    print(f'SCHEMA_INDEX_CONSTRAINTS_VERIFIED: {name}')
"
```
Expected: All required columns and indexes exist in both fresh and upgraded databases.

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
- Produces: Verification of 5-stage lifecycle (`Preview -> Draft -> Freeze -> Validate -> Execute`), plan-derived keep/quarantine assertions, real dedupe stale preflight rejection, and mandatory quarantine restore.

- [ ] **Step 1: Construct deterministic synthetic filesystem fixture**

Run:
```bash
FIXTURE_DIR="/tmp/gate5g-safety-fixture"
rm -rf "${FIXTURE_DIR}"
mkdir -p "${FIXTURE_DIR}/allowed_root" "${FIXTURE_DIR}/quarantine_root" "${FIXTURE_DIR}/sentinel_dir" "${FIXTURE_DIR}/config"

# Group 1 duplicates (byte-identical)
echo "GATE5G_SYNTHETIC_DUPLICATE_GROUP1_CONTENT_DATA_ABC" > "${FIXTURE_DIR}/allowed_root/group1_fileA.dat"
cp "${FIXTURE_DIR}/allowed_root/group1_fileA.dat" "${FIXTURE_DIR}/allowed_root/group1_fileB.dat"

# Stale duplicate group (byte-identical)
echo "GATE5G_SYNTHETIC_STALE_DUPLICATE_GROUP2_CONTENT_XYZ" > "${FIXTURE_DIR}/allowed_root/stale_group_fileA.dat"
cp "${FIXTURE_DIR}/allowed_root/stale_group_fileA.dat" "${FIXTURE_DIR}/allowed_root/stale_group_fileB.dat"

# Solitary unique file
echo "GATE5G_SYNTHETIC_UNIQUE_SOLITARY_FILE_123" > "${FIXTURE_DIR}/allowed_root/unique_file.txt"

# External sentinel file outside allowed root
echo "GATE5G_EXTERNAL_SENTINEL_DO_NOT_ALTER_SAFETY_LOCK" > "${FIXTURE_DIR}/sentinel_dir/external_file.txt"

# Symlink escape pointing outside allowed root
ln -s "${FIXTURE_DIR}/sentinel_dir/external_file.txt" "${FIXTURE_DIR}/allowed_root/symlink_to_external"

# Record baseline hashes, sizes, and mtimes
python3 -c "
import hashlib, os, json
from pathlib import Path

root = Path('${FIXTURE_DIR}')
baseline = {}
for p in root.rglob('*'):
    if p.is_file():
        rel = str(p.relative_to(root))
        st = p.stat()
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        baseline[rel] = {'sha256': h, 'size': st.st_size, 'mtime_ns': st.st_mtime_ns}

with open('${FIXTURE_DIR}/baseline_records.json', 'w') as f:
    json.dump(baseline, f, indent=2)
print('BASELINE_RECORDS_SAVED:', len(baseline), 'files')
"
```
Expected: Fixture created; duplicate members verified identical; external sentinel and symlink in place.

- [ ] **Step 2: Read-Only Safety Verification Stage (Real Worker-Backed Execution)**

Start real API and Worker containers with safe read-only configuration:
```bash
docker run -d --name gate5g-safety-ro-api \
  --platform linux/amd64 \
  -p 18081:8080 \
  -v "${FIXTURE_DIR}/config:/config" \
  -v "${FIXTURE_DIR}/allowed_root:/data:ro" \
  -v "${FIXTURE_DIR}/quarantine_root:/quarantine:ro" \
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

# Poll scan job until Worker completes it (zero manual SQLite status updates)
for i in {1..30}; do
  STATUS=$(curl -s -b "${FIXTURE_DIR}/cookie.txt" "http://127.0.0.1:18081/api/scans/${SCAN_ID}" | grep -o '"status":"[^"]*' | cut -d'"' -f4)
  echo "Polling scan status: ${STATUS}"
  if [ "${STATUS}" = "completed" ]; then break; fi
  if [ "${STATUS}" = "failed" ]; then echo "Scan failed in worker"; docker logs gate5g-safety-ro-worker; exit 1; fi
  sleep 1
done
[ "${STATUS}" = "completed" ] || { echo "Scan timed out waiting for worker"; exit 1; }

# 2. Trigger index via /api/indexes
INDEX_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie.txt" -X POST http://127.0.0.1:18081/api/indexes \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18081" \
  -d '{"root":"/data"}')
echo "Index enqueue response: ${INDEX_RESP}"
sleep 3

# 3. Trigger real dedupe preview
PREVIEW_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie.txt" -X POST "http://127.0.0.1:18081/api/scans/${SCAN_ID}/dedupe-preview" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18081" -d '{}')
echo "Preview response: ${PREVIEW_RESP}"

docker stop gate5g-safety-ro-worker gate5g-safety-ro-api
docker rm gate5g-safety-ro-worker gate5g-safety-ro-api

# Assert zero mutation: compare current hashes/sizes/mtimes with baseline
python3 -c "
import hashlib, json
from pathlib import Path

root = Path('${FIXTURE_DIR}')
with open('${FIXTURE_DIR}/baseline_records.json') as f:
    baseline = json.load(f)

for rel, expected in baseline.items():
    p = root / rel
    assert p.exists(), f'File disappeared: {rel}'
    st = p.stat()
    assert st.st_size == expected['size'], f'Size changed for {rel}'
    assert st.st_mtime_ns == expected['mtime_ns'], f'Mtime changed for {rel}'
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    assert h == expected['sha256'], f'Content hash changed for {rel}'
print('READ_ONLY_STAGE_ZERO_MUTATION_VERIFIED_SUCCESS')
"
```
Expected: Real scan and index executed by Worker; dedupe preview generated; zero mutations to disk.

- [ ] **Step 3: Controlled Dedupe Mutation Stage (Real Dedupe Chain & Plan-Derived Assertions)**

Start real API and Worker containers in controlled mutation mode:
```bash
docker run -d --name gate5g-safety-rw-api \
  --platform linux/amd64 \
  -p 18082:8080 \
  -v "${FIXTURE_DIR}/config:/config" \
  -v "${FIXTURE_DIR}/allowed_root:/data:rw" \
  -v "${FIXTURE_DIR}/quarantine_root:/quarantine:rw" \
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

# 5. Substep: Inspect Frozen Plan to extract actual plan-derived paths
PLAN_ITEMS=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" "http://127.0.0.1:18082/api/plans/${PLAN_ID}/items")
echo "Frozen Plan Items: ${PLAN_ITEMS}"

python3 -c "
import json
data = json.loads('''${PLAN_ITEMS}''')
items = data.get('items', [])
assert len(items) >= 1, 'No items in frozen plan'
# Filter for group1 item
target_item = None
for it in items:
    if 'group1' in it['source_path']:
        target_item = it
        break
assert target_item is not None, 'group1 item not found in plan'

with open('${FIXTURE_DIR}/plan_paths.json', 'w') as f:
    json.dump({
        'keep_path': target_item['keep_path'],
        'mutation_source': target_item['source_path'],
        'item_id': target_item['id']
    }, f)
print('PLAN_DERIVED_PATHS_EXTRACTED:', target_item['keep_path'], '->', target_item['source_path'])
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

# Query QuarantineEntry associated with actual executed item
Q_LIST=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" http://127.0.0.1:18082/api/quarantine)
python3 -c "
import json
data = json.loads('''${Q_LIST}''')
entries = data.get('items', [])
match = None
for e in entries:
    if e['original_path'] == '${ACTUAL_MUTATION_SOURCE}':
        match = e
        break
assert match is not None, f'No quarantine entry found for ${ACTUAL_MUTATION_SOURCE}'
assert match['state'] == 'quarantined', f'Expected state quarantined, got {match[\"state\"]}'

with open('${FIXTURE_DIR}/quarantine_entry.json', 'w') as f:
    json.dump(match, f)
print('QUARANTINE_ENTRY_ASSOCIATED:', match['id'], 'target:', match['quarantine_path'])
"
```
Expected: Real dedupe chain executed; keep path preserved; planned mutation source moved to quarantine root and associated with QuarantineEntry.

- [ ] **Step 4: Real Dedupe Stale Preflight Protection Stage**

Run:
```bash
# Build a genuine separate duplicate scan/group for stale_group
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

# Inspect frozen items to find actual stale mutation source
STALE_ITEMS=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/items")
python3 -c "
import json
data = json.loads('''${STALE_ITEMS}''')
items = data.get('items', [])
target = None
for it in items:
    if 'stale_group' in it['source_path']:
        target = it
        break
assert target is not None, 'stale_group item not found in frozen plan'
with open('${FIXTURE_DIR}/stale_source.txt', 'w') as f:
    f.write(target['source_path'])
print('STALE_ACTUAL_SOURCE:', target['source_path'])
"
ACTUAL_STALE_SOURCE=$(cat "${FIXTURE_DIR}/stale_source.txt")
HOST_STALE_SOURCE="${FIXTURE_DIR}/allowed_root/$(basename ${ACTUAL_STALE_SOURCE})"

# Externally modify THAT exact source after Freeze
echo "TAMPERED_MODIFIED_PAYLOAD_AFTER_FREEZE" >> "${HOST_STALE_SOURCE}"

# Validate -> MUST produce stale result
STALE_VAL_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/validate" -H "Origin: http://127.0.0.1:18082")
echo "Stale Validate Response: ${STALE_VAL_RESP}"
echo "${STALE_VAL_RESP}" | grep -E "stale|STALE" || { echo "Validate did not detect stale state"; exit 1; }

# Attempt Execute -> MUST BE REFUSED with 409 PLAN_STALE
STALE_EXEC_RESP=$(curl -s -w "\n%{http_code}" -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/execute" -H "Origin: http://127.0.0.1:18082")
STALE_EXEC_CODE=$(echo "${STALE_EXEC_RESP}" | tail -n1)
echo "Stale Execute Status Code: ${STALE_EXEC_CODE}"
[ "${STALE_EXEC_CODE}" = "409" ] || { echo "Expected 409 for stale execution, got ${STALE_EXEC_CODE}"; exit 1; }

# Verify source remains untouched on disk
[ -f "${HOST_STALE_SOURCE}" ] || { echo "Modified file was erroneously removed!"; exit 1; }
echo "STALE_PROTECTION_SUCCESS"
```
Expected: Validate explicitly reports stale; Execute refused with 409; file not moved or deleted.

- [ ] **Step 5: Mandatory Quarantine Restore Stage**

Run:
```bash
# Load associated quarantine entry id from Step 3
QUARANTINE_ENTRY_ID=$(python3 -c "import json; print(json.load(open('${FIXTURE_DIR}/quarantine_entry.json'))['id'])")
CONTAINER_QUARANTINE_PATH=$(python3 -c "import json; print(json.load(open('${FIXTURE_DIR}/quarantine_entry.json'))['quarantine_path'])")
HOST_QUARANTINE_FILE="${FIXTURE_DIR}/quarantine_root/$(basename ${CONTAINER_QUARANTINE_PATH})"

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
assert data.get('state') == 'restored', f'Expected state restored, got {data.get(\"state\")}'
print('RESTORE_RESPONSE_STATE_OK')
"

# Verify original destination file recovered with byte-for-byte hash
[ -f "${HOST_MUTATION_SOURCE}" ] || { echo "Restored file missing from original destination"; exit 1; }
RESTORED_HASH=$(sha256sum "${HOST_MUTATION_SOURCE}" | awk '{print $1}')
ORIGINAL_HASH=$(python3 -c "
import json
records = json.load(open('${FIXTURE_DIR}/baseline_records.json'))
print(records['allowed_root/$(basename ${HOST_MUTATION_SOURCE})']['sha256'])
")
[ "${RESTORED_HASH}" = "${ORIGINAL_HASH}" ] || { echo "Restored file hash mismatch!"; exit 1; }

# Verify quarantine source no longer exists
[ ! -f "${HOST_QUARANTINE_FILE}" ] || { echo "Quarantined source still exists in quarantine root"; exit 1; }

echo "MANDATORY_QUARANTINE_RESTORE_SUCCESS"
```
Expected: Specific QuarantineEntry restored; original file recovered with byte-for-byte identical hash; quarantine source cleaned up.

- [ ] **Step 6: Verify Sentinel and Symlink Traversal Protection**

Run:
```bash
python3 -c "
import hashlib, json
records = json.load(open('${FIXTURE_DIR}/baseline_records.json'))
sentinel_expected = records['sentinel_dir/external_file.txt']
current_h = hashlib.sha256(open('${FIXTURE_DIR}/sentinel_dir/external_file.txt', 'rb').read()).hexdigest()
assert current_h == sentinel_expected['sha256'], 'Sentinel file was modified!'
print('SENTINEL_INTEGRITY_VERIFIED_OK')
"
```

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

**Interfaces:**
- Consumes: Transferred image tar archive `G2_IMAGE_ARCHIVE_PATH` and checksum `G2_IMAGE_ARCHIVE_SHA256`.
- Produces: Target NAS environment metrics, exact Image ID equality verification, and end-to-end black-box verification logs.

- [ ] **Step 1: Transfer image archive to target 极空间 NAS and verify SHA256**

Run:
```bash
# On verifier host:
# scp "${G2_IMAGE_ARCHIVE_PATH}" user@nas:/tmp/nas-file-center-candidate.tar

# On NAS:
echo "Verifying transferred image archive SHA256 checksum on NAS..."
NAS_ARCHIVE_SHA256=$(sha256sum /tmp/nas-file-center-candidate.tar | awk '{print $1}')
echo "NAS_ARCHIVE_SHA256: ${NAS_ARCHIVE_SHA256}"
echo "G2_IMAGE_ARCHIVE_SHA256: ${G2_IMAGE_ARCHIVE_SHA256}"
[ "${NAS_ARCHIVE_SHA256}" = "${G2_IMAGE_ARCHIVE_SHA256}" ] || { echo "Image archive SHA256 mismatch on NAS!"; exit 1; }
```
Expected: SHA256 checksum on the NAS matches `G2_IMAGE_ARCHIVE_SHA256` bit-for-bit.

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

mkdir -p "${GATE5G_TEST_DATA_PATH}" "${GATE5G_TEST_CONFIG_PATH}" "${GATE5G_TEST_QUARANTINE_PATH}"

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

- [ ] **Step 5: Stage 1 — Read-Only Verification on NAS (`/data:ro`, `ALLOW_MUTATION=false`)**

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
    restart: "no"
EOF

docker compose -f /tmp/nas-gate5g-transient-compose.yaml up -d
sleep 5

# Verify health and worker online
curl -s http://127.0.0.1:28080/health | grep -q '"status":"ok"' || { echo "NAS API unhealthy"; exit 1; }

# Login
curl -s -c /tmp/nas_cookie.txt -X POST http://127.0.0.1:28080/api/auth/login \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# Verify worker online
curl -s -b /tmp/nas_cookie.txt http://127.0.0.1:28080/api/tasks/worker | grep -q '"online":true' || { echo "NAS Worker not online"; exit 1; }

# Verify fclones runs on mounted volume
docker exec gate5g-nas-api fclones group /data > /dev/null

# Verify ResourcePolicy and zero-scheduler invariant
curl -s -b /tmp/nas_cookie.txt http://127.0.0.1:28080/api/settings/resource-policy | grep -q '"scan_threads"' || { echo "Resource policy access failed"; exit 1; }

docker compose -f /tmp/nas-gate5g-transient-compose.yaml down
echo "NAS_STAGE1_READ_ONLY_SUCCESS"
```
Expected: Stage 1 read-only verification passes cleanly on target NAS.

- [ ] **Step 6: Stage 2 — Controlled Mutation Verification on NAS (`/data:rw`, `ALLOW_MUTATION=true`)**

Update `/tmp/nas-gate5g-transient-compose.yaml` for RW mode:
```bash
sed -i 's/:ro/:rw/g' /tmp/nas-gate5g-transient-compose.yaml
sed -i 's/ALLOW_MUTATION=false/ALLOW_MUTATION=true/g' /tmp/nas-gate5g-transient-compose.yaml

docker compose -f /tmp/nas-gate5g-transient-compose.yaml up -d
sleep 5

# 1. Setup fixture files on NAS test data
echo "NAS_DUP1_ALPHA" > "${GATE5G_TEST_DATA_PATH}/nas_fileA.dat"
cp "${GATE5G_TEST_DATA_PATH}/nas_fileA.dat" "${GATE5G_TEST_DATA_PATH}/nas_fileB.dat"
echo "NAS_STALE_ALPHA" > "${GATE5G_TEST_DATA_PATH}/nas_staleA.dat"
cp "${GATE5G_TEST_DATA_PATH}/nas_staleA.dat" "${GATE5G_TEST_DATA_PATH}/nas_staleB.dat"

# Login
curl -s -c /tmp/nas_rw_cookie.txt -X POST http://127.0.0.1:28080/api/auth/login \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# 2. Trigger scan
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

# Inspect frozen items: extract plan-derived paths
NAS_ITEMS=$(curl -s -b /tmp/nas_rw_cookie.txt "http://127.0.0.1:28080/api/plans/${NAS_PLAN_ID}/items")
python3 -c "
import json
data = json.loads('''${NAS_ITEMS}''')
item = data['items'][0]
with open('/tmp/nas_plan_paths.json', 'w') as f:
    json.dump({'keep': item['keep_path'], 'source': item['source_path']}, f)
print('NAS_PLAN_DERIVED_PATHS:', item['keep_path'], '->', item['source_path'])
"
NAS_KEEP=$(python3 -c "import json; print(json.load(open('/tmp/nas_plan_paths.json'))['keep'])")
NAS_SOURCE=$(python3 -c "import json; print(json.load(open('/tmp/nas_plan_paths.json'))['source'])")

# Validate & Execute
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

# Find QuarantineEntry ID
NAS_Q_LIST=$(curl -s -b /tmp/nas_rw_cookie.txt http://127.0.0.1:28080/api/quarantine)
NAS_Q_ID=$(python3 -c "
import json
data = json.loads('''${NAS_Q_LIST}''')
for e in data['items']:
    if e['original_path'] == '${NAS_SOURCE}':
        print(e['id'])
        break
")

# 4. Mandatory Quarantine Restore on NAS
RESTORE_RESP=$(curl -s -b /tmp/nas_rw_cookie.txt -X POST "http://127.0.0.1:28080/api/quarantine/${NAS_Q_ID}/restore" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:28080" -d '{}')
echo "${RESTORE_RESP}" | grep -q '"state":"restored"' || { echo "Restore failed on NAS"; exit 1; }
[ -f "${GATE5G_TEST_DATA_PATH}/$(basename ${NAS_SOURCE})" ] || { echo "Restored file missing on NAS"; exit 1; }

echo "NAS_STAGE2_MUTATION_AND_RESTORE_SUCCESS"
```
Expected: Real G6 lifecycle executed cleanly on NAS storage volume, including plan-derived quarantine and mandatory restore.

- [ ] **Step 7: Teardown transient NAS testbed**

Run (on NAS):
```bash
docker compose -f /tmp/nas-gate5g-transient-compose.yaml down -v
rm -f /tmp/nas-gate5g-transient-compose.yaml /tmp/nas_cookie.txt /tmp/nas_rw_cookie.txt /tmp/nas_plan_paths.json /tmp/nas-file-center-candidate.tar
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
PHASE_G5_RESULT: PASS (SQLite integrity_check=ok, foreign_key_check=0, singleton count=1 id=1, schema/indexes verified)
PHASE_G6_RESULT: PASS (Synthetic safety lifecycle verified: preview/draft/freeze/validate/execute, plan-derived quarantine, stale rejection, mandatory restore passed)
PHASE_G7_RESULT: PASS (Real 极空间 NAS smoke passed on isolated disposable mounts with verified image byte transfer)

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
STALE_PREFLIGHT_RESULT: validate rejected, execute refused with 409 PLAN_STALE, zero file corruption
RESTORE_RESULT: mandatory restore passed, byte-identical recovery verified

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
