# V1.6 Complete Media Organizer — Safe Group Publication and Finalization (SDD)

Status: **DESIGN IN PROGRESS — NOT A RELEASE APPROVAL**
Date: 2026-11-18
Primary work: #402 directory source-name race, #400 deferred cleanup/finalization, #399 legacy directory retire race
PR: #397

## Goal / Definition of Done

The user needs an actual completed organizer, not a read-only preview or a safety blocker.

1. Selected-root recursively finds eligible semantic units; image/video paths are separated into their reviewed `P` and `V` groups, with bounded per-group numbering. The selected organizing unit is scanned in full, so in-scope legacy P/V wrappers are inputs to the same frozen plan rather than reasons to suffix a new group name. If a proposed P/V target is occupied by an entry outside the frozen input set, block and preserve it; do not overwrite, adopt or suffix around a foreign occupant.
2. A homogeneous directory already fully organized must be skipped; original scattered/historical group names (including `P1`) are reconciled by the frozen plan. Never overwrite an existing file/directory or adopt a foreign group.
3. Preview → exact-unit confirmation → freeze → validate → stage → publish → verified source cleanup → finalized → second scan **zero changes**. A failed or interrupted job resumes from immutable journal/receipt checks without deleting/moving unrelated files.
4. Real media are not used for RED/GREEN or acceptance. Real SATA tests use the owner's dedicated disposable root. All production execution flags remain OFF until acceptance.
5. Security requirement: **no deletion or relocation of a foreign source entry**, even if the source path changes after a last identity check. Success must be supported by actual filesystem constraints, not an extra stat or operator ACK.

### 2026-11-20 clarification — P/V destination collisions

The user confirmed that each selected organizing unit is processed as a complete scope. Existing `P`, `P1`, `photos`, `V`, and equivalent in-scope classification wrappers are therefore collected and reconciled by the same frozen plan. A separate `P_1`/`V_1` suffix is not a normal response to an in-scope legacy directory. If the canonical destination is occupied by an entry not proven to be part of the frozen input set, the unit must be blocked for review without overwriting, adopting, relocating, or suffixing around that foreign entry. Existing tests cover both idempotent canonical buckets and refusal of an empty foreign final bucket.

## Known Physical Constraint

On Linux, `renameat2(RENAME_NOREPLACE)` binds only the destination non-overwrite condition; it does **not** bind the source basename to a previously verified directory inode. Directory hardlinks are forbidden; `mkdirat` does not return a pinned directory FD. Linux `unlinkat` does not provide an ordinary general-purpose atomic "unlink this pathname only if it still has inode X" primitive. Consequently no portable rename/mkdir/unlink sequence can promise source/target identity safety against a fully privileged or same-UID process allowed to change the same namespace during the operation.

**There is no code-only fix that permits arbitrary uncooperative same-UID/root/SMB writers and simultaneously guarantees no foreign pathname is affected.** The product must prove effective exclusive namespace and content-write custody for supported NAS mounts, or fail closed. Same-UID/root writers are explicitly outside an *enforceably exclusive* boundary unless blocked by OS-level isolation; a checkbox or WorkJob lease is not such a boundary.

## Approaches considered

1. **Keep current grouped hold** — provably avoids the known directory move, but fails the user's core functional requirement. Rejected as a final release.
2. **Direct public mkdir plus FD-bound file publication** — removes the particular source-directory rename race and avoids moving any foreign *source* directory. However, mkdir→open is not an atomic inode-bind and an uncooperative writer in the public unit's namespace could swap the directory before capture. Alone, insufficient for full release.
3. **Separate verified custody boundary + no-clobber group publication + journaled finalization** — chosen for implementation. Require an OS-enforceable isolation arrangement on the actual NAS for each unit and its relevant source/public parents. Use verified directory FDs, frozen inode evidence, exclusive target creation, and fail-closed post-crash reconciliation. The direct-mkdir approach may be used *inside* that boundary; no group publication should be enabled until its permissions and crash behavior are demonstrated.

## Execution design

### Phase A: Immutable preview / scope

- Freeze exact root, each source (dev, ino, size, mtime_ns, name/path, SHA-256 as appropriate), all old classification wrappers and final target names.
- Enforce `ALLOWED_ROOTS` / quarantine exclusions; reject symlinks, mount crossings, unexpected entries and mutable plan authority.
- Select P/V groups only for units that need them; no-op on fully homogeneous/already-organized units. Legacy wrapper remapping and numbering are covered by explicit tests.

### Phase B: Filesystem custody, before mutation

- Identify which OS principal actually performs NAS mutations, including container UID/GID mappings, ACLs, SMB user identities and mount type.
- Verify that no untrusted concurrent actor can write or rename *any relevant source parent, stage parent, public group parent or group child*. A private stage at mode 0700 is necessary but insufficient if another same-UID/root process exists.
- Require an explicit NAS custody evidence record bound to mount ID, unit inode, tested UID/GID/ACL policy, Worker identity and lease. A user-provided boolean ACK is not proof, and an unverified record must fail closed.
- A changed mount, permission, owner, parent inode or receipt invalidates the run; no automatic cleanup of foreign paths.

### Phase C: Group publication without foreign directory relocation

- Do not invoke name-based rename of a private pending group in V1.6 deferred Worker. Under proven exclusive namespace custody, create each public output group using an exclusive mkdir and immediately bind an FD to the child; retain a private checksummed group inode receipt and owner witness.
- Create final file entries *only* via pinned, frozen source FDs and exclusive destination hardlinks. A competitor who changes a source pathname cannot redirect the hardlink; never fall back to a name-based source unlink/rename.
- Every stage/public group operation rechecks custody, witnessed inode and parent-child binding. If a crash occurs before the group has a verifiable receipt, stop for manual review; never adopt an existing anonymous directory.
- Never auto-delete or move an unexpected directory even when the destination is empty.

### Phase D: Safe cleanup and idempotence

- After all final files pass hash/inode/count checks and a separate per-unit confirmation, run a journaled source/old-wrapper cleanup *only under proven OS-enforced namespace custody*.
- Source pathname unlink by name is allowed **only** if no other untrusted actor can rebind that name for the whole critical section. If custody cannot be established, retain source names and mark manual cleanup required — do not claim the job is fully finalized.
- For crash recovery, classify each frozen source as original/stage/public/current and verify immutable receipts before advancing; foreign changes must stop rather than be deleted.
- Retire old wrappers bottom-up and private stage only when each name/inode/children invariant is satisfied throughout the exclusive-custody period.
- Mark `finalized=true` only when canonical rescan reports `already_organized` and `needed_moves=0` and all owned stages/witnesses are either safely retired or recorded as retained separate recoverable evidence.

## Test matrix / acceptance gate

| Threat / behavior | Required RED→GREEN |
|---|---|
| Mixed image/video unit, ordinary isolated filesystem | both P/V groups populated with exact frozen hashes/counts, second preview zero |
| Source child replaced after final identity check | no foreign unlink/move/link |
| Private pending group name replaced before historical rename | no foreign directory relocated (the production path must not call this rename) |
| Public group destination already exists | fail, no overwrite or adoption |
| Public group replaced after FD opens | no foreign directory mutation; fail closed, preserve evidence |
| Crash after mkdir, witness, receipt, publication, cleanup entry | bounded resume or safe manual hold; never wrong target |
| Changed UID/ACL/mount, same-UID shared writable namespace | refuse execution even if user sets ACK |
| Legacy P1 / recursive / collisions / homogeneous no-op | exact output naming; no loss or unintended regrouping |
| Same-mount NAS validation on disposable SATA root | all supported primitives/permissions proven; retained artifacts inspectable |
| Finalization and second scan | finalized only on actually zero needed moves |

## Release policy

No v1.6.0 full-feature release or automatic feature enablement while #402/#400 are open. A fully green CI proves tested behaviors but not exclusivity on the user's actual NAS. The owner has said explicitly that **complete functionality**, not a restricted/preview-only release, is required. PR #397 remains Draft until this document's behavior and real-NAS acceptance are satisfied. Never relabel a blocked feature as a completed release.

The design describes the exact security assumptions that still need proof; it is not evidence that an ordinary shared-UID NAS installation satisfies them.
