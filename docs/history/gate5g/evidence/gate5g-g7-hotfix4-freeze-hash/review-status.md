# Gate5-G / G7 Hotfix4 Review Status

**Stage:** Gate5-G / G7 Hotfix4 (Generic Quarantine Freeze Must Capture Gate3 SHA256 Baseline)
**Baseline Remote Evidence HEAD:** `38692ff4296a75c2a59c4d568cd1e4f933abded5`
**Baseline Code Parent:** `958c5d04c6b71c0ffd1ee5f77cb52ee1b046147d`
**Code Candidate SHA:** `46d03d1d9d0745d9e936c06a8c6bb466b8e27c69`
**Status:** **READY FOR INDEPENDENT REVIEW**

## Summary of Findings & Implementation
1. **Root Cause Confirmed**: Real NAS G7-P3-A generic regular-file quarantine plans had `expected_hash = None`. Under `COMPAT_TRANSACTIONAL` (zfuse), the transactional engine requires candidate-anchor cryptographic qualification against Gate3 baseline. With `content_hash = None`, qualification against empty string deterministically failed and entered conflict.
2. **Freeze-Time Gate3 Baseline Capture**:
   - `app/service.py` (`freeze_plan`) now enforces authoritative SHA256 capture for generic regular-file quarantine items prior to committing frozen state.
   - Enforces pre/post-hash identity invariance across `object_type`, `device`, `inode`, `size`, `mtime_ns`, `ctime_ns`.
   - Fails closed (`StateConflictError`), leaving plan in `draft` state upon any anomaly, mutation, or I/O error.
3. **Preservation Invariants**:
   - Pre-existing non-null `expected_hash` is strictly preserved.
   - Dedupe (`keep_path`) semantics remain unchanged.
   - Non-regular items (directories, symlinks) are not hashed.
   - No fallback hashing in Execute/Worker.
4. **Verification**:
   - RED test confirmed failure on baseline `958c5d0`.
   - GREEN confirmed all 6 mandatory test cases pass.
   - Full regression passes: 1252 backend, 355 frontend tests, 0 failures.
