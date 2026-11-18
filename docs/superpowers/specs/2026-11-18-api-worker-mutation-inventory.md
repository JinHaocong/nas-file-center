# API / Worker Filesystem Mutation Inventory

Date: 2026-11-18  
Scope: HTTP request process and API startup paths that can mutate configured media/quarantine filesystems.  
PR: #397; prerequisite ticket: #403.  
This is a code-path inventory, not a security approval.

## Deployment facts

- \`app/main.py::create_app\` instantiates \`Gate6A2FileCenterService\`, not the base \`FileCenterService\`.
- The image has no Dockerfile \`USER\`; Compose services have no \`user:\`, so the current API and Worker containers default to UID 0.
- The Komodo Compose definition mounts the SATA data root read-write into both API and Worker.
- API startup currently creates the service/database/report directories, but does not call quarantine payload reconciliation or a media mutation routine. Worker startup owns job recovery/reconciliation.

## Confirmed request-process filesystem mutation paths

| HTTP route | Call path | Actual filesystem effect in API process | Required change |
|---|---|---|---|
| \`POST /api/quarantine/{id}/restore\` | \`app/api/router.py::restore_quarantine_entry\` → \`Gate6A2FileCenterService\` inherited \`FileCenterService.restore_quarantine_entry\` | For legacy/non-transactional rows, verifies the quarantine source, creates destination parent directories, then calls no-replace rename synchronously. For transactional rows, the route does not pass Worker authority, so the transactional branch fails closed rather than executing. | Freeze exact source/destination/identity and enqueue a Worker restore job for legacy rows too; preserve skip/rename/manual conflict policy and response compatibility via a documented async result. |
| \`POST /api/quarantine/{id}/purge\` | route → \`Gate6A2FileCenterService.purge_quarantine_entry\` → \`purge_single_transactional_entry\` → \`execute_journaled_unlink_purge\` | **Confirmed direct destructive path for transactional unlink_v1 rows.** The adapter calls the journaled unlink engine in the HTTP request thread and currently does not supply \`worker_id\`; the engine's Worker lease argument is optional. Legacy/non-transactional rows are rejected by the adapter and do not fall through to the base historical recursive purge. | Replace the synchronous adapter call with a frozen, explicit WorkJob and a Worker handler. Pass and enforce Worker lease before every unlink and terminal audit. |
| \`DELETE /api/quarantine/{id}/record\` | route → \`FileCenterService.delete_quarantine_record\` → \`_cleanup_empty_terminal_tx_artifacts\` → possibly \`_cleanup_abandoned_cross_storage_staging\` | Before metadata deletion or Worker enqueue, API code can unlink the exact verified abandoned/conflict cross-storage staging file and rmdir transaction directories. Purged rows may also have empty transaction directories removed. Restored rows skip this pre-cleanup and later enqueue the existing Worker cleanup job. | Move all filesystem cleanup into the existing \`quarantine-record-cleanup\` Worker job. API should validate metadata and enqueue only. |
| \`POST /api/quarantine/records/bulk-delete\` | route → \`FileCenterService.bulk_delete_quarantine_records\` → \`_cleanup_empty_terminal_tx_artifacts\` → \`_cleanup_abandoned_cross_storage_staging\` or metadata delete / Worker enqueue | Same pre-enqueue direct filesystem cleanup as single record deletion; non-restored selections can then delete metadata synchronously. | Always enqueue the cleanup Worker for selected terminal records; Worker owns filesystem cleanup and metadata retirement after lease checks. |

### Important implementation detail for single purge

Production uses the Gate6-A2 service adapter. The base \`FileCenterService.purge_quarantine_entry\` contains a historical recursive purge implementation, but **that is not the production app's current single-purge path** because \`app/main.py\` instantiates \`Gate6A2FileCenterService\`. The adapter rejects legacy rows and directly runs \`purge_single_transactional_entry\` for transactional unlink_v1 rows. The migration must preserve Gate6-A2 manifest, journal, audit and recovery semantics.

## API routes that create authority but do not mutate media payloads in the request

| HTTP route | Effect |
|---|---|
| \`POST /api/quarantine/bulk-preview\` | Read-only preview and identity evidence |
| \`POST /api/quarantine/bulk-plan\` | Persists a BatchPlan draft and frozen unlink/restore authority; payload mutation occurs only after the plan is executed through the Worker |
| \`POST /api/plans/{id}/execute\` | Enqueues \`batch-plan-execute\` WorkJob |
| \`POST /api/media_package/previews/{id}/execute\` | Enqueues MediaPackage execution WorkJob |
| \`POST /api/media-organizer/.../execute\` | Enqueues V1.6 Worker work; grouped execution remains fail-closed |
| \`POST /api/media/corrupt-delete/plan\` | Persists plan/authority; execution is through the generic plan Worker |
| \`POST /api/batch-utilities/generate-plan\` | Persists a plan; execution is through the generic plan Worker |

## Database-only / inspection routes (no payload mutation identified)

- \`DELETE /api/quarantine/{id}/missing-record\`: verifies absence and removes DB metadata/audit only.
- \`DELETE /api/quarantine/{id}/orphan-transaction-record\`: verifies orphan conditions and removes DB metadata/audit only.
- \`DELETE /api/quarantine/{id}/owner-deleted-record\`: narrow owner-attested DB-only incident override.
- \`GET /api/quarantine/{id}/recovery-diagnostic\`: read-only diagnostic.
- Plan/task/history/profile/settings CRUD and preview endpoints: DB state or read-only filesystem inspection only, based on the current call paths reviewed.

## TDD implementation order for #403

1. **Single purge:** add an API regression proving the request only enqueues a WorkJob and leaves all frozen payload links present; Worker later performs journaled unlink with a valid lease. This is the first RED/GREEN slice.
2. **Record cleanup:** move \`_cleanup_empty_terminal_tx_artifacts\` and abandoned cross-storage staging retirement into the existing Worker handler. Remove filesystem mutations from API enqueue/preflight methods. Preserve metadata-only and restored-record audit semantics.
3. **Restore:** migrate the legacy synchronous restore path to a frozen Worker job; keep conflict policy behavior and recovery.
4. Audit all remaining route/service call paths, then design API read-only / dedicated non-root Worker mounts and shared config/SQLite/report permissions.
5. Add NAS ACL/mount capability evidence. Do not assume POSIX mode bits or an environment ACK proves exclusive namespace custody.

## Release boundary

No automatic production ownership/ACL/mount changes. Keep V1.6 execution switches OFF. API read-only \`/data\` must not be enabled until all direct request-process mutations above have moved to Worker authority and regression tests pass.
