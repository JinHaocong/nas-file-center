# Media Organizer V1.6 — Safe Execution Gate (Draft)

**Status: single-unit Worker/API/UI integration exists behind an independent default-OFF feature gate. This is a Draft PR, not approved for NAS deployment.**

## SEC-12 temporary execution hold — grouped P/V/Other outputs

**Release blocked.** The current V1.6 Worker/API refuses **all new grouped
output directories** before staging, including mixed P/V and >200-file groups.
Read-only preview remains available, but the UI does not offer a confirmation
token for those units. Only eligible **pure-media <=200 flat** plans with
no source/final-name collisions may proceed through synthetic tests behind
the existing default-OFF execution and namespace gates. This is a deliberate
**loss of grouped execution functionality**, not a completed feature launch.

Reason: pending-source directory promotion uses
`rename_noreplace_at(stage_fd, pending_name, unit_fd, public_name)`. POSIX
NOREPLACE makes the **target** collision-safe, but does NOT constrain the
**source inode** against a concurrent writer replacing `pending_name`.
Checking `pending_fd` or the tombstone afterward is insufficient to prevent
moving a foreign directory. A synthetic last-check-to-rename fault injection
demonstrated this in RED. A separate source-inode-bound directory promotion
primitive or enforceable namespace exclusion requires independent approval
before group execution can be reinstated.

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

The historical library function remains only for legacy synthetic regression;
any manifest stamped `cleanup_policy=deferred` is now rejected before that
directory promotion. Do not bypass via an environment acknowledgement, direct
function invocation, ad-hoc cleanup or changing the freeze manifest. #402 is
**not closed**; this is fail-closed containment pending a functional fix.

## Verified library order

1. Review the independent organizing-unit preview; require status ready, actual P/V/Other counts/bytes and a stable source-to-target map.
2. Build a complete frozen manifest from a fresh scan, storing it as a checksum-protected, exclusive, private file. The Worker sets `cleanup_policy=deferred`; old classification directory identities are retained as evidence, **not** as automatic deletion authority.
3. Use an administrator-only API to queue **one named organizing unit** from a completed, conflict-free preview, after typing the exact unit-bound confirmation token. Require MEDIA_ORGANIZER_EXECUTION_ENABLED, ALLOW_MUTATION and ALLOW_DELETE **plus** MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK. The independent execution and namespace flags default to false. The Worker independently checks all permissions and requires an exclusive lease. The namespace flag is only an operator acknowledgement of externally established isolation; it does NOT create filesystem exclusion or solve an uncooperative writer race.
4. **validate_execution_preflight:** re-check unit identity, source rows, target occupancy, classification grouping and frozen values.
5. **stage_frozen_sources:** create an exclusive private staging directory with an owner witness and stage every frozen file by exclusive FD-bound hardlink, **retaining each original source path**. A missing Linux `linkat(AT_EMPTY_PATH)` capability fails closed, never falls back to a source-name rename/unlink. Resume only with the same immutable manifest and lease; never adopt an unknown staged directory.
6. **publish_frozen_stage (deferred mode):** verify staged entries and **NEVER rename or delete any old classification wrapper**. **SEC-12 holds every grouped plan at API/preflight before staging.** Eligible pure-media flattening uses pinned FD hardlinks for files only, with originals retained. The historical private-folder + NOREPLACE group-promotion routine remains in the library for non-deferred regression cases but must NOT be reachable from the active V1.6 Worker.
7. **record_deferred_cleanup_evidence (production Worker path):** verify every final media file, public-group inode receipt, untouched old wrapper directory, and retained private staging inode/file links. Write an immutable 0600 manual-cleanup record in the private report directory. The WorkJob ends with checkpoint phase `manual_cleanup_required`, **not** finalized; do not call `retire_published_stage`, remove stage hardlinks/markers, or run `rmdir`/old-wrapper rename. A fresh read-only preview can report `blocked` due to the deliberately retained private stage. Manual inspection and separately approved cleanup are required before claiming zero-change idempotency.

The new code is now wired into dedicated execution and manual recovery WorkJobs plus a gated Batch UI. Production NAS use remains prohibited until the release gates below are met. **No automatic batch-wide execution:** each request authorizes a single ready organizing unit, and any blocked unit in the original preview disallows execution. All tests use disposable synthetic directories.

## Deferred cleanup disposition (current safe WorkJob)

- The supported Worker now **only publishes final media and records a manual cleanup handoff**. It also retains **every original source file at its original path**, every staged hardlink, owner marker, old classification directory and private inode receipt. Thus it is not a finished move/sort until audited cleanup under #400.
- No user-facing automatic directory cleanup endpoint is registered. The legacy library-level `retire_published_stage` and `_retire_wrappers` code remain for isolated historical tests but are **not invoked by the V1.6 WorkJob**. Those old paths are still considered unsafe under uncooperative concurrent writers; they must not be routed into production.
- If an existing old classification bucket has the exact final P/V group name, `validate_deferred_publication` blocks the plan before staging. Users must resolve that conflict separately. Do not silently delete or overwrite it.
- The manual-cleanup record is `<manifest.json>.manual-cleanup.json` inside the private execution report directory and is not a deletion command. It contains the frozen authority checksum, original wrapper identities, final group identities and counts of preserved staged media links.
- Job `status=completed` means the **publication phase** finished, not that disk cleanup finished. Check `manual_cleanup_required=true`, `finalized=false`, and checkpoint phase `manual_cleanup_required`. The Batch UI shows a warning and does not claim a canonical zero-change rescan.
- Safe recovery from a publish-phase interruption can re-enter this read-only handoff with the original frozen manifest. Unknown stage entries, changed identity, missing owner witness or altered private journal always block further action.
- A future separately reviewed manual-cleanup workflow must verify directory identity and provide an independently approved plan; no cleanup operation is implemented or authorized in this PR.

## Required failure behavior

- No overwriting an unknown file or directory, including one appearing after preview or staging.
- Source, unit, old wrapper, stage inode/device/size/mtime changes block mutations.
- A missing or invalid witness never authorizes adopting public or staged directories.
- A copied public owner marker is insufficient: original group dev/inode must match the immutable private group receipt in both publication/recovery and final retirement.
- A nonempty or replaced old classification wrapper must not be deleted. Unknown entries are preserved for review.
- No-replace rename and directory fsync are required for wrapper retirement; filesystem refusal is a blocker, not permission to fall back to overwriting rename.
- Interrupted publication retains the staged source link, and retirement never removes the last verified link.
- **Last-marker recovery:** an empty stage after the last internal witness is deleted may be reconciled ONLY when an independently fsynced private receipt proves the original frozen manifest and the exact stage device/inode, and all published file identities are intact. Missing, tampered, or mismatched receipts require manual review. Synthetic crash tests verify this restriction; real NAS durability has not been established.
- A fully finished second scan must show zero planned moves and zero renamed media files.

**Current production Worker:** recovery to phase `published` resumes only the verified deferred cleanup record, never the old automatic retirement code. Historical library crash-recovery tests remain as synthetic evidence and do not grant NAS deployment permission.

## Assisted recovery semantics

- Original failed execution remains terminal and preserves its checksum manifest, phase checkpoint, and immutable job identity.
- Recovery requires the original job's exact confirmation token and a new WorkJob; no mutation runs on the HTTP request.
- The API verifies the ORIGINAL staged ownership marker contents, not just its filename, before queuing a new recovery attempt. Exception: a previously published, completely empty stage with no markers may be accepted only after verifying the durable external private receipt and stage identity.
- The Worker resumes staging/publication if the original checkpoint ended in frozen/staged, and **only** resumes retirement if the original phase was published. Re-staging after stage retirement started is forbidden.
- An already-completed recovery confirmation is idempotent and returns its prior result without touching files.
- A failed recovery does not recursively retry; an untrusted or unwitnessed stage needs manual review.

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
resistance**, fsync durability and exclusive scratch cleanup.

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
For currently enabled grouped operation the additional fields would
need `namespace_exclusive_custody_proven=true` and
`grouped_publication_authorized=true`; the present probe deliberately
does NOT produce those claims. No real NAS mount has been approved.
The cross-parent field specifically verifies a private stage child being
atomically promoted to a public sibling of the stage folder, matching the
current execution engine. Any false field, error, leftover scratch directory or an
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

The active Worker now uses deferred directory cleanup, so it no longer
invokes the known-unsafe name-based wrapper rename / final-stage rmdir paths.
**Issue #399 remains OPEN** for independent verification that all production
entry points are permanently disconnected from those legacy helpers and for
the design of separately reviewed manual cleanup. Neither a self-audit nor
an affirmative quiescence flag proves the underlying race is removed.

## Gates before live deployment / production NAS execution

- [ ] Independently resolve grouped source-name directory promotion risk in SEC-12 #402 (currently held before staging). Do not release full P/V/Other regrouping while this is unresolved.
- [ ] Independently resolve the source-name cleanup race in #399, or provide a verifiable exclusive namespace mechanism. Do not treat the new acknowledgement as a fix.
- [ ] Independent review and owner-approved NAS capability proof for the SEC-11 source-file race #401. Deferred mode now retains original source names and creates stage/public hardlinks from verified open file descriptors; non-deferred historical rename logic is NOT a production authorization.
- [ ] Independent security review of private pending group promotion, directory rename races, destination binding checks, same-name old bucket replacement and receipt-backed stage retirement.
- [x] Dedicated Worker ownership, exact unit-bound confirmation, freeze/validate before mutation, lease checkpoints, and explicit single-attempt recovery: verified in synthetic focused CI. Production security review still pending.
- [ ] No-replace / hardlink / directory fsync capability proved on the owner-approved disposable parent on the actual NAS mount using the probe above. GitHub-runner tests alone are insufficient.
- [ ] Additional concurrency and failure-injection tests at each mutation boundary, especially private stage namespace replacement, tombstone rename and live mount/device drift. Synthetic destination swap and last-marker receipt recovery tests have passed; real filesystem behavior remains unproven.
- [ ] Final candidate full backend regression, frontend test/typecheck/build, focused V1.6 TDD, visual checks, and all relevant safety workflows green. Earlier focused TDD passed; final PR state still pending.
- [ ] User approval before enabling mutation permissions, merging or deploying.

**References:** docs/superpowers/specs/2026-11-17-media-organizer-v1.6-design.md and docs/superpowers/plans/2026-11-17-media-organizer-v1.6.md.


## V1.6 real-SATA scratch acceptance (owner-created disposable root)

The current Komodo Compose binds host `/tmp/zfsv3/sata11/15246330601/data`
to container `/data`. The owner-created test root is therefore expected at:

```text
/tmp/zfsv3/sata11/15246330601/data/nas-file-center-v1.6-acceptance
├── nfc-organizer-c5-acceptance
└── nfc-scheduler-s5-acceptance
```

The dedicated PR workflow
`.github/workflows/media-organizer-v16-real-nas.yml` checks out the exact PR
HEAD and runs only on a self-hosted NAS runner carrying labels
`self-hosted, linux, x64, nas-file-center-acceptance`. Its preflight verifies
the expected path, real directories (no symlinks), same-device SATA placement,
the two child names, and empty/reserved contents before any test write.

The V1.6 harness records capability evidence and synthetic flat-file
publication under a unique `.nfc-v16-run-<sha>-*` directory inside
`nfc-organizer-c5-acceptance`. It deliberately leaves those test fixtures and
receipts for the owner to inspect and remove by deleting the single parent
`nas-file-center-v1.6-acceptance` after acceptance. The Scheduler root remains
unused and empty. The capability probe's own random scratch is removed only
when its exact ownership evidence still matches.

**This is NOT P/V group acceptance.** The report must retain
`grouped_publication_authorized=false` and
`namespace_exclusive_custody_proven=false`; mixed P/V plans remain blocked.
The flat deferred handoff retains originals/stage/public hardlinks and does
not yet satisfy a zero-change second scan; #400 remains open.

The workflow requires an online self-hosted runner with the labels above.
A pending/queued job with no assigned runner means the real NAS test has NOT
started. GitHub-hosted CI and Docker builds cannot substitute for this mount.


## #400 Read-only deferred cleanup audit interface

The authenticated admin can request `GET /api/media-organizer/executions/{job_id}/cleanup-review?page=1&page_size=25` only after publication has reached `manual_cleanup_required`. The endpoint reads a checksum-validated frozen manifest and bounded private 0600 manual-review journal, checks the original, staged and final hardlink identities on the requested page, and reports the original wrappers and expected counts/bytes. It cannot enqueue, delete or finalize anything: `cleanup_authorized=false`, `finalized=false`, `whole_unit_live_verified=false` are mandatory. An inaccessible journal, changed inode, stale stage or corrupt report fails closed with HTTP 409; pagination is bounded 1–100 and requires admin authentication. This is NOT a cleanup consent UI or end-to-end finalization.

**Cross-UID caveat:** the private Worker file uses 0600 today, and the API is a distinct UID in #403; until an explicitly reviewed shared evidence visibility mechanism exists, live API may be unable to read the report and will refuse with 409. Do not loosen existing NAS permissions or enable V1.6 execution to work around it.
