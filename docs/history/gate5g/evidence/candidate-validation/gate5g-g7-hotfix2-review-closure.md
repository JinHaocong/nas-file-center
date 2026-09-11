# Gate5-G / G7 Independent Implementation Review Closure (Hotfix 2)

**Date:** 2026-09-11  
**Target Release:** v0.3.5  
**Branch:** `v0.3.5-gate5c-hotfix4`  
**Previous Failed Candidate HEAD:** `f8f87c7a9253958b57bd761a6f012a5ffc4012e0`  
**Candidate Code HEAD:** `fd2bae07a30aab559e812ade4c0bcbab1cacea06`  
**Frozen Architecture:** `0ddf932747021578f08843c5069ef88a461d493f` (Revision 3.1)  
**Approved Implementation Plan:** `2a9d6444f8abead9438ca3fe391193cf64075807` (v1.1.3)  
**Candidate Package:** `nas-file-center-v0.3.5-gate5g-g7-hotfix6.zip`  
**Package SHA256:** `5bb24d96047587d574a8bf4c283638e679165ace483e86b8cec1a6a9b1b712e1`  
**Package Comment:** `fd2bae07a30aab559e812ade4c0bcbab1cacea06`  
**Status:** READY FOR INDEPENDENT IMPLEMENTATION REVIEW  

---

## 1. Review Finding Closures (9 / 9 Addressed)

### Item 1 & 6: Real Worker Transactional Restore Must Not Trust Public View & Eradicate Inconsistent Enum
- **Resolution**: In `app/tasks/handlers.py`, `app/execution/executor.py`, and `app/service.py`:
  - For transactional `QuarantineEntry`, mutation authority is strictly: Authoritative Anchor + Persisted Frozen DB Identity + Active Worker Lease + PathGuard.
  - Workers never execute legacy `validate_restore_destination_intent()` or `verify_quarantine_source_integrity(public_view)` as mutation authority.
  - Eliminated invalid `inconsistent` enum usage on transactional entries, transitioning deterministically to `conflict`.
- **Verification**: `tests/test_gate5g_g7_hotfix2_worker_restore_authority.py` (3 passed).

### Item 2: Reconciler Must Use `safe_open_parent_fd`
- **Resolution**: In `app/quarantine/reconcile.py`, all path operations across `orig_path`, `anchor`, `public_view`, and `restored` file paths use `safe_open_parent_fd` with strict `allowed_roots` boundaries. Ancestor symlink retargeting fails closed immediately.
- **Verification**: `tests/test_gate5g_g7_hotfix2_descriptor_relative_reconcile.py` (2 passed).

### Item 3: Candidate Anchor Qualification Must Be Descriptor-Relative
- **Resolution**: In `app/quarantine/engine.py`, eliminated secondary absolute path `os.open`. Qualification is performed directly via `dst_dir_fd` relative descriptor opening.
- **Verification**: `tests/test_gate5g_g7_hotfix2_descriptor_relative_reconcile.py` (2 passed).

### Item 4: Re-verify Authoritative Anchor Before Publishing
- **Resolution**: In `app/quarantine/restore.py` and `app/quarantine/reconcile.py`, before publishing restore destination or public presentation view, the worker re-verifies anchor device, inode, size, mtime_ns, and SHA256 under descriptor-relative inspection. If tampered, zero unlink/publish is executed and entry transitions to `conflict`.
- **Verification**: `tests/test_gate5g_g7_hotfix2_anchor_reverification.py` (2 passed).

### Item 5 & 8: Reconciler Outside Worker Mutation Transaction & Explicit Settings Forwarding
- **Resolution**: In `app/tasks/handlers.py`:
  - `BatchPlanExecuteHandler.run()` reconciles all in-flight transactional items prior to acquiring the outer write transaction.
  - `_reconcile_executing_item` supports `pre_reconciled=True` to eliminate nested `BEGIN IMMEDIATE` and `SQLITE_BUSY` deadlocks, while still cleanly reconciling for standalone callers.
  - Outer reconciliation calls explicitly pass `settings.quarantine_root` and `settings.allowed_roots`.
- **Verification**: `tests/test_gate5g_g7_hotfix2_worker_crash_no_nested_lock.py` (2 passed) and `tests/test_gate5g_g7_hotfix1_no_nested_immediate.py` (1 passed).

### Item 7: Write-Once Capture and View Retirement Slot Defense
- **Resolution**: In `app/quarantine/restore.py` and `app/quarantine/reconcile.py`, `captured_source` and retired view slots are strictly write-once. If a target slot already exists, `allocate_next_generation` allocates a new monotonic attempt generation directory without overwriting historical evidence.
- **Verification**: `tests/test_gate5g_g7_hotfix2_write_once_capture.py` (2 passed).

### Item 9: Upgrade R8/R9 Race Tests to Full Descriptor-Relative Fidelity
- **Resolution**: In `tests/test_gate5g_g7_races.py`, R8 and R9 tests maintain open file descriptors across the simulated worker lease boundary, spying on `os.link` / `os.rename` to assert zero mutation calls after lease loss while keeping descriptor handles valid.
- **Verification**: `tests/test_gate5g_g7_races.py` (16 passed).

---

## 2. Verification Summary Table

| Check | Target | Result | Status |
|---|---|---|---|
| Backend Full Suite | 0 failures | Exactly 1239 passed, 3 skipped (1242 collected) | PASS |
| G7 Hotfix2 Tests | 11 tests | 11 passed | PASS |
| G7 Hotfix1 Tests | 32 tests | 32 passed | PASS |
| G7 Races (R1 - R16) | 16 races | 16 passed | PASS |
| G7 Reconcile + E2E | 8 tests | 8 passed | PASS |
| Frontend Typecheck | 0 errors | `tsc --noEmit` clean | PASS |
| Frontend Unit Tests | 0 failures | 355 passed, 0 failed | PASS |
| Frontend Build | dist assets | clean build in 4.08s | PASS |
| Archive Testzip | None | `zip -T` OK | PASS |
| Archive Comment | Candidate HEAD | `fd2bae07a30aab559e812ade4c0bcbab1cacea06` | PASS |
| Forbidden Files | 0 | 0 | PASS |

---

## 3. Review Declaration

```text
G7 TRANSACTIONAL MUTATION IMPLEMENTATION HOTFIX2 COMPLETE
READY FOR INDEPENDENT IMPLEMENTATION REVIEW
```
