# Gate5-E / E3-hotfix2 Walkthrough

## Overview
- **Phase**: Gate5-E / E3-hotfix2 (Independent Review Blocker Fix)
- **Baseline HEAD**: `1479781bfd13944cb440ffea4c29df4523992715`
- **Baseline Artifact**: `nas-file-center-v0.3.5-gate5e-e3-hotfix1.zip`
- **Baseline SHA256**: `ff8a938046f79a69a35433235619a9e4daef73540bf8efb7083bee926c48d519`
- **Scope**: Production changes strictly confined to:
  - `app/batch_utilities/compiler.py`
  - `app/batch_utilities/flatten.py`
  - `app/batch_utilities/flatten_graph.py`
  - `app/service.py`
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

## Changes Made

### 1. Restore Draft Physical Identity Ownership
- **`app/batch_utilities/compiler.py`**:
  - `compile_flatten_one_level_preview` constructs `BatchUtilityDraftIntent` instances with explicitly zeroed physical identity:
    - `expected_device = 0`
    - `expected_inode = 0`
    - `expected_mtime_ns = 0`
    - `expected_hash = None`
  - Preview-time physical metadata is retained exclusively for `source_snapshot_digest` calculation.
  - Authoritative physical identity capture remains owned strictly by Gate3 Freeze (`service.freeze_plan`).
- **Regression**: `tests/test_gate5e_e3_generate.py::test_generate_e3_draft_physical_identity_ownership` verifies that generated draft plan items have all physical identity fields zeroed/null before Freeze, and freeze successfully populates them from disk.

### 2. Source Allowed-Root / Cross-Root Authority
- **`app/batch_utilities/flatten_graph.py`**:
  - `resolve_flatten_graph` now canonicalizes each candidate source and verifies that it is strictly contained within `allowed_roots`, is not within a reserved quarantine directory, and resides within the same allowed root as its wrapper.
  - If a source violates containment or escapes through symlinks, it is flagged with `SOURCE_OUTSIDE_ALLOWED_ROOT` or `CROSS_ROOT`.
- **`app/batch_utilities/compiler.py`**:
  - Registered `"SOURCE_OUTSIDE_ALLOWED_ROOT": 2` and `"CROSS_ROOT": 2` in `CONFLICT_PRIORITY_RANK`.
- **`app/service.py`**:
  - Priority 2 conflict check detects `SOURCE_OUTSIDE_ALLOWED_ROOT` and `CROSS_ROOT` to raise `BatchUtilityCrossRootError` (HTTP 409 `BATCH_UTILITY_CROSS_ROOT`).
- **Regressions**:
  - `tests/test_gate5e_e3_compiler.py::test_compiler_candidate_source_outside_allowed_roots_blocks`
  - `tests/test_gate5e_e3_compiler.py::test_compiler_candidate_source_escaped_symlink_race`
  - `tests/test_gate5e_e3_generate.py::test_generate_flatten_source_outside_allowed_roots_raises_cross_root`

### 3. Candidate Row Limit Must Include All Rows
- **`app/batch_utilities/flatten.py`**:
  - `discover_flatten_one_level` maintains total count `len(candidates) + len(errors)`. If the combined count exceeds `50,000`, discovery immediately raises `BatchUtilityLimitExceededError`.
- **`app/batch_utilities/compiler.py`**:
  - `compile_flatten_one_level_preview` validates `len(flatten_cands) + len(flatten_errors) > MAX_CANDIDATES_LIMIT` and raises `BatchUtilityLimitExceededError` before building preview rows.
- **Regression**: `tests/test_gate5e_e3_compiler.py::test_compiler_candidate_limit_includes_all_error_rows` verifies limit triggers on candidate + error sum.

### 4. Quarantine Wrapper Error Taxonomy
- **`app/batch_utilities/flatten_graph.py`**:
  - `validate_wrappers_preflight` separates quarantine validation from allowed-root root-level equality:
    - Wrapper inside quarantine directory raises `BatchUtilityCrossRootError` (HTTP 409 `BATCH_UTILITY_CROSS_ROOT`).
    - Wrapper equal to allowed root itself retains `BatchUtilityInvalidConfigError` (HTTP 422 `BATCH_UTILITY_INVALID_CONFIG`).
- **Regressions**:
  - `tests/test_gate5e_e3_compiler.py::test_compiler_quarantine_wrapper_maps_cross_root`
  - `tests/test_gate5e_e3_compiler.py::test_compiler_allowed_root_wrapper_maps_invalid_config`
  - `tests/test_gate5e_e3_api.py::test_preview_quarantine_wrapper_error_cross_root`

### 5. Wrapper Scandir Failure Is Scope Authority Failure
- **`app/batch_utilities/flatten.py`**:
  - `discover_flatten_one_level` wraps `os.scandir(w_path)` in a try/except block. On `OSError`, it immediately raises `BatchUtilityInvalidConfigError(f"Failed to scan wrapper directory '{w_path}': {e}", details={"wrapper_path": w_path, "errno": getattr(e, "errno", None)})`, failing closed.
- **Regressions**:
  - `tests/test_gate5e_e3_compiler.py::test_compiler_wrapper_scandir_oserror_fails_closed`
  - `tests/test_gate5e_e3_discovery.py::test_discover_flatten_oserror`
  - `tests/test_gate5e_e3_api.py::test_preview_wrapper_scandir_failure_invalid_config`

### 6. Overlap Fail-Closed Hardening
- **`app/batch_utilities/flatten_graph.py`**:
  - Removed all silent `except OSError: pass` in `check_wrapper_overlap` and `validate_wrappers_preflight`. Any `OSError` during resolution or stat immediately fails closed by raising `BatchUtilityInvalidConfigError`.
  - Added physical device/inode tracking via `seen_dev_ino` to detect aliased or duplicate wrapper directories across different path representations.
- **Regressions**:
  - `tests/test_gate5e_e3_compiler.py::test_compiler_overlap_resolution_oserror_fails_closed`
  - `tests/test_gate5e_e3_compiler.py::test_compiler_overlap_physical_dev_ino_duplicate`

---

## Regressions Tested & Verified

| Blocker | Test Name | File | Result |
|---|---|---|---|
| Blocker 1 | `test_generate_e3_draft_physical_identity_ownership` | `tests/test_gate5e_e3_generate.py` | PASS |
| Blocker 2 | `test_compiler_candidate_source_outside_allowed_roots_blocks` | `tests/test_gate5e_e3_compiler.py` | PASS |
| Blocker 2 | `test_compiler_candidate_source_escaped_symlink_race` | `tests/test_gate5e_e3_compiler.py` | PASS |
| Blocker 2 | `test_generate_flatten_source_outside_allowed_roots_raises_cross_root` | `tests/test_gate5e_e3_generate.py` | PASS |
| Blocker 3 | `test_compiler_candidate_limit_includes_all_error_rows` | `tests/test_gate5e_e3_compiler.py` | PASS |
| Blocker 4 | `test_compiler_quarantine_wrapper_maps_cross_root` | `tests/test_gate5e_e3_compiler.py` | PASS |
| Blocker 4 | `test_compiler_allowed_root_wrapper_maps_invalid_config` | `tests/test_gate5e_e3_compiler.py` | PASS |
| Blocker 4 | `test_preview_quarantine_wrapper_error_cross_root` | `tests/test_gate5e_e3_api.py` | PASS |
| Blocker 5 | `test_compiler_wrapper_scandir_oserror_fails_closed` | `tests/test_gate5e_e3_compiler.py` | PASS |
| Blocker 5 | `test_discover_flatten_oserror` | `tests/test_gate5e_e3_discovery.py` | PASS |
| Blocker 5 | `test_preview_wrapper_scandir_failure_invalid_config` | `tests/test_gate5e_e3_api.py` | PASS |
| Blocker 6 | `test_compiler_overlap_resolution_oserror_fails_closed` | `tests/test_gate5e_e3_compiler.py` | PASS |
| Blocker 6 | `test_compiler_overlap_physical_dev_ino_duplicate` | `tests/test_gate5e_e3_compiler.py` | PASS |

---

## Test Verification Summary
1. **E3 Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_e3_*.py
   # 48 passed in 2.37s
   ```
2. **E1 & E2 Regression Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py
   # 77 passed in 3.42s
   ```
3. **Gate5-E Complete Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_*.py
   # 125 passed in 5.86s
   ```
4. **Complete Repository Backend Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q
   # 942 passed in 86.89s
   ```

## Deliverables & Identity
- **Documentation**: `docs/history/gate5e/gate5e-e3-hotfix2-walkthrough.md`
- **Source Snapshot ZIP**: `nas-file-center-v0.3.5-gate5e-e3-hotfix2.zip`
- **Baseline HEAD**: `1479781bfd13944cb440ffea4c29df4523992715`
- **Final Repository HEAD**: Refer to git `FINAL_HEAD` (`git rev-parse HEAD`), matching ZIP Comment.
