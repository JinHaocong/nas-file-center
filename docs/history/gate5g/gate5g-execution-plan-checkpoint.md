# Gate5-G Final Validation Execution Plan Checkpoint — Revision 4 (Final Freeze-Alignment Closure)

**Date:** 2026-09-10
**Target Branch:** `v0.3.5-gate5c-hotfix4`
**BASE_HEAD:** `fab6be25fd47761a945ca5c05a1bc9ce7e906d88`
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
- **Revision 4 BASE_HEAD:** `fab6be25fd47761a945ca5c05a1bc9ce7e906d88`
- **Prior Closed Gates:** Gate5-A, Gate5-B, Gate5-C, Gate5-D, Gate5-E, and Gate5-F are all PASS / CLOSED.
- **Files Modified in this Checkpoint:**
  - `docs/superpowers/plans/2026-09-10-gate5g-final-validation-execution-plan.md` (Execution Plan)
  - `docs/history/gate5g/gate5g-execution-plan-checkpoint.md` (Execution Plan Checkpoint Record)
- **Production Files Modified:** `0`
- **Test Files Modified:** `0`
- **Frontend Files Modified:** `0`
- **Deployment / Configuration Files Modified:** `0`

---

## 3. Revision 4 Freeze-Alignment Findings & 1:1 Plan Verification Mapping

Revision 4 resolves all 4 freeze-alignment review findings. Every claim in this checkpoint maps one-to-one to executable commands in `2026-09-10-gate5g-final-validation-execution-plan.md`:

1. **Lease-Aware Worker Replacement & Restart (G3, G6, G7):**
   - Respects `WORKER_LEASE_TIMEOUT_SECONDS = 30` and the runtime fact that Worker graceful shutdown does not clear `TaskLock`.
   - Never clears, rewrites, unlocks, or deletes `WorkerState` or `TaskLock` manually.
   - For all 4 Worker replacement/restart scenarios using the same database:
     - G3 Worker restart
     - G6 RO → RW Worker transition
     - G7 RO → RW Worker transition
     - G7 final Worker restart
   - Captures `OLD_WORKER_ID` prior to restart/stop.
   - Polls for natural lease takeover with a 75-second timeout exceeding the 30-second lease timeout.
   - Asserts `NEW_WORKER_ID != OLD_WORKER_ID`, `online == True`, exactly one `WorkerState` row, `TaskLock.locked == True`, `TaskLock.owner == NEW_WORKER_ID`, and `WorkerState.worker_id == NEW_WORKER_ID`.
   - Prohibits enqueuing jobs until ownership takeover is proven; completely eliminates fixed `sleep 3` or `sleep 5` ownership assertions.

2. **All Dedupe-Preview Requests Validated JSON & Response Schema:**
   - Enforced `-H "Content-Type: application/json"` and `-H "Origin: ..."` with body `-d '{}'` for every `/dedupe-preview` call across the entire plan.
   - Fixed G6 stale preview, G7 primary preview, and G7 stale preview.
   - Added dedupe-preview to G7 RO matrix.
   - Parses each preview response and asserts valid content (`'groups' in data`), eliminating unasserted or ignored responses.

3. **G6 Controlled-Stage Zero-Mutation & Freeze Physical Identity Evidence:**
   - Before Preview: captures baseline snapshot of `allowed_root`, `quarantine_root`, and `sentinel_dir` (`sha256`, `size`, `mtime_ns`).
   - After Preview: asserts zero mutations, empty quarantine, and untouched sentinel with `ALLOW_MUTATION=true`, proving Preview preserves the 0-filesystem-mutation contract under active mutation configuration.
   - After Draft generation: repeats filesystem comparison proving draft generation persists DB state while the filesystem remains byte/stat identical.
   - After Freeze: directly inspects `/config/app.db` `BatchPlanItem` verifying `source_path`, `keep_path`, `expected_device > 0`, `expected_inode > 0`, `expected_size == os.lstat(source).st_size`, `expected_mtime_ns == os.lstat(source).st_mtime_ns`, `expected_hash == sha256(source)`.

4. **Dedicated NAS Read-Only Safety Fixture & Full Filesystem Snapshot Equality (G7):**
   - Before starting G7 Stage 1 RO containers, creates dedicated RO fixture inside `GATE5G_TEST_DATA_PATH`: `nas_ro_fileA.dat`, `nas_ro_fileB.dat` (duplicate pair), `nas_ro_unique.txt`, `symlink_to_external -> /sentinel/external_file.txt`, and external sentinel under `GATE5G_TEST_SENTINEL_PATH`.
   - Captures pre-RO baseline snapshot across `DATA`, `QUARANTINE`, and `SENTINEL`.
   - Executes real RO matrix (`/data:ro`, `/quarantine:ro`, `/sentinel:ro`, `ALLOW_MUTATION=false`) with Worker scan, `/api/indexes`, `fclones`, dedupe-preview, Zero-Scheduler delta proof, ResourcePolicy/RBAC checks.
   - Compares complete post-RO snapshot against baseline, asserting `DATA`, `QUARANTINE`, and `SENTINEL` unchanged, and asserts `NAS RO SAFETY = PASS`.
   - Cleans up RO-only test files explicitly recorded as verifier fixture management before constructing the RW fixture.

5. **Checkpoint Truthfulness & Boundary:**
   - Every claim in this checkpoint maps strictly 1:1 to executable commands in the execution plan.
   - Preserved all accepted Revision 1–3 corrections without regression.
   - Authoring agent does not self-approve.

---

## 4. Preserved Historical Corrections (No Regression)

The following previously accepted corrections remain fully preserved in the plan:
- `/api/settings/resource-policy` authoritative endpoint across all occurrences.
- Complete ResourcePolicy replacement payload and fresh GET readback.
- WorkJob count and max(id) delta proof for Zero-Scheduler invariant.
- G7 single WorkerState and TaskLock ownership lease proof.
- Full safe-policy persistence after restart matching `G7_SAFE_POLICY_REVISION`.
- G4 first-start fail-closed healthcheck polling loops.
- HTTP 409 and JSON `error.code == "PLAN_STALE"` assertions.
- Sentinel immutability assertions (`sha256`, `size`, `mtime_ns`).
- PRAGMA `index_list` + `index_info` unique-column constraints proof.
- Authoritative `G7_IMAGE_ARCHIVE_SHA256` production and equality with `G2_IMAGE_ARCHIVE_SHA256`.
- G2/G7 Image ID equality enforcement.
- Historical `app.db` migration identity and isolated `upgrade_test_config`.
- Correct historical ORM constructors matching Gate5-E SHA `3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9`.
- Separation of primary dedupe lifecycle and stale duplicate scenario.
- QuarantineEntry states `active` and `restored`.
- Relative path calculation supporting nested quarantine directories.
- Mandatory byte-identical quarantine restore verification.
- Production mount isolation and ancestry rejection.
- Immutable candidate restart rule.
