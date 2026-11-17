# Media Organizer V1.6 — Safe Execution Gate (Draft)

**Status: library implementation only. Do not enable against production NAS.**

## Verified library order

1. Review the independent organizing-unit preview; require status ready, actual P/V/Other counts/bytes and a stable source-to-target map.
2. Build a complete frozen manifest from a fresh scan, storing it as a checksum-protected, exclusive, private file. Retain source file identities and the device/inode binding of every old classification directory the plan may retire.
3. Acquire an authenticated Worker lease with a fencing callback; verify administrator confirmation and both mutation and deletion permission gates. This server/Worker integration **does not exist yet**.
4. **validate_execution_preflight:** re-check unit identity, source rows, target occupancy, classification grouping and frozen values.
5. **stage_frozen_sources:** create an exclusive private staging directory with an owner witness and stage every frozen file through no-replace moves. Resume only with the same immutable manifest and lease; never adopt an unknown staged directory.
6. **publish_frozen_stage:** verify all staged entries; retire only original empty classification wrappers by frozen device/inode identity. Publish public P/V/Other files by exclusive hardlinks from still-retained stage inodes, with group owner/completion witnesses. On interruption, prove already published identities and continue only missing entries.
7. **retire_published_stage:** verify every public output, persist retirement intent, unlink only staged links proven to have exact published counterparts, remove owned witnesses and safely retire the empty staging directory. Re-scan to confirm already_organized and zero changes.

These library functions are **not** exposed through an execute endpoint, Batch Plan or background mutation job. New code may mutate only synthetic temporary files in tests.

## Required failure behavior

- No overwriting an unknown file or directory, including one appearing after preview or staging.
- Source, unit, old wrapper, stage inode/device/size/mtime changes block mutations.
- A missing or invalid witness never authorizes adopting public or staged directories.
- A nonempty or replaced old classification wrapper must not be deleted. Unknown entries are preserved for review.
- No-replace rename and directory fsync are required for wrapper retirement; filesystem refusal is a blocker, not permission to fall back to overwriting rename.
- Interrupted publication retains the staged source link, and retirement never removes the last verified link.
- **Known recoverability boundary:** interruption after unlinking the final private retirement marker but before removing the empty staging directory can leave an unwitnessed empty directory. The implementation must fail closed and preserve it for manual reconciliation, not claim automatic recovery across this last gap.
- A fully finished second scan must show zero planned moves and zero renamed media files.

## Gates before any live execution endpoint

- [ ] Independent security review of path races, same-name old bucket replacement and marker/tombstone handling.
- [ ] Persistent Worker job ownership, exact confirmation token, freeze/validate before mutation, cancellation points and resume/recovery registration.
- [ ] No-replace and directory fsync compatibility proved on a disposable copy on the actual NAS storage.
- [ ] Interruption tests at each mutation boundary, including directory creation before witness, tombstone rename and last-marker retirement.
- [ ] Full backend regression, frontend test/typecheck/build, focused V1.6 TDD and all relevant safety workflows green.
- [ ] User approval before enabling mutation permissions, merging or deploying.

**References:** docs/superpowers/specs/2026-11-17-media-organizer-v1.6-design.md and docs/superpowers/plans/2026-11-17-media-organizer-v1.6.md.
