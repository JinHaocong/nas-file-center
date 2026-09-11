# Gate5-G / G7 Hotfix4-fix1 Walkthrough: Independent Review Closure

## 1. Objective & Background
Independent review of Hotfix4 identified three critical findings (P0-1, P0-2, P0-3):
1. **P0-1**: Chained generic quarantine plans (`rename A -> B; quarantine B`) bypassed freeze hash capture due to `continue` in chained producer resolution, freezing with `expected_hash = None`.
2. **P0-2**: Generic quarantine freeze hashing condition inadvertently caught dedupe items (`keep_path`), breaking legacy graceful failure semantics.
3. **P0-3**: Hashing helper re-opened files by pathname (`safe_quarantine_hash`), introducing a potential ABA replacement race condition.

Hotfix4-fix1 closes all three findings without touching frozen Architecture or Implementation Plan, modifying only `app/service.py`.

## 2. Technical Implementation
1. **P0-1 Fix (Chained Hash Capture)**:
   - In `freeze_plan()` chained item handling, when `it["operation"] == "quarantine"` and `it.get("keep_path") is None` and `snap["object_type"] == "file"` and `not computed_hash`:
   - Authoritative SHA256 is captured from `matched_origin` using the descriptor-bound protocol.
   - Persisted into `upd["expected_hash"]` and `meta["snapshot"]["hash"]`.
2. **P0-2 Fix (keep_path Guard)**:
   - In non-chained quarantine handling, added `and it.get("keep_path") is None`.
   - Dedupe items never invoke generic quarantine freeze hashing.
3. **P0-3 Fix (Descriptor-Bound Hashing)**:
   - `_freeze_capture_stable_quarantine_hash` uses `safe_open_parent_fd(src_p, allowed_roots)` and opens the leaf file descriptor directly with `O_RDONLY | O_NOFOLLOW`.
   - `fstat(fd)` verifies initial identity matches snapshot.
   - Dedicated `_descriptor_sha256(fd)` streams SHA256 directly from the open descriptor via `os.read`.
   - Post-hash `fstat(fd)` ensures descriptor facts did not mutate.
   - Post-hash `os.lstat(src_p)` verifies pathname did not suffer ABA replacement.
   - File descriptor is safely closed in `finally`.

## 3. Verification & Evidence
- Tests in `tests/test_gate5g_g7_hotfix4_freeze_hash.py`: 10 passed.
- Focused regressions: 46 passed.
- Gate5-G suite: 107 passed.
- Full backend regression: 1256 passed, 3 skipped, 0 failed.
- Full frontend regression: TypeScript typecheck PASS, 355 unit tests PASS, production build PASS.
- `git diff --check`: PASS.
- Candidate ZIP artifact: `nas-file-center-v0.3.5-gate5g-g7-hotfix8-fix1.zip` with comment `c07f9022c26db2fa152cddda528b5550d333b53a`.
