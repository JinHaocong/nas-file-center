# Media Organizer V1.6 — Safe Execution Gate (Draft)

**Status: single-unit Worker/API/UI integration exists behind an independent default-OFF feature gate. This is a Draft PR, not approved for NAS deployment.**

## Verified library order

1. Review the independent organizing-unit preview; require status ready, actual P/V/Other counts/bytes and a stable source-to-target map.
2. Build a complete frozen manifest from a fresh scan, storing it as a checksum-protected, exclusive, private file. Retain source file identities and the device/inode binding of every old classification directory the plan may retire.
3. Use an administrator-only API to queue **one named organizing unit** from a completed, conflict-free preview, after typing the exact unit-bound confirmation token. Require MEDIA_ORGANIZER_EXECUTION_ENABLED, ALLOW_MUTATION and ALLOW_DELETE. The first flag defaults to false. The Worker independently rechecks all three and requires an active exclusive lease.
4. **validate_execution_preflight:** re-check unit identity, source rows, target occupancy, classification grouping and frozen values.
5. **stage_frozen_sources:** create an exclusive private staging directory with an owner witness and stage every frozen file through no-replace moves. Resume only with the same immutable manifest and lease; never adopt an unknown staged directory.
6. **publish_frozen_stage:** verify all staged entries; retire only original empty classification wrappers by frozen device/inode identity. Publish public P/V/Other files by exclusive hardlinks from still-retained stage inodes, with group owner/completion witnesses. On interruption, prove already published identities and continue only missing entries.
7. **retire_published_stage:** verify every public output, persist retirement intent, unlink only staged links proven to have exact published counterparts, remove owned witnesses and safely retire the empty staging directory. Re-scan to confirm already_organized and zero changes.

The new code is now wired into dedicated execution and manual recovery WorkJobs plus a gated Batch UI. Production NAS use remains prohibited until the release gates below are met. **No automatic batch-wide execution:** each request authorizes a single ready organizing unit, and any blocked unit in the original preview disallows execution. All tests use disposable synthetic directories.

## Required failure behavior

- No overwriting an unknown file or directory, including one appearing after preview or staging.
- Source, unit, old wrapper, stage inode/device/size/mtime changes block mutations.
- A missing or invalid witness never authorizes adopting public or staged directories.
- A nonempty or replaced old classification wrapper must not be deleted. Unknown entries are preserved for review.
- No-replace rename and directory fsync are required for wrapper retirement; filesystem refusal is a blocker, not permission to fall back to overwriting rename.
- Interrupted publication retains the staged source link, and retirement never removes the last verified link.
- **Known recoverability boundary:** interruption after unlinking the final private retirement marker but before removing the empty staging directory can leave an unwitnessed empty directory. The implementation must fail closed and preserve it for manual reconciliation, not claim automatic recovery across this last gap.
- A fully finished second scan must show zero planned moves and zero renamed media files.

## Assisted recovery semantics

- Original failed execution remains terminal and preserves its checksum manifest, phase checkpoint, and immutable job identity.
- Recovery requires the original job's exact confirmation token and a new WorkJob; no mutation runs on the HTTP request.
- The API verifies the ORIGINAL staged ownership marker contents, not just its filename, before queuing a new recovery attempt.
- The Worker resumes staging/publication if the original checkpoint ended in frozen/staged, and **only** resumes retirement if the original phase was published. Re-staging after stage retirement started is forbidden.
- An already-completed recovery confirmation is idempotent and returns its prior result without touching files.
- A failed recovery does not recursively retry; an untrusted or unwitnessed stage needs manual review.

## Gates before live deployment / production NAS execution

- [ ] Independent security review of path races, same-name old bucket replacement and marker/tombstone handling.
- [x] Dedicated Worker ownership, exact unit-bound confirmation, freeze/validate before mutation, lease checkpoints, and explicit single-attempt recovery: verified in synthetic focused CI. Production security review still pending.
- [ ] No-replace and directory fsync compatibility proved on a disposable copy on the actual NAS storage.
- [ ] Additional concurrency and failure-injection tests at each mutation boundary, including directory creation before witness, tombstone rename, last-marker retirement, and live mount/device drift.
- [ ] Final candidate full backend regression, frontend test/typecheck/build, focused V1.6 TDD, visual checks, and all relevant safety workflows green. Earlier focused TDD passed; final PR state still pending.
- [ ] User approval before enabling mutation permissions, merging or deploying.

**References:** docs/superpowers/specs/2026-11-17-media-organizer-v1.6-design.md and docs/superpowers/plans/2026-11-17-media-organizer-v1.6.md.
