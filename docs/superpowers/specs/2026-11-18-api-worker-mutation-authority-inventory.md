# API / Worker mutation-authority inventory

Status: **INITIAL ROUTE + SERVICE INVENTORY — NOT A RELEASE APPROVAL**
Date: 2026-11-18
Related: PR #397, issue #403, blockers #399/#400/#401/#402

## Goal

The API container must not have write authority over media roots. Filesystem mutations under configured allowed roots must be performed by the dedicated, non-root Worker principal after the existing authorization, confirmation, frozen-authority and recovery checks.

This inventory distinguishes:
- **API → /data write**: request handling can create, rename, unlink or remove entries under an allowed media root.
- **API → Worker**: API validates/persists a WorkJob; Worker owns the filesystem operation.
- **Metadata/read-only**: API may read media paths or write SQLite/configuration metadata, but does not mutate media roots.

This is an initial call-graph audit of the current PR #397 head. It is not a claim that every transitive filesystem operation in the repository has been exhaustively audited.

## Confirmed API-side media-root mutation paths

| Route | Current call path | Filesystem effect | Required change |
|---|---|---|---|
| `POST /api/quarantine/{id}/restore` | `app/api/router.py::restore_quarantine_entry` → `Gate6A2FileCenterService.enqueue_quarantine_restore` | **Migrated:** API validates the destination and freezes the quarantine-entry identity, then queues `quarantine-restore`; it does not rename or create media paths. Worker checks the frozen identity and active lease before invoking the existing integrity/conflict/journal restore implementation. | Worker-owned; focused restore, conflict-policy, journal and frontend tests pass. Full regression passed on the preceding candidate. |
| `DELETE /api/quarantine/{id}/record` | `delete_quarantine_record` → `_enqueue_quarantine_record_cleanup` | **Migrated:** API validates terminal state and freezes the record identity; it does not remove `.tx` artifacts or retire the record. | Returns `202`; Worker revalidates the frozen record, performs bounded transaction-artifact cleanup, then retires metadata and records audit evidence. |
| `POST /api/quarantine/records/bulk-delete` | `bulk_delete_quarantine_records` → `_enqueue_quarantine_record_cleanup` | **Migrated:** API validates the complete selection and freezes each record identity; it performs no transaction-artifact cleanup. | Returns `202`; Worker revalidates the full selection, performs bounded cleanup and all-or-nothing metadata retirement with per-entry audit evidence. |
| `POST /api/archive-recovery/start` | `app/archive_recovery/router.py::start_archive` → `archive-recovery` WorkJob | **Migrated:** API now freezes source + parent device/inode and queues the job; it performs no media-root mkdir/rmdir. Worker validates the frozen identities, opens the parent with no-follow directory semantics, creates the sibling output exclusively at mode `0700`, and persists its device/inode before extraction. | Worker-owned. Keep the secret channel separate, bounded and readable by the Worker without granting API write access to media roots. |

### Important details

- `Gate6A2FileCenterService.purge_quarantine_entry` already queues `quarantine-single-purge`; the API route returns `202 Accepted`. The actual unlink is performed by its Worker handler. Keep this boundary.
- Single and bulk terminal-record deletion now enqueue `quarantine-record-cleanup`; API preflight no longer calls filesystem cleanup. Worker owns artifact cleanup and metadata retirement. Keep this boundary covered by the API-no-write and worker-execution regression tests.
- The `owner-deleted-record`, `orphan-transaction-record` and `missing-record` endpoints are currently metadata-only retirement paths. The orphan/missing checks inspect filesystem state but do not unlink or rename media. Keep them explicitly metadata-only and retain their no-filesystem-mutation audit fields.
- `POST /api/quarantine/bulk-plan` creates a database draft; it does not execute restore or purge. Actual plan execution must remain Worker-owned.

## Existing Worker-owned media operations

The following API surfaces currently persist or enqueue work rather than directly mutating media roots; preserve this pattern:

| API surface | Current boundary |
|---|---|
| `POST /api/plans/{plan_id}/execute` and plan stage-task enqueue | WorkJob/Worker execution |
| `POST /api/media_package/previews`, execute and recover | Worker jobs |
| `POST /api/media-organizer/previews`, execute and recover | Worker jobs; grouped V1.6 execution remains blocked by SEC-12 |
| `POST /api/scans` | Scan WorkJob |
| `POST /api/download-verification` | Verification WorkJob |
| `POST /api/archive-recovery/start` | API queues intent only; Worker creates and binds the output directory under the frozen source-parent identity |

## Read-only / metadata-only paths

- Filesystem listing, media summaries, integrity analysis, preview, mapping reads and recovery diagnostics are read-only with respect to media contents.
- Index, plan, workflow, task, schedule, favorite/recent and policy CRUD primarily writes SQLite/configuration metadata. These writes do not justify a read-write media-root mount in the API container.
- `FileCenterService.__init__` calls startup reconciliation. The audited reconciliation paths use existence/stat/hash reads and update SQLite state; no media rename/unlink/create operation was found in those functions. Add a regression test so future startup reconciliation cannot silently gain API-side media mutation.
- Download-verification reports, logs, SQLite, and archive password tokens have separate config/tmpfs storage requirements. They must be inventoried for shared API/Worker access, but are not a reason to mount media roots read-write in the API.

## Deployment target (not yet implemented)

1. API: dedicated non-root UID/GID, media roots mounted read-only, no capability that can override mount permissions.
2. Worker: dedicated non-root UID/GID, media roots read-write only where required, no root execution and no ambient privileged capabilities.
3. API and Worker share only the required SQLite/WAL, report, log and secret channels with deliberate ownership/group permissions. Do not solve this with broad `chmod 777` or automatic host `chown`.
4. Docker Compose and Komodo definitions must agree. The current `compose.yaml` has a configurable `DATA_MODE` default, but `compose.komodo.yaml` mounts `/data:rw` into both API and Worker and neither service declares a non-root `user:`; the Dockerfile has no `USER` instruction.
5. POSIX ACL / NAS ACL and mount identity must be checked on the actual supported filesystem. If named ACL entries, SMB mappings, FUSE behavior or shared UID processes prevent an exclusive Worker namespace, execution remains blocked.

## TDD slices

- [x] RED/GREEN: single restore API queues a Worker job; frozen identity, active lease, SHA256/conflict behavior and journal evidence are covered.
- [x] RED/GREEN: single and bulk terminal-record deletion queue Worker jobs; API leaves `.tx` artifacts untouched and Worker revalidates before cleanup/retirement.

- [x] RED/GREEN: archive-recovery API request only queues; Worker creates the output directory with exclusive binding to the frozen parent/source identity and persists the created inode before extraction.
- [x] Worker failure cleanup and restart cleanup are fenced to the frozen parent + output directory identities.
- [ ] RED: API container with `/data:ro` cannot mutate media through any registered API route or startup hook.
- [ ] GREEN: all legacy mutation workflows remain functional through Worker jobs; API read-only and Worker non-root deployment tests pass.
- [ ] Add a static route/service mutation inventory test or equivalent review gate so newly added direct media-root writes cannot bypass this boundary.

## Release restrictions

- Keep `MEDIA_ORGANIZER_EXECUTION_ENABLED=false` and `MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK=false`.
- Do not automatically change NAS ownership, POSIX ACLs, SMB ACLs or host mount permissions.
- Do not switch the production API mount to read-only until every confirmed direct mutation path above has been migrated and regression-tested.
- This inventory does not close #402: a dedicated Worker identity and real mount-level custody proof are prerequisites, not a substitute for independent review.
- PR #397 remains Draft; no merge, deployment or Docker release until #398–#403 dependencies, complete cleanup/finalization, full CI and owner-approved same-mount acceptance are satisfied.

## Progress — 2026-11-18: first API mutation moved behind Worker

### Completed slice: single quarantine restore

- `POST /api/quarantine/{id}/restore` now validates and enqueues a `quarantine-restore` WorkJob; it returns `202 Accepted` and does not move the quarantined file in the API process.
- The WorkJob freezes the quarantine-entry identity and requested conflict policy / custom destination. The Worker rechecks the frozen DB identity under the active Worker lease before invoking the existing restore implementation.
- The Worker uses the existing SHA-256 integrity check, no-overwrite destination behavior, conflict policy, restore journal and audit event. The existing mid-operation restore implementation is deliberately not advertised as blind retry/resume safe.
- The Restore modal now reports the queued task and invalidates the task-center query rather than claiming the file has already been restored.
- RED evidence: `test_legacy_restore_api_only_enqueues_worker_and_preserves_payload_until_worker_runs` failed on the old route because the API returned 200 and moved the file before the Worker ran.
- GREEN evidence: `Semantic Media Organizer V1.6 TDD` passed both backend-focused tests and frontend typecheck on commit `2b95fb1f28d1f5574d6fe57dfcedf1f3ace3c720`.

### Remaining direct API mutation paths

- [ ] Single and bulk quarantine-record deletion still invoke `_cleanup_empty_terminal_tx_artifacts` before any Worker handoff. Move the complete cleanup + metadata retirement sequence behind a Worker job.
- [ ] Archive recovery still creates its sibling output directory and removes it on API-side enqueue failure. Move output-directory creation/binding to the Worker.
- [ ] Add API read-only mount regression coverage for every registered route and startup hook.
- [ ] Implement dedicated non-root Worker identity, API read-only media mount, shared SQLite/report/secret permissions and supported NAS ACL validation. Do not change deployment mounts or host permissions before the inventory is complete.

Full Release Validation and UI Validation are still required after the complete migration; focused V1.6 TDD success is not release approval.

## Progress — 2026-11-18: Archive Recovery output creation migrated

- API `POST /api/archive-recovery/start` no longer calls `mkdir` or `rmdir` beneath a media root. It stores the source identity, parent identity, output candidate and request intent only.
- API preflight no longer claims that the API container's filesystem write permission proves Worker write capability. It reports `mutation_enabled` and `worker_write_check_required`; the Worker verifies actual access at execution time.
- Worker creates the output directory with `mkdirat` semantics relative to the frozen parent directory descriptor, after a lease refresh and source inode/size/mtime check. It requires a same-device, Worker-owned, mode-`0700` directory.
- The created directory device/inode is persisted in WorkJob state before archive extraction. Failure/restart cleanup checks both the frozen parent and output identities.
- Added an API regression proving the queued request leaves the sibling output path absent and stores no output identity before Worker execution.
- Full CI for this commit is pending; this is not yet a #403 closure or deployment approval.
