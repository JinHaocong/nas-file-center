# NAS File Center v0.3.5 — Gate5-F Implementation Plan Re-Review 3

## 1. Statement of Authority & Provenance

This document records findings supplied by an external independent reviewer.
The implementation agent is transcribing and addressing those findings and
does not claim to have independently reviewed its own plan.

- **Reviewed Plan Commit:** `8c168cd1b773bf02a72aef351310bae82023ea0a`
- **Branch:** `v0.3.5-gate5c-hotfix4`
- **Target Component:** Gate5-F Resource Control Implementation Plan (Revision 3)
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

### Blocker 1: API Router Service Access Pattern
- **Finding:** The plan referenced a nonexistent `Depends(get_service)` injection. The repository canonical pattern is `request.app.state.service`.
- **Resolution:** Replaced all endpoint signatures in Task 3 with `request: Request` accessing `request.app.state.service.get_resource_policy()` and `request.app.state.service.update_resource_policy()`. Added explicit imports for `typing.Literal`, `Request`, and `ResourcePolicyValidationError`.

### Blocker 2: Genuinely Strict Request Integer Validation
- **Finding:** `scan_threads: int = Field(..., ge=1, le=32)` allows Pydantic to coerce boolean (`{"scan_threads": true}`) or string values before service validation, potentially passing invalid types.
- **Resolution:** Enforced `strict=True` on numeric and boolean fields (`scan_threads`, `hash_threads`, `active_window_enabled`). Defined clear division: schema/type errors rejected by Pydantic as HTTP 422; semantic errors (`start == end`, invalid IANA timezone) raised as `ResourcePolicyValidationError` and converted by router to HTTP 422. Preserved the complete valid-base-payload mutation matrix.

### Blocker 3: Bounded Claim-Race Retry Exhaustion Semantics
- **Finding:** The plan specified bounded retries (up to 3 attempts) when ResourcePolicy changes between Phase A and Phase B, but did not define behavior upon retry exhaustion.
- **Resolution:** Formulated explicit canonical fallback semantics: upon 3 unstable snapshot attempts, the worker MUST NOT use a stale policy or claim resource-controlled jobs (`index-root`, `fclones-scan`); these jobs remain queued without fabricating paused/failed/lease-lost states. Under the fallback transaction, eligible non-resource-controlled mutation jobs may still be claimed. Added deterministic tests covering both mutation-claimed and resource-only-none scenarios.

---

## 3. Preservation of Prior Fixes

All 10 original review fixes and 5 Revision 2 fixes remain fully preserved:
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
