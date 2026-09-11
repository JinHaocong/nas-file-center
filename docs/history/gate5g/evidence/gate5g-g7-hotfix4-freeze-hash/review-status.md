# Gate5-G / G7 Hotfix4-fix1 Review Status

**Stage:** Gate5-G / G7 Hotfix4-fix1 (Independent Review Closure)
**Baseline Evidence HEAD:** `238056e2f25eb323072ca579a8f89e553464ebbf`
**Baseline Code Parent:** `958c5d04c6b71c0ffd1ee5f77cb52ee1b046147d`
**Prior Code Candidate under Review:** `46d03d1d9d0745d9e936c06a8c6bb466b8e27c69`
**New Code Candidate SHA:** `c07f9022c26db2fa152cddda528b5550d333b53a`
**Status:** **READY FOR INDEPENDENT REVIEW**

## Closure of Independent Review Findings

1. **P0-1: Chained Generic Quarantine Hash Capture (CLOSED)**:
   - Fixed `freeze_plan()` chained item branch (`is_chained and producer_match is not None and matched_origin is not None`): captures authoritative SHA256 from `matched_origin` when `operation == "quarantine" and it.get("keep_path") is None and snap["object_type"] == "file" and not computed_hash`.
   - Persisted into `item.expected_hash` and `metadata.snapshot.hash`.
   - Proven by `test_p0_1_chained_rename_quarantine_captures_origin_sha256`: chained plan `rename A -> B; quarantine B` freezes with `expected_hash == SHA256(A)`, validates to `ready` without payload mutation.

2. **P0-2: Keep-Path / Dedupe Semantics Preservation (CLOSED)**:
   - Explicitly guarded generic quarantine freeze capture with `and it.get("keep_path") is None`.
   - Legacy dedupe items with `keep_path` never enter `_freeze_capture_stable_quarantine_hash`.
   - Proven by `test_p0_2_keep_path_dedupe_failure_preserves_legacy_semantics`: failed dedupe hashing gracefully freezes without `expected_hash` and does not raise `StateConflictError`.

3. **P0-3: Descriptor-Bound Hashing & ABA Resistance (CLOSED)**:
   - Upgraded `_freeze_capture_stable_quarantine_hash` to a descriptor-bound protocol:
     - Directory traversed and parent opened via `safe_open_parent_fd(src_p, allowed_roots)`.
     - Leaf descriptor opened with `os.O_RDONLY | os.O_NOFOLLOW`.
     - Pre-hash `fstat(fd)` verifies match with `snap` (dev, ino, size, mtime_ns, ctime_ns).
     - SHA256 computed directly from `fd` via `_descriptor_sha256(fd)`. Path-based `safe_quarantine_hash` is never called.
     - Post-hash `fstat(fd)` verifies no descriptor-level mutation.
     - Post-hash `os.lstat(src_p)` verifies pathname still references the same dev/ino and remains a regular file, detecting any pathname ABA replacement.
     - Descriptor always closed in `finally` block.
   - Proven by `test_p0_3_pathname_aba_replacement_fails_closed` and `test_p0_3_aba_path_swap_fails_closed`.

## Verification Summary
- Hotfix4 test suite: 10 passed.
- Focused regressions: 46 passed.
- Gate5-G suite: 107 passed.
- Full backend regression: 1256 passed, 3 skipped, 0 failed.
- Frontend regression: typecheck PASS, 355 tests PASS, production build PASS.
