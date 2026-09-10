# NAS File Center v0.3.5 — Gate5-F Implementation Plan Re-Review 4

## 1. Statement of Authority & Provenance

This document records findings supplied by an external independent reviewer.
The implementation agent is transcribing and addressing those findings and
does not claim to have independently reviewed its own plan.

- **Reviewed Plan Commit:** `065f389d66488e369ce6f2cdd9b312bc1718f55c`
- **Branch:** `v0.3.5-gate5c-hotfix4`
- **Target Component:** Gate5-F Resource Control Implementation Plan (Revision 4)
- **Status / Verdict:**
  ```text
  Gate5-F Implementation Plan = CHANGES REQUIRED
  New Plan Execution Blockers = 3
  Gate5-F Architecture Freeze = remains APPROVED / CLOSED
  Gate5-F Implementation = NOT AUTHORIZED pending independent re-review
  Gate5-G = FORBIDDEN
  v0.3.5 = NOT CLOSED
  ```

---

## 2. Re-Review Findings & Corrective Actions

### Blocker 1: Full Policy Fingerprint Binding in Phase B
- **Finding:** Comparing `current_rev != expected_revision` only is insufficient. A policy could have uncommitted or concurrent field modifications without revision bump, or revision equality could falsely validate a mutated policy snapshot.
- **Resolution:** Introduced canonical helper `resource_policy_row_fingerprint(row)` capturing a 10-field tuple (`revision`, `scan_threads`, `hash_threads`, `io_limit`, `job_priority`, `active_window_enabled`, `active_window_start`, `active_window_end`, `active_window_timezone`, `outside_window_mode`). Phase B now strictly validates equality of the full policy fingerprint. Added deterministic tests proving same-revision field drift triggers retry and eventual non-resource fallback.

### Blocker 2: Fresh Transaction-Time UTC for Lease Fencing
- **Finding:** Sampling `now = utcnow()` before Phase A and reusing it in Phase B weakened Worker lease fencing, as the lease could expire during Phase A preparation while Phase B evaluated it against the stale timestamp.
- **Resolution:** Removed pre-Phase A lease evaluation. Phase B now samples fresh `claim_now = utcnow()` under `BEGIN IMMEDIATE`, evaluates `assert_active_worker_lease(session, worker_id, now=claim_now)`, and stamps `started_at=claim_now` and `heartbeat_at=claim_now`. Added regression test verifying that lease expiry during Phase A raises `JobLeaseLost` and prevents job claim.

### Blocker 3: Transaction-Time Active Window Evaluation in Phase B
- **Finding:** Evaluating `evaluate_resource_policy` during Phase A and reusing its admission verdict in Phase B allowed race conditions where active window expired (transitioned to outside/pause) between Phase A and Phase B, leading to unauthorized resource job claim.
- **Resolution:** Redesigned protocol so Phase A only prepares the validated snapshot, captures full fingerprint, and pre-resolves/caches the `ZoneInfo` object outside write lock. Phase B under `BEGIN IMMEDIATE` performs the actual active window evaluation against fresh `claim_now` using the prepared timezone object (zero filesystem I/O in Phase B). Added boundary race test (02:59:59 Phase A -> 03:00:00 Phase B) proving resource jobs are safely held when Phase B crosses the window boundary.

---

## 3. Preservation of Prior Fixes

All 18 prior review fixes remain fully preserved:
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
