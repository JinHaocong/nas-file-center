# Media Organizer V1.6 — Safe Execution Gate (Draft)

**Status: single-unit Worker/API/UI integration exists behind an independent default-OFF feature gate. This is a Draft PR, not approved for NAS deployment.**

## Verified library order

1. Review the independent organizing-unit preview; require status ready, actual P/V/Other counts/bytes and a stable source-to-target map.
2. Build a complete frozen manifest from a fresh scan, storing it as a checksum-protected, exclusive, private file. Retain source file identities and the device/inode binding of every old classification directory the plan may retire.
3. Use an administrator-only API to queue **one named organizing unit** from a completed, conflict-free preview, after typing the exact unit-bound confirmation token. Require MEDIA_ORGANIZER_EXECUTION_ENABLED, ALLOW_MUTATION and ALLOW_DELETE **plus** MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK. The independent execution and namespace flags default to false. The Worker independently checks all permissions and requires an exclusive lease. The namespace flag is only an operator acknowledgement of externally established isolation; it does NOT create filesystem exclusion or solve an uncooperative writer race.
4. **validate_execution_preflight:** re-check unit identity, source rows, target occupancy, classification grouping and frozen values.
5. **stage_frozen_sources:** create an exclusive private staging directory with an owner witness and stage every frozen file through no-replace moves. Resume only with the same immutable manifest and lease; never adopt an unknown staged directory.
6. **publish_frozen_stage:** verify all staged entries; retire only original empty classification wrappers by frozen device/inode identity. Prepare each P/V/Other directory with its owner witness INSIDE the verified private stage, and durably write a separate 0600 private group identity receipt (manifest checksum, group ordinal/name and original directory dev/inode) BEFORE atomic no-replace promotion. Resume requires that exact receipt; copied owner markers alone cannot authorize adopting another directory. Every public hardlink rechecks its original group inode receipt, ownership and directory binding. On interruption, prove already published identities before continuing missing entries.
7. **retire_published_stage:** verify every public output AND every public GROUP's original private inode receipt before removing staged hardlinks or public witnesses; copied owner markers and copied/hardlinked media in a foreign directory do not suffice. Persist retirement intent; unlink only staged links proven to have exact published counterparts; durably save an independent private stage-retirement receipt (manifest checksum plus stage device/inode) before removing the final in-stage witness. After safely retiring the empty staging directory, re-scan to confirm already_organized and zero changes.

The new code is now wired into dedicated execution and manual recovery WorkJobs plus a gated Batch UI. Production NAS use remains prohibited until the release gates below are met. **No automatic batch-wide execution:** each request authorizes a single ready organizing unit, and any blocked unit in the original preview disallows execution. All tests use disposable synthetic directories.

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
directory no-replace rename against an existing **empty** directory, public
hardlink no-clobber, fsync durability and exclusive scratch cleanup.

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
original_probe_compatible, cleanup_complete, and compatible.
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

Issue #399 remains OPEN until source-name cleanup can be guaranteed safe or
the executor is redesigned to defer those deletions and report a manual
cleanup state. Neither a reviewer-free self-audit nor an affirmative flag is
proof that the race has been removed.

## Gates before live deployment / production NAS execution

- [ ] Independently resolve the source-name cleanup race in #399, or provide a verifiable exclusive namespace mechanism. Do not treat the new acknowledgement as a fix.
- [ ] Independent security review of private pending group promotion, directory rename races, destination binding checks, same-name old bucket replacement and receipt-backed stage retirement.
- [x] Dedicated Worker ownership, exact unit-bound confirmation, freeze/validate before mutation, lease checkpoints, and explicit single-attempt recovery: verified in synthetic focused CI. Production security review still pending.
- [ ] No-replace / hardlink / directory fsync capability proved on the owner-approved disposable parent on the actual NAS mount using the probe above. GitHub-runner tests alone are insufficient.
- [ ] Additional concurrency and failure-injection tests at each mutation boundary, especially private stage namespace replacement, tombstone rename and live mount/device drift. Synthetic destination swap and last-marker receipt recovery tests have passed; real filesystem behavior remains unproven.
- [ ] Final candidate full backend regression, frontend test/typecheck/build, focused V1.6 TDD, visual checks, and all relevant safety workflows green. Earlier focused TDD passed; final PR state still pending.
- [ ] User approval before enabling mutation permissions, merging or deploying.

**References:** docs/superpowers/specs/2026-11-17-media-organizer-v1.6-design.md and docs/superpowers/plans/2026-11-17-media-organizer-v1.6.md.
