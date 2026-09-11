# Gate5-G / G7 Independent Implementation Review Closure (Hotfix 3)

**Date:** 2026-09-11  
**Target Release:** v0.3.5  
**Branch:** `v0.3.5-gate5c-hotfix4`  
**Previous Failed Candidate HEAD:** `fd2bae07a30aab559e812ade4c0bcbab1cacea06`  
**Candidate Code HEAD:** `958c5d04c6b71c0ffd1ee5f77cb52ee1b046147d`  
**Frozen Architecture:** `0ddf932747021578f08843c5069ef88a461d493f` (Revision 3.1)  
**Approved Implementation Plan:** `2a9d6444f8abead9438ca3fe391193cf64075807` (v1.1.3)  
**Candidate Package:** `nas-file-center-v0.3.5-gate5g-g7-hotfix7.zip`  
**Package SHA256:** `9e1938df884d31c4a4f79faccec2c1d0d8f54a73c9c5d368173234333f470dd5`  
**Package Comment:** `958c5d04c6b71c0ffd1ee5f77cb52ee1b046147d`  
**Status:** READY FOR FINAL INDEPENDENT IMPLEMENTATION REVIEW  

---

## 1. Review Finding Closures (4 / 4 Addressed)

### Finding 1: Full Post-Capture Qualification Before Active
- **Resolution**:
  - In `app/quarantine/engine.py` (Step 5) and `app/quarantine/reconcile.py` (Phase 3), capture rename never marks `state='active'` or `tx_phase='active'` based on pre-rename stat or post-rename dev/ino checks alone.
  - After capture rename, the descriptor-relative handle to `captured_source` is opened and passed to `qualify_candidate_anchor_fd()` to verify full frozen Gate3 authority: `S_ISREG`, `device`, `inode`, `size`, `mtime_ns`, `SHA256`, and intra-qualification ctime stability.
  - If any qualification check fails or size/hash mismatch occurs, the transaction transitions deterministically to `state='conflict'`, `tx_phase='conflict'`, with ZERO unlink of payload and ZERO rename-back.
- **Verification**:
  - `tests/test_gate5g_g7_hotfix3_post_capture_qualification.py` (3 passed).

### Finding 2: Restore Takeover Must Never Reuse Old In-Flight Slot
- **Resolution**:
  - In `app/quarantine/reconcile.py` (`_reconcile_restoring`), when taking over an uncompleted restore whose worker lease expired, if `pub_path` still exists and must be retired, the reconciler allocates an exclusive incremented generation directory `attempt-(G+1)` via `allocate_and_create_attempt_dir()`.
  - The old attempt directory was in-flight when the previous worker crashed; retiring into a fresh generation ensures retired slots are never reused or subjected to write collisions.
- **Verification**:
  - `tests/test_gate5g_g7_hotfix3_restore_takeover_generation.py` (3 passed).

### Finding 3: Existing Restore Evidence = Classify First (Variant 13)
- **Resolution**:
  - In `app/quarantine/restore.py` (`execute_transactional_restore`) and `app/quarantine/reconcile.py` (`_reconcile_restoring`), before allocating any new generation attempt or initiating mutations:
    1. Scan and inspect all existing generation directories and the destination `restored_path`.
    2. If valid completed restore evidence matching the authoritative anchor exists, converge immediately to `state='restored'`, `tx_phase='restored'` with zero new generation allocations and zero file mutations.
    3. If foreign, corrupt, or tampered evidence is detected (such as foreign files in attempt slots or restored destinations), fail closed immediately to `state='conflict'`, `tx_phase='conflict'`, with zero new attempt directories, zero renames, and zero unlinks.
- **Verification**:
  - `tests/test_gate5g_g7_hotfix3_restore_takeover_generation.py` and `tests/test_gate5g_g7_hotfix1_worker_restore.py`.

### Finding 4: Attempt Directory Creation Must Be Exclusive
- **Resolution**:
  - Added `allocate_and_create_attempt_dir()` in `app/quarantine/tx_allocator.py`.
  - Completely eradicated `mkdir(parents=True, exist_ok=True)`.
  - Strict atomic directory creation using `os.mkdir(attempt_dir, mode=0o700)`.
  - If `FileExistsError` is caught, the allocator increments the generation counter and retries until an unused slot is created exclusively.
  - Adopted across `app/quarantine/engine.py`, `app/quarantine/restore.py`, and `app/quarantine/reconcile.py`.
- **Verification**:
  - `tests/test_gate5g_g7_hotfix3_exclusive_attempt_dir.py` (1 passed).

---

## 2. Verification Summary Table

| Check | Target | Result | Status |
|---|---|---|---|
| Backend Full Suite | 0 failures | 1246 passed, 3 skipped (1249 collected) | PASS |
| Gate5-G Dedicated Suite | 97 tests | 97 passed in 2.94s | PASS |
| G7 Hotfix3 Finding 1 (Post-Capture Qualification) | 3 tests | 3 passed | PASS |
| G7 Hotfix3 Finding 2 & 3 (Restore Takeover & Classify First) | 3 tests | 3 passed | PASS |
| G7 Hotfix3 Finding 4 (Exclusive Attempt Dir) | 1 test | 1 passed | PASS |
| G7 Hotfix2 Suite | 11 tests | 11 passed | PASS |
| G7 Hotfix1 Suite | 32 tests | 32 passed | PASS |
| G7 Races (R1 - R16) | 16 races | 16 passed | PASS |
| Frontend Typecheck | 0 errors | `tsc --noEmit` clean | PASS |
| Frontend Unit Tests | 0 failures | 355 passed, 0 failed | PASS |
| Frontend Build | dist assets | clean build in 4.06s | PASS |
| Archive Testzip | None | `zip -T` OK | PASS |
| Archive Comment | Candidate HEAD | `958c5d04c6b71c0ffd1ee5f77cb52ee1b046147d` | PASS |
| Archive Total Entries | Valid count | 611 entries | PASS |
| Forbidden Files | 0 | 0 (.git, node_modules, pyc, etc.) | PASS |

---

## 3. Review Declaration

```text
G7 TRANSACTIONAL MUTATION IMPLEMENTATION HOTFIX3 COMPLETE
READY FOR FINAL INDEPENDENT IMPLEMENTATION REVIEW
```
