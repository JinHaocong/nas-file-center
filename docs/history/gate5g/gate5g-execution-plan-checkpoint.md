# Gate5-G Final Validation Execution Plan Checkpoint — Revision 2 (Closure Fix)

**Date:** 2026-09-10
**Target Branch:** `v0.3.5-gate5c-hotfix4`
**BASE_HEAD:** `17010b037f984d14458669fa31028130f711f683`
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
- **Revision 2 BASE_HEAD:** `17010b037f984d14458669fa31028130f711f683`
- **Prior Closed Gates:** Gate5-A, Gate5-B, Gate5-C, Gate5-D, Gate5-E, and Gate5-F are all PASS / CLOSED.
- **Files Modified in this Checkpoint:**
  - `docs/superpowers/plans/2026-09-10-gate5g-final-validation-execution-plan.md` (Execution Plan)
  - `docs/history/gate5g/gate5g-execution-plan-checkpoint.md` (Execution Plan Checkpoint Record)
- **Production Files Modified:** `0`
- **Test Files Modified:** `0`
- **Frontend Files Modified:** `0`
- **Deployment / Configuration Files Modified:** `0`

---

## 3. Revision 2 Findings & 1:1 Plan Verification Mapping

Revision 2 implements all 13 closure corrections. Every claim in this checkpoint maps one-to-one to executable commands in `2026-09-10-gate5g-final-validation-execution-plan.md`:

1. **Historical ORM Constructors Exact (G4):**
   - Verified all constructors against Gate5-E closed baseline SHA `3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9`.
   - Removed nonexistent `created_at` argument from `BatchPlanItem`.
   - Removed nonexistent `created_at` argument from `IndexedPath`, using historical fields `first_seen_at` and `last_seen_at`.
   - Preserved original pre-migration database untouched in `historical_original_config/app.db`.

2. **Upgrade Candidate Database Identity (G4):**
   - Candidate application container strictly uses `Settings.database_path = CONFIG_DIR / "app.db"`.
   - Created isolated `upgrade_test_config/` directory whose historical copy is named exactly `app.db`.
   - Booted candidate container against `upgrade_test_config:/config`, verified automatic additive migration, gracefully stopped container, and inspected `upgrade_test_config/app.db` offline.
   - Restarted candidate container against the same `app.db` to prove idempotency.

3. **Executable SQLite PRAGMA & Schema / Index / Unique Constraints (G5):**
   - Plan explicitly executes `PRAGMA wal_checkpoint(TRUNCATE)`, `PRAGMA integrity_check` (asserting `[('ok',)]`), and `PRAGMA foreign_key_check` (asserting `0` violations).
   - Confirmed singleton `resource_policy` `id=1, revision=1`.
   - Executed `PRAGMA table_info(resource_policy)` verifying all 11 columns.
   - Executed `PRAGMA foreign_key_list` verifying critical relationships (`batch_plan_items -> batch_plans`, `sessions -> users`).
   - Executed `PRAGMA index_list` verifying unique constraint indexes on `users`, `sessions`, `quarantine_entries`, and `indexed_paths`.
   - Verified required named indexes in `sqlite_master`.

4. **API Response Schema Compliance (G6 & G7):**
   - Replaced all parsing of `source_path` and `keep_path` when querying `/api/plans/{id}/items` with actual returned schema fields `source` and `keep` across both desktop G6 and NAS G7 tasks.

5. **QuarantineEntry State & Path Mapping (G6 & G7):**
   - Asserted `QuarantineEntry.state == "active"` upon successful quarantine execution (prohibiting `"quarantined"`).
   - Asserted `QuarantineEntry.state == "restored"` following restore.
   - Mapped `quarantine_path` to host filesystem using relative path from container `/quarantine` (`os.path.relpath(..., '/quarantine')`), correctly supporting nested quarantine storage structures.

6. **Independent Primary and Stale Duplicate Scenarios (G6 & G7):**
   - Separated primary and stale test groups. The primary dedupe plan and restore cycle execute strictly before the stale duplicate pair is created.
   - Stale scenario begins with a fresh, genuine duplicate pair (`stale_fileA.dat`, `stale_fileB.dat`), followed by an independent scan, preview, draft plan, freeze, disk tampering, validate failure, and execute rejection.

7. **Terminal WorkJob Polling for Indexing & Exact Baseline Comparison (G6):**
   - Captured `work_job_id` from `POST /api/indexes`.
   - Polled `/api/tasks/{work_job_id}` until terminal status `completed`, failing explicitly on `failed`, `cancelled`, or timeout.
   - Implemented exact snapshot comparison asserting identical file sets (unexpected file addition/deletion fails), SHA256 hashes, file sizes, and `mtime_ns`.

8. **Genuinely Reachable Symlink Escape Fixture (G6 & G7):**
   - Mounted external sentinel directory into container at `/sentinel:ro` outside allowed roots (`ALLOWED_ROOTS=/data`).
   - Symlink inside `/data` points to container-internal `/sentinel/external_file.txt`.
   - Asserted escape target exists and symlink resolves from container namespace prior to testing.
   - Verified sentinel file content, size, and hash remain completely unmodified across all mutation stages.

9. **Mandatory NAS Read-Only Matrix (G7):**
   - Validated `/health` HTTP 200 with exact safety flags (`allow_mutation=false`).
   - Verified Worker online and single ownership lease.
   - Completed real Worker-backed scan and real `/api/indexes` WorkJob on NAS filesystem.
   - Verified `fclones` execution inside container on NAS mount.
   - Verified admin `ResourcePolicy` GET and PUT (revision incremented to 2 and read back).
   - Verified ordinary user RBAC rejection (HTTP 403).
   - Proved Zero-Scheduler Invariant (zero scheduled work jobs).
   - Restored `ResourcePolicy` to safe test value prior to mutation stage.

10. **Complete NAS Read-Write Safety Matrix (G7):**
    - Executed primary dedupe lifecycle on NAS storage volume.
    - Performed mandatory quarantine restore, verifying restored file with SHA256 byte equality against original content, and verifying quarantine source cleanup.
    - Executed independent stale duplicate lifecycle: preview, draft, freeze, disk tampering, validate failure, execute rejection with HTTP 409 `PLAN_STALE`.
    - Verified reachable symlink escape and sentinel protection on NAS.
    - Verified zero filesystem escape outside `GATE5G_TEST_ROOT`.

11. **NAS Restart Resilience & State Persistence (G7):**
    - Restarted Worker container and verified heartbeat/lease recovery.
    - Restarted API container and verified healthcheck recovery.
    - Verified SQLite database and `ResourcePolicy` persisted across container restarts.
    - Verified container restart counts `<= 1`, confirming absence of crash loops.

12. **Executable G2 -> G7 Transport Manifest (G2 & G7):**
    - Phase G2 explicitly writes `/tmp/gate5g-image-manifest.env` containing `G2_IMAGE_TAG`, `G2_IMAGE_ID`, `G2_IMAGE_ARCHIVE_PATH`, and `G2_IMAGE_ARCHIVE_SHA256`.
    - Phase G7 explicitly transfers and sources this manifest on the NAS shell, eliminating implicit variable assumptions and enforcing exact bit-for-bit image identity.
