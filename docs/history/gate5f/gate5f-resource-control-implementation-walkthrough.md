# Gate5-F: Resource Control Implementation Walkthrough & Verification

**Date:** 2026-09-10  
**Target Branch:** `v0.3.5-gate5c-hotfix4`  
**Authorized Baseline HEAD:** `c1500fad05731bf87d4723506ad07c5b262e3c75`  
**Status:** IMPLEMENTATION COMPLETE / READY FOR INDEPENDENT REVIEW  

---

## 1. Executive Summary

Gate5-F successfully implemented application-level resource control for NAS workloads strictly following the frozen architecture (`docs/history/gate5f/gate5f-architecture-freeze.md`) and implementation plan (`docs/superpowers/plans/2026-09-10-gate5f-resource-control-implementation-plan.md`).

All tasks followed the strict TDD workflow:
1. Pure evaluator and snapshot validation (`app/resource_control.py`).
2. Database persistence singleton table (`resource_policy`) with check constraints and migration seeding (`app/models.py`, `app/db.py`).
3. Two-phase service update method and admin settings API (`app/service.py`, `app/api/router.py`).
4. Two-phase worker claim admission with atomic lease assertion, fresh claim time, full 10-field policy fingerprint matching, and graceful non-resource job fallback (`app/tasks/recovery.py`).
5. Thread-bounded fclones execution and diagnostic task event logging (`app/tasks/handlers.py`, `app/scanners/fclones.py`).
6. Preservation of single-threaded serial execution for root indexing (`app/tasks/handlers.py`).
7. Non-resumable running job window transition semantics (`tests/test_gate5f_running_job_semantics.py`).
8. Administrative web settings interface with real-time profile visualization and explicit concurrency notices (`frontend/`).
9. Fail-closed safety for missing or corrupted policy rows (`app/tasks/recovery.py`, `tests/test_gate5f_fail_closed.py`).
10. Complete regression verification across all closed gates (5A~5E) and the entire 1139-test backend test suite, plus clean frontend build.

---

## 2. Commit Log

The following commits were created on `v0.3.5-gate5c-hotfix4`:

- `87b1a16` feat(gate5f): add resource policy evaluator
- `6f7ed1a` feat(gate5f): add resource policy persistence
- `1fb6bb4` refactor(gate5f): use direct ResourcePolicy import in tests
- `7076243` feat(gate5f): expose admin resource policy api
- `13e3ed5` feat(gate5f): add resource-aware task admission
- `ff218b2` feat(gate5f): enforce bounded fclones resources
- `63bce75` test(gate5f): lock index resource admission semantics
- `1bc6b57` test(gate5f): preserve non-resumable running jobs
- `ca12d85` feat(gate5f): add resource control settings ui
- `59bb8be` fix(gate5f): fail closed without blocking mutation jobs

---

## 3. Detailed Component Verification

### Task 1: Database Persistence & Singleton
- Added `ResourcePolicy` table to `app/models.py` with singleton check `id == 1`, thread bounds `1..32`, and strict enum constraints.
- Seeded initial row (`id=1`, `revision=1`) in `app/db.py`.
- Verified via `tests/test_gate5f_migration.py` (3 passed).

### Task 2: Pure Policy Evaluator & Fingerprinting
- Implemented `ResourcePolicySnapshot`, `EffectiveResourcePolicy`, `validate_resource_policy_snapshot`, `evaluate_resource_policy`, `resource_policy_row_fingerprint` (10-tuple), `compose_fclones_thread_cap`, `is_resource_controlled_job`.
- Zero file I/O inside evaluation; cached timezone resolution.
- Verified via `tests/test_gate5f_resource_policy.py` (9 passed).

### Task 3: Backend Admin API
- Added `GET /api/settings/resource-policy` and `PUT /api/settings/resource-policy`.
- Two-phase write: Phase A timezone and semantic validation outside write lock; Phase B short SQLite `BEGIN IMMEDIATE` write transaction.
- 401 unauthenticated, 403 non-admin, 422 strict validation with zero state drift.
- Verified via `tests/test_gate5f_resource_policy_api.py` (3 passed).

### Task 4: Resource-Aware Worker Claim Admission
- Implemented two-phase admission in `claim_next_job()`:
  - Phase A: snapshot read, timezone pre-resolution, full 10-field fingerprint capture.
  - Phase B: `BEGIN IMMEDIATE`, fresh `claim_now = utcnow()`, authoritative worker lease assertion, full fingerprint recheck.
  - On fingerprint drift: rollback and retry up to 3 times.
  - On retry exhaustion: fallback to claiming non-resource jobs only.
- Verified via `tests/test_gate5f_resource_claim.py` (6 passed).

### Task 5: fclones Resource Bounds & Subprocess Isolation
- In `FclonesScanHandler`, load policy, evaluate thread cap, compose effective threads with settings and payload overrides, record diagnostic `resource_policy_applied` event via `context.log()`, and pass bounded `--threads` to `build_group_command()`.
- Verified via `tests/test_gate5f_fclones_resources.py` (2 passed).

### Task 6: Index-Root Resource Control Semantics
- In `IndexRootHandler`, record diagnostic `resource_policy_applied` event with `execution_concurrency: 1`. Preserved strict serial single-threaded execution.
- Verified via `tests/test_gate5f_index_resources.py` (1 passed).

### Task 7: Running-Job Window Transition Semantics
- Verified that non-resumable running jobs (`index-root`, `fclones-scan`) are never killed or fake-paused when policy transitions across window boundaries.
- Verified via `tests/test_gate5f_running_job_semantics.py` (2 passed).

### Task 8: Frontend Resource Control Settings UI
- Added TypeScript types, API client, validation helpers, and Admin Settings card with soft concurrency notices.
- Verified via `tsc --noEmit` and `vite build` (0 errors, clean distribution bundle).

### Task 9: Failure & Corruption Safety
- Ensured fail-closed behavior when singleton is missing or corrupted: resource jobs remain queued without crashing or blocking mutation jobs.
- Verified via `tests/test_gate5f_fail_closed.py` (2 passed).

---

## 4. Full Regression Verification Summary

```text
============================= test session starts ==============================
tests/test_gate5f_*.py:                     28 passed (100%)
tests/test_worker_recovery_and_claim.py:    20 passed (100%)
tests/test_fclones.py & index suites:       43 passed (100%)
Closed Gate 5A~5E suites:                  572 passed (100%)
Full repository pytest suite:             1139 passed (100%)
Frontend typecheck & build:                  0 errors (100%)
Working tree state:                              clean
```

---

## 5. Invariant & Safety Checklist

- [x] Closed Gates 5A, 5B, 5C, 5D, 5E untouched and preserved.
- [x] No scheduler or cron engine introduced.
- [x] No automatic time-based job creation.
- [x] No second worker or parallel WorkJob execution introduced.
- [x] No modifications to mutation, quarantine, or restore invariants.
- [x] No modification to Plan/Freeze/Validate/Execute semantics.
- [x] `os.cpu_count()` is never called to scale thread caps.
- [x] `index-root` serial execution strictly preserved.
- [x] Gate5-G remains strictly FORBIDDEN.
