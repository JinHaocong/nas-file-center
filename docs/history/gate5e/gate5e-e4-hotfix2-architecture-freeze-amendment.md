# NAS File Center v0.3.5 — Gate5-E / E4-hotfix2

## Architecture Freeze Amendment — Quarantine-First Logical Removal

**Date:** 2026-09-10
**Status:** ARCHITECTURE FREEZE AMENDMENT — APPROVED BY PROJECT OWNER
**Implementation status:** NOT YET AUTHORIZED — remote provenance must be committed and independently verified first
**Authoring baseline:** `73fc9ac7d3fc952da5593bd3b1024b712e992d49`
**Target branch:** `v0.3.5-gate5c-hotfix4`

---

# 1. Amendment authority

This document is a narrow amendment to:

```text
NAS File Center v0.3.5
Gate5-E / E4 Remove Empty Directories
Architecture Freeze — 2026-09-10
```

The original E4 Architecture Freeze remains authoritative except where this Amendment explicitly supersedes it.

This Amendment exists because E4-hotfix1 Independent Review established a blocker:

```text
final identity check
→ concurrent final-component replacement
→ rmdir(name, dir_fd=parent_fd)
```

cannot provide the original strong guarantee:

```text
replacement object must never be deleted
```

`parent_fd` safely anchors the containing directory and prevents ancestor-path redirection, but `rmdir` / `unlinkat(..., AT_REMOVEDIR)` still removes the directory entry identified by the name at mutation time. There is no Linux/POSIX primitive that means:

```text
remove this directory entry
ONLY IF
its current inode still equals Frozen inode X
```

Adding more `stat()` / `lstat()` calls does not remove that final userspace check-to-mutation race.

The project priority therefore remains controlling:

```text
Data safety
> correctness
> recoverability
> performance
> UI
> feature count
```

---

# 2. Sections superseded

Where inconsistent with this Amendment, the following original E4 Freeze sections are superseded:

```text
§3.1 items concerning direct rmdir execution, structural Undo and rmdir recovery
§17 Execute semantics — rmdir_empty
§18 Operation Journal contract
§19 Structural Undo contract
§20 Undo-of-Undo consistency
§21 Crash reconciliation
§24.7 Execute tests
§24.8 Undo tests
§24.9 Crash recovery tests
§26 iterative implementation artifact transport
§28 acceptance-summary lines concerning os.rmdir and structural mkdir_empty Undo
```

Sections covering:

```text
scope semantics
recursive discovery
true emptiness
virtual graph
Preview
preview_digest
Generate Phase A / Phase B
Draft zero identity
Gate3 Freeze
Validate
candidate limits
E1/E2/E3 non-regression
```

remain unchanged unless explicitly stated below.

---

# 3. Public behavior remains unchanged

The public Batch Utility action remains:

```json
{
  "type": "remove_empty_dirs",
  "scope_paths": ["/managed/root/subtree"],
  "recursive": true
}
```

The existing endpoints remain:

```text
POST /api/batch-utilities/preview
POST /api/batch-utilities/generate-plan
```

The lifecycle remains:

```text
Preview / Compile
→ Explicit Generate BatchPlan(draft)
→ Freeze
→ Validate
→ Execute
```

No automatic Freeze, Validate or Execute is introduced.

Preview remains 0-mutation.

Generate Phase A remains read-only.

Generate Phase B remains a short SQLite persistence transaction with zero filesystem traversal/mutation.

---

# 4. Internal operation compatibility

Existing Draft items continue to use:

```text
operation = rmdir_empty
```

The operation name is retained to avoid schema/model migration and unnecessary compatibility breakage.

However, after this Amendment:

```text
rmdir_empty
```

no longer means:

```text
physically destroy the directory with os.rmdir()
```

It now means:

```text
logically remove the authorized empty directory
from the managed user namespace
by atomically relocating it into reserved quarantine storage
without destroying the directory object.
```

This semantic change is intentional and is the central safety correction of E4-hotfix2.

---

# 5. Safety guarantee after Amendment

E4-hotfix2 MUST guarantee:

```text
Unknown or replacement filesystem objects are never permanently destroyed.

A final-component race may at worst cause an unexpected object to be
temporarily relocated into reserved quarantine.

If that occurs:
→ never delete it
→ attempt atomic no-replace rollback
→ if rollback is impossible, preserve it in quarantine
→ expose conflict/recovery evidence

Data destruction is never the race-resolution mechanism.
```

The following is no longer claimed:

```text
A concurrent replacement can never be moved.
```

That guarantee is not available from the target operating-system primitives.

The required strong guarantee is instead:

```text
replacement object MUST NOT be destroyed
unknown identity MUST NOT be permanently deleted
all detected race outcomes MUST remain recoverable
```

---

# 6. Permission gates

For compatibility with the already-approved E4 contract, successful `rmdir_empty` execution continues to require:

```text
ALLOW_MUTATION=true
ALLOW_DELETE=true
```

Although E4-hotfix2 no longer permanently destroys the directory object, `ALLOW_DELETE` remains as a conservative authorization gate for this release.

This Amendment does not widen existing permissions.

A future Gate may independently reconsider whether quarantine-only empty-directory removal should require `ALLOW_DELETE`.

E4-hotfix2 must not make that policy change.

---

# 7. Reserved quarantine trust boundary

`QUARANTINE_ROOT` is the E4-hotfix2 internal holding namespace.

It must be treated as reserved application storage.

Before E4 relocation:

```text
quarantine root exists
quarantine root is a real directory
quarantine root leaf is not a symlink
quarantine root can be opened with directory/no-follow semantics
quarantine root physical identity is bound for the duration of the mutation
```

Normal NAS File Center:

```text
Workflow
Batch Utility
Organizer
Filter-driven mutation
user-selected managed-path actions
```

must not treat quarantine storage as ordinary user-managed namespace.

External mutation of `QUARANTINE_ROOT` by another operating-system process, privileged actor, direct shell operation or a process holding a pre-existing file descriptor is classified as:

```text
out-of-band storage tampering
```

E4 must detect observable inconsistencies and fail closed.

E4 does not claim protection against a malicious operating-system root actor capable of arbitrarily mutating application-private storage.

Even under detected out-of-band tampering:

```text
E4 must not respond by deleting unknown objects.
```

---

# 8. Deterministic E4 quarantine target

Each `rmdir_empty` Plan item derives a deterministic direct-child target below `QUARANTINE_ROOT`.

Recommended canonical form:

```text
<QUARANTINE_ROOT>/
  .nfc-e4-p<plan_id>-s<sequence>-<source_digest16>
```

Where:

```text
source_digest16 =
first 16 hexadecimal characters of SHA256(canonical source_path bytes)
```

Requirements:

```text
fixed bounded name length
single direct child of QUARANTINE_ROOT
no source basename interpolation required
no recursive target-directory creation required
no replacement of an existing quarantine target
deterministically derivable during reconciliation
```

Existing target:

```text
must never be overwritten
```

An existing deterministic target is recovery/conflict evidence, not permission to replace it.

---

# 9. Required FD-relative no-replace rename primitive

The existing:

```text
app/fs_ops.py::rename_noreplace()
```

already uses Linux:

```text
renameat2(..., RENAME_NOREPLACE)
```

but currently operates through `AT_FDCWD`.

E4-hotfix2 is authorized to add one narrow helper equivalent to:

```python
rename_noreplace_at(
    source_dir_fd: int,
    source_name: str,
    target_dir_fd: int,
    target_name: str,
) -> None
```

On Linux this MUST use:

```text
renameat2(
    source_dir_fd,
    source_name,
    target_dir_fd,
    target_name,
    RENAME_NOREPLACE
)
```

Requirements:

```text
no overwrite
no ordinary os.rename fallback
no shutil.move fallback
no copy+delete fallback
no shell command fallback
no path reconstruction through /proc/self/fd
```

If the platform/kernel/filesystem cannot provide the required atomic no-replace primitive:

```text
fail closed
```

If relocation returns:

```text
EXDEV
```

then:

```text
item fails safely
source remains in managed tree
0 copy fallback
0 delete fallback
```

Cross-filesystem support is NOT added by E4-hotfix2.

---

# 10. rmdir_empty Execute protocol

## 10.1 Pre-mutation preparation

Immediately before mutation:

1. verify `ALLOW_MUTATION=true`;
2. verify `ALLOW_DELETE=true`;
3. acquire the containing allowed-root path using stable directory descriptors;
4. reach the source parent using `O_DIRECTORY | O_NOFOLLOW`;
5. bind the final source leaf with no-follow `stat`;
6. verify real directory;
7. verify Frozen `(st_dev, st_ino)`;
8. verify allowed-root / reserved-path constraints;
9. open and bind `QUARANTINE_ROOT`;
10. derive the deterministic quarantine target;
11. verify target does not already exist.

These checks remain necessary but are not treated as an atomic deletion guarantee.

## 10.2 Atomic namespace relocation

The mutation boundary is:

```text
rename_noreplace_at(
    source_parent_fd,
    source_leaf,
    quarantine_root_fd,
    quarantine_target_name
)
```

The source is therefore removed from the user-visible directory tree by one no-replace rename.

E4-hotfix2 MUST NOT call:

```text
os.rmdir
os.unlink
shutil.rmtree
rm -rf
recursive delete
copy+delete
```

as part of successful `rmdir_empty`.

## 10.3 Post-relocation identity verification

After a successful rename, E4 must open the quarantine target with directory + no-follow semantics and inspect the actual moved object.

It must verify:

```text
real directory
not symlink
(st_dev, st_ino) == Frozen identity
```

It must also perform an immediate read-only emptiness observation.

### Outcome A — expected identity, empty

```text
moved identity == Frozen X
and
directory is empty
```

Result:

```text
logical removal completed
directory remains preserved in reserved quarantine
journal success
NO physical destruction
```

### Outcome B — moved identity differs

Example:

```text
Frozen X
→ final userspace check sees X
→ actor replaces leaf with empty Y
→ rename moves Y
```

E4 MUST:

```text
never destroy Y
attempt atomic RENAME_NOREPLACE rollback:
quarantine target → original source name
```

If rollback succeeds:

```text
Y restored to original user-tree location
item = failed/conflict/stale
0 permanent deletion
```

If rollback fails because the original source name is now occupied:

```text
preserve Y in quarantine
item = failed/conflict
record deterministic quarantine path
record observed identity
manual/reconciliation recovery remains possible
```

No overwrite is permitted.

### Outcome C — expected identity but now non-empty

If the correct Frozen directory X was moved, but a file/symlink/special entry appeared through a concurrent/pre-existing handle:

```text
never delete its contents
attempt atomic no-replace rollback
```

Rollback success:

```text
directory restored
item = failed/conflict
```

Rollback impossible:

```text
directory including all contents remains preserved in quarantine
item = failed/conflict
```

No child entry is removed.

### Outcome D — post-relocation verification cannot be completed

Any unexpected:

```text
stat failure
open failure
I/O failure
unexpected type
identity uncertainty
```

must trigger:

```text
no destruction
best-effort atomic no-replace rollback
otherwise preserve quarantine target
item = failed/conflict
```

---

# 11. Final-component race contract

The following race MUST have an explicit regression test:

```text
Frozen source = inode X

1. final identity observation sees X
2. observation returns successfully
3. before mutation, external actor replaces source leaf with
   a different empty directory inode Y
4. E4 mutation begins
```

Acceptable outcomes:

```text
A. Y is atomically moved then successfully rolled back
   → Y survives
   → operation fails/conflicts

B. Y is atomically moved but rollback cannot safely restore it
   → Y remains preserved in quarantine
   → operation fails/conflicts
```

Forbidden outcome:

```text
Y is permanently destroyed
```

This is the core E4-hotfix2 acceptance invariant.

---

# 12. OperationJournal amendment

Successful logical removal continues to record:

```text
operation = rmdir_empty
```

but the journal representation changes.

Required fields include:

```text
before_json.path
before_json.scope_root
before_json.object_type = directory

after_json.logical_removed = true
after_json.preserved = true
after_json.quarantine_path

metadata_before_json:
  final authorized source identity/snapshot

metadata_after_json:
  quarantine object identity/snapshot
```

The Journal must make it possible to determine:

```text
original path
scope anchor
quarantine path
expected/Frozen identity
actual preserved identity
```

without reconstructing undocumented filesystem state.

Failed/conflict relocation that leaves an object preserved in quarantine must record enough evidence in the Plan item metadata/reason/reconciliation state to locate that object.

No DB migration is authorized.

---

# 13. Undo amendment

New E4-hotfix2 successful `rmdir_empty` operations MUST NOT generate structural `mkdir_empty` Undo.

The exact original directory object is still preserved, so Undo should restore that object.

Add one narrow internal operation:

```text
restore_empty_dir
```

Its Draft representation uses existing BatchPlanItem fields:

```text
operation = restore_empty_dir
source_path = recorded E4 quarantine path
target_path = original managed path
expected_device = 0
expected_inode = 0
expected_size = 0
expected_mtime_ns = 0
expected_hash = null
state = planned
```

Gate3 Freeze remains the only authority that captures the quarantined source directory's physical identity.

## 13.1 restore_empty_dir Validate

Validate requires:

```text
quarantine source exists
quarantine source is a real directory
source identity matches Freeze
target is inside original authorized scope / ALLOWED_ROOTS
target is not quarantine
target does not exist, including symlink
target parent exists as a real directory
target parent does not escape through symlink traversal
```

For nested restoration, journal reversal must produce:

```text
shallowest-first restore order
```

so parent directories are restored before their children.

## 13.2 restore_empty_dir Execute

Requires:

```text
ALLOW_MUTATION=true
```

It does not require permanent-delete authorization.

Use stable source quarantine FD and stable target parent FD.

Mutation:

```text
rename_noreplace_at(
    quarantine_root_fd,
    quarantine_name,
    target_parent_fd,
    target_leaf
)
```

No overwrite.

No merge.

No recursive mkdir.

No copy fallback.

Successful restoration preserves the original directory inode/object.

## 13.3 Existing mkdir_empty compatibility

Existing `mkdir_empty` production support introduced before this Amendment must not be casually removed during hotfix2.

For compatibility:

```text
legacy/pre-amendment persisted plans may still execute mkdir_empty
```

subject to their existing safety rules.

However:

```text
new E4-hotfix2 Undo generation MUST NOT emit mkdir_empty
```

for newly completed quarantine-first `rmdir_empty` operations.

---

# 14. Undo-of-Undo consistency

The new logical inverse is:

```text
rmdir_empty
→ restore_empty_dir
```

A successful:

```text
restore_empty_dir
```

may itself be inverted by a newly generated:

```text
rmdir_empty
```

plan through the normal:

```text
Draft
→ Freeze
→ Validate
→ Execute
```

lifecycle.

No inverse operation executes immediately.

No direct filesystem mutation is performed while creating Undo plans.

---

# 15. Crash reconciliation amendment

The deterministic quarantine target is part of reconciliation authority.

## 15.1 rmdir_empty crash states

### State A

```text
source exists as Frozen X
quarantine target absent
```

Interpretation:

```text
relocation did not complete
```

Result:

```text
return to existing retryable/planned convention
```

### State B

```text
source absent or occupied by unrelated object
quarantine target exists as Frozen X
```

Interpretation:

```text
authorized object was relocated
```

Result:

```text
mark original item completed if other safety evidence is consistent
create missing success Journal exactly once
never alter any unrelated object now occupying original source path
```

### State C

```text
quarantine target exists but identity != Frozen X
```

Interpretation:

```text
race/conflict object was relocated
```

Result:

```text
never destroy target
attempt safe no-replace rollback when possible
otherwise preserve in quarantine
mark conflict/failed
record recovery evidence
```

### State D

```text
source Frozen X exists
and
quarantine target also exists
```

Treat as conflict/recovery state.

Do not overwrite either object.

Do not guess which object should be removed.

### State E

```text
source absent
quarantine target absent
```

Without sufficient durable evidence that a prior relocation completed:

```text
fail closed
do not fabricate success
```

## 15.2 restore_empty_dir crash states

### Restore source still in quarantine; target absent

```text
restore did not complete
→ retryable/planned
```

### Quarantine source absent; target exists with Frozen restore identity

```text
restore completed
→ reconcile completed
→ journal exactly once
```

### Target exists with different identity

```text
conflict
→ never overwrite/delete target
```

### Both source and target exist

```text
conflict
→ preserve both
```

Reconciliation remains idempotent.

---

# 16. Quarantine retention limitation

E4-hotfix2 does not permanently destroy quarantined empty-directory objects.

Existing file-quarantine Purge behavior MUST NOT be implicitly reused for these directory holdings unless separately proven safe for directories.

E4-hotfix2 MUST NOT add:

```text
directory purge
recursive purge
retention-time rmdir
automatic cleanup of preserved E4 directories
```

without a separate explicit Architecture Freeze.

Known V1 limitation:

```text
successful remove_empty_dirs may accumulate empty directory objects
inside reserved quarantine storage.
```

This is accepted in favor of avoiding irreversible race-driven deletion.

The objects contain no directory entries at the successful verification point, but their filesystem metadata/inode storage remains allocated.

---

# 17. Required RED tests before production fix

No hotfix2 production change may be written until the new regression tests demonstrate RED against the current `73fc9ac...` behavior.

At minimum add tests covering:

### Final identity race

```text
final authorized identity observation sees X
→ replace source leaf with empty Y
→ mutation proceeds
→ assert Y is NEVER destroyed
```

The current hotfix1 implementation must fail this test for the expected reason.

### Wrong-object rollback

```text
Y moved by race
→ rollback destination free
→ Y restored to original path
→ operation not completed
```

### Rollback collision

```text
Y moved
→ another object occupies original source name
→ rollback NOREPLACE fails
→ Y remains in quarantine
→ neither object destroyed
```

### Non-empty-after-relocation

```text
expected X moved
→ post-relocation observation finds child entry
→ never delete child
→ rollback or preserve conflict
```

### EXDEV

```text
renameat2 returns EXDEV
→ source remains
→ target absent
→ 0 copy
→ 0 rmdir
→ 0 unlink
```

### Quarantine target collision

```text
deterministic quarantine target already exists
→ no overwrite
→ source remains
→ fail/reconcile closed
```

### Forbidden destructive fallback

For the new `rmdir_empty` execution path prove:

```text
0 os.rmdir
0 os.unlink
0 shutil.rmtree
0 recursive delete
0 copy+delete fallback
```

### Crash after successful relocation

```text
X moved
→ process crashes before DB completion
→ reconciliation discovers X at deterministic quarantine target
→ completed exactly once
→ one Journal
```

### Crash with wrong relocated identity

```text
Y at quarantine target
→ never delete Y
→ rollback or preserve conflict
```

### Undo exact-object restoration

```text
successful E4 quarantine relocation preserves inode X
→ Undo Draft
→ Freeze
→ Validate
→ restore_empty_dir
→ restored path has inode X
```

### Undo destination collision

```text
original path already occupied
→ no overwrite
→ quarantined directory remains preserved
→ Undo conflict
```

---

# 18. Regression gate

After RED evidence and implementation, fresh verification must include:

```text
new E4-hotfix2 focused regression tests
all E4 tests
all Gate5-E E1 tests
all Gate5-E E2 tests
all Gate5-E E3 tests
planning / Gate3 / execution / recovery regression
full backend tests/
```

All must show zero failures before the implementation agent may state:

```text
Gate5-E / E4-hotfix2 IMPLEMENTATION COMPLETE
READY FOR INDEPENDENT REVIEW
```

Those words still do NOT mean PASS/CLOSED.

Only Independent Review / project-owner authority may close E4.

---

# 19. Production scope boundary

E4-hotfix2 may modify only the minimum implementation surface required for this Amendment.

Expected candidates:

```text
app/fs_ops.py
app/execution/executor.py
app/service.py
app/tasks/handlers.py
E4-specific supporting helper only if genuinely required
tests/test_gate5e_e4_*.py
docs/history/gate5e/**
```

Possible operation representation additions may touch:

```text
app/batch/plans.py
```

only when necessary for `restore_empty_dir`.

No authorization is granted for:

```text
DB migration
model/table/column migration
new Worker
new worker protocol
new general Undo engine
E1 semantic changes
E2 semantic changes
E3 semantic changes
Gate5-D changes
Workflow changes
Frontend
Gate5-F Resource Control
Scheduler
Copy
Quarantine UI redesign
general Quarantine refactor
unrelated refactor
```

If implementation discovers that any DB migration is necessary:

```text
STOP
→ request another Architecture Freeze amendment
```

---

# 20. TDD and implementation discipline

Required process:

```text
confirm GitHub baseline
→ RED regression
→ verify RED is caused by the known race
→ minimal GREEN implementation
→ focused regression
→ REFACTOR only if necessary
→ full regression
→ implementation walkthrough
→ commit
→ push
→ independent review from remote GitHub commit
```

Do not write production code first and add tests afterward.

Do not weaken the regression to make implementation pass.

Do not mock away the actual mutation-boundary behavior being tested.

---

# 21. GitHub delivery and provenance amendment

For iterative E4-hotfix2 development and review, GitHub is the authoritative code transport.

Target repository:

```text
https://github.com/JinHaocong/nas-file-center
```

Target branch:

```text
v0.3.5-gate5c-hotfix4
```

Each development/review stage must:

```text
commit
push
report exact new HEAD
keep working tree clean
```

Independent Review reads the pushed GitHub commit directly.

A new source ZIP is NOT required for each hotfix iteration.

The original clean-ZIP requirement remains applicable to a later formal release/closure artifact if Gate5-G requires it.

No fabricated ZIP hash/comment/provenance is allowed.

---

# 22. Hotfix2 acceptance invariants

E4-hotfix2 is implementation-correct only if all are simultaneously true:

```text
Public remove_empty_dirs API remains unchanged.

Preview remains 0 mutation.

Generate still requires exact preview_digest.

Draft physical identity remains zero/null.

Gate3 Freeze remains the only physical-identity authority.

Validate still detects stale source identity/type.

rmdir_empty retains ALLOW_MUTATION + ALLOW_DELETE gates.

User-tree removal uses FD-anchored atomic RENAME_NOREPLACE.

No successful E4-hotfix2 rmdir_empty calls os.rmdir.

No successful E4-hotfix2 rmdir_empty calls os.unlink.

No successful E4-hotfix2 rmdir_empty calls shutil.rmtree.

No cross-filesystem copy/delete fallback exists.

The object actually moved into quarantine is verified after relocation.

A wrong replacement object is never permanently destroyed.

A wrong moved object is rolled back with NOREPLACE when safe.

If rollback cannot safely occur, the object remains preserved in quarantine.

A directory found non-empty after relocation is never recursively cleaned.

Successful logical removal records the quarantine location.

New Undo restores the preserved directory object with restore_empty_dir.

New Undo does not overwrite an occupied original path.

No DB migration is introduced.

Existing legacy mkdir_empty support is not casually broken.

Crash reconciliation is deterministic and idempotent.

E1/E2/E3 semantics remain unchanged.

Gate5-F remains forbidden until E4 independently passes/closes.
```

---

# 23. Status after this Amendment

After this Architecture Freeze Amendment is committed and provenance-verified:

```text
E4-hotfix1 = NOT PASS / NOT CLOSED

E4-hotfix2 Architecture Freeze Amendment
= APPROVED / CLOSED

E4-hotfix2 implementation
= AUTHORIZED NEXT

Gate5-F
= FORBIDDEN
```

Implementation may begin only from the independently verified GitHub HEAD containing this Amendment.

This Amendment itself does not declare E4 PASS or CLOSED.
