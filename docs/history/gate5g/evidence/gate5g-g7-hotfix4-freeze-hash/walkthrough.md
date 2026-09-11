# Gate5-G / G7 Hotfix4 Walkthrough: Generic Quarantine Freeze Must Capture Gate3 SHA256 Baseline

## 1. Objective & Background
During REAL NAS validation (G7-P3-A), regular-file generic quarantine plans (`operation="quarantine"`, `keep_path=None`, `expected_hash=None`) reached `draft` -> `frozen` -> `validated/ready` without capturing an authoritative cryptographic baseline (`expected_hash` remained `None`). When executed on `COMPAT_TRANSACTIONAL` filesystems (zfuse), the transactional quarantine engine requires candidate-anchor SHA256 qualification against the Gate3 frozen baseline. Because `expected_hash` was `None`, qualification compared against empty string and deterministically entered `conflict`.

Under Hotfix4, `freeze_plan()` captures and persists an authoritative SHA256 for generic regular-file quarantine operations before committing the frozen baseline, ensuring Gate3 cryptographic authority is established and propagates cleanly to `QuarantineEntry.content_hash`.

## 2. Technical Changes
1. **Authoritative Hash Capture in Freeze**:
   - Location: `app/service.py` -> `freeze_plan()`.
   - Condition: For any item where `it["operation"] == "quarantine"`, `snap["object_type"] == "file"`, and `not computed_hash` (i.e. `expected_hash` is None/absent).
   - Dedicated helper: `_freeze_capture_stable_quarantine_hash(src_p: Path, snap: dict[str, Any]) -> str`.
2. **Strict Pre-Hash / Post-Hash Stability Invariant**:
   - Captures pre-hash facts (`st_dev`, `st_ino`, `st_size`, `st_mtime_ns`, `st_ctime_ns`, `object_type=="file"`).
   - Computes SHA256 via repository standard `safe_quarantine_hash()`.
   - Captures post-hash facts.
   - Enforces pre/post equality across all 6 dimensions.
   - Requires object to remain a regular non-symlink file (`stat.S_ISREG(st.st_mode) and not os.path.islink()`).
3. **Fail-Closed Guarantees**:
   - On mutation, deletion, replacement, stat failure, or hashing error: raises `StateConflictError`.
   - The database transaction (`BEGIN IMMEDIATE`) is never entered on error; the plan remains `draft`.
   - No partial expected_hash or partial identity snapshot is committed.
4. **Preservation of Existing Semantics**:
   - Pre-existing `expected_hash` is strictly preserved and not overwritten.
   - Dedupe (`keep_path`) hashing behavior is preserved.
   - Non-regular sources (directories, symlinks) are not hashed.
   - No Execute-time re-baselining or fallback hashing.

## 3. Verification & Evidence
- Focused unit/integration tests in `tests/test_gate5g_g7_hotfix4_freeze_hash.py`: 6 passed.
- Gate5-G test suite: 103 passed.
- Full backend regression: 1252 passed, 3 skipped, 0 failed.
- Full frontend regression: TypeScript typecheck PASS, 355 unit tests PASS, production build PASS.
- Clean candidate ZIP artifact generated with CODE CANDIDATE comment.
