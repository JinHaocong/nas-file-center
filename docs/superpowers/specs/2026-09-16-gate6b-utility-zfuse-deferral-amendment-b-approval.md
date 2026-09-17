# Gate6-B Architecture Amendment B — Approval / Freeze Record

**Status:** APPROVED / FROZEN
**Approval date:** 2026-09-16
**Approved by:** project owner in the Gate6-B coordination session
**Canonical branch:** `v0.3.6-gate6b-utility-recursive-dirbal`
**Approved spec:** `docs/superpowers/specs/2026-09-16-gate6b-utility-zfuse-deferral-amendment-b.md`
**Approved spec commit:** `6c363b7ce24154451fb07054917085791a7ca87d`
**Pre-amendment reviewed/NAS candidate:** `fb120bfe2a760c1294c0ed650f95988dac1410ce`

This record promotes the exact Amendment B text at commit `6c363b7ce24154451fb07054917085791a7ca87d` to **APPROVED / FROZEN**. If the status header inside that proposed-spec snapshot still says `PROPOSED / AWAITING WRITTEN SPEC REVIEW`, this approval record controls and supersedes that header for architecture authority.

## Frozen decisions

1. Gate6-B MUST preserve strict no-overwrite semantics and MUST NOT add an ordinary `rename()` fallback for Utility MOVE on `zfuse.zfsv3` / COMPAT filesystems lacking native `RENAME_NOREPLACE`.
2. Utility Preview MUST resolve the COMPAT limitation before Generate authority. A valid wrapper topology on unsupported COMPAT storage is exposed as `UNSUPPORTED_FILESYSTEM` (or the exact stable equivalent frozen by the approved spec), `selectable=false`, with stable reason/code `UTILITY_MOVE_UNSUPPORTED_FILESYSTEM`.
3. Generate MUST reject forced selection of that candidate and persist **zero Draft**.
4. Gate6-B may close on the target zfuse NAS only after real-NAS evidence proves truthful unsupported COMPAT behavior with zero filesystem mutation and zero OperationJournal mutation.
5. Actual zfuse Single-Child Wrapper Collapse mutation is deferred to a separate `Gate6-B2` Architecture Freeze; Gate6-B2 is not implementation-authorized by this record.
6. Native filesystems with strict no-replace support retain the full Utility contract: MOVE first, verify, then identity-bound verified-empty wrapper removal.
7. The paired Utility empty-wrapper removal is a narrowly-scoped structural cleanup authority and is not equivalent to regular-file permanent deletion. It MUST NOT widen `ALLOW_DELETE` for unlink, purge, recursive delete, non-empty directories, unrelated `rmdir_empty`, or any regular-file operation.
8. Amendment B takes precedence over conflicting Parent Freeze language about successful Utility mutation on COMPAT/zfuse filesystems. Amendment A recursive Last-File semantics remain unchanged.

## Review reset

The old exact candidate `fb120bfe2a760c1294c0ed650f95988dac1410ce` remains historical review/Docker/NAS evidence only. Post-Amendment-B implementation requires a new exact candidate and renewed TDD, regression, Coordinator Source Review, Independent Review, linux/amd64 Docker validation, and affected real-NAS acceptance before Gate6-B closure.

No merge, production deployment, or Gate closure is authorized by this approval record alone.
