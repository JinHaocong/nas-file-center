# Gate5-E / E3-hotfix1 Walkthrough

## Overview
- **Phase**: Gate5-E / E3-hotfix1 (Independent Review Blocker Fix)
- **Baseline HEAD**: `997b56774f85d74e0fa28f14313557ccbe8f8bed`
- **Baseline Artifact**: `nas-file-center-v0.3.5-gate5e-e3.zip`
- **Scope**: Production changes strictly confined to `app/batch_utilities/*` and `app/service.py`. Zero modifications to executor, models, migrations, frontend, fs_ops, or handlers.

---

## Changes Made

### 1. Casefold Graph Authority & Preflight Validation
- **`app/batch_utilities/flatten_graph.py`**:
  - Implemented `validate_wrappers_preflight` with strict no-follow validation before resolution:
    - Symlink wrapper: raises `BatchUtilitySymlinkBlockedError`.
    - Non-existent wrapper: raises `BatchUtilityScopeNotFoundError`.
    - Wrapper outside allowed roots: raises `BatchUtilityCrossRootError`.
    - Wrapper inside quarantine or equal to allowed root: raises `BatchUtilityInvalidConfigError`.
    - Overlapping wrappers (identical or ancestor/descendant): raises `BatchUtilityScopeOverlapError`.
  - Implemented `resolve_flatten_graph` target-parent casefold authority:
    - Target parent directories scanned deterministically via `os.scandir`.
    - Any `OSError` during scandir fails closed, marking affected items with `CASE_ONLY_COLLISION`.
    - Generates deterministic directory observations recording `parent` and `scan_status: OK | FAILED` (plus `errno` if present).
    - Detects planned vs existing casefold collisions (`CASE_ONLY_COLLISION`).
    - Detects planned vs planned casefold collisions (`CASE_ONLY_COLLISION`).
    - Excludes all conflicting items from `ordered_items`.
  - Request-level dependency resolution:
    - Kahn's topological sort handling vacating occupants.
    - Cycle detection emitting `RENAME_CYCLE` blocking conflicts.
    - Blocked occupant propagation emitting `TARGET_EXISTS` blocking conflicts.

### 2. Schema, Types, and Lexical Normalization
- **`app/batch_utilities/schema.py`**:
  - `FlattenOneLevelAction.validate_wrapper_paths`: Normalized path comparison via `os.path.normpath` to reject lexical duplicate paths (e.g. `"/tmp/a"` and `"/tmp/x/../a"` or trailing slashes).
  - `BatchUtilityPreviewRow`: Added `index_root_id: int | None = None`, `index_root_path: str | None = None`, `wrapper_path: str | None = None`, and allowed `"MOVE"` in `decision`.
- **`app/batch_utilities/graph.py`**:
  - `TargetItemCandidate`: Added `is_dir`, `object_type`, `wrapper_path`, and optional `index_root_id` / `index_root_path`.

### 3. Discovery, Compiler, and Snapshot Digest Binding
- **`app/batch_utilities/flatten.py`**:
  - `FlattenCandidate`: Added `wrapper_path`, `object_type`, `size`, `mtime_ns`, `device`, `inode`, `is_dir`.
  - `discover_flatten_one_level`: Captures full `os.lstat` metadata distinguishing files and directories without following symlinks.
- **`app/batch_utilities/compiler.py`**:
  - `compile_flatten_one_level_preview`:
    - Executes `validate_wrappers_preflight` on input wrapper paths.
    - Sets preview row `decision = "MOVE"` for safe items, `"BLOCKING_CONFLICT"` for blocked items.
    - Sets `index_root_id = None`, `index_root_path = None`, and populates `wrapper_path`.
    - Restricts draft intent creation strictly to safe ordered items (`len(draft_intents) == planned_operations_count`).
    - Per-item metadata stores `utility_action="flatten_one_level"`, `wrapper_path`, `object_type`, `source_basename`, `target_path`.
    - Binds full source snapshot payload: canonical wrappers, wrapper observations, direct children (device, inode, mtime_ns, size, type), target observations, casefold directory observations (`scan_status`), dependency edges, conflict facts, and ordered safe sources.
    - Sets `db_lineage_digest = None`.

### 4. Service & Draft Persistence
- **`app/service.py`**:
  - `create_batch_utility_plan`: Validates priority 1 blocking conflicts including `TARGET_SYMLINK` and `WRAPPER_CHILD_SYMLINK` to raise `BatchUtilitySymlinkBlockedError`.
  - `_persist_batch_utility_draft`: Explicit branch for `flatten_one_level` sets `current_lineage = None` and skips lineage validation when `db_lineage_digest is None`. Persists `wrapper_paths` in `plan_metadata`.

---

## 17 Reviewer Regressions Tested

| # | Regression Requirement | Test File & Function | Result |
|---|------------------------|----------------------|--------|
| 1 | Casefold existing sibling collision (`CASE_ONLY_COLLISION`) | `tests/test_gate5e_e3_graph.py::test_casefold_existing_sibling_collision` | PASS |
| 2 | Casefold scandir `PermissionError` fails closed (`CASE_ONLY_COLLISION`, `scan_status=FAILED`) | `tests/test_gate5e_e3_graph.py::test_casefold_scandir_oserror_fails_closed` | PASS |
| 3 | Blocked source creates no intent | `tests/test_gate5e_e3_compiler.py::test_compiler_blocked_source_creates_no_intent` | PASS |
| 4 | `planned_operations_count` excludes blocked sources | `tests/test_gate5e_e3_compiler.py::test_compiler_blocked_source_creates_no_intent` | PASS |
| 5 | Directory preview `object_type=directory` | `tests/test_gate5e_e3_compiler.py::test_compiler_preview_row_fields_and_directory` | PASS |
| 6 | Safe preview `decision=MOVE` | `tests/test_gate5e_e3_compiler.py::test_compiler_preview_row_fields_and_directory` | PASS |
| 7 | E3 `index_root` fields are null | `tests/test_gate5e_e3_compiler.py::test_compiler_preview_row_fields_and_directory` | PASS |
| 8 | `wrapper_path` populated on preview rows | `tests/test_gate5e_e3_compiler.py::test_compiler_preview_row_fields_and_directory` | PASS |
| 9 | Wrapper symlink maps `SYMLINK_BLOCKED` | `tests/test_gate5e_e3_api.py::test_preview_wrapper_symlink_error` | PASS |
| 10 | Outside wrapper maps `CROSS_ROOT` | `tests/test_gate5e_e3_api.py::test_preview_wrapper_cross_root_error` | PASS |
| 11 | Normalized lexical duplicates rejected | `tests/test_gate5e_e3_schema.py::test_flatten_one_level_action_normalized_lexical_duplicate` | PASS |
| 12 | Same-size mtime / source identity change alters digest | `tests/test_gate5e_e3_compiler.py::test_compiler_digest_changes_on_same_size_mtime_change` | PASS |
| 13 | `dependency_edges` populated for dependent items | `tests/test_gate5e_e3_graph.py::test_dependency_edges_and_vacating_occupant` | PASS |
| 14 | Rename cycle -> `RENAME_CYCLE` | `tests/test_gate5e_e3_graph.py::test_rename_cycle_detection` | PASS |
| 15 | Stable topological sort | `tests/test_gate5e_e3_graph.py::test_stable_topo_sort` | PASS |
| 16 | Vacating occupant | `tests/test_gate5e_e3_graph.py::test_dependency_edges_and_vacating_occupant` | PASS |
| 17 | Blocked occupant propagation | `tests/test_gate5e_e3_graph.py::test_blocked_occupant_propagation` | PASS |

---

## Test Verification Summary
1. **E3 Focused Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_e3_*.py
   # 36 passed, 0 failed
   ```
2. **E1 & E2 Regression Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_e1_*.py tests/test_gate5e_e2_*.py
   # 77 passed, 0 failed
   ```
3. **Gate5-E Combined Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q tests/test_gate5e_*.py
   # 113 passed, 0 failed
   ```
4. **Complete Repository Backend Suite**:
   ```bash
   pytest -o addopts='' --disable-warnings -q
   # 930 passed, 0 failed
   ```

## Deliverables & Identity
- **Documentation**: `docs/history/gate5e/gate5e-e3-hotfix1-walkthrough.md`
- **Source Snapshot ZIP**: `nas-file-center-v0.3.5-gate5e-e3-hotfix1.zip`
- **Baseline HEAD**: `997b56774f85d74e0fa28f14313557ccbe8f8bed`
- **Implementation HEAD**: `abb7123d625a5afac8afedc4583336c8b433d491`
- **Final Repository HEAD**: Refer to git `FINAL_HEAD` (`git rev-parse HEAD`), matching ZIP Comment.
