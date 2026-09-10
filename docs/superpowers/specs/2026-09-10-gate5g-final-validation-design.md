# NAS File Center v0.3.5 — Gate5-G Final Validation Design Specification

**Document Version:** 1.0.0  
**Date:** 2026-09-10  
**Status:** DESIGN SPECIFICATION CANDIDATE / ARCHITECTURE FREEZE PROPOSAL  
**Implementation / Execution Status:** NOT AUTHORIZED  
**Authoritative Baseline HEAD:** `e04399c8ee8a5b2a81b9090dabb402c49e21e2fb`  
**Target Branch:** `v0.3.5-gate5c-hotfix4`  

---

## 1. Context, Authority, and Objectives

### 1.1 Gate Hierarchy and Immutability of Prior Baselines
NAS File Center v0.3.5 development has formally passed and closed all preceding functional and structural gates:
```text
Gate5-A = PASS / CLOSED (Task Engine Core & Job Models)
Gate5-B = PASS / CLOSED (Task Engine Cancellation, Fencing & Leases)
Gate5-C = PASS / CLOSED (Worker Recovery & Task Engine Rebuild)
Gate5-D = PASS / CLOSED (Advanced Deduplication Preview & Compiler)
Gate5-E = PASS / CLOSED (Batch Utilities, Symlink Safety & Graph DAG Engine)
Gate5-F = PASS / CLOSED (Resource Control & Active Window Governance)

Gate5-G = AUTHORIZED FOR DESIGN / ARCHITECTURE FREEZE ONLY
v0.3.5  = NOT CLOSED
```
Gate5-G is the **final release validation and safety verification gate** for version 0.3.5. It does not introduce new features, state machines, or domain capabilities. Gate5-G must not reopen, redesign, or weaken any closed gate (Gate5-A through Gate5-F).

### 1.2 Core Safety Priorities
All verification criteria and failure triage in Gate5-G strictly enforce the project's foundational hierarchy of priorities:
```text
数据安全 (Data Safety)
  > 正确性 (Correctness)
    > 可恢复性 (Recoverability)
      > 性能 (Performance)
        > 用户界面 (User Interface)
          > 功能特性 (Features)
```

### 1.3 Immutable Mutation Lifecycle
No validation scenario or test workflow may bypass the mandatory mutation lifecycle:
```text
Preview
  → Explicit Generate Draft
    → Freeze
      → Validate
        → Execute
```
Verification actions must actively test and prove that every stage of this lifecycle is respected and that safety boundaries cannot be bypassed under any operational condition.

---

## 2. Fundamental Gate5-G Verification Model

### 2.1 The Immutable Candidate Equation
Gate5-G enforces strict candidate immutability. Verification is never performed against an ambiguous, shifting, or partially updated repository state. The formal candidate model is:
```text
One Immutable Candidate SHA
  + One Immutable Built Image Identity (Tag & Digest)
    + One Fixed Verification Matrix (Phases G0 through G7)
      = One Gate5-G Candidate Evaluation
```

### 2.2 Prohibited Identity Practices
Gate5-G explicitly prohibits the following practices as verification proof:
- "Mostly the same SHA" or testing across multiple cherry-picked commits.
- "Latest branch state" or floating `HEAD` references.
- "Whatever image is currently tagged `:latest`".
- Reusing an old local image built from an unverified or prior commit.

Every single verification artifact, test log, and status report must bind to:
1. Exact Git commit SHA (full 40-character hexadecimal string).
2. Exact source tree (clean working tree verified by `git status --short` and `git diff --check`).
3. Exact built Docker image tag and immutable Image ID / RepoDigest.
4. Target CPU architecture (`linux/amd64`).
5. Specific target verification environment (local testbed vs. target 极空间 NAS).

---

## 3. Mandatory Immutable-Candidate Restart Rule

### 3.1 Strict Invalidation Protocol
If any phase of Gate5-G verification discovers an issue, bug, or blocker that necessitates a modification to:
- Production application code (`app/**`)
- Test suites (`tests/**`)
- Frontend application code or configuration (`frontend/**`)
- Build definitions (`Dockerfile`, `.dockerignore`)
- Orchestration manifests (`compose.yaml`, `compose.komodo.yaml`)
- Package metadata (`pyproject.toml`, `package.json`, `package-lock.json`)
- Committed runtime configuration files or environment definitions
- Database migration behavior or schema scripts

Then the following actions are **mandatory and non-negotiable**:
1. The current Gate5-G candidate is immediately marked:
   ```text
   Gate5-G candidate = FAIL
   ```
2. A separately authorized, bounded hotfix must be implemented, verified, and committed to produce a **new immutable candidate Git commit SHA**.
3. **All executable verification must restart from Phase G0.**
4. No verification evidence, test outputs, or container smoke results from the prior candidate SHA may be carried over, reused, or cited as proof for the new candidate.

### 3.2 Documentation-Only Archival Exception
A single, narrowly bounded exception to the restart rule is permitted:
- If a post-verification commit modifies **strictly and exclusively** documentation under `docs/history/gate5g/**` to record final verification evidence and walkthrough logs,
- AND an independent reviewer confirms via `git diff --name-only` that zero production, test, frontend, build, or deployment files were touched,
- THEN the executable evidence collected on the direct parent commit remains valid for release closure.

In such cases, the final audit report must explicitly disclose both commit identities:
- `VERIFIED_RUNTIME_HEAD`: The exact commit SHA upon which all tests, builds, and container smokes were executed.
- `ARCHIVAL_RECORD_HEAD`: The docs-only commit containing the finalized historical report.

---

## 4. Verification Phases Overview (G0 – G8)

Gate5-G is organized into nine sequential verification phases. These phases represent **verification stages of a single candidate evaluation**, not independently closed product gates:

```text
+-------------------------------------------------------------------------------+
| G0: Candidate & Release Metadata Preflight                                    |
+---------------------------------------+---------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
| G1: Source Regression & Frontend Verification                                 |
+---------------------------------------+---------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
| G2: Linux amd64 Docker Clean Build & Image Inspection                         |
+---------------------------------------+---------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
| G3: API + Worker Container Smoke & Process Ownership                          |
+---------------------------------------+---------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
| G4: Database Migration (Fresh Install & Upgrade from Gate5-E Baseline)        |
+---------------------------------------+---------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
| G5: SQLite Integrity Check & Foreign Key Verification                         |
+---------------------------------------+---------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
| G6: Synthetic Filesystem Safety & Mutation Lifecycle Black-Box               |
+---------------------------------------+---------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
| G7: Target 极空间 NAS Black-Box Environment Smoke                             |
+---------------------------------------+---------------------------------------+
                                        |
+---------------------------------------v---------------------------------------+
| G8: Final Release Evidence & Immutable Release-Candidate Audit               |
+-------------------------------------------------------------------------------+
```

---

## 5. Detailed Phase Specifications

### 5.1 Phase G0 — Candidate & Release Metadata Preflight

#### 5.1.1 Target Release Version
The canonical release version for this milestone is strictly:
```text
0.3.5
```

#### 5.1.2 Consistency Requirements
Before executing expensive build and test phases, all release-bearing metadata committed in the candidate must align:
1. `pyproject.toml` -> `[project].version == "0.3.5"`
2. `app/main.py` -> `FastAPI(..., version="0.3.5")`
3. `frontend/package.json` -> `"version": "0.3.5"`
4. `frontend/package-lock.json` -> root package `"version": "0.3.5"` (if present)
5. `compose.yaml` -> default application image tag `nas-file-center:0.3.5`
6. `compose.komodo.yaml` -> production image reference `kerwinjhc/nas-file-center:0.3.5` or an immutable image digest.

#### 5.1.3 Prohibition on `:latest` in Production Manifests
For immutable production deployments (including Komodo deployment), `:latest` is strictly rejected as the sole image identity. `compose.komodo.yaml` must bind explicitly to `kerwinjhc/nas-file-center:0.3.5` or an immutable `@sha256:...` digest. A convenience `:latest` tag alias may only be published post-release.

#### 5.1.4 Known Baseline Finding (Recorded as KNOWN G0 BLOCKING FINDING)
At the authoritative baseline HEAD (`e04399c8ee8a5b2a81b9090dabb402c49e21e2fb`), the repository exhibits the following known version discrepancies:
- `pyproject.toml`: `version = "0.3.3"`
- `app/main.py`: `version="0.3.3"`
- `frontend/package.json`: `"version": "0.3.3"`
- `frontend/package-lock.json`: `"version": "0.3.3"`
- `compose.yaml`: `image: nas-file-center:0.3.2`
- `compose.komodo.yaml`: `image: kerwinjhc/nas-file-center:latest`

**Resolution Plan:**
- This discrepancy is formally recorded as `KNOWN G0 BLOCKING FINDING`.
- It must **not** be modified in this design checkpoint commit.
- During initial Gate5-G G0 execution, the current candidate will formally FAIL on Phase G0.
- A dedicated, bounded release-metadata hotfix will subsequently be authorized to align all metadata to `0.3.5`, generating the true release-candidate SHA for full Gate5-G execution.

---

### 5.2 Phase G1 — Source Regression & Frontend Verification

#### 5.2.1 Backend Test Suites
Executed in an environment meeting filesystem case-sensitivity requirements:
1. **Gate5-A ~ Gate5-F Focused Suites**:
   - `pytest tests/test_gate5a_*.py tests/test_gate5b_*.py tests/test_gate5c_*.py tests/test_gate5d_*.py tests/test_gate5e_*.py tests/test_gate5f_*.py -v`
2. **Task Engine, Worker, and Scanner Core Suites**:
   - `pytest tests/test_worker_recovery_and_claim.py tests/test_task_state_machine.py tests/test_task_api.py tests/test_task_checkpoint.py tests/test_task_pause_resume_e2e.py tests/test_gate2_hotfix1_worker_fencing.py tests/test_fclones.py tests/test_scan_jobs.py tests/test_indexing.py tests/test_index_root_lifecycle.py tests/test_index_root_progress_regression.py -v`
3. **Planning & Execution Engine Suites**:
   - `pytest tests/test_planning.py tests/test_execution.py -v`
4. **Full Backend Repository Suite**:
   - `pytest tests/`

**Pass Criteria:**
- `0 failed, 0 errors` across all backend test runs.
- Total passed tests, warning counts, and exact execution elapsed times must be captured in raw format without citing historical values.

#### 5.2.2 Frontend Quality Gates
Executed within the `frontend/` directory:
1. `npm run typecheck` (`tsc --noEmit`) -> exit code `0`, `0 errors`.
2. `npm run test` (`node scripts/run-tests.mjs`) -> exit code `0`. (Must not be skipped).
3. `npm run build` (`tsc && vite build`) -> exit code `0`, distribution bundle generated in `frontend/dist`.

#### 5.2.3 Repository Hygiene
- `git diff --check` -> exit code `0`, empty output (no whitespace errors, no syntax anomalies).
- `git status --short` -> clean working tree before and after test execution.

---

### 5.3 Phase G2 — Linux amd64 Docker Clean Build & Inspection

#### 5.3.1 Target Platform Requirement
Production deployments target `linux/amd64` (x86_64) running Docker Engine on 极空间 NAS. Building or validating only for macOS ARM64 (`darwin/arm64`) is strictly insufficient.

#### 5.3.2 Clean Build Protocol
- Build invocation must specify `--platform linux/amd64`.
- Image caching must not reuse obsolete application layers (`--no-cache` on application build stages).
- Candidate source SHA must be fixed and recorded prior to build.
- Tag convention: `nas-file-center:0.3.5-gate5g-<shortSHA>`.

#### 5.3.3 Internal Container Inspection
Run a temporary container from the built image and verify:
1. Architecture: `uname -m` outputs `x86_64`.
2. Python: `python --version` matches requirement (`>=3.12`).
3. Binary dependencies:
   - `/usr/local/bin/fclones` exists and is executable.
   - `/usr/local/bin/fclones --version` succeeds.
4. Python application package:
   - `python -c "import app; import app.main; import app.worker; print('IMPORT_OK')"` succeeds.
5. Static frontend distribution:
   - `/app/frontend/dist/index.html` exists and is non-empty.

**Recorded Artifacts:**
- Full Image Tag, Image ID (SHA256), RepoDigest (if pushed to registry), Architecture, OS, and Source Candidate SHA.

---

### 5.4 Phase G3 — API + Worker Docker Smoke & Process Ownership

#### 5.4.1 Real Service Model
Validate containerized processes using the exact operational topology:
- **API Service**: `uvicorn app.main:app --host 0.0.0.0 --port 8080`
- **Worker Service**: `python -m app.worker`
- **Shared Volumes**: Isolated host directory mounted to container `/config`, controlled test fixture mounted to container `/data`.

#### 5.4.2 Smoke Verification Checklist
1. **Startup & Healthcheck**:
   - API container starts and transitions to healthy state.
   - `GET http://127.0.0.1:8080/health` returns HTTP `200 OK` with JSON payload `{"status": "ok", ...}`.
   - Safety flags returned by healthcheck accurately reflect environment variables (`ALLOW_MUTATION`, `ALLOW_DELETE`, `PROTECT_LAST_FILE`).
2. **Session Authentication & RBAC**:
   - Authenticate via `POST /api/auth/login` using standard credentials.
   - Obtain session cookie.
   - Authenticated API endpoints are functional.
3. **Worker Ownership & State**:
   - Call `GET /api/tasks/worker`.
   - Verify exactly one active Worker is registered, online, and maintaining lease heartbeats.
   - Verify no second worker architecture exists.
   - Verify neither API nor Worker experiences crash-looping or unhandled exceptions.
4. **Resource Policy RBAC**:
   - Admin user `GET /api/settings/resource-policy` -> HTTP `200 OK`.
   - Non-admin user `GET /api/settings/resource-policy` -> HTTP `403 Forbidden`.
5. **Process Lifecycle & Resilience**:
   - Restart Worker container: verify Worker acquires ownership, asserts lease, and recovers without orphan state.
   - Restart API container: verify database connectivity is restored and existing data remains accessible.
   - Verify that neither active window configuration nor background polling introduces any unauthorized scheduler process or jobs.

---

### 5.5 Phase G4 — Database Migration & Schema Resilience

#### 5.5.1 Scenario A: Fresh Installation
- Provide an empty, isolated directory as `CONFIG_DIR`.
- Start the application container.
- Verify:
  1. SQLite database file is created successfully.
  2. All tables across all gates (users, tasks, plans, journals, resource policies) are created.
  3. `resource_policy` table contains exactly one row with `id = 1` and default values.
  4. Subsequent container restart against the newly created database is completely idempotent and reports zero migration errors.

#### 5.5.2 Scenario B: Upgrade from Authoritative Gate5-E Closed Baseline
- Baseline SHA: `3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9` (Gate5-E CLOSED).
- Create a disposable database generated from the Gate5-E schema.
- Seed representative pre-existing records:
  - User records and sessions.
  - Completed and queued `WorkJob` entries.
  - `BatchPlan` and `BatchPlanItem` records.
  - Index and scan history rows.
  - `OperationJournal` records.
- Start the Gate5-G candidate container against a copy of this pre-existing database.
- Verify:
  1. Additive migrations apply cleanly.
  2. All pre-existing records (users, jobs, plans, journal entries) remain intact and unaltered.
  3. No tables are dropped, recreated, or emptied.
  4. `resource_policy` singleton row is seeded with `id = 1` and `revision = 1`.
  5. Subsequent container restart against the upgraded database is idempotent.

**Strict Prohibition:**
- Migration tests must never be run against real user data or production NAS databases. Only isolated, disposable test databases may be used.

---

### 5.6 Phase G5 — SQLite Integrity & Constraint Verification

#### 5.6.1 Verification Protocol
Following the completion of fresh install, upgrade install, and container restart tests (after ensuring clean WAL checkpoints via graceful container shutdown):
1. Execute `PRAGMA integrity_check;` on the SQLite database file.
   - **Required Result:** Exactly one row returned with value `ok`.
2. Execute `PRAGMA foreign_key_check;` on the SQLite database file.
   - **Required Result:** Exactly zero rows returned.
3. Query Singleton Invariants:
   - `SELECT count(*) FROM resource_policy;` -> Exactly `1`.
   - `SELECT id FROM resource_policy;` -> Exactly `1`.
4. Table Schema Integrity:
   - Verify all expected indexes, unique constraints, and schema revisions are valid.

---

### 5.7 Phase G6 — Synthetic Filesystem Safety Black-Box

#### 5.7.1 Dedicated Disposable Fixture
Construct an isolated filesystem hierarchy on the host:
```text
/tmp/gate5g-safety-fixture/
  ├── allowed_root/
  │     ├── unique_file.txt
  │     ├── group1_fileA.dat (duplicate)
  │     ├── group1_fileB.dat (duplicate)
  │     └── symlink_to_external -> ../sentinel_dir/external_file.txt
  ├── quarantine_root/
  └── sentinel_dir/
        └── external_file.txt (MUST REMAIN UNTOUCHED)
```

#### 5.7.2 Stage 1: Read-Only Safety Verification
- Start containers with safe default configuration:
  - `ALLOW_MUTATION=false`
  - `ALLOW_DELETE=false`
  - `PROTECT_LAST_FILE=true`
  - `DATA_MODE=ro`
- Execute filesystem scan, fclones duplicate detection, index creation, and plan preview.
- **Verification:** Assert that zero files within `allowed_root`, `quarantine_root`, or `sentinel_dir` have modified timestamps, modified sizes, or altered contents.

#### 5.7.3 Stage 2: Controlled Mutation Lifecycle Verification
- Restart containers with controlled mutation configuration:
  - `ALLOW_MUTATION=true`
  - `ALLOW_DELETE=false`
  - `PROTECT_LAST_FILE=true`
  - `DATA_MODE=rw`
- Execute full 5-stage lifecycle:
  1. **Preview**: Request deduplication preview. Assert zero disk mutation.
  2. **Draft Generation**: Generate explicit batch plan. Assert zero disk mutation.
  3. **Freeze**: Freeze batch plan. Verify exact file sizes, mtimes, and inode/fingerprint identities are locked in database.
  4. **Validate**: Perform preflight validation against unchanged disk state. Assert validation passes.
  5. **Execute**: Execute the validated plan.
- **Verification:**
  - One protected keep copy (`group1_fileA.dat`) remains in `allowed_root`.
  - Duplicate copy (`group1_fileB.dat`) is moved into `quarantine_root`.
  - No file is permanently deleted (unlink) because `ALLOW_DELETE=false`.
  - Quarantine location remains strictly confined within `quarantine_root`.

#### 5.7.4 Stage 3: Stale Preflight Protection
- Create a new frozen plan targeting `unique_file.txt`.
- Prior to plan execution, modify the physical file externally on disk (e.g. append bytes or change content).
- Trigger validation and execution.
- **Verification:** Plan validation must explicitly fail with a stale identity error; execution must refuse to touch the modified file.

#### 5.7.5 Stage 4: Boundary & Symlink Traversal Protection
- Verify that `sentinel_dir/external_file.txt` was never moved, modified, or quarantined.
- Verify that `symlink_to_external` was rejected or neutralized in accordance with Gate5-E symlink security rules.
- If quarantine restore functionality is exposed in the API, perform one restore operation and verify file contents are bit-for-bit identical to original state.

---

### 5.8 Phase G7 — Target 极空间 NAS Black-Box Validation

#### 5.8.1 Mandatory Target Environment Testing
Desktop/VM Linux amd64 Docker verification is necessary but **not sufficient** for final v0.3.5 release closure. Because the production target is 极空间 NAS, Gate5-G requires end-to-end execution on a real 极空间 NAS instance.

#### 5.8.2 Environmental Record
The verifier must record the target NAS hardware and software context:
- NAS Model (e.g., Z4Pro, Z423, etc.) and ZSpace OS firmware version.
- Host CPU architecture (must be x86_64).
- Docker Engine version running on the NAS.
- Volume filesystem type (e.g., ZFS, Btrfs, ext4) and mount parameters.
- Candidate Git commit SHA and Docker image tag/digest.

#### 5.8.3 Real NAS Validation Execution
Using a dedicated disposable test directory on the NAS (never touching user media or real storage pools):
1. Deploy API and Worker containers via Docker Compose / Komodo.
2. Verify API and Worker container startup and healthcheck status.
3. Authenticate and verify web UI / API accessibility.
4. Verify Worker reports online and healthy.
5. Execute scan and index operations across the mounted NAS test directory.
6. Verify `fclones` executes successfully against the NAS volume without permission or filesystem compatibility errors.
7. Verify Resource Policy settings can be read and updated by admin, and that active window governance does not create scheduled jobs.
8. Execute the synthetic filesystem safety test (Phase G6 suite) directly on the NAS test filesystem:
   - Preview -> Draft -> Freeze -> Validate -> Execute.
   - Confirm quarantine move works on NAS storage pool.
   - Confirm stale validation rejects modified files.
   - Confirm no path escape outside the allowed NAS test root.
9. Restart containers and verify persistent settings and SQLite database integrity on NAS storage.

---

### 5.9 Phase G8 — Final Evidence & Release Candidate Audit

#### 5.9.1 Unified Evidence Checklist
Gate5-G PASS requires that **all phases G0 through G7 have passed against the same immutable candidate**:
- [ ] G0 PASS: Release metadata consistent (version 0.3.5 across all components).
- [ ] G1 PASS: Full backend test suites (100% pass) and frontend typecheck/test/build (100% pass).
- [ ] G2 PASS: Clean Linux amd64 Docker build with verified internal binary and application dependencies.
- [ ] G3 PASS: API and Worker container smoke, single worker ownership, and crash-loop free operation.
- [ ] G4 PASS: Clean database initialization on fresh install and seamless additive upgrade from Gate5-E baseline.
- [ ] G5 PASS: SQLite `integrity_check` (ok) and `foreign_key_check` (0 errors).
- [ ] G6 PASS: Synthetic filesystem safety lifecycle (preview, draft, freeze, validate, execute, quarantine, stale protection).
- [ ] G7 PASS: Target 极空间 NAS end-to-end operational and safety black-box smoke.

#### 5.9.2 Unacceptable Evidence Practices
- Any skipped phase automatically results in `Gate5-G = NOT PASS`.
- "Not tested" must never be converted to or reported as "assumed pass".
- Tests performed on different commit SHAs cannot be combined or aggregated.

---

## 6. Failure Classification and Remediation Workflow

### 6.1 Severity Levels

| Severity Level | Definition | Impact on Gate5-G | Remediation Protocol |
| :--- | :--- | :--- | :--- |
| **BLOCKER** | Any defect involving data loss/corruption risk, mutation safety bypass, lease fencing failure, migration loss, SQLite corruption, inability to run on `linux/amd64`, container startup failure, inability to run on 极空间 NAS, or version metadata identifying wrong release. | **Gate5-G Candidate = FAIL** | Candidate rejected. Authorized hotfix required -> New candidate SHA -> Restart validation from Phase G0. |
| **BOUNDED RELEASE FIX** | Packaging omissions, compose file tag errors, healthcheck tuning, or minor deployment manifest discrepancies not affecting core safety or application code. | **Gate5-G Candidate = FAIL** (Pending fix) | Narrow hotfix authorized -> New candidate SHA -> Restart validation from Phase G0. |
| **NON-BLOCKING NOTE** | Cosmetic logging warnings, documentation typos, or third-party deprecation notices that do not affect data safety, correctness, recoverability, or deployment stability. | Permitted with explicit disclosure | Recorded in final walkthrough; does not invalidate candidate. |

---

## 7. Explicit Gate5-G Prohibitions & Anti-Scope

Gate5-G is strictly an audit and validation gate. The following activities are **explicitly forbidden**:
1. Introduction of new product features or user-facing business logic.
2. Implementation of a Task Scheduler, cron system, or automatic job generator.
3. Introduction of a second Worker process or distributed worker architecture.
4. Alterations to Task Engine state machines (`JobState`, lease recovery, heartbeat thresholds).
5. Modification of deduplication algorithms, compiler rules, or planning logic.
6. Changes to quarantine semantics or permanent file deletion logic.
7. Implementation of OS-level cgroups, hard IOPS limits, or thread-throttling redesigns.
8. User interface redesigns or frontend component refactoring.
9. Reopening, altering, or re-architecting any closed gate (Gate5-A through Gate5-F).
10. Unilateral creation or pushing of the Git release tag `v0.3.5`.
11. Commencing v0.3.6 roadmap tasks.

Any requirement or attempt to execute items in this list must immediately trigger:
```text
STOP
OUT OF GATE5-G SCOPE
```

---

## 8. Release Tagging & Publication Boundary

### 8.1 Post-Validation Authority
The creation of the final immutable Git release tag:
```text
v0.3.5
```
is **strictly prohibited** during the design and validation phases. 

### 8.2 Sequence of Authority
1. Gate5-G executable verification completes with 100% passing results across G0–G8.
2. An independent audit confirms candidate immutability and report completeness.
3. Gate5-G is formally declared `PASS / CLOSED`.
4. Milestone v0.3.5 is formally declared `PASS / CLOSED`.
5. **Only then** may the project owner authorize the tagging of commit `v0.3.5` and the publication of production Docker images to registry `kerwinjhc/nas-file-center:0.3.5`.
