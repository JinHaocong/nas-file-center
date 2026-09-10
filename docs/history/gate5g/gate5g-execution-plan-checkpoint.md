# Gate5-G Final Validation Execution Plan Checkpoint — Revision 3 (Final Protocol Closure)

**Date:** 2026-09-10
**Target Branch:** `v0.3.5-gate5c-hotfix4`
**BASE_HEAD:** `6c692e93bb1bc8a9877ddc5fc4bef9544a4b126d`
**APPROVED_FREEZE_HEAD:** `073a69eb1e001e1738c32739f9b57820cba1b05f`

---

## 1. Gate Status Declarations

```text
Gate5-G Architecture / Validation Freeze
= PASS / APPROVED / CLOSED

Gate5-G Execution Plan
= READY FOR FINAL INDEPENDENT CLOSURE REVIEW

Gate5-G Execution
= NOT AUTHORIZED
= NOT STARTED

v0.3.5
= NOT CLOSED
```

> **Review Boundary Notice:**
> This checkpoint records a plan candidate prepared for final external independent closure review.
> The authoring agent does not claim independent approval of its own plan.
> Formal execution of Gate5-G remains NOT AUTHORIZED until independent plan closure review and project-owner approval are granted.

---

## 2. Baseline & Scope Integrity

- **Authoritative Freeze Baseline HEAD:** `073a69eb1e001e1738c32739f9b57820cba1b05f`
- **Revision 3 BASE_HEAD:** `6c692e93bb1bc8a9877ddc5fc4bef9544a4b126d`
- **Prior Closed Gates:** Gate5-A, Gate5-B, Gate5-C, Gate5-D, Gate5-E, and Gate5-F are all PASS / CLOSED.
- **Files Modified in this Checkpoint:**
  - `docs/superpowers/plans/2026-09-10-gate5g-final-validation-execution-plan.md` (Execution Plan)
  - `docs/history/gate5g/gate5g-execution-plan-checkpoint.md` (Execution Plan Checkpoint Record)
- **Production Files Modified:** `0`
- **Test Files Modified:** `0`
- **Frontend Files Modified:** `0`
- **Deployment / Configuration Files Modified:** `0`

---

## 3. Revision 3 Protocol Closure & 1:1 Plan Verification Mapping

Revision 3 implements all 11 final protocol closure corrections. Every claim in this checkpoint maps one-to-one to executable commands in `2026-09-10-gate5g-final-validation-execution-plan.md`:

1. **G7 ResourcePolicy Endpoint Exact:**
   - Replaced every G7 occurrence of `/api/resource-policy` with the authoritative endpoint `/api/settings/resource-policy`.
   - Covers admin GET, admin PUT, normal-user RBAC rejection (HTTP 403), safe policy restore, and post-restart persistence verification.
   - Zero modifications to production API.

2. **ResourcePolicy Full Replacement Payload & Readback Verification:**
   - Complying with `ResourcePolicyUpdateRequest(extra="forbid")`, removed nonexistent `expected_revision`.
   - PUT sends complete 9-field valid payload (`scan_threads`, `hash_threads`, `io_limit`, `job_priority`, `active_window_enabled`, `active_window_start`, `active_window_end`, `active_window_timezone`, `outside_window_mode`).
   - Asserts HTTP 200 and `revision == old_revision + 1`.
   - Fresh GET readback verifies every persisted field matches intended configuration.
   - Sets complete known-safe policy before mutation stage and captures `G7_SAFE_POLICY_REVISION`.

3. **Zero-Scheduler WorkJob Delta Proof:**
   - Eliminated invalid query `WorkJob.status == "scheduled"` (`"scheduled"` is not a Task Engine state).
   - Finishes explicit scan and index jobs, then captures baseline `G7_WORKJOB_COUNT_BEFORE_POLICY` and `G7_WORKJOB_MAX_ID_BEFORE_POLICY`.
   - Performs active-window ResourcePolicy PUT and waits `sleep 6` across multiple worker polling iterations.
   - Queries WorkJob again and asserts count and max(id) unchanged (`AUTOMATIC_JOBS_CREATED = 0`), proving zero automatic jobs were spawned.

4. **Executable G7 Single-Worker Ownership Proof:**
   - Following `/api/tasks/worker` heartbeat check, added authoritative DB proof matching G3:
     - `WorkerState` record count == 1.
     - `TaskLock` `id=1` exists and has `locked == True`.
     - `TaskLock.owner == WorkerState.worker_id`.

5. **Strengthened Restart Persistence & DB Integrity Proof:**
   - After Worker and API container restarts, verifies `/config/app.db` via `PRAGMA integrity_check` returning `[('ok',)]`.
   - Performs GET `/api/settings/resource-policy` and compares against safe policy written before mutation stage, asserting all 10 fields (`scan_threads`, `hash_threads`, `io_limit`, `job_priority`, `active_window_enabled`, `active_window_start`, `active_window_end`, `active_window_timezone`, `outside_window_mode`, and `revision == G7_SAFE_POLICY_REVISION`).

6. **G4 Initial Health Polling Fails Closed:**
   - Added deterministic fail-closed healthcheck polling loops (`HEALTH_OK=0` / `UPGRADE_HEALTH_OK=0`) with max 30 attempts.
   - Explicitly asserts `[ "${HEALTH_OK}" = "1" ]` / `[ "${UPGRADE_HEALTH_OK}" = "1" ]`, dumping `docker logs` and exiting 1 on timeout before any DB inspection.

7. **Exact PLAN_STALE Error Identity:**
   - For both desktop G6 and NAS G7 stale Execute:
     - Captures HTTP status code and response body.
     - Asserts HTTP status == 409.
     - Asserts JSON `error.code == "PLAN_STALE"`.

8. **Complete Sentinel Immutability Evidence:**
   - For both desktop G6 and NAS G7:
     - Records SHA256, size, and `mtime_ns` prior to mutation.
     - Following all scan, index, dedupe, stale, and restore actions, asserts all three properties (`sha256`, `size`, `mtime_ns`) remain strictly unchanged.
     - Sentinel remains mounted read-only outside `ALLOWED_ROOTS`.

9. **Tightened Unique-Constraint Verification:**
   - Using `PRAGMA index_list` combined with `PRAGMA index_info(<index>)`, inspects indexed column names.
   - Proves verified unique constraints on:
     - `users.username`
     - `sessions.token_hash`
     - `quarantine_entries.quarantine_path`
     - `indexed_paths.absolute_path`

10. **Normalized G7 Archive Evidence Variable:**
    - After NAS archive verification, explicitly sets `G7_IMAGE_ARCHIVE_SHA256="${NAS_ARCHIVE_SHA256}"`.
    - Asserts `G7_IMAGE_ARCHIVE_SHA256 == G2_IMAGE_ARCHIVE_SHA256`, directly satisfying Phase G8 audit prerequisite.

11. **Checkpoint Truthfulness & Boundary:**
    - Every claim in this checkpoint maps strictly 1:1 to executable commands in the execution plan.
    - Preserved all accepted Revision 2 corrections without regression.
    - Authoring agent does not self-approve.

---

## 4. Preserved Historical Corrections (No Regression)

The following previously accepted corrections remain fully preserved in the plan:
- Correct historical ORM constructors matching Gate5-E SHA `3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9`.
- Dedicated `upgrade_test_config/app.db` ensuring untouched `historical_original_config/app.db`.
- PRAGMA `wal_checkpoint(TRUNCATE)`, `integrity_check`, and `foreign_key_check`.
- Plan-item API schema fields `source` and `keep`.
- QuarantineEntry states `active` and `restored`.
- Relative path calculation supporting nested quarantine directories.
- Separation of primary dedupe lifecycle and stale duplicate scenario.
- Terminal WorkJob polling for `/api/indexes`.
- Reachable `/sentinel` symlink traversal testing.
- NAS host mount isolation and ancestry rejection against production paths.
- G2 transport manifest `/tmp/gate5g-image-manifest.env`.
- G2/G7 Image ID equality enforcement.
- NAS read-only verification before read-write testing.
- Mandatory byte-identical quarantine restore verification.
- Restart resilience with restart count `<= 1`.
- Dynamic G8 evidence audit table.
- Immutable candidate restart rule.
