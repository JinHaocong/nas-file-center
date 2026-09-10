# NAS File Center v0.3.5 — Gate5-F Implementation Plan Independent Review

## 1. Statement of Authority & Provenance

This document records findings supplied by an external independent reviewer.
The implementation agent is transcribing and addressing those findings and
does not claim to have independently reviewed its own plan.

- **Reviewed Plan Commit:** `7b90f0ba4e60bb4b490d28cc429784252d5b55d9`
- **Branch:** `v0.3.5-gate5c-hotfix4`
- **Target Component:** Gate5-F Resource Control Implementation Plan
- **Status / Verdict:**
  ```text
  Gate5-F Implementation Plan = CHANGES REQUIRED
  Gate5-F Architecture Freeze = remains APPROVED / CLOSED
  Gate5-F Implementation = NOT AUTHORIZED pending plan re-review
  Gate5-G = FORBIDDEN
  v0.3.5 = NOT CLOSED
  ```

---

## 2. Review Findings & Required Fixes

### Finding 1 (FIX 1) — Canonical Profile Vocabulary Mismatch
- **Severity:** HIGH
- **Issue:** The Plan used `normal | limited | pause` for effective profile. The authoritative Architecture Freeze explicitly specifies canonical profile as `full | limited | pause`.
- **Resolution:** Replaced all occurrences of `profile: normal` with `profile: full` across Python types, evaluators, API responses, and TypeScript definitions. Kept `io_limit = 'normal'` intact.

### Finding 2 (FIX 2) — Placeholder Test Body in Task 7
- **Severity:** HIGH
- **Issue:** Task 7 running-job test contained a `pass` placeholder in the test body while claiming "Expected PASS".
- **Resolution:** Replaced with a concrete, deterministic test design with full setup, transition simulation, and assertions proving running jobs are neither killed nor fake-paused when window transitions to outside/pause.

### Finding 3 (FIX 3) — Nonexistent JobContext Logging Interface
- **Severity:** MEDIUM
- **Issue:** Plan referenced `context.log_event(...)` which does not exist in the codebase.
- **Resolution:** Aligned with actual `JobContext.log(event_type, message, level='info', context=None)` signature across all plan examples and handlers.

### Finding 4 (FIX 4) — Nonexistent index-root Test Seam
- **Severity:** MEDIUM
- **Issue:** Plan mocked `app.tasks.handlers.scan_and_index_root`, which does not exist. The actual call chain invokes `FileCenterService.reindex_root(...)`.
- **Resolution:** Updated Task 6 test design to mock `FileCenterService.reindex_root` directly, verifying single-threaded serial execution.

### Finding 5 (FIX 5) — Frontend TypeScript Syntax and API Client Alignment
- **Severity:** MEDIUM
- **Issue:** Frontend interface examples contained Python types like `: int`, and API client examples used Axios-style `(await client.get(...)).data`.
- **Resolution:** Converted to standard TypeScript `: number` and aligned API calls with `api.get<T>(...)` and `api.put<T>(...)` from `./client`.

### Finding 6 (FIX 6) — API Auth Tests Must Use Session Auth
- **Severity:** HIGH
- **Issue:** Plan assumed `Authorization: Bearer ...` and mock bearer tokens, whereas the repository uses session cookie authentication and Origin/CSRF header checks.
- **Resolution:** Refactored all API test designs to use `client.post('/api/auth/login')` session cookies and `Origin` headers.

### Finding 7 (FIX 7) — Nonexistent Regression Test Filenames
- **Severity:** HIGH
- **Issue:** Task 10 listed nonexistent filenames (`test_task_service.py`, `test_task_handlers.py`, `test_worker_lease.py`, `test_worker_recovery.py`).
- **Resolution:** Discovered actual existing test suites and froze concrete filenames into Task 10 (`test_worker_recovery_and_claim.py`, `test_task_state_machine.py`, `test_task_api.py`, `test_task_checkpoint.py`, `test_fclones.py`, `test_indexing.py`, `test_index_root_lifecycle.py`, etc.).

### Finding 8 (FIX 8) — Deterministic Claim-Time Tests
- **Severity:** HIGH
- **Issue:** Plan used wall-clock dependent time ranges (`01:00-02:00 UTC`) without frozen time mocking.
- **Resolution:** Standardized on deterministic frozen UTC timestamps (`fixed_now = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)`) applied consistently to both lease acquisition and claim evaluation.

### Finding 9 (FIX 9) — ZoneInfo File I/O Under BEGIN IMMEDIATE
- **Severity:** HIGH
- **Issue:** Task 3 update policy executed `ZoneInfo()` resolution inside `BEGIN IMMEDIATE`, violating SQLite short-transaction requirements.
- **Resolution:** Implemented two-phase pattern for PUT: Phase A (outside tx) validates payload and pre-resolves/caches `ZoneInfo`; Phase B (short `BEGIN IMMEDIATE`) applies normalized data and increments revision.

### Finding 10 (FIX 10) — Clarify Claim-to-Subprocess Race Condition
- **Severity:** HIGH
- **Issue:** Ambiguity on whether a job claimed `RUNNING` should be paused if active window transitions to pause before external subprocess starts.
- **Resolution:** Clarified that a claimed `RUNNING` job continues under latest captured bounded resources; only corrupted/unresolvable policy aborts external subprocess execution with fail-closed error.

---

## 3. Plan Revision Directives

1. Modify `docs/superpowers/plans/2026-09-10-gate5f-resource-control-implementation-plan.md` incorporating all 10 fixes.
2. Ensure 0 production, 0 test, 0 frontend, and 0 database code modifications in this turn.
3. Commit both documents and push to `origin/v0.3.5-gate5c-hotfix4`.
