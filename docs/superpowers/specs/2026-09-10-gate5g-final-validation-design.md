# NAS File Center v0.3.5 — Gate5-G Final Validation Design Specification

**Document Version:** 1.1.0 (Revision 1)
**Date:** 2026-09-10
**Status:** DESIGN SPECIFICATION REVISION 1 / ARCHITECTURE FREEZE PROPOSAL
**Implementation / Execution Status:** NOT AUTHORIZED
**Authoritative Baseline HEAD:** `cd49f6cbb244cd4e4ff4bbbd0e4608fdf752db12`
**Target Branch:** `v0.3.5-gate5c-hotfix4`

---

## 1. Context, Authority, and Objectives

### 1.1 Gate Hierarchy and Immutability of Prior Baselines
NAS File Center v0.3.5 development has formally passed and closed all preceding functional and structural gates:
```text
Gate5-A = PASS / CLOSED
Gate5-B = PASS / CLOSED
Gate5-C = PASS / CLOSED
Gate5-D = PASS / CLOSED
Gate5-E = PASS / CLOSED
Gate5-F = PASS / CLOSED

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
  + One Immutable Built Image Identity (Tag, Image ID & Archive Digest)
    + One Fixed Verification Matrix (Phases G0 through G7)
      = One Gate5-G Candidate Evaluation
```

### 2.2 Prohibited Identity Practices
Gate5-G explicitly prohibits the following practices as verification proof:
- "Mostly the same SHA" or testing across multiple cherry-picked commits.
- "Latest branch state" or floating `HEAD` references.
- "Whatever image is currently tagged `:latest`".
- Rebuilding the application image on the NAS or substituting another image built from the same SHA.
- Reusing an old local image built from an unverified or prior commit.

Every single verification artifact, test log, and status report must bind to:
1. Exact Git commit SHA (full 40-character hexadecimal string).
2. Exact source tree (clean working tree verified by `git status --short` and `git diff --check`).
3. Exact built Docker image tag, immutable Image ID, and image archive SHA256 digest.
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
| G2: Linux amd64 Docker Clean Build & Image Archive Inspection                 |
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
| G7: Target 极空间 NAS Isolated Black-Box Environment Smoke                    |
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

#### 5.1.2 Complete Release-Bearing Surface Inventory
Before executing expensive build and test phases, all release-bearing surfaces committed in the candidate must align to `0.3.5`:
1. `pyproject.toml` -> `[project].version == "0.3.5"`
2. `app/main.py` -> `FastAPI(..., version="0.3.5")`
3. `frontend/package.json` -> `"version": "0.3.5"`
4. `frontend/package-lock.json` -> top-level `"version": "0.3.5"` and `packages[""]["version"] == "0.3.5"`
5. `frontend/src/pages/Login/index.tsx` -> visible UI string containing `NAS File Center v0.3.5`
6. `frontend/src/components/Sidebar.tsx` -> visible UI string containing `v0.3.5`
7. `compose.yaml` -> default application image tag `nas-file-center:0.3.5`
8. `compose.komodo.yaml` -> production image reference `kerwinjhc/nas-file-center:0.3.5` (or an immutable `@sha256:...` image digest).

#### 5.1.3 Release-Version Contract Test
The repository maintains an automated version-consistency contract test:
```bash
pytest tests/test_release_version_consistency.py -v
```
- A future bounded G0 release-metadata hotfix must update `tests/test_release_version_consistency.py`'s expected release version to `0.3.5` in lockstep with the actual release surfaces.
- That future test change is permitted only under the separately authorized G0 release-metadata hotfix. Because it creates a new candidate Git commit SHA, full Gate5-G executable verification will restart from Phase G0.
- Do **not** make those modifications in this design checkpoint.

#### 5.1.4 Prohibition on `:latest` in Production Manifests
For immutable production deployments (including Komodo deployment), `:latest` is strictly rejected as the sole image identity. `compose.komodo.yaml` must bind explicitly to `kerwinjhc/nas-file-center:0.3.5` or an immutable `@sha256:...` digest. A convenience `:latest` tag alias may only be published post-release.

#### 5.1.5 Known Baseline Finding (Recorded as KNOWN G0 BLOCKING FINDING)
At the authoritative baseline HEAD (`cd49f6cbb244cd4e4ff4bbbd0e4608fdf752db12`), the repository exhibits the following known version discrepancies:
- `pyproject.toml`: `version = "0.3.3"`
- `app/main.py`: `FastAPI(..., version="0.3.3")`
- `frontend/package.json`: `"version": "0.3.3"`
- `frontend/package-lock.json`: `"version": "0.3.3"` (root and `packages[""]`)
- `frontend/src/pages/Login/index.tsx`: `NAS File Center v0.3.3`
- `frontend/src/components/Sidebar.tsx`: `v0.3.3`
- `compose.yaml`: `image: nas-file-center:0.3.2`
- `compose.komodo.yaml`: `image: kerwinjhc/nas-file-center:latest`

**Resolution Plan:**
- This discrepancy is formally recorded as `KNOWN G0 BLOCKING FINDING`.
- It must **not** be modified in this design checkpoint commit.
- During initial Gate5-G G0 execution, the current candidate will formally FAIL on Phase G0.
- A dedicated, bounded release-metadata hotfix will subsequently be authorized to align all metadata and `tests/test_release_version_consistency.py` to `0.3.5`, generating the true release-candidate SHA for full Gate5-G execution.
- G0 PASS requires all 8 surfaces to identify `0.3.5` and `pytest tests/test_release_version_consistency.py -v` to pass with exit code `0`.

---

### 5.2 Phase G1 — Source Regression & Frontend Verification

#### 5.2.1 Backend Test Suites
Executed in an environment meeting filesystem case-sensitivity requirements:
1. **Gate5-A ~ Gate5-F Focused Regression Command**:
   ```bash
   pytest \
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
2. **Task Engine, Worker, and Scanner Core Suites**:
   ```bash
   pytest \
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
3. **Planning & Execution Engine Suites**:
   ```bash
   pytest tests/test_planning.py tests/test_execution.py -v
   ```
4. **Full Backend Repository Suite**:
   ```bash
   pytest tests/
   ```

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

### 5.3 Phase G2 — Linux amd64 Docker Clean Build & Image Archive Inspection

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

#### 5.3.4 G2 -> G7 Image-Byte Transport Protocol
To enforce candidate immutability across disparate environments:
1. G2 builds the candidate image **exactly once**.
2. Record local image tag and full `G2_IMAGE_ID` (SHA256).
3. Save the exact image to a tar archive:
   ```bash
   docker save nas-file-center:0.3.5-gate5g-<shortSHA> -o /tmp/nas-file-center-0.3.5-gate5g-<shortSHA>.tar
   ```
4. Compute the SHA256 checksum of the archive:
   ```bash
   sha256sum /tmp/nas-file-center-0.3.5-gate5g-<shortSHA>.tar
   ```
   Record as `G2_IMAGE_ARCHIVE_SHA256`.
5. Transfer the exact `.tar` archive to the target 极空间 NAS.

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
  │     ├── group1_fileA.dat (duplicate group 1)
  │     ├── group1_fileB.dat (duplicate group 1)
  │     ├── stale_group_fileA.dat (duplicate group 2 for stale testing)
  │     ├── stale_group_fileB.dat (duplicate group 2 for stale testing)
  │     ├── unique_file.txt (single unique file)
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

#### 5.7.3 Stage 2: Controlled Mutation Lifecycle Verification (Plan-Derived Assertions)
- Restart containers with controlled mutation configuration:
  - `ALLOW_MUTATION=true`
  - `ALLOW_DELETE=false`
  - `PROTECT_LAST_FILE=true`
  - `DATA_MODE=rw`
- Execute full 5-stage lifecycle targeting `group1`:
  1. **Preview**: Request deduplication preview. Assert zero disk mutation.
  2. **Draft Generation**: Generate explicit batch plan. Assert zero disk mutation.
  3. **Freeze**: Freeze batch plan. Verify exact file sizes, mtimes, and inode/fingerprint identities are locked in database.
  4. **Inspect Frozen Plan**:
     - Extract `actual keep_path` determined by the scorer/policy.
     - Extract `actual planned mutation/quarantine source` determined by the plan.
     - Extract `planned quarantine target path`.
     - Record these three paths explicitly as evidence.
  5. **Validate**: Perform preflight validation against unchanged disk state. Assert validation passes.
  6. **Execute**: Execute the validated plan.
- **Verification (Dynamic, Plan-Derived):**
  - The plan's `actual keep_path` remains intact in `allowed_root`.
  - The plan's `actual planned mutation source` is successfully moved into `quarantine_root`.
  - At least one protected member remains in `allowed_root`.
  - No unauthorized file or non-duplicate member is moved.
  - No file is permanently deleted (unlink) because `ALLOW_DELETE=false`.
  - Quarantine location remains strictly confined within `quarantine_root`.

#### 5.7.4 Stage 3: Real Dedupe Stale Preflight Protection
Test stale rejection using a real duplicate candidate group (`stale_group`):
1. Execute scan across `stale_group_fileA.dat` and `stale_group_fileB.dat`.
2. Generate deduplication Preview.
3. Generate Explicit Batch Plan Draft.
4. Freeze the plan.
5. Inspect the frozen plan and determine the exact source path scheduled for quarantine/mutation (`stale_target_source`).
6. **Simulate Stale State**: Externally modify `stale_target_source` on disk (e.g. append bytes or change content) after Freeze.
7. Trigger Plan Validation via normal API/lifecycle.
8. **Verification:**
   - Preflight validation must explicitly fail, reporting stale identity (mtime/size/fingerprint mismatch).
   - Subsequent execution attempt via API must be strictly refused.
   - The modified file `stale_target_source` must not be moved, modified, or quarantined.
   - All other fixture files remain completely untouched.
   - No mock rows or synthetic DB updates are used; the lifecycle must run through genuine service APIs.

#### 5.7.5 Stage 4: Boundary & Symlink Traversal Protection
- Verify that `sentinel_dir/external_file.txt` was never moved, modified, or quarantined.
- Verify that `symlink_to_external` was rejected or neutralized in accordance with Gate5-E symlink security rules.
- If quarantine restore functionality is exposed in the API, perform one restore operation and verify file contents are bit-for-bit identical to original state.

---

### 5.8 Phase G7 — Target 极空间 NAS Isolated Black-Box Validation

#### 5.8.1 Mandatory Target Environment Testing
Desktop/VM Linux amd64 Docker verification is necessary but **not sufficient** for final v0.3.5 release closure. Because the production target is 极空间 NAS, Gate5-G requires end-to-end execution on a real 极空间 NAS instance.

#### 5.8.2 Strict Mount Isolation from Committed Manifests
The committed `compose.komodo.yaml` contains production NAS host paths (e.g. `/tmp/zfsv3/nvme13/15246330601/data/NasFileCenter` and `/tmp/zfsv3/sata11/15246330601/data`).
- **Strict Prohibition:** G6/G7 verification must **never** execute mutation scenarios using the committed `compose.komodo.yaml` host mount paths.
- The committed `compose.komodo.yaml` must **not** be edited in place merely to run validation.
- NAS verification must execute using one of the following isolated mechanisms:
  1. A verifier-owned transient Docker Compose file located outside the Git worktree.
  2. A verifier-owned transient Compose override file located outside the Git worktree.
  3. Direct `docker run` commands issued by the verifier.
- All mechanisms must bind strictly to:
  - Exact G2-loaded image (`nas-file-center:0.3.5-gate5g-<shortSHA>`).
  - Dedicated disposable host `CONFIG` directory on the NAS.
  - Dedicated disposable host `DATA` directory containing the Phase G6 safety fixture.
  - Dedicated quarantine directory within the disposable fixture.
  - Zero access to production media, storage pools, or production `app.db`.

#### 5.8.3 Pre-Mutation Host Path Assertion
Before enabling read-write mode (`DATA_MODE=rw`, `ALLOW_MUTATION=true`), the verifier must formally assert:
```text
real production DATA mount path != Gate5-G disposable test DATA path
real production CONFIG mount path != Gate5-G disposable CONFIG path
```
If this absolute path isolation cannot be verified:
```text
STOP
G7 = FAIL / NOT EXECUTED
```
Testing directly or "carefully" against production data is strictly prohibited.

#### 5.8.4 Image Byte Loading on the NAS
1. Prior to container execution, verify the SHA256 checksum of the transferred `.tar` archive matches `G2_IMAGE_ARCHIVE_SHA256`.
2. Load image into NAS Docker daemon:
   ```bash
   docker load -i /path/to/nas-file-center-0.3.5-gate5g-<shortSHA>.tar
   ```
3. Inspect loaded image:
   - `G7_LOADED_IMAGE_ID` must equal `G2_IMAGE_ID`.
   - Target architecture must be `linux/amd64`.
4. The NAS must **not** rebuild the image, run `docker compose build`, pull floating tags, or substitute images. A local verifier tag may be attached to the loaded image ID for execution.

#### 5.8.5 Real NAS Execution Protocol
1. Record environmental context:
   - NAS Model (e.g., Z4Pro, Z423) and ZSpace OS firmware version.
   - Host CPU architecture (must be x86_64).
   - Docker Engine version running on the NAS.
   - Filesystem type of the disposable mount (e.g., ZFS, Btrfs, ext4).
2. Deploy API and Worker containers using the isolated configuration.
3. Read-only verification stage:
   - `/data` mounted `:ro`, `ALLOW_MUTATION=false`, `ALLOW_DELETE=false`.
   - Verify API health (`GET /health` -> 200) and Worker online heartbeat.
   - Execute indexing and verify `fclones` runs successfully on NAS storage volume.
   - Verify Resource Policy read/write by admin; confirm active window does not spawn scheduler jobs.
4. Mutation verification stage:
   - Mount isolated fixture `:rw`, `ALLOW_MUTATION=true`, `ALLOW_DELETE=false`, `PROTECT_LAST_FILE=true`.
   - Execute full Phase G6 synthetic filesystem lifecycle on the NAS volume:
     - Preview -> Draft -> Freeze -> Validate -> Execute.
     - Verify plan-derived keep and quarantine behavior.
     - Verify stale modification rejection.
     - Verify zero path traversal outside disposable root.
5. Graceful restart and SQLite database integrity verification on NAS storage.

---

### 5.9 Phase G8 — Final Evidence & Release Candidate Audit

#### 5.9.1 Unified Evidence Checklist
Gate5-G PASS requires that **all phases G0 through G7 have passed against the same immutable candidate**:
- [ ] G0 PASS: Release metadata complete inventory consistent (`0.3.5` across all 8 surfaces) and `test_release_version_consistency.py` passes.
- [ ] G1 PASS: Full backend test suites (100% pass) and frontend typecheck/test/build (100% pass).
- [ ] G2 PASS: Clean Linux amd64 Docker build; verified internal dependencies; exact image archive saved and hashed.
- [ ] G3 PASS: API and Worker container smoke, single worker ownership, and crash-loop free operation.
- [ ] G4 PASS: Clean database initialization on fresh install and seamless additive upgrade from Gate5-E baseline.
- [ ] G5 PASS: SQLite `integrity_check` (ok) and `foreign_key_check` (0 errors).
- [ ] G6 PASS: Synthetic filesystem safety lifecycle (preview, draft, freeze, validate, execute, plan-derived quarantine, real dedupe stale protection).
- [ ] G7 PASS: Target 极空间 NAS end-to-end operational and safety black-box smoke on isolated disposable mounts with verified image byte transfer.

#### 5.9.2 Mandatory Image Byte Evidence Fields
The final report in Phase G8 must record:
- `G2_IMAGE_ID`
- `G2_IMAGE_TAG`
- `G2_IMAGE_ARCHIVE_SHA256`
- `G7_LOADED_IMAGE_ID`
- `G7_IMAGE_ARCHIVE_SHA256`
- `identity_match = YES`

#### 5.9.3 Unacceptable Evidence Practices
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
