# Media Organizer V1.6 — Safe Execution Gate (Draft)

**Status: single-unit Worker/API/UI integration exists behind an independent default-OFF feature gate. This is a Draft PR, not approved for NAS deployment.**

## SEC-12 production execution hold — grouped P/V/Other outputs

**Release blocked.** Grouped publication, retained canonical groups and
separately confirmed cleanup/recovery are implemented and exercised with
injected custody on disposable test storage. Production grouped execution and
cleanup remain blocked by `app/batch/media_organizer_custody.py`: there is no
approved NAS custody issuer. Execution/quiescence flags cannot create one.

The historical pending-directory promotion uses
`rename_noreplace_at(stage_fd, pending_name, unit_fd, public_name)`. NOREPLACE
protects the destination, not the source inode against replacement. That
legacy promotion path is not the active deferred grouped workflow. The current
workflow creates/binds groups under custody and publishes FD-pinned file links;
retained groups require their frozen inode identities. This still requires
external exclusion of concurrent namespace and content writers on the NAS.

Synthetic RED→GREEN tests also require private-stage mode/owner verification
at fresh staging, every pinned-FD media link and resume. A 0700 stage owned by
the Worker is a **necessary** file permission boundary, not evidence that
same-UID/root/NAS-mapped clients cannot modify its child namespace.

The capability probe now exposes
`private_stage_owner_verified`, `private_stage_mode_verified`,
`flat_filesystem_capabilities_compatible`, `grouped_promotion_proven`,
`grouped_publication_authorized`, and
`namespace_exclusive_custody_proven`. Even if the legacy `compatible`
field is TRUE, it describes **filesystem operations only**, applicable at
most to currently allowed flat-file workflows; grouped authorization remains
FALSE. No automatically generated POSIX mode evidence can change this status.

Historical promotion remains for legacy synthetic regression. Do not bypass
the production issuer through an acknowledgement, direct function invocation,
ad-hoc cleanup or edits to frozen authority. #402 remains open for actual host
proof and independent review.

## Verified library order

1. Review the independent organizing-unit preview; require status ready, actual P/V/Other counts/bytes and a stable source-to-target map.
2. Build a complete frozen manifest from a fresh scan, storing it as a checksum-protected, exclusive, private file. The Worker sets `cleanup_policy=deferred`; old classification directory identities are retained as evidence, **not** as automatic deletion authority.
3. Use an administrator-only API to queue **one named organizing unit** from a completed, conflict-free preview, after typing the exact unit-bound confirmation token. Require MEDIA_ORGANIZER_EXECUTION_ENABLED, ALLOW_MUTATION and ALLOW_DELETE **plus** MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK. The independent execution and namespace flags default to false. The Worker independently checks permissions, its lease and required external custody. The namespace flag does NOT create filesystem exclusion or replace the default-deny issuer.
4. **validate_execution_preflight:** re-check unit identity, source rows, target occupancy, classification grouping and frozen values.
5. **stage_frozen_sources:** create an exclusive private staging directory with an owner witness and stage every frozen file by exclusive FD-bound hardlink, **retaining each original source path**. A missing Linux `linkat(AT_EMPTY_PATH)` capability fails closed, never falls back to a source-name rename/unlink. Resume only with the same immutable manifest and lease; never adopt an unknown staged directory.
6. **publish_frozen_stage (deferred mode):** verify staged entries and retain all original names and old wrappers. Under injected valid custody, new role-aware manifests retain exact final names/canonical groups, publish unoccupied finals and defer occupied finals to separate cleanup approval. Legacy manifests retain their previous semantics. Historical directory promotion must not be routed into this workflow.
7. **record_deferred_cleanup_evidence:** verify the prepared inventory and write immutable review evidence and a cleanup plan. Shared mode uses verified 0640 review artifacts and checkpoint digests; private receipts/stage/progress remain Worker-only. The execution ends at `manual_cleanup_required`, with `finalized=false`. `publication_complete=false` identifies deferred finals. The separate cleanup job must complete and rescan before zero-change completion can be claimed.
8. **Separately confirmed cleanup WorkJob:** revalidate the frozen plan, live inventory, custody and lease. If needed, durably protect staged copies, release only frozen collision names, publish deferred finals and verify all finals before removing obsolete links/wrappers. A chained private journal governs interruption recovery. Set `finalized=true` only after actual cleanup and a canonical rescan proving zero moves and renames.

The new code is now wired into dedicated execution and manual recovery WorkJobs plus a gated Batch UI. Production NAS use remains prohibited until the release gates below are met. **No automatic batch-wide execution:** each request authorizes a single ready organizing unit, and any blocked unit in the original preview disallows execution. All tests use disposable synthetic directories.

## Deferred cleanup disposition (current safe WorkJob)

- The initial execution retains **every original source file at its original path**, every staged hardlink and old classification directory. It prepares publication and a review plan; the separate cleanup approval is required to finish the layout.
- The registered cleanup endpoint queues a separate WorkJob; it performs no HTTP media mutation. Legacy `retire_published_stage` and `_retire_wrappers` helpers are not this journaled cleanup implementation and must not be substituted for it.
- `path_role_policy=confirmed_relayout_v1` explicitly supports frozen canonical group reuse and retained final names. The cleanup plan lists deferred publications and released/retained names; foreign occupants still block. Old manifests/plans are not silently reinterpreted.
- The manual-cleanup record is `<manifest.json>.manual-cleanup.json` inside the private execution report directory and is not a deletion command. It contains the frozen authority checksum, original wrapper identities, final group identities and counts of preserved staged media links.
- An execution at phase `manual_cleanup_required` can have `status=completed` while layout work remains. Check `manual_cleanup_required`, `publication_complete`, deferred counts and `finalized`; completion of that WorkJob alone is not a canonical zero-change rescan.
- Safe recovery from a publish-phase interruption can re-enter this read-only handoff with the original frozen manifest. Unknown stage entries, changed identity, missing owner witness or altered private journal always block further action.
- Cleanup and explicit recovery are implemented under injected test custody. Their existence grants no live NAS authority; the production custody issuer still refuses them.

## Required failure behavior

- No overwriting an unknown file or directory, including one appearing after preview or staging.
- Source, unit, old wrapper, stage inode/device/size/mtime changes block mutations.
- A missing or invalid witness never authorizes adopting public or staged directories.
- A copied public owner marker is insufficient: original group dev/inode must match the immutable private group receipt in both publication/recovery and final retirement.
- A nonempty or replaced old classification wrapper must not be deleted. Unknown entries are preserved for review.
- Journaled wrapper/stage removal requires exact identities, emptiness, custody and parent-directory fsync; filesystem refusal blocks further progress.
- Interrupted publication retains the staged source link, and retirement never removes the last verified link.
- **Last-marker recovery:** an empty stage after the last internal witness is deleted may be reconciled ONLY when an independently fsynced private receipt proves the original frozen manifest and the exact stage device/inode, and all published file identities are intact. Missing, tampered, or mismatched receipts require manual review. Synthetic crash tests verify this restriction; real NAS durability has not been established.
- A fully finished second scan must show zero planned moves and zero renamed media files.

**Current production boundary:** publication recovery does not grant cleanup
approval. Cleanup/recovery is a separate job-bound workflow and remains gated
by the unavailable NAS custody issuer. Historical library tests grant no
deployment permission.

## Assisted recovery semantics

- Original failed execution remains terminal and preserves its checksum manifest, phase checkpoint, and immutable job identity.
- Recovery requires the original job's exact confirmation token and a new WorkJob; no mutation runs on the HTTP request.
- The Worker verifies original stage ownership and frozen evidence. Shared API review uses a digest-bound Worker snapshot rather than accessing private stage/progress evidence.
- Execution recovery and cleanup recovery have separate authority. A failed/interrupted cleanup requires a new exact predecessor/job/plan-bound confirmation; the Worker reconciles its private progress journal. Missing future inputs and foreign replacements cannot acquire new journal intent. Re-staging after cleanup started is forbidden.
- An already-completed recovery confirmation is idempotent and returns its prior result without touching files.
- Recovery never retries automatically. A further cleanup attempt must explicitly name the latest failed predecessor; untrusted evidence requires review.

For shared-mode execution recovery, every new Worker checkpoint binds the frozen
manifest checksum. The API verifies the failed original job, checkpoint identity
and readable frozen manifest; it does not open the private stage. The recovery
job binds that original checksum and phase, and its Worker repeats private/live
validation before mutation. A failed `manual_cleanup_required` checkpoint can
also recover the gap before the execution status was committed: revalidate the
handoff without restaging or republishing. New grouped/path-role recovery queues
also require scoped custody; the Worker must independently reacquire it.

Execution recovery retains the existing single-assisted-attempt contract: a
failed recovery itself requires manual review, not a nested execution retry.
Cleanup recovery has its separate, explicitly confirmed predecessor chain.

## Private directory exclusion scope

- Configure exact protected directory basenames outside the repository via
  MEDIA_ORGANIZER_EXCLUDED_DIR_NAMES, using a comma-separated value.
- The matcher is case-insensitive and checks **directory components only**.
  A media filename containing the same text remains eligible under its
  independently identified organizing unit.
- The preview worker, per-unit planner, frozen manifest and final canonical
  rescan all apply the same exclusion names. Direct selection of a protected
  subtree is rejected.
- No private source basename is committed to this repository. The flag
  remains an explicit deployment setting, not a guessed classification.

## Disposable filesystem capability test — not yet performed on the owner's NAS

The current repository includes an opt-in synthetic probe which verifies
directory no-replace rename against an existing **empty** directory, ordinary
hardlink no-clobber, **Linux pinned-source FD hardlink no-clobber and name-swap
resistance**, directory fsync support and exclusive scratch cleanup.
It checks syscall behavior, not physical power-loss durability.

Run **only after the owner approves an existing disposable parent directory on
the target NAS filesystem**, not on a real media package:

~~~sh
python -m app.batch.media_organizer_capability_probe \
  --parent "/path/to/owner-approved-scratch-parent" \
  --ack-scratch-write
~~~

The command creates its own randomly named private child directories, checks
their inode identities and only removes directories it created while still
empty. Unknown or replaced scratch entries are **not automatically deleted**.
The CLI deliberately refuses to start without --ack-scratch-write.

Require all fields to be true: directory_noreplace,
directory_cross_parent_noreplace, collision_preserved, directory_fsync,
hardlink_noreplace, cross_directory_hardlink,
source_fd_hardlink_noreplace, source_fd_name_swap_safe,
private_stage_owner_verified, private_stage_mode_verified,
original_probe_compatible, cleanup_complete, and compatible.
For real grouped operation the additional fields would
need `namespace_exclusive_custody_proven=true` and
`grouped_publication_authorized=true`; the present probe deliberately
does NOT produce those claims. No real NAS mount has been approved.
The cross-parent field verifies a private stage child being atomically promoted
to a public sibling, covering the historical promotion primitive rather than
the complete current cleanup workflow. Any false required field, error, leftover scratch directory or an
unsupported rename/no-replace operation blocks deployment.

GitHub Actions tests exercise this probe on synthetic runner storage only.
**Their success does not establish NAS mount compatibility**; no real NAS
probe has been executed in this PR.

## Directory cleanup source-name race — still a release blocker (#399)

The old classification wrapper cleanup and final empty-stage cleanup use POSIX
name-based rename/rmdir operations. An inode check, O_NOFOLLOW directory FD,
Worker lease or directory NOREPLACE destination protection cannot make the
SOURCE name identity conditional on its inode at the instant of this syscall.

**Temporary fail-closed containment:** MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK
defaults to false and is required in addition to the existing three gates.
API enqueue, preview execute controls and Worker entry check it. The switch
must remain false on any NAS mount whose namespace can be modified by
uncooperative SMB, WebDAV, NAS apps or other writers. The synthetic CI tests
set the acknowledgement explicitly to exercise execution in isolated
temporary test directories.

Setting this flag to true **does not enforce exclusivity**. It is permitted
only after a separate technical determination that concurrent writes to the
relevant parent directories are enforceably excluded, including during
recovery and cleanup. If that cannot be demonstrated, do not enable it.
No production NAS execution is authorized by this document or by passing CI.

The initial execution defers cleanup; the separately confirmed cleanup Worker
uses its immutable plan and private journal under revalidated custody. It does
not use the legacy wrapper-rename retirement helpers. **Issue #399 remains
OPEN** for actual host namespace exclusion and review of the supported path.
Neither a self-audit nor an affirmative quiescence flag proves the underlying
name-based syscall race is removed.

## Gates before live deployment / production NAS execution

- [ ] Provide independently reviewed NAS custody for SEC-12 #402 and verify the active grouped/retained workflow on that host. The production issuer remains default-deny.
- [ ] Independently resolve the source-name cleanup race in #399, or provide a verifiable exclusive namespace mechanism. Do not treat the new acknowledgement as a fix.
- [ ] Independent review and owner-approved NAS capability proof for the SEC-11 source-file race #401. Deferred mode now retains original source names and creates stage/public hardlinks from verified open file descriptors; non-deferred historical rename logic is NOT a production authorization.
- [ ] Independent review of the actual custody boundary, destination binding, retained groups, confirmed collision release/publication and journaled stage retirement.
- [x] Dedicated Worker ownership, exact unit-bound confirmation, freeze/validate before mutation, lease checkpoints, and explicit single-attempt recovery: verified in synthetic focused CI. Production security review still pending.
- [ ] No-replace / hardlink / directory fsync capability proved on the owner-approved disposable parent on the actual NAS mount using the probe above. GitHub-runner tests alone are insufficient.
- [ ] Additional concurrency and failure-injection tests at each mutation boundary, especially private stage namespace replacement, tombstone rename and live mount/device drift. Synthetic destination swap and last-marker receipt recovery tests have passed; real filesystem behavior remains unproven.
- [x] Exact code `ae95b60` passed all nine non-release workflows, including full backend/frontend/build validation and focused V1.6 actual-UID cleanup/recovery. See the run identifiers below.
- [ ] Release Validation, final review and real-host acceptance remain separate gates. The Draft-only skipped release run is not a passing result; later code changes require renewed evidence.
- [ ] User approval before enabling mutation permissions, merging or deploying.

**References:** docs/superpowers/specs/2026-11-17-media-organizer-v1.6-design.md and docs/superpowers/plans/2026-11-17-media-organizer-v1.6.md.


## V1.6 real-SATA primitive harness (owner-created disposable root)

Use [real-nas-acceptance.md](real-nas-acceptance.md) for the current read-only
host preflight, config backup/candidate/rollback sequence and separately
approved direct Compose command. No self-hosted runner or dedicated real-NAS
GitHub workflow is required. `compose.v16-real-nas-acceptance.yaml` mounts only
the disposable acceptance root and evidence directory writable, plus the
acceptance script read-only; production config and media roots are not mounted.

`PASS_FLAT_AND_GROUP_HOLD` means real-mount flat primitives/publication passed
and mixed P/V publication was refused. Original/staged/public flat hardlinks
remain; the scheduler fixture is unused. It proves neither grouped/retained
layout completion, cleanup recovery, zero-change final scanning nor custody.
The full approved end-to-end NAS run remains a separate outstanding gate.

At `ae95b60e8c11fb6e38a377039547291f1cd37f81`, focused CI run `44364472632`
passed, including actual distinct-UID execution, cleanup and explicit recovery
via `scripts/test_v16_cleanup_cross_uid.sh`. Those files are disposable CI
fixtures, not NAS media. All nine non-release workflows succeeded on that
same commit, including full backend/frontend/build validation in `Scheduler
S5 Closure` run `44364473023`. `Release Validation` run `44364472586` was
skipped because the PR is Draft. These results establish no actual NAS
identity/ACL/SMB/secret-volume behavior.


## #400 Read-only deferred cleanup audit interface

The authenticated admin can request `GET /api/media-organizer/executions/{job_id}/cleanup-review?page=1&page_size=25` after phase `manual_cleanup_required`. The read-only response reports frozen rows and planned counts; pagination is bounded 1–100. In shared-GID mode it verifies the completed Worker's digest-bound snapshot and reports `verification_scope=worker_handoff_snapshot`, `live_inventory_verified=false`. It does not read private stage/progress evidence or claim a fresh live audit. The explicit single-UID legacy branch retains its live reader. Invalid or inaccessible authority fails closed with HTTP 409; review alone cannot enqueue, delete or finalize anything.


### #400–#403 shared evidence permissions (candidate)

When `NFC_SHARED_CONFIG_GID` is configured, new execution report directories use trusted setgid 2770 permissions; new frozen manifests, manual-cleanup review reports and cleanup plans use 0640. The completed Worker checkpoint binds their digests. Progress journals, group receipts and media staging remain private to the Worker. Existing incompatible evidence fails closed without automatic chmod/chown. Single-UID defaults remain private. These are cross-UID review permissions, not external NAS custody or release permission.

### Shared-review compatibility

Legacy completed shared-mode jobs without the checkpoint fields
`manifest_checksum`, `cleanup_plan_sha256` and `cleanup_report_sha256` fail
closed when their review/plan/audit is requested. Current code provides no
automatic backfill or migration that mints those bindings. Preserve the original
rows and evidence for review; do not add guessed digests, remove private-file
protection, switch modes to bypass verification, or present a permission change
as a compatibility fix. This is an outstanding compatibility consideration for
any existing config copied into the candidate deployment.

Failed shared-mode executions likewise require an existing Worker-issued
`manifest_checksum` at the original recoverable checkpoint. Missing old bindings
are not backfilled. The newly recoverable terminal handoff phase also requires
that binding in single-UID mode; older frozen/staged/published single-UID
recovery retains its original private-evidence checks.
Previously queued shared-mode recovery jobs without the new digest/phase
bindings also refuse; the implementation does not retrofit their authority.


### #400 Full read-only inventory audit

The admin-only `GET /api/media-organizer/executions/{job_id}/cleanup-audit` returns the verified Worker handoff summary in shared mode, explicitly without a new live-inventory claim. The single-UID legacy branch performs the full live frozen-link/wrapper audit. The cleanup Worker always performs its own live checks before mutation. Neither HTTP review mode supplies cleanup consent, namespace exclusion or a zero-change rescan; existing release holds remain mandatory.


### #400 immutable cleanup-plan review (not a cleanup executor)

After verifying prepared publication, the Worker writes bounded O_EXCL/fsynced `manifest.json.cleanup-plan.json` before stamping `manual_cleanup_required`. It binds frozen originals/staged/final identities, wrappers and manifest/plan checksums. Schema 2 explicitly records retained groups/names and deferred publications; legacy plans retain schema 1 semantics. Existing plan reuse requires exact verified content. Admin `GET /api/media-organizer/executions/{job_id}/cleanup-plan` pages the shared snapshot or the legacy live-reviewed plan; it does not perform cleanup.

This is *not* a cleanup command or confirmation. `cleanup_authorized=false`, `finalized=false` and `zero_change_rescan_verified=false` are mandatory. No source name is unlinked, no wrapper rmdir is attempted, and no NAS namespace exclusivity is claimed. #402 / #399 / #398 / #403 release holds remain open.


## #402 Scoped namespace custody injection — integration not deployment approval

The grouped API/Worker path is now wired to a **fail-closed external custody issuer**. No production implementation of the issuer exists yet, because on the owner's NAS we have not proved exclusions of hostile concurrent same-UID/root/SMB writers and actual mount ACL mapping. The provider raises SEC-12 by default, even if the operator sets all execution/quiescence flags. Synthetic tests can inject a `tmp_path`-limited provider and prove the full grouped P/V WorkJob, no-replace direct group creation, retained originals, durable cleanup plan and 0-change rescan only under that controlled boundary. A Boolean ACK, missing proof or revoked proof never queues/stages grouped jobs. Keep PR #397 Draft, no merge or NAS execution until the actual issuer, reviewer sign-off, and approved disposable SATA validation are complete.


## #400 WorkJob wiring — still no live NAS authorization

A second, admin-only `POST /api/media-organizer/executions/{job_id}/cleanup`
now exists and queues only a `media-organizer-cleanup` WorkJob with an exact
job/unit/plan checksum confirmation; no HTTP media writes occur. The registered
non-root Worker rechecks the external namespace-custody grant, frozen plan,
source/final identities and lease before each cleanup step. It uses a chained
durable progress journal and sets `finalized=true` on the original execution
only AFTER real cleanup and read-only canonical rescan have proved 0 moves and
0 renames. In production this endpoint **fails closed** because there is no
approved NAS custody issuer; do not treat the new route as authority to
run a destructive task. Owner-approved same-mount tests, independent review,
actual host recovery validation and original `/config` migration/rollback
preparation are still mandatory. Synthetic journal recovery is implemented;
it does not replace those real-host gates.
