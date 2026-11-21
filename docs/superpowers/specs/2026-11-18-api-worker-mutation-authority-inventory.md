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

## Progress — 2026-11-18: API mutation paths migrated behind Worker

### Completed slice: single quarantine restore

- `POST /api/quarantine/{id}/restore` now validates and enqueues a `quarantine-restore` WorkJob; it returns `202 Accepted` and does not move the quarantined file in the API process.
- The WorkJob freezes the quarantine-entry identity and requested conflict policy / custom destination. The Worker rechecks the frozen DB identity under the active Worker lease before invoking the existing restore implementation.
- The Worker uses the existing SHA-256 integrity check, no-overwrite destination behavior, conflict policy, restore journal and audit event. The existing mid-operation restore implementation is deliberately not advertised as blind retry/resume safe.
- The Restore modal now reports the queued task and invalidates the task-center query rather than claiming the file has already been restored.
- RED evidence: `test_legacy_restore_api_only_enqueues_worker_and_preserves_payload_until_worker_runs` failed on the old route because the API returned 200 and moved the file before the Worker ran.
- GREEN evidence: `Semantic Media Organizer V1.6 TDD` passed both backend-focused tests and frontend typecheck on commit `2b95fb1f28d1f5574d6fe57dfcedf1f3ace3c720`.

### Completed slice: terminal quarantine-record cleanup

- Single and bulk terminal-record deletion now return `202 Accepted` and enqueue `quarantine-record-cleanup`.
- API preflight no longer calls `_cleanup_empty_terminal_tx_artifacts`; the transaction tree remains unchanged until Worker execution.
- The WorkJob freezes each selected record's identity. Worker revalidates the full selection under its active lease, performs bounded artifact cleanup, verifies no unknown artifacts remain, and only then retires metadata with audit evidence.
- RED/GREEN coverage now checks API non-mutation, successful Worker cleanup, and fail-closed behavior for changed source / unknown artifacts.

### Remaining #403 work

- [ ] Finish a complete route/service mutation audit and add a regression gate so no API route or startup hook can mutate media roots.
- [ ] Add API read-only mount regression coverage for every registered route and startup hook.
- [ ] Implement dedicated non-root Worker identity, API read-only media mount, shared SQLite/report/secret permissions and supported NAS ACL validation.
- [ ] Validate the new Archive Recovery Worker-owned output path in the current full Release Validation and UI Validation runs.

Do not change deployment mounts or host permissions before the inventory is complete. This PR remains Draft and no production NAS mount/ACL changes have been made.


## #403 RED→GREEN shared-config permission slice

- On distinct container UIDs (API 10001, Worker 10002), the pre-existing DB / WAL and per-job report assumptions are insufficient: SQLite opens new DBs without a group-write bit, and archive reports default to 0700 directories / 0600 files. A shared numeric GID alone does not grant access.
- `NFC_SHARED_CONFIG_GID` opts **only** the config permission check/creation into a dedicated group-bound mode; Compose sets it to the expected shared GID. Newly created `app.db` / `.db-init.lock` use 0660 and new `archive-recovery-reports` uses 2770 with 0640 report JSON. SQLite WAL/SHM must inherit 0660 from the DB. Existing files/directories failing owner/group/mode/no-follow preflight **stop** rather than being silently chmod/chowned.
- Host operator must provision a separate trusted config mount with owner-controlled group 10000 and appropriate 2770 directories, convert **existing** database/sidecar/lock and reports only after separate backup/maintenance approval, and establish the exact NAS ACL and mapping semantics; the application does not modify pre-existing host ownership or media ACLs.
- The archive password tmpfs channel remains a separate unresolved cross-UID design: API presently uses 0600 token files, which a different Worker UID cannot read. Do not weaken that file mode or claim password-protected archive recovery is cross-UID-ready. Keep #403 open until an independently reviewed, owner-authorized shared ephemeral secret mechanism and real Docker tests exist.
- This is a necessary functional preflight, not exclusive namespace custody. The media organizer execution/quiescence gates remain OFF; NAS media have not been tested.


## #403 isolated shared-memory password channel — candidate implementation

- **RED:** V1.6 focused TDD commits `6bc5138` + `31c6099` demonstrated that neither Compose service had a shared RAM secret mount and legacy 0600 API tokens could not satisfy cross-UID Worker consumption. New mode/collision/symlink tests require fail-closed handling.
- **Implementation candidate:** API UID 10001 and Worker UID 10002 both mount one Docker **named local-driver tmpfs volume** at `/run/nfc-recovery-secrets`. Its mount options require owner 10001, trusted group 10000, 2770 mode, noexec/nosuid/nodev, and 1 MiB cap. This is **not** a separate tmpfs mount for each service.
- Both services explicitly configure `NFC_SECRET_OWNER_UID` and `NFC_SECRET_GROUP_GID`. API creates only exclusive one-time 0640 tokens from unguessable UUIDs and stores only the token in WorkJob; Worker opens with NOFOLLOW and validates file owner, group, mode, maximum length before reading, then safely discards the inode-verified token. Invalid modes, symlinks, missing mount or group mismatches fail closed; no automatic chmod/chown of existing files or any NAS path.
- **Important boundary:** local mountinfo + POSIX metadata cannot establish that two containers have an identical RAM mount. Real two-UID Docker acceptance must verify API writes and Worker reads/removes the *same* token, with unrelated UID denied. Docker local volume mounts need exact NAS engine verification; Docker/Komodo config tests alone are insufficient. Host uid mapping and same-group untrusted process exclusion remain review requirements.
- This does not enable grouped media organization or close #403. NAS and original media remain untouched; #402/#400/#398 gates are unchanged.


## #403 shared subdirectory + Docker media-boundary TDD checkpoint

- RED [commit 338d588](https://github.com/JinHaocong/nas-file-center/commit/338d588b9571f888b1e35ae5927f05baccb30313) / [focused run 44313734697](https://github.com/JinHaocong/nas-file-center/actions/runs/44313734697): four synthetic startup tests failed on existing `reports`, `backups`, `logs`, `home` directory modes and failure to reject legacy-private/symlinked directories before creating the SQLite database.
- Candidate GREEN: when `NFC_SHARED_CONFIG_GID` is configured, `FileCenterService` now requires an existing verified setgid `/config` root, creates **new** subdirectories with group-owned 2770 permissions, and rejects any incompatible **existing** subdirectory without changing its contents/modes/ownership. Without shared-group configuration, existing single-UID behavior is unchanged. This is deliberately a fail-closed startup migration boundary.
- Added `scripts/test_v16_media_bind_mount_boundary.sh` to focused V1.6 CI. It renders the actual Komodo Compose model to assert API `/data:ro`, Worker `/data:rw`, non-root distinct UIDs and default-OFF V1.6 gates; then uses **only disposable GitHub-hosted files** and real Docker bind mounts to assert API file/create/rename/unlink/mkdir denial (EROFS), Worker positive create/rename/unlink, unrelated UID denial, byte-exact original file and zero unexpected residue. It never mounts the NAS and cannot prove the NAS's ACL/SMB namespace custody.
- Owner must separately approve and execute any remediation/migration of *existing* `/config` host directory modes, SQLite files and NAS mount/ACLs. #403 and #402 remain open, PR Draft, no NAS data has been touched. The exact HEAD targeted CI must be confirmed separately before claiming this code is green.


## #403 V1.6 preview reports across distinct UIDs — synthetic RED/GREEN

The first UID split left semantic preview report root `media_package-previews` and full-mapping directories at private 0700, JSONL/summary/mapping files at 0600. Thus the API cannot display Worker-produced previews under UID 10001 when Worker UID 10002 owns the reports. RED commit `9d66a59` reproduced three failures: incompatible root mode, private-dir acceptance, and reader allowing a private 0600 mapping file under shared mode.

**Candidate fix:** when `NFC_SHARED_CONFIG_GID` is explicitly configured, require an existing trusted setgid `/config/reports` parent and create only NEW preview/mapping directories with 2770 and NEW files with 0640 plus expected GID. The API's report and full-mapping reads refuse unexpected mode/GID or symlinks rather than attempting to chmod/chown old evidence. Without opt-in, legacy 0700/0600 behavior is untouched. This is necessary shared-report functionality but does not prove actual distinct host UIDs, NAS ACL or same-UID/root namespace exclusion; it does not relax SEC-12 or authorize media grouping/cleanup.
