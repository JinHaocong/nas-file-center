# NAS File Center v0.3.5 — Gate5-F Implementation Plan Final Review

## 1. Statement of Authority & Provenance

This document records findings supplied by an external independent reviewer during the final closure review of the Gate5-F Implementation Plan.
The implementation agent is transcribing and addressing those findings and does not claim to have independently reviewed its own plan.

### Historical Lineage & Provenance Note
The revision progression from `065f389d66488e369ce6f2cdd9b312bc1718f55c` to `86c604e75af76da768a8081e0e53fa096b7a8259` contains two docs-only commits:
1. `839ff0acaf730bc84a46c9b38ed850d9c0a9a6cc`: Initial implementation of Revision 4 findings (full fingerprint, fresh lease check, transaction-time active window evaluation).
2. `86c604e75af76da768a8081e0e53fa096b7a8259`: Explicit refinement of deterministic regression tests and canonical task summary.

In accordance with strict project rules, existing commit history was preserved without rebasing or force-pushing.

- **Reviewed Plan Commit:** `86c604e75af76da768a8081e0e53fa096b7a8259`
- **Branch:** `v0.3.5-gate5c-hotfix4`
- **Target Component:** Gate5-F Resource Control Implementation Plan (Final Closure)
- **Status / Verdict:**
  ```text
  Gate5-F Implementation Plan = READY FOR FINAL INDEPENDENT CLOSURE REVIEW
  Final Closure Review Findings Addressed = 3 / 3
  Gate5-F Architecture Freeze = remains APPROVED / CLOSED
  Gate5-F Implementation = NOT STARTED / NOT AUTHORIZED
  Gate5-G = FORBIDDEN
  v0.3.5 = NOT CLOSED
  ```

---

## 2. Final Closure Review Findings & Corrective Actions

### Finding 1: Fresh Worker Lease Age in Boundary Race Test
- **Finding:** The boundary race test in Task 4 acquired Worker ownership at `02:59:00` and evaluated claim at `03:00:00`. Because the Worker lease timeout is 30 seconds, the 60-second lease age triggered `JobLeaseLost` before active-window admission could be evaluated.
- **Resolution:** Adjusted lease acquisition time to `02:59:45` (15 seconds before the 03:00:00 boundary). The Worker lease remains unquestionably fresh (age 15s < 30s timeout), allowing the test to verify that `03:00:00` (exclusive end boundary) correctly evaluates to outside the pause window and holds resource-controlled jobs (`fclones-scan`) while admitting non-resource mutation jobs (`batch-plan-execute`). Maintained both the mutation-claimed case and the only-resource-job case (returning `None`). Retained the separate 35-second lease expiry regression proving stale lease raises `JobLeaseLost`.

### Finding 2: Mandatory Active-Window Evaluator Pure Tests Restored
- **Finding:** Revision 4 accidentally removed explicit test coverage for same-day active window boundaries (inclusive start, exclusive end), cross-midnight active window transitions, and outside limited profile, as required by Architecture Freeze §24.
- **Resolution:** Restored deterministic pure evaluator test cases in Task 1 (`tests/test_gate5f_resource_policy.py`):
  - `test_active_window_same_day_boundaries`: explicitly tests inclusive start (`08:00`), inside window (`17:59`), and exclusive end boundary (`18:00` -> `pause`, resource jobs rejected).
  - `test_active_window_cross_midnight`: explicitly tests cross-midnight window (`23:00` to `07:00`), before midnight (`23:30`), after midnight (`06:59`), exclusive end (`07:00` -> `limited`, thread cap 1), and daytime outside (`12:00` -> `limited`).
  - Retained `test_evaluate_resource_policy_with_pre_resolved_timezone` as additional pre-resolution verification.

### Finding 3: Zero Persisted Mutation on Invalid PUT Verified via State Projection
- **Finding:** The invalid PUT test suite previously checked only `assert get_resp.json()["revision"] == 1`, which did not prove that no uncommitted or partial field modifications occurred in the database.
- **Resolution:** Implemented `PERSISTED_POLICY_KEYS` projection covering all 12 persistent schema fields:
  `("id", "scan_threads", "hash_threads", "io_limit", "job_priority", "active_window_enabled", "active_window_start", "active_window_end", "active_window_timezone", "outside_window_mode", "revision", "updated_at")`.
  Excluded runtime-derived `effective_now`. For every invalid input case (scan_threads=0, scan_threads=true, hash_threads=33, invalid io_limit, invalid job_priority, invalid outside_window_mode, start == end, invalid IANA timezone, extra forbidden field), the test captures before/after projections and asserts `persisted_projection(after) == persisted_projection(before)` alongside HTTP 422.

---

## 3. Preservation of All Prior Review Corrections

All 18 prior findings and 3 Revision 4 findings remain intact:
1. Canonical profile vocabulary: `full | limited | pause`.
2. I/O pressure: `low | normal | unlimited`.
3. `JobContext.log()` real interface.
4. `FileCenterService.reindex_root` real call seam.
5. Frontend TypeScript `number` types and `api.get<T>` / `api.put<T>` client.
6. Session cookie authentication and Origin/CSRF header testing.
7. Real regression test suite filenames.
8. Deterministic frozen UTC time.
9. Two-phase PUT architecture preventing ZoneInfo file I/O under `BEGIN IMMEDIATE`.
10. Running non-resumable jobs preserved across window transitions.
11. Local isolated DB test setup (`make_task_db`), zero imaginary fixtures.
12. Task 5 & Task 6 test executability (exact dictionary log assertions, report parsing isolation, `context.worker_id = None`, real temporary `Settings`).
13. Task 7 time freezing enclosing lease acquisition.
14. Complete semantic invalid PUT HTTP 422 test matrix with zero DB mutation.
15. Deterministically corrupted active window test and missing singleton test.
16. Router canonical `request.app.state.service` access pattern.
17. Strict Pydantic types (`strict=True`) preventing bool-as-int coercion.
18. Bounded retry exhaustion fallback claiming only non-resource jobs.
19. Full policy fingerprint binding in Phase B (`resource_policy_row_fingerprint`).
20. Fresh transaction-time UTC for lease fencing (`now=claim_now`, `now=fallback_now`).
21. Transaction-time active window evaluation in Phase B with pre-resolved timezone.
