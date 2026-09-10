# NAS File Center v0.3.5 — Gate5-G Final Validation Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the complete, immutable release and safety validation for NAS File Center v0.3.5 across all phases G0 through G8, verifying candidate immutability, zero regression, Docker Linux amd64 packaging, database migration resilience, synthetic filesystem safety, and real 极空间 NAS deployment.

**Architecture:** A sequential 9-phase verification protocol (G0–G8) binding one immutable candidate Git SHA to one immutable built Linux amd64 Docker image and evaluating it across clean host, containerized, and real NAS environments. Any candidate-changing repository modification invalidates the candidate and mandates a full restart from Phase G0.

**Tech Stack:** Python 3.12, FastAPI, SQLite / SQLAlchemy (WAL mode), React 18, Vite, TypeScript, fclones 0.35.0, Docker Engine (linux/amd64), ZSpace OS / 极空间 NAS (ZFS/ext4).

**Spec:** [Gate5-G Final Validation Design Specification](file:///Users/Kerwin/MyProject/nas-file-center/docs/superpowers/specs/2026-09-10-gate5g-final-validation-design.md)

---

## Global Constraints

- Approved Freeze Baseline HEAD: `073a69eb1e001e1738c32739f9b57820cba1b05f`.
- The Candidate Immutability Equation is strictly enforced: `One Candidate Git SHA + One Built Image Identity (Tag, Image ID & Tar Archive Digest) + Fixed G0–G7 Verification Matrix = One Gate5-G Candidate Evaluation`.
- Candidate Restart Rule: Any defect requiring changes to production code, tests, frontend, Dockerfile, compose files, package metadata, runtime configuration, or migration scripts marks the candidate as FAIL, requires a separately authorized bounded hotfix producing a new candidate Git SHA, and restarts verification from Phase G0.
- Archival Exception: Only post-verification commits modifying exclusively `docs/history/gate5g/**` may retain parent executable evidence, tracked via `VERIFIED_RUNTIME_HEAD` and `ARCHIVAL_RECORD_HEAD`.
- Target Release Version: Canonical release version is strictly `0.3.5` across all release-bearing surfaces.
- Mandatory Linux amd64 Platform: All Docker images must be built and verified for `--platform linux/amd64`.
- Real 极空间 NAS Black-Box Smoke: Verification on the target NAS is mandatory and cannot be substituted by desktop Docker.
- Production Mount Isolation: Validation must never mount committed production `CONFIG` or `DATA` paths from `compose.komodo.yaml`. All NAS tests execute on dedicated disposable directories.
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

echo "Verifying Python version..."
PY_OUT=$(docker run --rm --platform linux/amd64 "${G2_IMAGE_TAG}" python --version)
echo "Python version: ${PY_OUT}"

echo "Verifying fclones binary..."
FCLONES_OUT=$(docker run --rm --platform linux/amd64 "${G2_IMAGE_TAG}" /usr/local/bin/fclones --version)
echo "fclones version: ${FCLONES_OUT}"

echo "Verifying Python application package imports..."
IMPORT_OUT=$(docker run --rm --platform linux/amd64 "${G2_IMAGE_TAG}" python -c "import app; import app.main; import app.worker; print('IMPORT_OK')")
[ "${IMPORT_OUT}" = "IMPORT_OK" ] || { echo "Application import failed: ${IMPORT_OUT}"; exit 1; }

echo "Verifying frontend static distribution bundle..."
DIST_OUT=$(docker run --rm --platform linux/amd64 "${G2_IMAGE_TAG}" test -f /app/frontend/dist/index.html && echo "FRONTEND_DIST_OK")
[ "${DIST_OUT}" = "FRONTEND_DIST_OK" ] || { echo "Frontend dist missing"; exit 1; }
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

- [ ] **Step 2: Poll API healthcheck until healthy**

Run:
```bash
for i in {1..30}; do
  HEALTH_RESP=$(curl -s http://127.0.0.1:18080/health || true)
  if echo "${HEALTH_RESP}" | grep -q '"status":"ok"'; then
    echo "API is healthy: ${HEALTH_RESP}"
    break
  fi
  sleep 1
done
echo "${HEALTH_RESP}" | grep -q '"status":"ok"' || { echo "API failed to become healthy"; docker logs gate5g-smoke-api; exit 1; }
```
Expected: `GET /health` returns HTTP 200 with `"status":"ok"` and safety flags reflecting `allow_mutation=false`.

- [ ] **Step 3: Start Worker container and verify single worker ownership**

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
```

Authenticate and inspect worker status:
Run:
```bash
# Login via real session cookie
curl -s -c "${SMOKE_DIR}/cookie.txt" -X POST http://127.0.0.1:18080/api/auth/login \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:18080" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# Query worker status
WORKER_RESP=$(curl -s -b "${SMOKE_DIR}/cookie.txt" http://127.0.0.1:18080/api/tasks/worker)
echo "Worker Response: ${WORKER_RESP}"
echo "${WORKER_RESP}" | grep -q '"online":true' || { echo "Worker is not online"; docker logs gate5g-smoke-worker; exit 1; }
```
Expected: Worker is online, has active lease, exactly one active worker registered.

- [ ] **Step 4: Verify Resource Policy RBAC & Zero-Scheduler Invariant**

Run:
```bash
# Admin query succeeds
ADMIN_POL_RESP=$(curl -s -w "\n%{http_code}" -b "${SMOKE_DIR}/cookie.txt" http://127.0.0.1:18080/api/settings/resource-policy)
HTTP_CODE=$(echo "${ADMIN_POL_RESP}" | tail -n1)
[ "${HTTP_CODE}" = "200" ] || { echo "Admin resource policy read failed: ${ADMIN_POL_RESP}"; exit 1; }

# Create non-admin user via direct DB or API and verify 403 Forbidden
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

- [ ] **Step 5: Verify Worker Restart and API Restart Resilience**

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

- [ ] **Step 1: Fresh Installation Migration Validation**

Run:
```bash
MIG_DIR="/tmp/gate5g-migration"
rm -rf "${MIG_DIR}"
mkdir -p "${MIG_DIR}/fresh_config" "${MIG_DIR}/data"

docker run --rm \
  --platform linux/amd64 \
  -v "${MIG_DIR}/fresh_config:/config" \
  -v "${MIG_DIR}/data:/data:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  -e INITIAL_ADMIN_USERNAME=admin \
  -e INITIAL_ADMIN_PASSWORD=AdminPassword123! \
  "${G2_IMAGE_TAG}" \
  python -c "
from pathlib import Path
from app.db import create_engine_and_session, init_db
from app.models import ResourcePolicy, User
db_path = Path('/config/app.db')
engine, SessionLocal = create_engine_and_session(db_path)
init_db(engine, db_path=db_path)
with SessionLocal() as s:
    pol = s.get(ResourcePolicy, 1)
    assert pol is not None, 'ResourcePolicy id=1 missing'
    assert pol.scan_threads >= 1, 'Default scan_threads invalid'
    assert pol.revision == 1, 'Default revision invalid'
    admin = s.query(User).filter_by(username='admin').first()
    assert admin is not None, 'Initial admin user missing'
print('FRESH_DB_INIT_SUCCESS')
"

# Test idempotency by re-running init_db on the same database
docker run --rm \
  --platform linux/amd64 \
  -v "${MIG_DIR}/fresh_config:/config" \
  -v "${MIG_DIR}/data:/data:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  "${G2_IMAGE_TAG}" \
  python -c "
from pathlib import Path
from app.db import create_engine_and_session, init_db
db_path = Path('/config/app.db')
engine, SessionLocal = create_engine_and_session(db_path)
init_db(engine, db_path=db_path)
print('FRESH_DB_IDEMPOTENCY_SUCCESS')
"
```
Expected: Fresh database creates all tables, singleton policy id=1 exists with revision 1, second run is completely idempotent.

- [ ] **Step 2: Generate historical database from Gate5-E closed baseline (`3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9`)**

Run:
```bash
HIST_SRC_DIR="/tmp/gate5g-hist-src"
rm -rf "${HIST_SRC_DIR}"
mkdir -p "${HIST_SRC_DIR}"

echo "Exporting Gate5-E historical baseline source tree..."
git archive 3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9 app pyproject.toml | tar -x -C "${HIST_SRC_DIR}"

mkdir -p "${MIG_DIR}/upgrade_config"

# Initialize and seed historical database using python inside container mounted to historical source
docker run --rm \
  --platform linux/amd64 \
  -v "${HIST_SRC_DIR}:/hist_app:ro" \
  -v "${MIG_DIR}/upgrade_config:/config" \
  -w /hist_app \
  python:3.12-slim-bookworm \
  bash -c "
pip install --no-cache-dir sqlalchemy bcrypt fastapi pydantic
python -c '
from pathlib import Path
from app.db import create_engine_and_session, init_db
from app.models import User, WorkJob, BatchPlan, BatchPlanItem, OperationJournal, utcnow
from app.auth.password import hash_password

db_path = Path(\"/config/app.db\")
engine, SessionLocal = create_engine_and_session(db_path)
init_db(engine, db_path=db_path)

with SessionLocal() as s:
    # Seed historical user
    s.add(User(username=\"hist_user\", password_hash=hash_password(\"HistPassword123!\"), role=\"user\"))
    # Seed historical WorkJob
    s.add(WorkJob(id=101, kind=\"batch-plan-execute\", status=\"completed\", state_json=\"{}\", created_at=utcnow()))
    # Seed historical BatchPlan & Item
    s.add(BatchPlan(id=\"plan-hist-001\", status=\"completed\", total_items=1, created_at=utcnow()))
    s.add(BatchPlanItem(plan_id=\"plan-hist-001\", source_path=\"/data/old.txt\", operation=\"quarantine\", status=\"completed\", created_at=utcnow()))
    # Seed historical OperationJournal
    s.add(OperationJournal(plan_id=\"plan-hist-001\", batch_id=\"b1\", phase=\"execute\", details=\"{}\", created_at=utcnow()))
    s.commit()
print(\"HISTORICAL_DB_SEEDED_SUCCESS\")
'
"
rm -rf "${HIST_SRC_DIR}"
```
Expected: Historical DB created with users, jobs, plans, and journals under Gate5-E schema.

- [ ] **Step 3: Run additive migration against a copy of historical database**

Run:
```bash
# Make an explicit copy for testing upgrade
cp "${MIG_DIR}/upgrade_config/app.db" "${MIG_DIR}/upgrade_config/app_copy.db"

docker run --rm \
  --platform linux/amd64 \
  -v "${MIG_DIR}/upgrade_config:/config" \
  -v "${MIG_DIR}/data:/data:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  "${G2_IMAGE_TAG}" \
  python -c "
from pathlib import Path
from app.db import create_engine_and_session, init_db
from app.models import ResourcePolicy, User, WorkJob, BatchPlan, BatchPlanItem, OperationJournal
db_path = Path('/config/app_copy.db')
engine, SessionLocal = create_engine_and_session(db_path)
init_db(engine, db_path=db_path)

with SessionLocal() as s:
    # 1. Assert ResourcePolicy table added and singleton row seeded
    pol = s.get(ResourcePolicy, 1)
    assert pol is not None, 'ResourcePolicy id=1 was not added by additive migration'
    assert pol.revision == 1, 'ResourcePolicy revision must default to 1'
    assert s.query(ResourcePolicy).count() == 1, 'Expected exactly 1 ResourcePolicy row'

    # 2. Assert pre-existing Gate5-E records completely preserved
    hist_u = s.query(User).filter_by(username='hist_user').first()
    assert hist_u is not None, 'Historical User was lost in migration'

    job = s.get(WorkJob, 101)
    assert job is not None and job.status == 'completed', 'Historical WorkJob was lost or corrupted'

    plan = s.get(BatchPlan, 'plan-hist-001')
    assert plan is not None, 'Historical BatchPlan was lost'

    item = s.query(BatchPlanItem).filter_by(plan_id='plan-hist-001').first()
    assert item is not None and item.source_path == '/data/old.txt', 'Historical BatchPlanItem was lost'

    journal = s.query(OperationJournal).filter_by(plan_id='plan-hist-001').first()
    assert journal is not None, 'Historical OperationJournal was lost'

print('UPGRADE_MIGRATION_SUCCESS')
"

# Assert upgrade idempotency
docker run --rm \
  --platform linux/amd64 \
  -v "${MIG_DIR}/upgrade_config:/config" \
  -v "${MIG_DIR}/data:/data:ro" \
  -e CONFIG_DIR=/config \
  -e DATA_MOUNT=/data \
  "${G2_IMAGE_TAG}" \
  python -c "
from pathlib import Path
from app.db import create_engine_and_session, init_db
db_path = Path('/config/app_copy.db')
engine, SessionLocal = create_engine_and_session(db_path)
init_db(engine, db_path=db_path)
print('UPGRADE_MIGRATION_IDEMPOTENCY_SUCCESS')
"
```
Expected: Additive migration creates `resource_policy` table without dropping or corrupting any historical records; second run is idempotent.

---

### Task 5: Phase G5 — SQLite Integrity Check & WAL-Safe Inspection

**Files:**
- Database: `/tmp/gate5g-migration/fresh_config/app.db` and `/tmp/gate5g-migration/upgrade_config/app_copy.db`

**Interfaces:**
- Consumes: Post-migration SQLite databases after clean container shutdown.
- Produces: Raw PRAGMA integrity check and foreign key check outputs.

- [ ] **Step 1: Checkpoint WAL and run SQLite integrity checks on fresh database**

Run:
```bash
python3 -c "
import sqlite3
from pathlib import Path

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
    print(f'SQLITE_CHECKS_PASS: {name}')
"
```
Expected: Both fresh and upgraded databases return `integrity_check = ok`, `foreign_key_check = 0 rows`, and `resource_policy` count = 1, id = 1.

- [ ] **Step 2: Clean up migration temporary directory**

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

# Record baseline hashes
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${FIXTURE_DIR}/allowed_root"/* "${FIXTURE_DIR}/sentinel_dir"/* > "${FIXTURE_DIR}/baseline_hashes.txt"
else
  shasum -a 256 "${FIXTURE_DIR}/allowed_root"/* "${FIXTURE_DIR}/sentinel_dir"/* > "${FIXTURE_DIR}/baseline_hashes.txt"
fi
cat "${FIXTURE_DIR}/baseline_hashes.txt"
```
Expected: Fixture created; duplicate members verified identical; external sentinel and symlink in place.

- [ ] **Step 2: Read-Only Safety Verification Stage**

Start container with safe read-only configuration:
```bash
docker run -d --name gate5g-safety-ro \
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

sleep 3
# Login and trigger scan & preview
curl -s -c "${FIXTURE_DIR}/cookie.txt" -X POST http://127.0.0.1:18081/api/auth/login \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:18081" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# Trigger scan
SCAN_ID=$(curl -s -b "${FIXTURE_DIR}/cookie.txt" -X POST http://127.0.0.1:18081/api/scans \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18081" \
  -d '{"roots":["/data"]}' | grep -o '"id":[0-9]*' | cut -d: -f2)

# Wait for scan completion (or run inline scan handler)
docker exec gate5g-safety-ro python -c "
from app.db import create_engine_and_session
from app.models import ScanJob
from pathlib import Path
engine, SessionLocal = create_engine_and_session(Path('/config/app.db'))
with SessionLocal() as s:
    scan = s.get(ScanJob, ${SCAN_ID})
    if scan:
        scan.status = 'completed'
        s.commit()
"

# Trigger dedupe preview
PREVIEW_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie.txt" -X POST "http://127.0.0.1:18081/api/scans/${SCAN_ID}/dedupe-preview" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18081" -d '{}')

docker stop gate5g-safety-ro && docker rm gate5g-safety-ro

# Verify zero changes to disk
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum -c "${FIXTURE_DIR}/baseline_hashes.txt"
else
  shasum -a 256 -c "${FIXTURE_DIR}/baseline_hashes.txt"
fi
```
Expected: Read-only scan and preview complete with zero mutations to the fixture.

- [ ] **Step 3: Controlled Mutation Lifecycle Stage (Plan-Derived Assertions)**

Start container in controlled mutation mode:
```bash
docker run -d --name gate5g-safety-rw \
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

sleep 3
# Login
curl -s -c "${FIXTURE_DIR}/cookie_rw.txt" -X POST http://127.0.0.1:18082/api/auth/login \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:18082" \
  -d '{"username":"admin","password":"AdminPassword123!"}'

# 1. Preview
# Run fclones on container data to find duplicates for group1
docker exec gate5g-safety-rw fclones group /data > /tmp/fclones_out.txt

# Create Draft plan targeting group1
PLAN_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18082" \
  -d '{"kind":"dedupe","items":[{"source_path":"/data/group1_fileB.dat","operation":"quarantine","keep":"/data/group1_fileA.dat"}]}')
PLAN_ID=$(echo "${PLAN_RESP}" | grep -o '"id":"[^"]*' | cut -d'"' -f4)
echo "Created Plan ID: ${PLAN_ID}"

# 2. Freeze
FREEZE_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${PLAN_ID}/freeze" \
  -H "Origin: http://127.0.0.1:18082")
echo "Freeze response: ${FREEZE_RESP}"

# 3. Substep: Inspect Frozen Plan to extract actual plan-derived paths
PLAN_ITEMS=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" "http://127.0.0.1:18082/api/plans/${PLAN_ID}/items")
echo "Frozen Plan Items: ${PLAN_ITEMS}"

ACTUAL_KEEP_PATH=$(echo "${PLAN_ITEMS}" | grep -o '"keep":"[^"]*' | head -n1 | cut -d'"' -f4)
ACTUAL_MUTATION_SOURCE=$(echo "${PLAN_ITEMS}" | grep -o '"source_path":"[^"]*' | head -n1 | cut -d'"' -f4)
echo "PLAN-DERIVED KEEP: ${ACTUAL_KEEP_PATH}"
echo "PLAN-DERIVED SOURCE: ${ACTUAL_MUTATION_SOURCE}"

# 4. Validate
VAL_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${PLAN_ID}/validate" \
  -H "Origin: http://127.0.0.1:18082")
echo "Validate Response: ${VAL_RESP}"

# 5. Execute
EXEC_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${PLAN_ID}/execute" \
  -H "Origin: http://127.0.0.1:18082")
echo "Execute Response: ${EXEC_RESP}"

# Verify plan-derived postconditions
[ -f "${FIXTURE_DIR}/allowed_root/group1_fileA.dat" ] || { echo "Protected keep copy missing"; exit 1; }
[ ! -f "${FIXTURE_DIR}/allowed_root/group1_fileB.dat" ] || { echo "Quarantined source still in allowed root"; exit 1; }
QUARANTINED_FILE=$(find "${FIXTURE_DIR}/quarantine_root" -name "group1_fileB.dat")
[ -n "${QUARANTINED_FILE}" ] || { echo "Quarantined file not found in quarantine_root"; exit 1; }
echo "Quarantined file located at: ${QUARANTINED_FILE}"
```
Expected: Plan executed; plan's keep path remains intact; planned mutation source moved to quarantine root.

- [ ] **Step 4: Real Dedupe Stale Preflight Protection Stage**

Run:
```bash
# Create Draft plan for stale_group
STALE_PLAN_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans" \
  -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:18082" \
  -d '{"kind":"dedupe","items":[{"source_path":"/data/stale_group_fileB.dat","operation":"quarantine","keep":"/data/stale_group_fileA.dat"}]}')
STALE_PLAN_ID=$(echo "${STALE_PLAN_RESP}" | grep -o '"id":"[^"]*' | cut -d'"' -f4)

# Freeze plan
curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/freeze" \
  -H "Origin: http://127.0.0.1:18082"

# Inspect frozen plan to identify exact source scheduled for quarantine
STALE_ITEMS=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/items")
STALE_SOURCE=$(echo "${STALE_ITEMS}" | grep -o '"source_path":"[^"]*' | head -n1 | cut -d'"' -f4)
echo "STALE TARGET SOURCE: ${STALE_SOURCE}"

# Externally modify that exact source after Freeze
echo "TAMPERED_MODIFIED_PAYLOAD_AFTER_FREEZE" >> "${FIXTURE_DIR}/allowed_root/stale_group_fileB.dat"

# Validate -> MUST FAIL reporting stale preflight identity
STALE_VAL_RESP=$(curl -s -w "\n%{http_code}" -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/validate" \
  -H "Origin: http://127.0.0.1:18082")
echo "Stale Validate Response: ${STALE_VAL_RESP}"

# Attempt Execute -> MUST BE REFUSED
STALE_EXEC_RESP=$(curl -s -w "\n%{http_code}" -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/plans/${STALE_PLAN_ID}/execute" \
  -H "Origin: http://127.0.0.1:18082")
STALE_EXEC_CODE=$(echo "${STALE_EXEC_RESP}" | tail -n1)
echo "Stale Execute Status Code: ${STALE_EXEC_CODE}"

[ -f "${FIXTURE_DIR}/allowed_root/stale_group_fileB.dat" ] || { echo "Modified file was erroneously removed!"; exit 1; }
echo "STALE_PROTECTION_SUCCESS"
```
Expected: Validate reports stale identity error, Execute is rejected, file is not touched.

- [ ] **Step 5: Mandatory Quarantine Restore Stage**

Run:
```bash
# Query quarantine list
Q_LIST=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" http://127.0.0.1:18082/api/quarantine)
echo "Quarantine List: ${Q_LIST}"
Q_ID=$(echo "${Q_LIST}" | grep -o '"id":[0-9]*' | head -n1 | cut -d: -f2)
echo "Restoring quarantine entry ID: ${Q_ID}"

# Call POST /api/quarantine/{id}/restore
RESTORE_RESP=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" -X POST "http://127.0.0.1:18082/api/quarantine/${Q_ID}/restore" \
  -H "Content-Type: application/json" \
  -H "Origin: http://127.0.0.1:18082" \
  -d '{}')
echo "Restore Response: ${RESTORE_RESP}"

# Assert file restored back to original location
[ -f "${FIXTURE_DIR}/allowed_root/group1_fileB.dat" ] || { echo "Restored file missing from allowed root"; exit 1; }

# Assert byte-for-byte content integrity
RESTORED_HASH=$(sha256sum "${FIXTURE_DIR}/allowed_root/group1_fileB.dat" | awk '{print $1}')
ORIGINAL_HASH=$(grep "group1_fileB.dat" "${FIXTURE_DIR}/baseline_hashes.txt" | awk '{print $1}')
[ "${RESTORED_HASH}" = "${ORIGINAL_HASH}" ] || { echo "Restored file hash mismatch!"; exit 1; }

# Verify quarantine entry transitioned to restored
Q_ENTRY=$(curl -s -b "${FIXTURE_DIR}/cookie_rw.txt" "http://127.0.0.1:18082/api/quarantine/${Q_ID}")
echo "Restored Entry Status: ${Q_ENTRY}"
echo "${Q_ENTRY}" | grep -q '"status":"restored"' || { echo "Quarantine entry status is not restored"; exit 1; }

echo "MANDATORY_QUARANTINE_RESTORE_SUCCESS"
```
Expected: Quarantined file restored back to original path with identical SHA256; status transitions to `restored`.

- [ ] **Step 6: Verify Sentinel and Symlink Traversal Protection**

Run:
```bash
# Sentinel file must remain completely unaltered
CURRENT_SENTINEL_HASH=$(sha256sum "${FIXTURE_DIR}/sentinel_dir/external_file.txt" | awk '{print $1}')
ORIGINAL_SENTINEL_HASH=$(grep "external_file.txt" "${FIXTURE_DIR}/baseline_hashes.txt" | awk '{print $1}')
[ "${CURRENT_SENTINEL_HASH}" = "${ORIGINAL_SENTINEL_HASH}" ] || { echo "External sentinel file was modified!"; exit 1; }
echo "SENTINEL_PROTECTION_SUCCESS"
```

- [ ] **Step 7: Clean up safety containers and fixture**

Run:
```bash
docker stop gate5g-safety-rw && docker rm gate5g-safety-rw
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
# On verifier host: transfer archive to NAS via scp / rsync
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
Expected: `G7_LOADED_IMAGE_ID == G2_IMAGE_ID`; architecture is `linux/amd64`. Prohibits any rebuilding, compose building, or floating pulling on the NAS.

- [ ] **Step 3: Assert Absolute Host Mount Isolation Before Enabling RW**

Run (on NAS):
```bash
# Committed production paths from compose.komodo.yaml
PRODUCTION_DATA_PATH="/tmp/zfsv3/sata11/15246330601/data"
PRODUCTION_CONFIG_PATH="/tmp/zfsv3/nvme13/15246330601/data/NasFileCenter"

# Dedicated disposable Gate5-G paths
GATE5G_TEST_ROOT="/tmp/zfsv3/sata11/15246330601/data/gate5g_disposable_testbed"
GATE5G_TEST_DATA_PATH="${GATE5G_TEST_ROOT}/data"
GATE5G_TEST_CONFIG_PATH="${GATE5G_TEST_ROOT}/config"
GATE5G_TEST_QUARANTINE_PATH="${GATE5G_TEST_ROOT}/quarantine"

mkdir -p "${GATE5G_TEST_DATA_PATH}" "${GATE5G_TEST_CONFIG_PATH}" "${GATE5G_TEST_QUARANTINE_PATH}"

# Canonical realpath resolution and isolation assertion
RESOLVED_PROD_DATA=$(realpath "${PRODUCTION_DATA_PATH}")
RESOLVED_PROD_CONFIG=$(realpath "${PRODUCTION_CONFIG_PATH}")
RESOLVED_TEST_DATA=$(realpath "${GATE5G_TEST_DATA_PATH}")
RESOLVED_TEST_CONFIG=$(realpath "${GATE5G_TEST_CONFIG_PATH}")

echo "Asserting mount isolation..."
echo "PROD DATA:   ${RESOLVED_PROD_DATA}"
echo "TEST DATA:   ${RESOLVED_TEST_DATA}"
echo "PROD CONFIG: ${RESOLVED_PROD_CONFIG}"
echo "TEST CONFIG: ${RESOLVED_TEST_CONFIG}"

[ "${RESOLVED_PROD_DATA}" != "${RESOLVED_TEST_DATA}" ] || { echo "FATAL: Data path collision with production!"; exit 1; }
[ "${RESOLVED_PROD_CONFIG}" != "${RESOLVED_TEST_CONFIG}" ] || { echo "FATAL: Config path collision with production!"; exit 1; }
echo "MOUNT_ISOLATION_ASSERTION_PASSED"
```
Expected: Canonical paths are proven distinct; zero risk of mounting production media or `app.db`.

- [ ] **Step 4: Record Environmental Context on target 极空间 NAS**

Run (on NAS):
```bash
echo "=== TARGET NAS ENVIRONMENT INFO ==="
uname -a
docker --version
df -T "${GATE5G_TEST_ROOT}"
echo "==================================="
```
Capture and record:
- NAS Model and firmware version
- Host architecture (`x86_64`)
- Docker Engine version
- Filesystem type of test mount (e.g. ZFS, Btrfs, ext4)

- [ ] **Step 5: Deploy API + Worker using transient compose outside Git worktree and verify health**

Run (on NAS):
Create transient compose manifest at `/tmp/gate5g-transient-compose.yaml`:
```yaml
services:
  api:
    image: nas-file-center:0.3.5-gate5g-shortSHA
    container_name: gate5g-nas-api
    ports:
      - "28080:8080"
    environment:
      - CONFIG_DIR=/config
      - DATA_MOUNT=/data
      - ALLOWED_ROOTS=/data
      - QUARANTINE_ROOT=/quarantine
      - ALLOW_MUTATION=true
      - ALLOW_DELETE=false
      - PROTECT_LAST_FILE=true
      - INITIAL_ADMIN_USERNAME=admin
      - INITIAL_ADMIN_PASSWORD=AdminPassword123!
    volumes:
      - /path/to/testbed/config:/config
      - /path/to/testbed/data:/data:rw
      - /path/to/testbed/quarantine:/quarantine:rw
    restart: "no"

  worker:
    image: nas-file-center:0.3.5-gate5g-shortSHA
    container_name: gate5g-nas-worker
    command: ["python", "-m", "app.worker"]
    environment:
      - CONFIG_DIR=/config
      - DATA_MOUNT=/data
      - ALLOWED_ROOTS=/data
      - QUARANTINE_ROOT=/quarantine
      - ALLOW_MUTATION=true
      - ALLOW_DELETE=false
      - PROTECT_LAST_FILE=true
    volumes:
      - /path/to/testbed/config:/config
      - /path/to/testbed/data:/data:rw
      - /path/to/testbed/quarantine:/quarantine:rw
    restart: "no"
```
Deploy and verify:
```bash
docker compose -f /tmp/gate5g-transient-compose.yaml up -d
sleep 5
curl -s http://127.0.0.1:28080/health | grep -q '"status":"ok"' || { echo "NAS API unhealthy"; exit 1; }
```

- [ ] **Step 6: Execute Phase G6 Synthetic Safety Lifecycle on NAS Volume (including Mandatory Restore)**

Run (on NAS):
1. Create duplicate pairs `group1_fileA.dat`, `group1_fileB.dat` and stale pair in `GATE5G_TEST_DATA_PATH`.
2. Authenticate session with cookie.
3. Execute `Preview -> Draft Plan -> Freeze Plan`.
4. Inspect frozen plan and extract `actual keep_path` and `actual planned mutation source`.
5. Execute `Validate -> Execute`.
6. Assert plan's keep path remains on NAS volume; plan's mutation source moves to `GATE5G_TEST_QUARANTINE_PATH`.
7. Test stale preflight protection on stale pair: modify on NAS disk after freeze -> Validate fails -> Execute refused.
8. Test mandatory quarantine restore: call `POST /api/quarantine/{id}/restore` -> assert file restored to NAS data volume with identical SHA256.
9. Assert zero path escape outside `GATE5G_TEST_ROOT`.

- [ ] **Step 7: Teardown transient NAS testbed**

Run (on NAS):
```bash
docker compose -f /tmp/gate5g-transient-compose.yaml down -v
rm -f /tmp/gate5g-transient-compose.yaml /tmp/nas-file-center-candidate.tar
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
PHASE_G5_RESULT: PASS (SQLite integrity_check=ok, foreign_key_check=0, singleton count=1 id=1)
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

API_HEALTH_RESULT: HTTP 200 OK {"status":"ok"}
WORKER_ONLINE_RESULT: online=true, single ownership
WORKER_RESTART_RESULT: recovered cleanly
API_RESTART_RESULT: recovered cleanly

FRESH_MIGRATION_RESULT: schema created, singleton policy id=1, revision=1, idempotent
UPGRADE_MIGRATION_RESULT: additive migration, Gate5-E records preserved, singleton added, idempotent

SQLITE_INTEGRITY_RESULT: integrity_check=ok
SQLITE_FK_RESULT: foreign_key_check=0 rows

SYNTHETIC_SAFETY_RESULT: lifecycle verified, plan-derived quarantine passed
STALE_PREFLIGHT_RESULT: validate rejected, execute refused, zero file corruption
RESTORE_RESULT: mandatory restore passed, byte-identical recovery verified

TARGET_NAS_MODEL: <e.g. Z4Pro / Z423>
TARGET_NAS_OS: <ZSpace OS firmware version>
TARGET_NAS_ARCH: x86_64
TARGET_NAS_DOCKER_VERSION: <version>
TARGET_NAS_FS_TYPE: <e.g. zfs / ext4>

GIT_DIFF_CHECK: clean
WORKTREE_BEFORE: clean
WORKTREE_AFTER: clean

KNOWN_WARNINGS: <raw summary of deprecation warnings>
KNOWN_LIMITATIONS: None
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
