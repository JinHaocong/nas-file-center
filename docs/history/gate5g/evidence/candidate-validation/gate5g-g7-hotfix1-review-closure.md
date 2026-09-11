# Gate5-G / G7 Independent Implementation Review Closure (Hotfix 1)

**Date:** 2026-09-11  
**Target Release:** v0.3.5  
**Branch:** `v0.3.5-gate5c-hotfix4`  
**Previous Failed Candidate HEAD:** `8057724d1e4fdd34e9d28ef2c44ecb3fbe08a3ab`  
**Candidate Code HEAD:** `f8f87c7a9253958b57bd761a6f012a5ffc4012e0`  
**Frozen Architecture:** `0ddf932747021578f08843c5069ef88a461d493f` (Revision 3.1)  
**Approved Implementation Plan:** `2a9d6444f8abead9438ca3fe391193cf64075807` (v1.1.3)  
**Candidate Package:** `nas-file-center-v0.3.5-gate5g-g7-hotfix5.zip`  
**Package SHA256:** `86a3b61cb255d0c3a96f0627e8fb438c70ef9ccfaaef2207134f1a53eb8ac25f`  
**Package Comment:** `f8f87c7a9253958b57bd761a6f012a5ffc4012e0`  
**Status:** READY FOR INDEPENDENT IMPLEMENTATION REVIEW  

---

## 1. Review Finding Closures (13 / 13 Addressed)

### Finding 1: Real Worker Quarantine Must Carry Gate3 Authority
- **Resolution**: In `app/tasks/handlers.py`, Phase 1 quarantine entry creation now directly initializes `expected_size`, `expected_content_hash`, `expected_device`, `expected_inode`, and `expected_mtime_ns` from the frozen `BatchPlanItem`.
- **Verification**: `tests/test_gate5g_g7_hotfix1_worker_gate3.py` verifies full Gate3 authority inheritance.

### Finding 2: Actual BatchPlan Restore Must Use Transactional Restore
- **Resolution**: In `app/execution/executor.py`, restore execution routes to `execute_transactional_restore` when anchor/entry exists. For COMPAT mode where no authoritative anchor exists, fails closed with `OSError(errno.EOPNOTSUPP)`.
- **Verification**: `tests/test_gate5g_g7_hotfix1_worker_restore.py` verifies transactional routing and fail-closed behavior.

### Finding 3: Transaction Engine Owns Transaction State
- **Resolution**: In `app/tasks/handlers.py`, Phase 3 completion logic protects transactional entries: `conflict` state is preserved rather than overwritten to `abandoned`, and authoritative DB values are never overwritten with recalculations from mutable presentation paths.
- **Verification**: `tests/test_gate5g_g7_hotfix1_tx_state_ownership.py` verifies state ownership.

### Finding 4: Remove Nested BEGIN IMMEDIATE Reconciliation
- **Resolution**: In `app/tasks/handlers.py`, worker crash recovery is decomposed into three clean stages:
  1. Read-only collection of executing items outside write transactions;
  2. Transactional reconciliation loop invoked outside outer write locks;
  3. Short, focused write transaction to finalize non-transactional items and job status.
- **Verification**: `tests/test_gate5g_g7_hotfix1_no_nested_immediate.py` validates deadlock-free execution.

### Finding 5: Restore Terminal Evidence Must Be Strict
- **Resolution**: In `app/quarantine/restore.py` and `app/quarantine/reconcile.py`, if public path is absent and captured target is absent, the system fails closed to `conflict` rather than inferring success.
- **Verification**: `tests/test_gate5g_g7_hotfix1_strict_restore_evidence.py` asserts strict terminal evidence.

### Finding 6: API Transactional Restore Must Not Bypass Worker Lease or PathGuard
- **Resolution**: In `app/service.py`, `restore_quarantined_file` verifies worker lease and invokes `validate_mutation_destination` via PathGuard.
- **Verification**: `tests/test_gate5g_g7_hotfix1_api_lease_pathguard.py` checks lease enforcement and symlink escape rejection.

### Finding 7: Use Frozen Descriptor-Relative Transaction Ops
- **Resolution**: `app/quarantine/engine.py` and `app/quarantine/restore.py` use `safe_open_parent_fd` and descriptor-relative operations (`os.link(..., src_dir_fd=..., dst_dir_fd=...)`, `os.rename(..., src_dir_fd=..., dst_dir_fd=...)`). `app/batch_utilities/empty_dir_quarantine.py` fails closed on ancestor symlink retarget.
- **Verification**: `tests/test_gate5g_g7_hotfix1_descriptor_relative.py` validates descriptor-relative isolation.

### Finding 8: Fix Transaction Namespace + Generation Creation
- **Resolution**: `app/quarantine/tx_allocator.py` and `app/quarantine/reconcile.py` accept `quarantine_root` parameter, fix `(gen, attempt_dir)` tuple unpacking, and create generation directories with `0o700` mode.
- **Verification**: `tests/test_gate5g_g7_hotfix1_namespace_generation.py` validates proper directory layout and permissions.

### Finding 9: Restore Reconciliation Must Use Transaction Reconciler
- **Resolution**: Executing-item restore crash recovery delegates directly to `reconcile_quarantine_transaction`.
- **Verification**: Covered by `tests/test_gate5g_g7_hotfix1_worker_restore.py` and `tests/test_gate5g_g7_task10_reconcile.py`.

### Finding 10: R1-R16 Test Fidelity
- **Resolution**: In `tests/test_gate5g_g7_races.py`, R8 and R9 tests hold real open file descriptors (`dir_fd`, `parent_fd`) across simulated lease transfer before asserting `JobLeaseLost`.
- **Verification**: `tests/test_gate5g_g7_races.py` (16 passed).

### Finding 11: fs_ops Decommission Cleanup
- **Resolution**: Cleaned up deprecated fallback methods from `app/fs_ops.py` and updated docstrings to explicitly state `EOPNOTSUPP` semantics.
- **Verification**: `tests/test_gate5g_g7_hotfix1_fs_ops.py` (16 passed).

### Finding 12: Full Verification
- **Backend Tests**: Exactly **1228 passed, 3 skipped, 19 warnings in 97.35s** (0 failures).
- **Frontend Typecheck**: `npm run typecheck` passed (0 errors).
- **Frontend Tests**: `npm test` passed (**355 passed**, 0 failures).
- **Frontend Build**: `npm run build` passed (built in 3.63s).

### Finding 13: Evidence / Artifact Generation
- **Artifact**: `nas-file-center-v0.3.5-gate5g-g7-hotfix5.zip`
- **SHA256**: `86a3b61cb255d0c3a96f0627e8fb438c70ef9ccfaaef2207134f1a53eb8ac25f`
- **Comment**: `f8f87c7a9253958b57bd761a6f012a5ffc4012e0`
- **Integrity**: `testzip()` OK (None), 601 entries, zero forbidden files.

---

## 2. Verification Summary Table

| Check | Target | Result | Status |
|---|---|---|---|
| Backend Full Suite | 0 failures | 1228 passed, 3 skipped | PASS |
| G7 Races (R1 - R16) | 16 races | 16 passed | PASS |
| Frontend Typecheck | 0 errors | tsc clean | PASS |
| Frontend Unit Tests | 0 failures | 355 passed | PASS |
| Frontend Build | dist assets | clean build | PASS |
| Archive Testzip | None | None | PASS |
| Archive Comment | Candidate HEAD | `f8f87c7a9253958b57bd761a6f012a5ffc4012e0` | PASS |
| Forbidden Files | 0 | 0 | PASS |

---

## 3. Review Declaration

```text
G7 TRANSACTIONAL MUTATION IMPLEMENTATION HOTFIX1 COMPLETE
READY FOR INDEPENDENT IMPLEMENTATION REVIEW
```
