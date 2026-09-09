# Gate5-E / E3-hotfix3 Walkthrough

## Overview
- **Phase**: Gate5-E / E3-hotfix3 (Source Authority Fail-Closed Fix)
- **Baseline HEAD**: `bd3f67759538fff8647f01f6099621c8125f0617`
- **Baseline Artifact**: `nas-file-center-v0.3.5-gate5e-e3-hotfix2.zip`
- **Baseline SHA256**: `d79f493852acf1634b48523615a15a236ff98b429551e19e150c8a469f8302f9`
- **Production Scope**:
  - `app/batch_utilities/flatten_graph.py` (Source authority revalidation & fail-closed observation)
  - `app/batch_utilities/compiler.py` (Registered `SOURCE_MISSING`, `SOURCE_INACCESSIBLE`, `SOURCE_TYPE_CHANGED` in priority rank)
- **Zero Modifications Outside Scope**:
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
Between discovery and graph validation, if a discovered source file disappeared or mutated:
- `resolve(strict=True)` previously fell back to `resolve(strict=False)`.
- `_lstat(source)` caught `FileNotFoundError` and silently passed (`pass`).
- This allowed a missing source to enter target and dependency processing, resulting in `MOVE` decision and `BatchUtilityDraftIntent` generation for non-existent files.
- Furthermore, if a regular file mutated into a directory (or vice-versa), the compiler silently reinterpreted the object rather than failing closed.

### 2. Source Revalidation (Phase A in `resolve_flatten_graph`)
Before any source is admitted into target or dependency processing, `resolve_flatten_graph` executes a fresh, non-following source observation:
1. **Fresh `_lstat(source_path)`**:
   - `FileNotFoundError`: Emits deterministic blocking conflict `SOURCE_MISSING` (reason: `SOURCE_MISSING`). Source blocked.
   - Other `OSError`: Emits deterministic blocking conflict `SOURCE_INACCESSIBLE` with errno. Source blocked.
2. **Symlink Check**:
   - `stat.S_ISLNK`: Emits `WRAPPER_CHILD_SYMLINK`. Source blocked.
3. **Supported Type & Type Race Detection**:
   - Confirms source is either regular file (`stat.S_ISREG`) or directory (`stat.S_ISDIR`). If neither (socket, FIFO, device), emits `UNSUPPORTED_OBJECT`.
   - Compares current type with discovery candidate (`item.is_dir` / `item.object_type`). If file mutated to directory, or directory mutated to file, emits `SOURCE_TYPE_CHANGED`. Source blocked.
4. **Strict Physical Resolution**:
   - Executes `resolve(strict=True)`. Any `FileNotFoundError` or `OSError` blocks the source (`SOURCE_MISSING` or `SOURCE_INACCESSIBLE`).
5. **Containment**:
   - Verifies canonical path inside `allowed_roots` and outside `quarantine_root`.
6. **Isolation**:
   - Any source that fails Phase A is added to `source_blocked_paths` and **strictly excluded from Phase B (target validation, target collision, casefold checks, target observations, and dependency resolution)**.
   - Blocked sources are excluded from `unblocked_items` and `ordered_items`, guaranteeing `planned_operations_count = 0` and 0 Draft intents.

### 3. Preservation of Draft Physical Identity Contract
All hotfix2 guarantees remain intact:
- Draft intents continue to set `expected_device = 0`, `expected_inode = 0`, `expected_mtime_ns = 0`, `expected_hash = None`.
- Gate3 Freeze remains the sole and final physical identity owner.

---

## Reviewer Regressions Tested & Verified

| Test | Description | File & Function | Result |
|---|---|---|---|
| **Test A** | `gone.txt` discovered -> unlinked -> graph/compiler -> `planned_operations_count = 0`, 0 intent, `BLOCKING_CONFLICT`, `reason = SOURCE_MISSING` | `tests/test_gate5e_e3_compiler.py::test_compiler_source_missing_after_discovery` | PASS |
| **Test B** | regular file discovered -> mutated to directory -> graph/compiler -> 0 intent, `BLOCKING_CONFLICT`, `reason_code = SOURCE_TYPE_CHANGED` | `tests/test_gate5e_e3_compiler.py::test_compiler_source_type_race_file_to_directory` | PASS |
| **Test C** | directory discovered -> mutated to regular file -> graph/compiler -> 0 intent, `BLOCKING_CONFLICT`, `reason_code = SOURCE_TYPE_CHANGED` | `tests/test_gate5e_e3_compiler.py::test_compiler_source_type_race_directory_to_file` | PASS |
| **Test D** | Generate Phase A racing discovery with missing source -> 409 `BATCH_UTILITY_CONFLICT`, `blocking_conflict_count = 1`, `SOURCE_MISSING`, 0 Draft in DB | `tests/test_gate5e_e3_generate.py::test_generate_flatten_source_missing_race_raises_409` | PASS |

---

## Test Verification Summary

1. **New Reviewer Regressions**:
   ```bash
   pytest -o addopts='' -v tests/test_gate5e_e3_compiler.py -k "test_compiler_source_missing_after_discovery or test_compiler_source_type_race"
   # 3 passed in 0.16s
   pytest -o addopts='' -v tests/test_gate5e_e3_generate.py -k "test_generate_flatten_source_missing_race_raises_409"
   # 1 passed in 0.43s
   ```
2. **E3 Complete Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_e3_*.py
   # 52 passed, 0 failed in 2.12s
   ```
3. **E1 & E2 Regression Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py
   # 77 passed, 0 failed in 5.89s
   ```
4. **Gate5-E Complete Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_*.py
   # 129 passed, 0 failed in 7.28s
   ```
5. **Complete Repository Backend Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q
   # 946 passed, 0 failed in 87.78s
   ```

## Deliverables & Identity
- **Documentation**: `docs/history/gate5e/gate5e-e3-hotfix3-walkthrough.md`
- **Source Snapshot ZIP**: `nas-file-center-v0.3.5-gate5e-e3-hotfix3.zip`
- **Baseline HEAD**: `bd3f67759538fff8647f01f6099621c8125f0617`
- **Final Repository HEAD**: Refer to git `FINAL_HEAD` (`git rev-parse HEAD`), matching ZIP Comment.
