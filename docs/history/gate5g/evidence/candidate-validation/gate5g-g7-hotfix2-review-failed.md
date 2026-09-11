# Gate5-G / G7 Independent Implementation Review — FAILED (Hotfix 3 Required)

**Date:** 2026-09-11  
**Candidate Commit Evaluated:** `fd2bae07a30aab559e812ade4c0bcbab1cacea06`  
**Manifest Commit:** `0d713563559c4c7f191afca5227e5a994cc1bd11`  
**Frozen Architecture:** `0ddf932747021578f08843c5069ef88a461d493f` (Revision 3.1)  
**Approved Implementation Plan:** `2a9d6444f8abead9438ca3fe391193cf64075807` (v1.1.3)  
**Result:** **FAILED INDEPENDENT IMPLEMENTATION REVIEW**  

---

## Findings Requiring Hotfix 3

1. **Full Post-Capture Qualification Before Active**:
   Both `execute_transactional_quarantine()` and `reconcile_quarantine_transaction()` transitioned to `state='active'`, `tx_phase='active'` based only on pre-rename stat or post-rename dev/ino checks. After capture rename, the worker and reconciler must open `captured_source` descriptor-relative and execute full frozen qualification against persisted Gate3 authority (`S_ISREG`, `device`, `inode`, `size`, `mtime_ns`, `SHA256`, and intra-qualification ctime stability). If qualification fails, transition deterministically to `conflict`, with zero payload unlink and zero rename-back.

2. **Restore Takeover Must Never Reuse Old In-Flight Slot**:
   When reconciling an uncompleted restore transaction whose lease expired, if `pub_path` still exists and must be retired, it must not be renamed into the old attempt directory. The old attempt was in-flight when the worker crashed, so its retired slot might already be corrupted, partially written, or occupied. The reconciler must allocate an exclusive next generation `attempt-(G+1)`.

3. **Existing Restore Evidence = Classify First (Variant 13)**:
   In restore takeover and reconciliation, if a restored destination or retired public view already exists:
   - Classify existing evidence first:
     a) Valid completed restore evidence (matches authoritative anchor): converge to `restored` immediately without allocating a new generation attempt or mutating filesystem state.
     b) Foreign, corrupt, or unrecognized evidence (does not match authoritative anchor): fail-closed to `conflict` immediately with zero new attempt directory allocation, zero rename, and zero unlink.

4. **Attempt Directory Creation Must Be Exclusive**:
   Directory creation must eliminate `mkdir(parents=True, exist_ok=True)` and strictly use `os.mkdir(..., mode=0o700)`. If `FileExistsError` is encountered, it must never be silently adopted; it must increment the generation counter and retry until an unused slot is created exclusively.
