# Gate5-F Hotfix1: Disabled Active-Window Semantic Compliance Walkthrough

**Date:** 2026-09-10  
**Target Branch:** `v0.3.5-gate5c-hotfix4`  
**BASE_HEAD:** `f0ba119eebb27a49ba733629e4f01e50044cdb73`  
**Status:** IMPLEMENTATION COMPLETE / READY FOR INDEPENDENT REVIEW  

---

## 1. Independent Review Finding & Blocker

Independent review identified an Architecture Freeze violation in `app/resource_control.py`:
When `active_window_enabled = false`, the validator `validate_resource_policy_snapshot()` incorrectly enforced the semantic constraint `active_window_start != active_window_end`.

According to the closed Architecture Freeze:
- `start == end` is invalid **only while active_window is enabled**.
- When `active_window` is disabled, `start/end/timezone` do not restrict execution.
- Persisting equal start/end values when disabled is completely harmless and valid, provided individual non-null values are syntactically valid (HH:MM format).
- Enforcing `start != end` when disabled caused harmless persisted configurations to be treated as corrupt, triggering fail-closed logic and erroneously blocking queued resource-controlled tasks.

---

## 2. Root Cause

In `app/resource_control.py` (`validate_resource_policy_snapshot()`):
```python
    else:
        if snapshot.active_window_start is not None:
            _parse_time(snapshot.active_window_start)
        if snapshot.active_window_end is not None:
            _parse_time(snapshot.active_window_end)
        if snapshot.active_window_start is not None and snapshot.active_window_end is not None:
            if _parse_time(snapshot.active_window_start) == _parse_time(snapshot.active_window_end):
                raise ResourcePolicyValidationError("active_window_start and active_window_end cannot be equal")
```
The disabled branch (`else:`) applied the equality rejection constraint intended strictly for enabled active windows.

---

## 3. Strict TDD Implementation

### 3.1 RED Phase
Reproduced the issue with three failing tests across all affected architectural layers:
1. Pure evaluator test: `test_disabled_active_window_allows_equal_valid_times` in `tests/test_gate5f_resource_policy.py`.
2. Worker claim integration test: `test_claim_with_disabled_window_and_equal_times_admits_resource_job` in `tests/test_gate5f_resource_claim.py`.
3. Admin API PUT test: `test_put_resource_policy_disabled_window_allows_equal_times` in `tests/test_gate5f_resource_policy_api.py`.

Also verified that syntactic validation of malformed times (e.g. `"99:99"`) remains strictly enforced in `test_disabled_active_window_still_rejects_malformed_non_null_time`.

**RED execution output:**
```text
FAILED tests/test_gate5f_resource_policy.py::test_disabled_active_window_allows_equal_valid_times
       - ResourcePolicyValidationError: active_window_start and active_window_end cannot be equal
FAILED tests/test_gate5f_resource_claim.py::test_claim_with_disabled_window_and_equal_times_admits_resource_job
       - assert None == 801
FAILED tests/test_gate5f_resource_policy_api.py::test_put_resource_policy_disabled_window_allows_equal_times
       - assert 422 == 200
```
Committed as `d5006d8 test(gate5f): reproduce disabled active window validation bug`.

### 3.2 GREEN Phase
Removed lines 106-108 in `app/resource_control.py`, allowing `start == end` when `active_window_enabled = false` while maintaining syntactic parsing of non-null times and timezone validation.

**GREEN execution output:**
```text
tests/test_gate5f_resource_policy.py ...........                         [ 50%]
tests/test_gate5f_resource_claim.py .......                              [ 81%]
tests/test_gate5f_resource_policy_api.py ....                            [100%]
======================== 22 passed, 2 warnings in 1.18s ========================
```
Committed as `f870e2e fix(gate5f): honor disabled active window semantics`.

---

## 4. Verification Results

### 4.1 Gate5-F Regression
`pytest tests/test_gate5f_*.py -v`:
- **32 passed**, 2 warnings in 1.19s (100%)

### 4.2 Task Engine & Worker Regression
`pytest tests/test_worker_recovery_and_claim.py tests/test_task_state_machine.py tests/test_task_api.py tests/test_task_checkpoint.py tests/test_task_pause_resume_e2e.py tests/test_gate2_hotfix1_worker_fencing.py tests/test_fclones.py tests/test_scan_jobs.py tests/test_indexing.py tests/test_index_root_lifecycle.py tests/test_index_root_progress_regression.py -v`:
- **63 passed**, 9 warnings in 6.07s (100%)

### 4.3 Closed Gate Regression
`pytest tests/test_gate5d_*.py tests/test_gate5e_*.py tests/test_planning.py tests/test_execution.py -v`:
- **510 passed**, 2 warnings in 28.26s (100%)

### 4.4 Full Backend Test Suite
`pytest tests/`:
- **1143 passed**, 19 warnings in 97.57s (100%)

### 4.5 Frontend Typecheck & Build
- `cd frontend && npm run typecheck && npm run build`:
  - `tsc --noEmit`: 0 errors
  - `vite build`: success

### 4.6 Workspace Integrity
- `git diff --check`: clean (0 whitespace/syntax issues)
- `git status --short`: clean

---

## 5. Scope Audit & Invariants

- Modified files strictly restricted to:
  - `app/resource_control.py` (3 lines removed)
  - `tests/test_gate5f_resource_policy.py`
  - `tests/test_gate5f_resource_claim.py`
  - `tests/test_gate5f_resource_policy_api.py`
  - `docs/history/gate5f/gate5f-hotfix1-walkthrough.md`
- No changes to `app/tasks/handlers.py`, `app/tasks/recovery.py` production logic, `app/models.py`, `app/db.py`, or `frontend/**`.
- Closed gates (5A~5E) completely untouched and preserved.
- Gate5-G remains strictly FORBIDDEN.
- No rebase, reset, or force push.
