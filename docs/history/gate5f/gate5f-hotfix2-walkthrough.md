# Gate5-F Hotfix2: Bounded Implementation & Acceptance Completion Walkthrough

**Date:** 2026-09-10  
**Target Branch:** `v0.3.5-gate5c-hotfix4`  
**BASE_HEAD:** `53e35d62cb3d805d16e9c2e900487082a82adf7b`  
**Status:** IMPLEMENTATION COMPLETE / READY FOR INDEPENDENT REVIEW  

---

## 0. Hotfix1 SHA Errata / 权威来源勘误

In previous documentation, the authoritative Hotfix1 commits are confirmed as follows:
- Test commit: `d5006d8adae371602495ed1bf32019cf673657de` (`test(gate5f): reproduce disabled active window validation bug`)
- Fix commit: `f870e2ebf1c29a47bf35e85142dfd0f12a9ba990` (`fix(gate5f): honor disabled active window semantics`)
- Walkthrough commit: `53e35d62cb3d805d16e9c2e900487082a82adf7b` (`docs(gate5f): record hotfix1 verification`)

The Hotfix1 semantic fix (`active_window_enabled = false` allows `active_window_start == active_window_end`) is completely preserved and untouched in `app/resource_control.py`.

---

## 1. Production Blocker Resolution (Architecture Freeze §21 Observability)

### Finding
Per Architecture Freeze §21 and independent review, when `ResourcePolicy` is missing, validation fails, timezone resolution fails, or thread limits are corrupted, worker task claim (`claim_next_job()`) must not silently swallow errors while failing closed. It must log clear WARNING messages outside the write transaction (`BEGIN IMMEDIATE`) indicating:
1. `ResourcePolicy invalid or unavailable`
2. `resource-controlled jobs held fail-closed`

### Root Cause & Implementation
Previously, in `app/tasks/recovery.py`, Phase A caught exceptions or noted a missing row without emitting logs.
In this hotfix:
- Added module-level logger: `logger = logging.getLogger(__name__)`.
- In `claim_next_job()`:
  - Tracked `policy_error_reason: str | None = None` during Phase A.
  - Set `policy_error_reason = "ResourcePolicy singleton row missing"` when the singleton row does not exist.
  - Captured exception messages (`policy_error_reason = str(exc)`) when snapshot construction, validation, or timezone resolution fails.
  - After Phase A read session exits and **strictly before** Phase B `BEGIN IMMEDIATE` write transaction:
    ```python
    if not policy_valid:
        logger.warning(
            "ResourcePolicy invalid or unavailable (%s); resource-controlled jobs held fail-closed",
            policy_error_reason or "unknown error",
        )
    ```
  - Also added warning log at retry exhaustion fallback if policy remains unstable after maximum attempts.

---

## 2. Acceptance Lock Tests

Four targeted acceptance lock tests were added to prevent regression on core architectural requirements:

1. **Job Priority Scheduling Semantics** (`tests/test_gate5f_resource_claim.py`):
   - `test_claim_job_priority_background_prefers_mutation_over_resource`: When `job_priority="background"`, queued mutation jobs (e.g. `batch-plan-execute`) are claimed first, leaving queued resource-controlled jobs (`fclones-scan`) in `queued` state.
   - `test_claim_job_priority_normal_uses_fifo`: When `job_priority="normal"`, tasks are claimed strictly in FIFO order by `id`.

2. **Active Window Is Not A Scheduler** (`tests/test_gate5f_resource_claim.py`):
   - `test_claim_with_configured_active_window_does_not_create_scheduled_jobs`: Verifies that configuring an active window and calling `claim_next_job()` with 0 queued jobs never automatically spawns or enqueues tasks (work job count remains 0).

3. **Admin Settings RBAC Authorization Matrix** (`tests/test_gate5f_resource_policy_api.py`):
   - `test_put_resource_policy_authorization_matrix`:
     - Unauthenticated PUT -> `401 Unauthorized` (database unchanged).
     - Non-admin authenticated user PUT -> `403 Forbidden` (database unchanged).
     - Admin authenticated user PUT -> `200 OK` (database policy updated and revision incremented).

4. **Fclones Handler Effective Thread Cap Clamping** (`tests/test_gate5f_fclones_resources.py`):
   - `test_fclones_scan_threads_effective_cap_clamping`:
     - Case A: Effective global cap = 2, job requested threads = 32 -> clamped to `threads="2"`.
     - Case B: Effective global cap = 2, job requested threads = 1 -> clamped to `threads="1"`.

---

## 3. Strict TDD Evidence

### OBSERVABILITY_RED Phase
Prior to modifying `app/tasks/recovery.py`, `tests/test_gate5f_fail_closed.py` asserted that `caplog` captured warning logs on fail-closed execution.
Result: **3 FAILURES** (all asserting that fail-closed warning log was missing).

### OBSERVABILITY_GREEN Phase
Following the implementation in `app/tasks/recovery.py`:
`CONFIG_DIR=/tmp/test_config DATA_MOUNT=/tmp/test_data .venv/bin/pytest tests/test_gate5f_fail_closed.py -v`
```text
tests/test_gate5f_fail_closed.py::test_corrupted_active_window_holds_resource_job_but_allows_mutation PASSED [ 33%]
tests/test_gate5f_fail_closed.py::test_missing_singleton_holds_resource_job_but_allows_mutation PASSED [ 66%]
tests/test_gate5f_fail_closed.py::test_missing_singleton_with_only_resource_job_returns_none_and_logs PASSED [100%]
============================== 3 passed in 0.33s ===============================
```

---

## 4. Verification Results

### 4.1 Gate5-F Test Suite
`CONFIG_DIR=/tmp/test_config DATA_MOUNT=/tmp/test_data .venv/bin/pytest tests/test_gate5f_*.py -v`
- **38 passed**, 2 warnings in 1.47s (100%)

### 4.2 Task Engine & Worker Regression Suite
`CONFIG_DIR=/tmp/test_config DATA_MOUNT=/tmp/test_data .venv/bin/pytest tests/test_task_*.py tests/test_worker_recovery_and_claim.py tests/test_fclones.py tests/test_indexing.py tests/test_gate5f_*.py -v`
- **84 passed**, 4 warnings in 4.20s (100%)

### 4.3 Closed Gate Regression Suite (Gate5-D & Gate5-E)
Tested on dedicated case-sensitive APFS volume (`/Volumes/CaseSensitiveTest`):
`CONFIG_DIR=/Volumes/CaseSensitiveTest/tmp DATA_MOUNT=/Volumes/CaseSensitiveTest/tmp .venv/bin/pytest tests/test_gate5d_*.py tests/test_gate5e_*.py --basetemp=/Volumes/CaseSensitiveTest/tmp/pytest -v`
- **496 passed**, 2 warnings in 29.15s (100%)

### 4.4 Full Backend Test Suite
`CONFIG_DIR=/Volumes/CaseSensitiveTest/tmp DATA_MOUNT=/Volumes/CaseSensitiveTest/tmp .venv/bin/pytest tests/ --basetemp=/Volumes/CaseSensitiveTest/tmp/pytest`
- **1149 passed**, 19 warnings in 99.63s (100%)

### 4.5 Frontend Verification
`cd frontend && npm run typecheck && npm run build`
- `tsc --noEmit`: 0 errors
- `vite build`: success (3763 modules transformed, bundles emitted)

### 4.6 Workspace & Whitespace Hygiene
- `git diff --check`: 0 errors
- `git status --short`: clean

---

## 5. Scope Audit & Commit Summary

### Commits on `v0.3.5-gate5c-hotfix4`
1. `9eac64f1ab2d4c78057dc69516a0d9c0be22717d` (`test(gate5f): add observability and acceptance lock tests for hotfix2`)
2. `5b2ab9d91a9449d83070faf3bbe38cc9f5fe76dd` (`fix(gate5f): emit observable logs on fail closed resource policy`)

### Files Modified
- Production files (1):
  - `app/tasks/recovery.py`
- Test files (4):
  - `tests/test_gate5f_fail_closed.py`
  - `tests/test_gate5f_fclones_resources.py`
  - `tests/test_gate5f_resource_claim.py`
  - `tests/test_gate5f_resource_policy_api.py`
- Documentation files (1):
  - `docs/history/gate5f/gate5f-hotfix2-walkthrough.md`

### Invariants & Boundaries
- `app/resource_control.py`: Unmodified, preserving Hotfix1 resolution.
- Closed gates Gate5-A ~ Gate5-E: Completely untouched and passing.
- Gate5-G: Strictly FORBIDDEN.
- No rebase, reset, or force push.
