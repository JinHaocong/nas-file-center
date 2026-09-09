# NAS File Center v0.3.5 Gate5-E / E1 Implementation Walkthrough

## 1. Baseline & Final Context

- **Baseline HEAD**: `c8c9dabf0b6b9500fce0a1d394ea5906e599d8e2`
- **Baseline Artifact**: `nas-file-center-v0.3.5-gate5d-d4-hotfix3.zip`
- **Baseline SHA256**: `f2d0d99bcd8b3db3392e72e996e5347a21807b752f844f1bbc58b079d1429be5`
- **Implementation HEAD**: `7f4980f1c0a27aa5ae6df7737b62683e0d8f786f`
- **Documentation Commit**: `docs(gate5e): record E1 filtered quarantine verification`
- **Current Status**: `Gate5-E E1 IMPLEMENTATION COMPLETE / READY FOR INDEPENDENT REVIEW`

---

## 2. Commit Log

```text
docs(gate5e): record E1 filtered quarantine verification (Task 6)
7f4980f fix(gate5e): preserve final last-file fence in worker execution (Task 5)
388b6d6 feat(gate5e): generate filtered quarantine drafts with preview authority (Task 4)
3ee6968 feat(gate5e): expose authoritative batch utility preview API (Task 3)
39f650e feat(gate5e): compile filtered quarantine previews (Task 2)
36b9e33 feat(gate5e): add batch utility E1 schema and digest primitives (Task 1)
```

---

## 3. Scope Audit

Command executed:
```bash
git diff --name-only c8c9dabf0b6b9500fce0a1d394ea5906e599d8e2...HEAD
```

Output:
```text
app/api/router.py
app/batch_utilities/__init__.py
app/batch_utilities/compiler.py
app/batch_utilities/digest.py
app/batch_utilities/errors.py
app/batch_utilities/schema.py
app/batch_utilities/service.py
app/service.py
app/tasks/handlers.py
tests/test_gate5e_e1_api.py
tests/test_gate5e_e1_compiler.py
tests/test_gate5e_e1_generate.py
tests/test_gate5e_e1_lifecycle.py
tests/test_gate5e_e1_schema.py
```

### Strict Boundaries Adherence:
- `frontend/**`: 0 files modified (0 diff lines).
- `app/models.py`: 0 files modified (0 database schema changes / migrations).
- `app/workflows/**`: 0 files modified (0 new workflow step actions).
- `app/quarantine/**`: 0 files modified (0 custom quarantine engine).
- Static forbidden operation check (`unlink()`, `rmdir()`, `shutil.rmtree()`): 0 occurrences in `app/batch_utilities`.

---

## 4. E1 API Endpoint Contracts

### 4.1 Preview Endpoint
- **Path**: `POST /api/batch-utilities/preview`
- **Status**: `200 OK`
- **Request Body**:
  ```json
  {
    "action": {
      "type": "quarantine_filtered",
      "root_ids": [1],
      "filter": {
        "field": "extension",
        "operator": "eq",
        "value": "txt"
      }
    },
    "page": 1,
    "page_size": 50
  }
  ```
- **Response**:
  ```json
  {
    "utility_action": "quarantine_filtered",
    "utility_engine_version": 1,
    "preview_source": "index-readonly-safety",
    "live_filesystem_verified": false,
    "matched_count": 2,
    "matched_bytes": 14,
    "candidate_count": 2,
    "candidate_bytes": 14,
    "planned_operations_count": 2,
    "skipped_count": 0,
    "safety_excluded_count": 0,
    "blocking_conflict_count": 0,
    "expected_reclaim_bytes": 14,
    "action_config_digest": "...",
    "source_snapshot_digest": "...",
    "preview_digest": "...",
    "effective_safety_policy": {
      "protect_last_file": true,
      "allowed_roots": ["/data/root"],
      "quarantine_root": "/quarantine"
    },
    "page": 1,
    "page_size": 50,
    "total_pages": 1,
    "items": [...]
  }
  ```
- **Semantics**: Read-only, 0 BatchPlan, 0 WorkJob, 0 QuarantineEntry, 0 filesystem modification. Pagination does not affect `preview_digest`.

### 4.2 Generate Draft Endpoint
- **Path**: `POST /api/batch-utilities/generate-plan`
- **Status**: `201 Created`
- **Request Body**:
  ```json
  {
    "action": {
      "type": "quarantine_filtered",
      "root_ids": [1],
      "filter": {
        "field": "extension",
        "operator": "eq",
        "value": "txt"
      }
    },
    "expected_preview_digest": "64_hex_digest..."
  }
  ```
- **Response**:
  ```json
  {
    "id": 1,
    "plan_id": 1,
    "status": "draft",
    "utility_action": "quarantine_filtered",
    "expected_changes": 2,
    "expected_reclaim_bytes": 14,
    "preview_digest": "64_hex_digest..."
  }
  ```
- **Authority Semantics**:
  - Phase A: Authoritative recompile in read session, digest recomputation, lowercase 64-char comparison. Mismatch raises `409 PREVIEW_CHANGED`. Empty actionable intents raises `422 BATCH_UTILITY_EMPTY_PLAN`.
  - Phase B: Short `BEGIN IMMEDIATE` transaction, DB lineage comparison. Mismatch rolls back and raises `409 PREVIEW_CHANGED`.
  - Exactly one `BatchPlan(status="draft", kind="batch-utility")` created; 0 WorkJob created; 0 filesystem modification.

---

## 5. TDD RED -> GREEN Progression

| Task | Component | RED Evidence | GREEN Evidence |
|---|---|---|---|
| **Task 1** | Schema & Digests | `tests/test_gate5e_e1_schema.py` failed due to missing module/classes | 8 passed after implementing Pydantic models with `extra="forbid"`, hex-64 validator, and canonical digest helpers |
| **Task 2** | Compiler | `tests/test_gate5e_e1_compiler.py` failed due to missing `compile_quarantine_filtered_preview` | 7 passed covering root resolution, Gate5-A filter translation, live safety stat checks, aggregate `PROTECT_LAST_FILE` planning, 50k limit |
| **Task 3** | Preview API & Service | `tests/test_gate5e_e1_api.py` failed due to missing route / service method | 3 passed covering 0 side-effects, pagination invariance of `preview_digest`, and Gate5-E structured error envelope |
| **Task 4** | Generate Draft & Authority | `tests/test_gate5e_e1_generate.py` failed with 404 / missing methods | 6 passed covering matching digest (201 Draft), digest mismatch (409), empty plan (422), DB lineage race rollback, item metadata retention |
| **Task 5** | Worker Last-File Fence | `tests/test_gate5e_e1_lifecycle.py` failed (quarantined last file because worker omitted `protected_dir`) | 2 passed after propagating `protected_dir` to `OperationItem` in `BatchPlanExecuteHandler` |

---

## 6. Comprehensive Verification & Regression Results

### 6.1 Focused E1 Test Suite (26 tests)
```text
tests/test_gate5e_e1_schema.py:     8 passed
tests/test_gate5e_e1_compiler.py:   7 passed
tests/test_gate5e_e1_api.py:        3 passed
tests/test_gate5e_e1_generate.py:   6 passed
tests/test_gate5e_e1_lifecycle.py:  2 passed
Total: 26 passed in 2.43s (100% PASS)
```

### 6.2 Gate5-A, Gate5-D & Quarantine Regressions (234 tests)
```text
tests/test_filter_ast.py
tests/test_filter_compiler.py
tests/test_filter_preview.py
tests/test_filter_preview_readonly.py
tests/test_gate4_backend_quarantine_undo.py
tests/test_gate5d_advanced_dedupe_core.py
tests/test_gate5d_dedupe_preview_compiler.py
tests/test_gate5d_dedupe_preview_api.py
tests/test_gate5d_dedupe_generate.py
tests/test_gate5d_dedupe_generate_api.py
tests/test_gate5d_d3_workflow_dedupe.py
Total: 234 passed in 17.54s (0 failures)
```

### 6.3 Full Backend Regression Suite (843 tests)
```text
843 passed, 18 warnings in 83.85s (0:01:23)
Baseline: 817 tests -> Current: 843 tests (+26 tests, 0 failures)
```

---

## 7. Real API Smoke & Mutation Verification

Executed live FastAPI smoke against real temporary SQLite DB and file fixtures:
```text
PREVIEW_STATUS: 200
PREVIEW_DIGEST: bb1f7162a838055b64d93915be7f9819ce09a74fbab6ed6575543e1697b8bd92
PREVIEW_MATCHED: 2
PREVIEW_PLANNED: 2
PREVIEW_DELTA_PLANS: 0
PREVIEW_DELTA_JOBS: 0
PREVIEW_FS_UNCHANGED: True

GENERATE_STATUS: 201
GENERATE_PLAN_ID: 1
GENERATE_STATUS_STR: draft
GENERATE_DELTA_PLANS: 1
GENERATE_DELTA_JOBS: 0
GENERATE_FS_UNCHANGED: True
```

---

## 8. Preserved Architectural Boundaries & Known Scope Exclusions

The following capabilities are deliberately **not implemented** in Gate5-E / E1, in strict conformance with the Architecture Freeze:
- `suffix_transform`: Scheduled for E2.
- `flatten_one_level`: Scheduled for E3.
- `remove_empty_dirs`: Scheduled for E4.
- Frontend UI / stale UX / modal flow: Scheduled for E5.
- Copy / Permanent Delete (`unlink` / `rmdir`): Out of scope for V1.
- New Workflow steps: Preserved for Gate5-F.
