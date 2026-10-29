# Manually deleted quarantine payload after interrupted cross-storage purge

Issue #357: entries #1106 and #884 were left in `purging` after Docker restart. The owner reports that the public quarantine files were subsequently deleted manually on the NAS. The admin-only read-only diagnosis (PR #361) reported `tx_phase=purging`, `transaction_mode=cross_storage_transactional`, generation 2 (for #1106), and no linked source task/plan. The private `.tx/entry-ID` directory was observed absent, but the public payload path was **indeterminate** (a missing intermediate directory can indicate an offline mount). The regular metadata-only cleanup correctly returned 409.

## Distinct emergency workflow

A separate administrator-only action is exposed in the **恢复诊断** panel for historical cross-storage `purging` entries when the private `.tx` directory is observed absent and the public payload is absent or indeterminate, with no linked provenance work job/plan. The UI **does not itself grant permission**; an explicit per-record confirmation calls:

`DELETE /api/quarantine/{id}/orphan-transaction-record?confirmation=RETIRE_ORPHAN_TX_{id}`

The service will retire the **one DB row only** and record the previous transaction state and operator attestation in `AuditEvent`. It **never** calls unlink, rmdir, rename, filesystem cleanup, Worker recovery or a transaction finalization; it never marks `purged`.

Within a single `BEGIN IMMEDIATE` SQLite transaction it twice validates:

- Administrator identity and mutation/deletion settings; the explicit confirmation token must include the exact record ID.
- The row must be an **old, pre-API-process-restart** `purging` cross-storage transaction at `tx_phase=purging` with positive attempt generation; no linked WorkJob, BatchPlanItem, or restore-target identity.
- No active destructive batch/quarantine Worker job and no pending quarantine purge/restore plan item referencing either original or quarantine path.
- No authoritative anchor outside the expected private `.tx/entry-{id}` namespace, and the **entire private transaction entry namespace must be absent** (even an empty directory blocks).
- A positive frozen `quarantine_device` recorded when the cross-storage file was published must match `st_dev` of the quarantine root opened through an `O_NOFOLLOW` directory FD walk; if the mount is offline/swapped, unknown, or differs, retirement fails.
- The public payload must be absent. Only this explicit, human-attested orphan workflow accepts a missing intermediate directory when the securely opened quarantine root's device matches frozen file identity. A replacement leaf, symlink, inaccessible ancestor or unsafe path fails closed.
- Any failed revalidation results in HTTP 409, with no DB deletion, no filesystem mutation and no success audit.

This is **not** an unqualified force-delete. Stale snapshots and same-device bind mounts remain possible operational concerns; the user is attesting they manually removed the file and should only act on the current known NAS mount. Original NAS files are never touched by this endpoint.

## Operator usage and limitations

1. Make a backup of application SQLite data and confirm NAS mounts are healthy before proceeding. **Do not delete `.tx`, modify SQL manually, or reset Worker state.**
2. Deploy a build that contains the endpoint through the owner's established process; no NAS deployment or real data mutation is performed by repository CI.
3. Log in as administrator, open **文件隔离区 → #1106 / #884 → 恢复诊断**. Review `tx_phase`, mode, payload path observation, and private `.tx` status. If a private directory is present or indeterminate, stop.
4. If the diagnostic displays **已手动删除文件：清理孤儿事务记录**, and the owner truly deleted that public payload, review the permanent DB-record removal confirmation for that ID and confirm once.
5. If the service returns a 409, **do not bypass the safeguards**. Capture the redacted reason and investigate the mount/Worker/Plan/evidence. The two records are independent: an eligible #1106 does not imply an eligible #884.
6. After an eligible success, refresh the quarantine list and verify an audit event with operation `quarantine.orphan_transaction_record_retire`. No claim of transaction completion or restored file may be made.

All tests use isolated temporary filesystem roots and synthetic records. Issue #357 remains open until an owner confirms both real records are retired safely.
