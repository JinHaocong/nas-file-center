# NAS File Center v0.3.5 — Gate5-F Implementation Plan Re-Review 2

## 1. Statement of Authority & Provenance

This document records findings supplied by an external independent reviewer.
The implementation agent is transcribing and addressing those findings and
does not claim to have independently reviewed its own plan.

- **Reviewed Plan Commit:** `e97b4d455597e03fd67c45c8fa2ca7695ee2a7ad`
- **Branch:** `v0.3.5-gate5c-hotfix4`
- **Target Component:** Gate5-F Resource Control Implementation Plan (Revision 2)
- **Status / Verdict:**
  ```text
  Gate5-F Implementation Plan = CHANGES REQUIRED
  New Plan Execution Blockers = 5
  Gate5-F Architecture Freeze = remains APPROVED / CLOSED
  Gate5-F Implementation = NOT AUTHORIZED pending independent re-review
  Gate5-G = FORBIDDEN
  v0.3.5 = NOT CLOSED
  ```

---

## 2. Re-Review Findings & Corrective Actions

### Blocker 1: Nonexistent Pytest Fixtures
- **Finding:** The plan referenced imaginary global `session_factory` and `engine` fixtures, which do not exist in the repository.
- **Resolution:** Replaced all references in test designs with explicit, isolated test database creation via `make_task_db(tmp_path)` using existing `create_engine_and_session` and `init_db`.

### Blocker 2: Task 5 and Task 6 Test Executability
- **Finding:**
  - 5A: Loose/invalid assertion `context=pytest.approx(dict, ...)`.
  - 5B: `FclonesScanHandler` test did not isolate report parsing/import or prevent mock worker lease fencing.
  - 5C: `IndexRootHandler` executed real `FileCenterService.__init__()` with mock settings.
- **Resolution:**
  - Replaced with exact deterministic dictionary field assertions inspecting `context.log.call_args_list`.
  - Added `patch("app.tasks.handlers.parse_fclones_report_iter", return_value=iter(()))` and set `context.worker_id = None`.
  - Initialized real temporary `Settings` for `IndexRootHandler` test while patching `FileCenterService.reindex_root`.

### Blocker 3: Task 7 Time Freezing Before Lease Acquisition
- **Finding:** Lease acquisition occurred before the `utcnow` patch, creating clock skew between lease `acquired_at` and claim evaluation.
- **Resolution:** Moved `acquire_worker_ownership` inside the `with patch("app.tasks.recovery.utcnow", return_value=fixed_outside):` block so all operations share the exact frozen UTC time.

### Blocker 4: Comprehensive Semantic Invalid PUT HTTP 422 Coverage
- **Finding:** The plan tested only a single partial payload `{"scan_threads": 0}`, which might fail on missing fields rather than semantic rules.
- **Resolution:** Built a full matrix based on a complete valid base payload, individually mutating fields (out-of-range integers, bool-as-int, invalid enums, start == end, invalid IANA timezone, extra fields) and asserting HTTP 422 with zero DB mutation. Added router exception handling converting `ResourcePolicyValidationError` to HTTP 422.

### Blocker 5: Deterministic Policy Corruption Test
- **Finding:** Updating timezone with `active_window_enabled = 0` did not trigger timezone evaluation.
- **Resolution:** Updated test to set `active_window_enabled = 1`, `start = '01:00'`, `end = '03:00'`, and `timezone = 'Invalid/Zone'`. Added a secondary test for deleted singleton (`DELETE FROM resource_policy`), proving fail-closed for resource jobs while mutation jobs remain claimable.

---

## 3. Preservation of Prior Fixes

All 10 prior review fixes are preserved:
1. Canonical profile vocabulary: `full | limited | pause`.
2. I/O pressure: `low | normal | unlimited`.
3. `JobContext.log()` interface.
4. `FileCenterService.reindex_root` call seam.
5. Frontend TypeScript `number` types and `api.get<T>` / `api.put<T>` client.
6. Session cookie authentication and Origin/CSRF header testing.
7. Real regression test suite filenames.
8. Deterministic frozen UTC time.
9. Two-phase PUT architecture preventing ZoneInfo file I/O under `BEGIN IMMEDIATE`.
10. Running non-resumable jobs preserved across window transitions.
