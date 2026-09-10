# Gate5-G Final Validation Execution Plan Checkpoint — Revision 1

**Date:** 2026-09-10
**Target Branch:** `v0.3.5-gate5c-hotfix4`
**BASE_HEAD:** `86ebf712bce619bcfdaf564cf29b577215c79b9c`
**APPROVED_FREEZE_HEAD:** `073a69eb1e001e1738c32739f9b57820cba1b05f`

---

## 1. Gate Status Declarations

```text
Gate5-G Architecture / Validation Freeze
= PASS / APPROVED / CLOSED

APPROVED_FREEZE_HEAD =
073a69eb1e001e1738c32739f9b57820cba1b05f

Gate5-G Execution Plan
= CANDIDATE / READY FOR INDEPENDENT REVIEW

Gate5-G Execution
= NOT AUTHORIZED
= NOT STARTED

v0.3.5
= NOT CLOSED
```

> **Review Boundary Notice:**
> This checkpoint records a plan candidate prepared for external independent review.
> The authoring agent does not claim independent approval of its own plan.
> Formal execution of Gate5-G remains NOT AUTHORIZED until independent plan review and project-owner approval are granted.

---

## 2. Baseline & Scope Integrity

- **Authoritative Freeze Baseline HEAD:** `073a69eb1e001e1738c32739f9b57820cba1b05f`
- **Revision 1 BASE_HEAD:** `86ebf712bce619bcfdaf564cf29b577215c79b9c`
- **Prior Closed Gates:** Gate5-A, Gate5-B, Gate5-C, Gate5-D, Gate5-E, and Gate5-F are all PASS / CLOSED.
- **Files Modified in this Checkpoint:**
  - `docs/superpowers/plans/2026-09-10-gate5g-final-validation-execution-plan.md` (Execution Plan)
  - `docs/history/gate5g/gate5g-execution-plan-checkpoint.md` (Execution Plan Checkpoint Record)
- **Production Files Modified:** `0`
- **Test Files Modified:** `0`
- **Frontend Files Modified:** `0`
- **Deployment / Configuration Files Modified:** `0`

---

## 3. Revision 1 Independent Review Findings & Resolutions

Revision 1 addresses all findings identified during independent review to ensure full executability, safety, and alignment with the Freeze specification:

1. **Header Spec Link:**
   - Updated spec reference link to repository-relative path `docs/superpowers/specs/2026-09-10-gate5g-final-validation-design.md`.

2. **Phase G2 / G3 Executable Verification:**
   - Replaced string checking of python version with programmatic assertion `sys.version_info >= (3, 12)`.
   - Verified non-empty `/app/frontend/dist/index.html` via `test -s`.
   - Asserted exact safety flags on `/health` (`status="ok"`, `allow_mutation=false`, `allow_delete=false`, `protect_last_file=true`).
   - Authenticated via real session cookie, verified single worker online status via API and direct DB query confirming exactly one `WorkerState` entry and active `TaskLock` owner lease.
   - Enforced container restart count assertions (`RestartCount <= 1`) proving zero crash-looping.

3. **Phase G4 Fresh Installation via Actual Application Container:**
   - Replaced direct `init_db()` validation with actual candidate container startup against an empty disposable CONFIG directory.
   - Polled `/health` until healthy, gracefully stopped container, and inspected SQLite tables offline.
   - Proved idempotency by restarting the candidate container against the same database.
   - Avoided false assertions of admin creation without bootstrap environment credentials.

4. **Phase G4 Historical Migration Determinism & Model Accuracy:**
   - Eliminated external network `pip install` by running historical database construction inside candidate container `${G2_IMAGE_TAG}` mounting historical source archived from `3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9`.
   - Seeded database adhering strictly to historical model schema:
     - `BatchPlan.id` (INTEGER), `BatchPlanItem.id` (INTEGER), `BatchPlanItem.sequence` (INTEGER).
     - `OperationJournal` with fields `operation`, `sequence`, `plan_id`, `plan_item_id`, `task_id`, `user_id`, `before_json`, `after_json`, `metadata_before_json`, `metadata_after_json`.
     - Password hashing via Argon2 (`app.auth.password.hash_password`), not bcrypt.
   - Seeded representative records across User, Session, completed/queued WorkJobs, BatchPlan, BatchPlanItem, ScanJob, IndexedPath, and OperationJournal.
   - Booted candidate application container against a copy of the pre-migration DB, verified automatic migration, graceful stop, offline DB verification, and idempotency restart.

5. **Phase G5 SQLite PRAGMA & Schema / Index Verification:**
   - Executed `PRAGMA table_info`, `foreign_key_list`, `index_list`, `integrity_check`, and `foreign_key_check`.
   - Asserted newly added `resource_policy` columns and required indexes (`ix_work_jobs_status`, `ix_work_jobs_kind`, `ix_batch_plan_items_plan_state`, `ix_operation_journal_plan_sequence`, `ix_indexed_paths_root_relative`).

6. **Phase G6 Read-Only Safety via Real Worker:**
   - Replaced inline database edits with real Worker-backed scan (`POST /api/scans` with name & roots) and index (`POST /api/indexes`).
   - Polled scan until Worker set status to `completed`.
   - Triggered dedupe preview and asserted zero filesystem mutation before vs after via baseline SHA256 hashes, sizes, and mtimes.

7. **Phase G6 Controlled Dedupe Lifecycle:**
   - Implemented real dedupe chain: `POST /api/scans` -> `dedupe-preview` -> capture preview digest -> `dedupe-plan` -> `freeze` -> inspect items -> `validate` -> `execute` -> poll WorkJob until completed.
   - Dynamically extracted plan-derived `keep_path`, `source_path`, and `item_id` without hardcoding file roles.
   - Verified protected keep file preserved and planned mutation source moved to quarantine root.
   - Associated executed item with its `QuarantineEntry`.

8. **Phase G6 Genuine Stale Preflight Protection:**
   - Constructed a separate duplicate group (`stale_group`).
   - Executed real scan, preview, draft plan, and freeze.
   - Modified actual source file on disk.
   - Verified `validate` fails and `execute` returns HTTP 409 `PLAN_STALE`.

9. **Phase G6 Mandatory Quarantine Restore:**
   - Identified the specific `QuarantineEntry` ID created during dedupe execution.
   - Called `POST /api/quarantine/{id}/restore`.
   - Verified entry state transitioned to `restored`.
   - Verified file restored to original destination with byte-for-byte identical SHA256 and size, and quarantine source deleted.

10. **Phase G7 Isolation & Ancestry Overlap Check:**
    - Established dedicated disposable testbed outside production data and config paths.
    - Implemented programmatic canonical realpath check rejecting testbed if it equals, is an ancestor of, or is a descendant of production directories.

11. **Phase G7 Real NAS Exact Image Substitution:**
    - Used programmatically substituted `${G2_IMAGE_TAG}` in transient compose manifest outside git worktree.
    - Prohibited building or floating pulling on NAS.

12. **Phase G7 Staged RO -> RW Sequence on NAS:**
    - Stage 1: Deployed read-only mode (`/data:ro`, `ALLOW_MUTATION=false`), verified health and read operations.
    - Stage 2: Switched to read-write mode, executed full dedupe lifecycle on NAS storage volume, verified plan-derived quarantine, and executed mandatory quarantine restore.

13. **Phase G8 Final Evidence Audit:**
    - Implemented unified evidence matrix capturing `KNOWN_LIMITATIONS` and raw deprecation warnings dynamically.
