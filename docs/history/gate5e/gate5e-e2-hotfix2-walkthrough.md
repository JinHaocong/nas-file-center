# Gate5-E / E2-hotfix2 Implementation Walkthrough

## 0. Baseline & Final Status
- **Baseline HEAD**: `29da8889cfff7fa6473c71306e29eef8b286c31d`
- **Baseline Artifact SHA256**: `48a1a4be2d21ff04e9e80cfb0293887dd251f7277e6bd679e8cbd630f3b477d6`
- **Final HEAD**: `d6c630cd8c9b7a8276d315dbdc9b58994b97e391`
- **Working Tree**: Clean (`git status --short` is empty)
- **Status**:
  ```text
  Gate5-E / E2-hotfix2
  IMPLEMENTATION COMPLETE

  READY FOR INDEPENDENT REVIEW
  ```

---

## 1. Commit History
```text
d6c630c fix(batch-utilities): fail closed on casefold scandir error and enforce primary conflict priority (E2-hotfix2)
29da888 fix(batch-utilities): resolve Gate5-E E2 review contract blockers (E2-hotfix1)
```

---

## 2. Real Diff Scope
```text
 app/batch_utilities/compiler.py  |  28 +++++++-
 app/batch_utilities/graph.py     |  29 ++++++--
 tests/test_gate5e_e2_api.py      | 128 ++++++++++++++++++++++++++++++++++
 tests/test_gate5e_e2_compiler.py | 145 +++++++++++++++++++++++++++++++++++++++
 tests/test_gate5e_e2_generate.py | 126 ++++++++++++++++++++++++++++++++++
 tests/test_gate5e_e2_graph.py    |  35 ++++++++++
 6 files changed, 486 insertions(+), 5 deletions(-)
```

---

## 3. Blocker 1 Root Cause, Fix, and Verification
- **Root Cause**: In [graph.py](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/graph.py#L278-L287), `os.scandir(p_dir)` caught broad `Exception` and silently passed (`except Exception: pass`), treating an unreadable directory as containing `[]` entries (failing open). Furthermore, scan failure outcome was omitted from `directory_observations`, failing to alter the authoritative preview digest.
- **Fix**:
  1. Caught `OSError` explicitly during parent directory scanning, recording `failed_parent_dirs: set[Path]`.
  2. Recorded `scan_status = "FAILED"` (or `"OK"`) deterministically in `directory_observations` for each target parent directory.
  3. Flagged `CASE_ONLY_COLLISION` on all target candidates whose parent failed scanning, excluding them from `ordered_items` and setting `has_blocking_conflicts = True`.
- **Reviewer Reproduction Tests**:
  - `tests/test_gate5e_e2_graph.py::test_casefold_scandir_failure_fails_closed`: Graph resolution fails closed with `CASE_ONLY_COLLISION` and empty `ordered_items`.
  - `tests/test_gate5e_e2_compiler.py::test_scandir_failure_fails_closed_and_changes_digest`: Preview has `planned_operations_count=0`, `blocking_conflict_count=1`, `decision="BLOCKING_CONFLICT"`, `reason_code="CASE_ONLY_COLLISION"`, and altered snapshot digest.
  - `tests/test_gate5e_e2_generate.py::test_generate_scandir_failure_raises_case_collision`: Service `create_batch_utility_plan` raises `BatchUtilityCaseCollisionError` and writes 0 Drafts to DB.
  - `tests/test_gate5e_e2_api.py::test_scandir_failure_fails_closed_in_preview_and_generate`: API returns HTTP 409 `BATCH_UTILITY_CASE_COLLISION` and 0 Drafts.

---

## 4. Blocker 2 Root Cause, Fix, and Verification
- **Root Cause**: In [compiler.py](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/compiler.py#L1225), `primary_c = conflicts_by_src[cand_item.source_path][0]` took the first conflict, which was sorted alphabetically (`c.conflict_type`). `"CASE_ONLY_COLLISION"` ("C") eclipsed `"TARGET_SYMLINK"` ("T"), violating the frozen Generate error priority.
- **Fix**:
  1. Defined deterministic ranking `CONFLICT_PRIORITY_RANK`:
     `TARGET_SYMLINK` (1) > `TARGET_OUTSIDE_ALLOWED_ROOT` (2) > `NAME_TOO_LONG` (3) > `CASE_ONLY_COLLISION` (4) > `TARGET_EXISTS` / `PLANNED_TARGET_COLLISION` / `RESERVED_TARGET` / `RENAME_CYCLE` (5).
  2. Implemented `select_primary_conflict(conflicts)` helper to choose the primary conflict row deterministically by priority rank.
  3. Kept raw `graph_res.conflicts` intact so all secondary conflict facts remain recorded in `source_snapshot_payload["conflict_facts"]`.
- **Reviewer Reproduction Tests**:
  - `tests/test_gate5e_e2_compiler.py::test_same_source_conflict_priority_reviewer_case_b`: Single source with both `TARGET_SYMLINK` and `CASE_ONLY_COLLISION` yields primary `reason_code="TARGET_SYMLINK"` in Preview rows, while retaining both facts.
  - `tests/test_gate5e_e2_generate.py::test_generate_same_source_symlink_and_casefold_raises_symlink_blocked`: Service raises `BatchUtilitySymlinkBlockedError` (priority 1) rather than `BatchUtilityCaseCollisionError`.
  - `tests/test_gate5e_e2_api.py::test_same_source_symlink_and_casefold_priority_in_api`: API returns HTTP 409 `BATCH_UTILITY_SYMLINK_BLOCKED` with 0 Drafts created in DB.

---

## 5. Verification Results
- **E2 Focus Suite**:
  `docker run --rm -v $(pwd):/app -w /app -e PYTHONPATH=. nas-test-env:latest pytest -o addopts='' -q tests/test_gate5e_e2_*.py`
  -> **48 passed, 0 failed** in 2.97s.
- **E1 Regression Suite**:
  `docker run --rm -v $(pwd):/app -w /app -e PYTHONPATH=. nas-test-env:latest pytest -o addopts='' -q tests/test_gate5e_e1_*.py`
  -> **29 passed, 0 failed** in 2.91s.
- **Full Backend Regression**:
  `docker run --rm -v $(pwd):/app -w /app -e PYTHONPATH=. nas-test-env:latest pytest -o addopts='' --disable-warnings -q`
  -> **894 passed, 0 failed** in 88.63s.

---

## 6. Architecture & Contract Audits
- **Phase B Write-Lock Restrictions**:
  - Phase B contains 0 Filter compilation (`test_generate_suffix_transform_phase_b_zero_filter_compilation` verified mock call count = 0).
  - Phase B contains 0 filesystem stat, 0 scandir, 0 graph construction, 0 target validation, 0 NAME_MAX validation.
- **Static Forbidden Scope**:
  - 0 forbidden files touched.
  - 0 modifications to `app/service.py`, `app/execution/executor.py`, `app/fs_ops.py`, `app/tasks/handlers.py`, `app/models.py`, `app/workflows/**`, `frontend/**`.
  - 0 database migrations added.
  - 0 new background workers, 0 new undo engines, 0 temporary rename choreography.
  - No E3/E4/E5/Gate5-F/Gate5-G scope touched.
