# V1.6 Complete Organizer Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans with test-driven-development. No production code without an observed failing test.

**Goal:** Finish real P/V grouped publication, safe original/wrapper cleanup and zero-change repeated scans without false security claims.

**Architecture:** Verified exclusive NAS namespace custody is a precondition for group publication and source-path deletion. Group directory publication removes name-based private pending-directory rename; all file publication remains source-FD pinned. A crash-safe journal drives finalization.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy WorkJobs, pytest, React/TypeScript, Linux renameat2/linkat, Docker.

**Spec:** `docs/superpowers/specs/2026-11-18-media-organizer-v16-complete-execution-design.md`

## Global Constraints

- Never modify production NAS media from CI, GitHub automation or without separate live authorization.
- Preserve defaults `MEDIA_ORGANIZER_EXECUTION_ENABLED=false`, `MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK=false`.
- Never treat a user ACK, a Worker lease or after-the-fact inode checks as exclusion of an uncooperative writer.
- No foreign file/dir deletion or relocation in fault-injection tests; no overwrite.
- Keep PR #397 Draft, no merge/release until complete behavior is verified.

## Review Focus

- Same-UID/root/SMB writers with parent directory mutation permission; fail closed without demonstrated isolation.
- Direct mkdir followed by swapped child before first open; cannot silently adopt foreign inode.
- Crash between source check and unlink; cannot unlink a foreign replacement.
- Existing numbered P/V groups and P1 wrappers in deep recursion; preserve every byte and collision suffix.
- Stale frozen manifests/mount identity and reordered directory entries; never double-execute.

## Tasks

### Task 1: Record real namespace trust model and capability gate

Files: `app/batch/media_organizer_capability_probe.py`, `app/batch/media_organizer_execution.py`, `tests/test_media_organizer_namespace_custody.py`, `docs/media-organizer-v16-execution-gate.md`.

- [ ] Write RED tests for shared-UID/group-writable/ACL/mount mismatches and rejection *before staging*.
- [ ] Verify RED in the dedicated V1.6 TDD workflow.
- [ ] Implement an enforceable custody validation interface; if mount proof cannot be obtained, return a hard stop. No bool-only bypass.
- [ ] Verify GREEN and record the limits of the proof.
- [ ] Commit.

### Task 2: Replace pending directory promotion

Files: `app/batch/media_organizer_publish.py`, `app/batch/media_organizer_deferred_cleanup.py`, `tests/test_media_organizer_pending_group_race.py`, `tests/test_media_organizer_publish.py`.

- [ ] RED: mixed P/V group under a mock/proven exclusive namespace publishes exact directory/file bindings; fault-injected source swap cannot relocate foreign directory.
- [ ] RED: crash before group receipt cannot adopt an unrecognized folder.
- [ ] Implement exclusive direct group creation under verified custody with durable receipt and FD-bound file links; remove V1.6 reachability of pending source rename.
- [ ] GREEN: all targeted group publication + recovery tests; commit.

### Task 3: Crash-safe audited cleanup and zero-change rescan

Files: `app/batch/media_organizer_cleanup_jobs.py`, `app/batch/media_organizer_deferred_cleanup.py`, `app/batch/media_organizer_execute_jobs.py`, `tests/test_media_organizer_finalization.py`.

- [ ] RED: frozen original paths, P1 wrappers and stage links remain after publication until separately confirmed cleanup.
- [ ] RED: under denied/revoked custody, no source unlink/rmdir occurs; foreign replacement survives.
- [ ] Implement private journal, per-unit confirmation and resumable cleanup with preflight proof; no broad directory delete.
- [ ] GREEN: finalization never precedes verified zero-change rescan and hash/count preservation; commit.

### Task 4: Wire complete UI / API semantics

Files: `app/batch/media_organizer_execute_jobs.py`, `app/media_organizer/router.py`, `frontend/src/pages/Batch/SemanticMediaOrganizerEditor.tsx`, `frontend/tests/media_organizer_preview.test.ts`.

- [ ] RED: grouped approval requires exact confirmed plan and effective custody proof; preview/complete/finalized states accurately shown.
- [ ] Replace temporary SEC-12 hold only after Tasks 1–3 make the Worker path safe.
- [ ] GREEN: frontend/backend focused tests; commit.

### Task 5: Isolated NAS and release

Files: `scripts/media_organizer_v16_real_nas_acceptance.py`, `docs/media-organizer-v16-execution-gate.md`, release notes.

- [ ] Check Linux filesystem semantics/permissions against the specific owner-created SATA acceptance root, with explicit execution authorization.
- [ ] Create disposable mixed-media, recursive, P1, conflict, interruption and homogeneous test sets. Check total counts and SHA-256 before/after.
- [ ] Run the full complete flow twice; second canonical scan reports `needed_moves=0` without unsafe stage hiding.
- [ ] Run all eight exact-HEAD GitHub CI checks to success, plus same-mount acceptance.
- [ ] Record residual risk and explicit owner approval; only then mark PR ready, merge and publish the stable Docker image.


## Progress log — 2026-11-18: Worker identity / namespace custody

### Evidence discovered
- The production `Dockerfile` has no `USER` instruction.
- `compose.yaml` and `compose.komodo.yaml` do not set a service `user:`.
- Therefore the current API and Worker containers run as UID 0 by default. The API and Worker also both receive writable `/data` mounts in the Komodo deployment.
- The direct grouped-publication primitive's POSIX owner/mode and ancestor checks are necessary but cannot establish a separate, least-privilege mutation principal while the Worker runs as root.

### TDD slice
- RED test added: `test_direct_group_refuses_root_worker_before_any_public_mutation`.
- First run exposed an ordering issue: stage-owner validation failed before the intended root-Worker assertion. The guard was moved to the beginning of the direct group creation function.
- GREEN: the focused backend + frontend V1.6 TDD workflow passed on commit `cbee88115408` (run `44265925311`). The new test now proves a root Worker is refused before public group creation and leaves original synthetic files byte-exact.

### Decision / remaining work
- This is a new necessary precondition, **not** a completed custody proof.
- Do not change production bind-mount ownership/ACLs automatically.
- Next: design and test a dedicated non-root Worker identity, separate API read-only access to `/data`, compatible shared database/report permissions, and explicit supported ACL/mount validation. If the actual NAS cannot prove that only this Worker principal can mutate the selected unit namespace during a job, keep grouped execution blocked.
- Task 1 remains OPEN until those deployment and mount-level checks exist. #402 remains OPEN; #400 cleanup and true second-scan-zero remain separate blockers.


## Follow-up ticket created — #403 API/Worker mutation-authority split

The audit found that changing only the API container's `/data` mount to read-only would break existing behavior:
- `POST /quarantine/{id}/restore` can execute a non-transactional restore directly in `service.restore_quarantine_entry` when no transactional Worker authority is supplied.
- `POST /quarantine/{id}/purge` directly removes the selected quarantine payload in `service.purge_quarantine_entry`.
- `DELETE /quarantine/{id}/record` and bulk record deletion call terminal transaction-artifact cleanup before metadata retirement; restored entries may then enqueue Worker cleanup.
- Plan and MediaPackage execution routes already enqueue WorkJobs, but they are not the only filesystem-mutation paths.

Ticket **#403** now tracks the complete route/service mutation inventory, migration of direct mutations to Worker jobs, dedicated non-root Worker UID/GID, API read-only media access, shared SQLite/report permissions, and supported NAS ACL validation:
https://github.com/JinHaocong/nas-file-center/issues/403

**Do not simply flip the API bind mount to read-only** until #403's inventory and migrations are complete. That would be a compatibility regression. #403 is a prerequisite for a defensible least-privilege namespace-custody model under #402.


## Progress log — 2026-11-18: API / Worker mutation-authority inventory

- Added `docs/superpowers/specs/2026-11-18-api-worker-mutation-authority-inventory.md`.
- Confirmed direct API media-root mutation paths that must move behind Worker jobs:
  - `POST /api/quarantine/{id}/restore` (legacy/non-transactional restore path).
  - `DELETE /api/quarantine/{id}/record` and `POST /api/quarantine/records/bulk-delete` (pre-enqueue transaction-artifact unlink/rmdir).
  - `POST /api/archive-recovery/start` (API creates/removes the sibling output directory before/around enqueue).
- Confirmed `POST /api/quarantine/{id}/purge` already queues `quarantine-single-purge`; do not regress this boundary.
- Confirmed owner-deleted, orphan-transaction and missing-record retirement endpoints are explicitly metadata-only; keep their no-filesystem-mutation contract.
- Confirmed startup reconciliation currently reads media state and writes SQLite metadata only; added it to the required regression guard so it cannot silently gain API-side writes.
- Confirmed deployment gap: Dockerfile has no `USER`; Komodo gives both API and Worker `/data:rw` and does not set a non-root `user:`.
- No production data, NAS paths, ownership or ACLs were modified by this inventory.

**Task 1 status:** initial route/service inventory recorded. RED→GREEN migration tests, Worker handlers, deployment split and actual NAS ACL/mount evidence remain open. #403 remains OPEN and is a prerequisite for a defensible #402 custody boundary.


## #400 Read-only cleanup review groundwork

- RED commit `5746359` added five synthetic API tests for admin-only paginated source→stage→final audit, tampered private report refusal, foreign replacement refusal, unfinished-job refusal and 422 page bounds. Initial CI confirmed all five fail on missing endpoint.
- Candidate GREEN: `GET /api/media-organizer/executions/{job_id}/cleanup-review` reads only an already completed, deferred, frozen publication. It validates the checksum manifest and 0600 private journal, verifies the requested page's three no-follow file identities and the old wrapper inode bindings, returns immutable counts/mapping with `cleanup_authorized=false` and `finalized=false`. It performs no filesystem mutations, WorkJob enqueue, deletion or cleanup.
- This is a **page-limited review**, not a whole-unit full-content/hash verification and not finalization. Grouped publication remains SEC-12 blocked; no cleanup Worker, source unlink, rmdir, or second-zero-scan claim is created.
- With #403 distinct container UIDs, a 0600 Worker-owned private journal remains unavailable to the API until a separately verified group-readable evidence contract is implemented. The endpoint must return a safe 409, never chmod/chown the host evidence.


### #400 full frozen-inventory read-only audit checkpoint

RED `93d5c23`: six tests require an admin-only, nonmutating full-inventory audit after deferred publication. It must verify every original/staged/final inode (including file 30, beyond the paged review), old P1 wrapper membership, reject an unknown private-stage entry, fail on corrupted journal and refuse incomplete or unauthorized jobs; initial focused V1.6 test run recorded all six missing-endpoint failures.

GREEN candidate adds `GET /api/media-organizer/executions/{job_id}/cleanup-audit`. It reuses the frozen checksum manifest, owner/group-checked manual journal, private stage witness, group receipts and published inode checks, then checks ALL source/stage/final hardlinks and exact old-wrapper child membership. Only filesystem metadata is read; no source-file content, unlink/rmdir/rename, new job or new receipt. It explicitly returns `cleanup_authorized=false`, `finalized=false`, `zero_change_rescan_verified=false`, `namespace_exclusive_custody_proven=false`. The check covers **frozen items**, not the entire uncooperative NAS directory namespace, and does not satisfy independent review or the future destructive cleanup design.


### #400 durable per-unit cleanup plan — review-only milestone

RED [5863ec2](https://github.com/JinHaocong/nas-file-center/commit/5863ec2fe00dd48e7ff18c8fce49f38a1ca1312a) adds tests requiring the completed Worker to persist an exact cleanup proposal under its immutable execution report directory; read-only authenticated paginated review; no silent overwrite of an existing foreign plan; checksum-based tamper refusal and no disclosure for uncompleted jobs. RED CI observed all five tests failing for missing plan/endpoint.

GREEN implementation candidate: before `manual_cleanup_required` is stamped, the dedicated Worker runs the **full existing frozen-inventory audit**, then atomically creates a single bounded `manifest.json.cleanup-plan.json` with O_EXCL and fsync. It binds frozen job ID, manifest checksum, all original/stage source identities and final target names, oldest wrappers sorted deepest first, private stage dev/inode and a canonical SHA-256. Exact retries read and verify the same immutable file; any other existing content or symlink fails closed without overwrite/chmod/chown. In shared API/Worker mode only newly created records are group-owned 0640; legacy records remain 0600. Admin GET `/api/media-organizer/executions/{job_id}/cleanup-plan` rereads the full audit then returns a bounded review page. **No cleanup operation, confirmation endpoint, source unlink/rmdir, finalization or zero-change rescan is authorized.** This is a durable, crash-recoverable *review plan*, not a destructive cleanup journal.


## #402 end-to-end grouping requires external custody issuer

The production default issuer `app/batch/media_organizer_custody.py:verified_namespace_custody` **always fails closed** until a separately reviewed implementation can prove supported NAS-mount/ACL writer exclusion. A boolean namespace ACK or WorkJob lease is not an issuer. The admin API must obtain scoped proof before queueing grouped plans, the Worker reacquires proof before staging, the Worker lease fence revalidates all frozen source/stage/target parents, and deferred publication/handoff require the same proof. Direct public mkdir + pinned-FD links are the only Worker grouped publication path. Isolated synthetic unit tests may inject a test-only scoped issuer to exercise the complete admin→Worker→deferred publication→separate confirmed finalization→second scan zero path; this does not authorize deployment. Absent/revoked/unscoped/boolean proof remains a hard SEC-12 refusal before staging.


## #400 separately confirmed cleanup Worker — wired but issuer fail-closed

A dedicated `media-organizer-cleanup` WorkJob is registered. Admin-only
`POST /api/media-organizer/executions/{job_id}/cleanup` requires a **second**
token bound to frozen job ID, unit and exact cleanup plan SHA-256, validates the
entire read-only frozen inventory and separately acquires effective scoped
namespace custody. The API only queues the job. The non-root Worker rechecks
the original publication, token, immutable plan, Worker lease and all
source/stage/final parents before entering the crash-resumable cleanup engine.
An internal custody wrapper revalidates the Worker lease on each name-based
mutation. Only after durable finalization and the canonical 0/0 second scan
does the original WorkJob switch from `manual_cleanup_required` to
`finalized=true`. The default issuer refuses ALL cleanup in production;
synthetic tmp_path tests inject it for end-to-end verification. Interrupted
cleanup needs a distinct explicit recovery workflow before release, and all
host NAS writer exclusions, independent review and same-mount acceptance
remain outstanding.
