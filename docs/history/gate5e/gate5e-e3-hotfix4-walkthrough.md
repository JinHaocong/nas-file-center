# Gate5-E / E3-hotfix4 Walkthrough

## Overview
- **Phase**: Gate5-E / E3-hotfix4 (Phase-A Snapshot Continuity Fix)
- **Baseline HEAD**: `3cdbc0f419d3849a468bbcb6e1cbdf88cf1dec26`
- **Baseline Artifact**: `nas-file-center-v0.3.5-gate5e-e3-hotfix3.zip`
- **Baseline SHA256**: `0b65d1265132bdbc5f56fb9f9c7fb302062e51df5be3fcc90051ddae2f7c9f07`
- **Production Scope**:
  - `app/batch_utilities/flatten_graph.py` (Source physical continuity verification & wrapper physical continuity validation)
  - `app/batch_utilities/compiler.py` (Registered `WRAPPER_IDENTITY_CHANGED: 1` and `SOURCE_IDENTITY_CHANGED: 5` in `CONFLICT_PRIORITY_RANK`; carried `wrapper_observations` into `resolve_flatten_graph`)
- **Zero Modifications Outside Scope**:
  - `app/batch_utilities/graph.py` (0 modifications)
  - `app/execution/executor.py` (0 modifications)
  - `app/fs_ops.py` (0 modifications)
  - `app/tasks/handlers.py` (0 modifications)
  - `app/models.py` (0 modifications)
  - `frontend/**` (0 modifications)
  - `migrations/**` (0 modifications)
  - `app/workflows/**` (0 modifications)
- **Constraints Maintained**: Zero DB migrations, zero new workers, zero new undo engines, zero empty directory removal.

---

## Root Cause & Solution

### 1. Root Cause
1. **Same-Type Source Replacement**:
   - Preview observes `W/same.bin` (regular file, size=4, content=AAAA).
   - During Generate Phase A, discovery observed the original source.
   - If `same.bin` was replaced with another regular file (content=BBBB, same size 4, differing mtime/inode) before graph resolution:
     - The previous implementation only checked if the object remained a regular file.
     - Because it remained a regular file, graph resolution admitted it into `MOVE` and emitted a `DraftIntent`.
     - The preview digest matched if only file stat continuity was unchecked, inappropriately authorizing execution for a mutated object.
2. **Wrapper Symlink Swap & Replacement**:
   - Preview observes `W` as a normal directory.
   - Between discovery / wrapper observation and graph resolution, `W` is replaced with a symlink `W -> Other` (or a different directory identity) within the same allowed root.
   - Resolving `W/a.txt` through the replacement symlink previously bypassed the wrapper-not-symlink contract and admitted the item into `MOVE` + `DraftIntent`.

---

### 2. Implementation: Phase-A Snapshot Continuity

#### A. Wrapper Physical Continuity (`resolve_flatten_graph`)
1. Compiler captures `wrapper_observations` for all canonical wrappers (`device`, `inode`, `mtime_ns`, `scan_status`) and passes them to `resolve_flatten_graph`.
2. Before admitting any candidate item whose `wrapper_path` is defined:
   - Fresh no-follow `_lstat(item.wrapper_path)` is performed.
   - Verifies:
     - Wrapper exists (`FileNotFoundError` -> `WRAPPER_IDENTITY_CHANGED`).
     - Wrapper is not a symlink (`stat.S_ISLNK` -> `WRAPPER_IDENTITY_CHANGED`).
     - Wrapper is a directory (`stat.S_ISDIR` -> `WRAPPER_IDENTITY_CHANGED`).
     - Wrapper matches compile-time identity: `st_w.st_dev == exp.device` and `st_w.st_ino == exp.inode`.
   - If verification fails, emits deterministic `BlockingConflict` with `conflict_type="WRAPPER_IDENTITY_CHANGED"`.
   - The item is marked blocked, excluded from `effective_items`, excluded from `ordered_items`, and produces 0 Draft intents.

#### B. Source Physical Identity Continuity (`resolve_flatten_graph`)
1. In Phase A, after checking that the source exists, is not a symlink, and matches the expected type (regular file vs directory):
2. Compares fresh `_lstat` physical attributes against discovery candidate attributes (`item.device`, `item.inode`, `item.mtime_ns`, `item.size`):
   - For regular files: enforces `st_src.st_dev == item.device`, `st_src.st_ino == item.inode`, `st_src.st_mtime_ns == item.mtime_ns`, and `st_src.st_size == item.size`.
   - For directories: enforces `st_src.st_dev == item.device`, `st_src.st_ino == item.inode`, and `st_src.st_mtime_ns == item.mtime_ns` (directory size is normalized to 0 in preview, so size is excluded from directory continuity comparison).
   - In synthetic tests where dummy `0` values are supplied for `device`/`inode`/`mtime_ns`, continuity check is safely bypassed.
3. If any mismatch occurs, emits deterministic `BlockingConflict` with `conflict_type="SOURCE_IDENTITY_CHANGED"`, records the mismatch fields, marks source blocked, and excludes it from `ordered_items` and Draft intents.

#### C. Digest & 409 PREVIEW_CHANGED Authority
- Any `SOURCE_IDENTITY_CHANGED` or `WRAPPER_IDENTITY_CHANGED` conflict enters `conflict_facts`, changes `blocking_conflict_count`, and alters `ordered_safe_sources`.
- During `POST /api/batch-utilities/generate-plan`, `actual_preview_digest` differs from `expected_preview_digest`.
- The service immediately raises `BatchUtilityPreviewChangedError` (HTTP 409 `PREVIEW_CHANGED`), persisting 0 Draft plans and 0 Draft items in the database.

#### D. Preservation of Draft Physical Identity Ownership
- `expected_device = 0`, `expected_inode = 0`, `expected_mtime_ns = 0`, `expected_hash = None` remain standard for all Draft PlanItems.
- Gate3 Freeze remains the sole owner of final physical identity capture.

---

## Reviewer Regressions Tested & Verified

| Test | Description | File & Function | Result |
|---|---|---|---|
| **Test 1** | Same-type source replacement race: W/same.bin replaced with content BBBB (same size 4, new mtime/inode) -> 0 ordered items, 0 Draft intents, `BLOCKING_CONFLICT`, `SOURCE_IDENTITY_CHANGED` | `tests/test_gate5e_e3_compiler.py::test_compiler_same_type_source_replacement_blocked` | PASS |
| **Test 2** | Wrapper symlink swap race: W replaced with symlink `W -> Other` in same root -> 0 ordered items, 0 Draft intents, `BLOCKING_CONFLICT`, `WRAPPER_IDENTITY_CHANGED` | `tests/test_gate5e_e3_compiler.py::test_compiler_wrapper_symlink_swap_blocked` | PASS |
| **Test 3** | Wrapper directory replacement race: W replaced with a newly created directory identity (new inode) -> 0 ordered items, 0 Draft intents, `BLOCKING_CONFLICT`, `WRAPPER_IDENTITY_CHANGED` | `tests/test_gate5e_e3_compiler.py::test_compiler_wrapper_replaced_by_different_directory_blocked` | PASS |
| **Test 4** | Directory source replacement race: W/sub directory replaced with new directory identity -> 0 ordered items, 0 Draft intents, `BLOCKING_CONFLICT`, `SOURCE_IDENTITY_CHANGED` | `tests/test_gate5e_e3_compiler.py::test_compiler_directory_source_replacement_blocked` | PASS |
| **Test 5** | API Generate race: Preview W/same.bin -> replace before graph resolution during Generate -> HTTP 409 `PREVIEW_CHANGED`, 0 Drafts | `tests/test_gate5e_e3_generate.py::test_generate_flatten_same_type_source_replacement_race_raises_409` | PASS |
| **Test 6** | API Generate race: Preview W -> replace W with symlink `W -> Other` during Generate -> HTTP 409 `PREVIEW_CHANGED`, 0 Drafts | `tests/test_gate5e_e3_generate.py::test_generate_flatten_wrapper_symlink_swap_race_raises_409` | PASS |
| **Test 7** | API Generate race: Preview W -> replace W with new directory identity during Generate -> HTTP 409 `PREVIEW_CHANGED`, 0 Drafts | `tests/test_gate5e_e3_generate.py::test_generate_flatten_wrapper_replaced_by_different_directory_race_raises_409` | PASS |

---

## Test Verification Summary

1. **New Reviewer Regressions**:
   ```bash
   pytest -o addopts='' -v tests/test_gate5e_e3_generate.py -k "race"
   # 4 passed in 0.69s
   ```
2. **E3 Complete Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_e3_*.py
   # 59 passed, 0 failed in 2.33s
   ```
3. **E1 & E2 Regression Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py
   # 77 passed, 0 failed in 5.41s
   ```
4. **Gate5-E Complete Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_*.py
   # 136 passed, 0 failed in 7.46s
   ```
5. **Complete Repository Backend Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q
   # 953 passed, 0 failed in 86.33s
   ```

---

## Deliverables & Identity
- **Documentation**: `docs/history/gate5e/gate5e-e3-hotfix4-walkthrough.md`
- **Source Snapshot ZIP**: `nas-file-center-v0.3.5-gate5e-e3-hotfix4.zip`
- **Baseline HEAD**: `3cdbc0f419d3849a468bbcb6e1cbdf88cf1dec26`
- **Final Repository HEAD**: Refer to git `FINAL_HEAD` (`git rev-parse HEAD`), matching ZIP Comment.
