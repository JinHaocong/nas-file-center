# Gate5-G / G7 Independent Implementation Review — FAILED (Hotfix 1 Required)

**Date:** 2026-09-11  
**Candidate Commit Evaluated:** `8057724d1e4fdd34e9d28ef2c44ecb3fbe08a3ab`  
**Manifest Commit:** `b3122b1c807f3a2e90f4f3c3281343be24ed81fe`  
**Frozen Architecture:** `0ddf932747021578f08843c5069ef88a461d493f` (Revision 3.1)  
**Approved Implementation Plan:** `2a9d6444f8abead9438ca3fe391193cf64075807` (v1.1.3)  
**Result:** **FAILED INDEPENDENT IMPLEMENTATION REVIEW**  

---

## Findings Requiring Hotfix 1

1. **Real Worker Quarantine Must Carry Gate3 Authority**:
   `BatchPlanExecuteHandler` creates `QuarantineEntry` without the frozen `BatchPlanItem` identity (`expected_size`, `expected_hash`, `expected_device`, `expected_inode`, `expected_mtime_ns`), relying on recalculation from mutable path.
2. **Actual BatchPlan Restore Must Use Transactional Restore**:
   `execute_item` restore branch still invokes `rename_noreplace` and falls back instead of using `execute_transactional_restore`. COMPAT without authoritative anchor must fail closed with `EOPNOTSUPP`.
3. **Transaction Engine Owns Transaction State**:
   Generic Phase-3 finalizer overwrites transactional state (`conflict` -> `abandoned`/`inconsistent`) and recalculates DB authority from public quarantine view. Public view is presentation-only and must never overwrite authoritative DB values.
4. **Remove Nested BEGIN IMMEDIATE Reconciliation**:
   Worker crash recovery holds `BEGIN IMMEDIATE` and invokes `reconcile_quarantine_transaction()`, causing locked SQLite connections / `SQLITE_BUSY`. Transaction reconciliation must happen outside outer write transaction.
5. **Restore Terminal Evidence Must Be Strict**:
   `restored` status cannot be inferred merely from absent public path. If public path is absent AND captured view is absent, must fail-closed to `conflict`.
6. **API Transactional Restore Must Not Bypass Worker Lease or PathGuard**:
   API direct restore path calls transactional restore with `worker_id=None` and skips `validate_mutation_destination`. Unsafe direct API transactional mutation must fail closed.
7. **Use Frozen Descriptor-Relative Transaction Ops**:
   Candidate link, public view link, source capture, restore publication, and view retirement must strictly use descriptor-relative operations (`os.link(..., src_dir_fd=..., dst_dir_fd=...)`, `os.rename(..., src_dir_fd=..., dst_dir_fd=...)`). Ancestor symlink retarget must fail closed.
8. **Fix Transaction Namespace + Generation Creation**:
   Private tx namespace must be `<quarantine_root>/.tx/entry-<entry_id>/attempt-<generation>/`, not derived from nested public path. Generation directory creation must use mode `0700` without `exist_ok=True`. Fix `allocate_next_generation` tuple unpacking bug (`(gen, attempt_dir)`).
9. **Restore Reconciliation Must Use Transaction Reconciler**:
   Executing-item restore reconciliation must delegate to unified transaction reconciler rather than inferring completion from target existence.
10. **R1-R16 Test Fidelity**:
    Upgrade skeletal tests, especially R8 (real retained old attempt dir_fd) and R9 (real retained source parent fd).
11. **fs_ops Decommission Cleanup**:
    Remove unreachable fallback methods `_execute_safe_noreplace_fallback` and `_execute_safe_noreplace_at_fallback` and update docstrings to reflect EOPNOTSUPP on unsupported filesystems.
12. **Full Verification**:
    Exact passed count required across backend suite (no "1200+"), plus frontend typecheck/test/build.
13. **Evidence / Artifact Generation**:
    Walkthrough, clean new ZIP artifact with REAL_HEAD comment, push to `origin/v0.3.5-gate5c-hotfix4`.
