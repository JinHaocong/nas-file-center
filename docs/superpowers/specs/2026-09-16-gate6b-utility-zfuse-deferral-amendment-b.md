# Gate6-B Architecture Amendment B — Utility zfuse Deferral + Empty-Wrapper Removal Authority

**Status:** APPROVED / FROZEN  
**Approval date:** 2026-09-16  
**Parent Freeze:** `2026-09-16-gate6b-utility-recursive-dirbal-architecture-freeze.md`  
**Amendment A:** `2026-09-16-gate6b-recursive-last-file-concurrency-amendment-a.md`  
**Baseline reviewed candidate before this amendment:** `fb120bfe2a760c1294c0ed650f95988dac1410ce`  
**Canonical branch:** `v0.3.6-gate6b-utility-recursive-dirbal`  
**Target platform:** 极空间 NAS / Linux amd64 / Docker / `zfuse.zfsv3`  
**Authority:** User-approved architecture amendment after real-NAS acceptance blocker  
**Implementation status:** NOT AUTHORIZED BY THIS DOCUMENT ALONE — implementation requires a post-amendment implementation plan and renewed review/validation chain.

---

## 1. Why this amendment exists

Gate6-B exact candidate `fb120bfe2a760c1294c0ed650f95988dac1410ce` passed source review, Independent Review, CI, and linux/amd64 Docker validation, then reached real-NAS small-data acceptance on the target 极空间 `zfuse.zfsv3` filesystem.

Recursive Directory Balanced by Bytes, Recursive Last-File Protection, Execute-time live preflight, Worker fail-closed behavior, Quarantine/Restore, and reserved Quarantine exclusion passed their real-NAS acceptance scenarios.

The final Utility acceptance scenario exposed a target-filesystem execution blocker for Single-Child Wrapper Collapse:

```text
scope:  /data/utility/A
source: /data/utility/A/B/C
target: /data/utility/A/C
plan:   MOVE source -> target
        REMOVE_EMPTY_DIR /data/utility/A/B
```

Observed exact-candidate result:

```text
BatchPlan #4 = partial
MOVE          = failed
reason        = [Errno 95] Atomic no-replace rename not supported by filesystem
RMDIR_EMPTY   = skipped
reason        = permanent deletion is disabled
WorkJob #7    = completed (handler terminal status, NOT plan success)
OperationJournal mutations = 0
```

Filesystem evidence after the failed execution:

```text
filesystem = zfuse.zfsv3 / fuseblk
source payload still present
source SHA256 unchanged
source device/inode/size unchanged
target absent
wrapper present
child present
rename probe residue absent
partial filesystem mutation = false
```

This is a real target-platform capability mismatch, not a test-script failure and not candidate drift.

---

## 2. Root cause and architectural constraint

The existing Gate5-E / BatchPlan MOVE path uses strict kernel no-replace rename semantics through `rename_noreplace()`.

On native filesystems that support `renameat2(..., RENAME_NOREPLACE)`, this provides the required atomic target-exclusion guarantee.

On the target `zfuse.zfsv3` filesystem, `RENAME_NOREPLACE` is not supported and the primitive correctly fails closed with `EOPNOTSUPP`.

Ordinary POSIX `rename()` on this filesystem is not an acceptable transparent fallback for Gate6-B Utility because it can replace an existing destination. A userspace sequence such as:

```text
check target absent
-> rename(source, target)
```

cannot preserve the frozen absolute `NEVER overwrite` guarantee against an arbitrary external writer that creates the target in the final syscall gap.

The existing Gate5-G COMPAT transactional quarantine engine does not automatically solve this directory MOVE problem. Its namespace, payload-anchor, write-once capture, and recovery invariants are specific to Quarantine/Restore. Reusing its existence as justification for an ordinary Utility directory rename would be architecturally false.

Therefore Gate6-B MUST NOT silently weaken `NEVER overwrite`, MUST NOT introduce a bare ordinary-rename fallback, and MUST NOT grow a new recursive directory-migration transaction subsystem inside this already-reviewed Gate.

---

## 3. Frozen decision A — defer COMPAT/zfuse Utility mutation

For Gate6-B, Single-Child Wrapper Collapse execution support is frozen as:

```text
NATIVE_ATOMIC_NOREPLACE filesystem
    -> Utility candidate may proceed through the existing MOVE + empty-wrapper chain.

COMPAT_TRANSACTIONAL / no native RENAME_NOREPLACE filesystem
    -> Utility filesystem mutation is NOT supported in Gate6-B.
    -> fail closed before filesystem mutation.
    -> zero MOVE, zero RMDIR, zero OperationJournal mutation.
```

This amendment intentionally narrows the Gate6-B delivery boundary on COMPAT filesystems rather than weakening target-exclusion safety.

### 3.1 Truthful capability surface

A COMPAT/zfuse Utility scope MUST NOT be presented as fully executable and then fail only after Worker mutation starts.

Before a filesystem-mutating Utility Plan becomes executable, the system must resolve the mutation capability for the authoritative Utility scope.

For Gate6-B on COMPAT filesystems, the product must expose an explicit unsupported/fail-closed state such as:

```text
UTILITY_MOVE_UNSUPPORTED_FILESYSTEM
```

or another stable, documented equivalent.

Required semantics:

- Preview remains read-only.
- Discovery may still explain the wrapper candidate topology.
- The UI/API must make the COMPAT mutation limitation explicit.
- Generate/Freeze/Validate/Execute MUST NOT create false mutation authority for an unsupported COMPAT Utility MOVE.
- No ordinary `rename()` compatibility fallback is authorized by Gate6-B.
- No overwrite, merge, auto-rename, copy-delete, recursive migration, or second executor is authorized.

The exact product stage at which the unsupported state becomes terminal may be chosen during implementation, but it MUST be no later than Validate and MUST occur before Worker filesystem mutation authority. The preferred UX is Preview/Generate-time truthfulness when capability is already knowable.

### 3.2 Native behavior remains unchanged

On filesystems where strict native `RENAME_NOREPLACE` is positively supported:

```text
MOVE A/B/C -> A/C
-> verify MOVE completed
-> reopen/re-check B
-> REMOVE_EMPTY_DIR B only if physically empty
```

remains the Gate6-B Utility execution contract.

Target collision remains fail closed with zero overwrite/merge/auto-rename.

---

## 4. Frozen decision B — create Gate6-B2 for COMPAT Utility MOVE

Actual Utility Single-Child Wrapper Collapse mutation on `zfuse.zfsv3` is deferred to a dedicated follow-up Gate:

```text
Gate6-B2 — COMPAT Utility Move / Single-Child Wrapper Collapse
```

Gate6-B2 is not authorized to start implementation without its own Architecture Freeze.

Its future architecture MUST explicitly solve, not hand-wave, all of the following:

1. strict no-overwrite semantics on a filesystem without native `RENAME_NOREPLACE`;
2. source directory identity / parent identity / target authority;
3. source and target ABA/rebind handling;
4. external-writer race boundaries and any unavoidable non-linearizability claims;
5. crash/restart reconciliation;
6. stale Worker / lease behavior;
7. deterministic success/conflict states;
8. recovery without deleting unknown or foreign objects;
9. directory inode / metadata preservation expectations;
10. bounded scope that does not become an implicit general recursive directory migration engine.

Gate6-B2 MUST NOT be implemented as:

```text
if target does not exist:
    os.rename(source, target)
```

or any equivalent check-then-rename sequence that can overwrite a concurrently-created target.

Gate6-B2 MUST also decide explicitly whether directory-inode preservation is a product requirement. If preserving the directory inode conflicts with strict target-exclusion safety on COMPAT, that trade-off requires user approval in the Gate6-B2 Freeze.

---

## 5. Frozen decision C — empty-wrapper removal is narrow structural cleanup

The real-NAS run also exposed that the existing executor groups `rmdir_empty` under the broad `ALLOW_DELETE` gate and therefore skips it when `ALLOW_DELETE=false`.

For Gate6-B Utility, this broad classification is amended.

A Utility `REMOVE_EMPTY_DIR` generated exclusively as the second half of an approved Single-Child Wrapper Collapse is defined as:

```text
EMPTY_WRAPPER_STRUCTURAL_CLEANUP
```

It is NOT equivalent to permanent file deletion and MUST NOT implicitly authorize:

- `unlink()` of regular files;
- Quarantine purge;
- recursive directory deletion;
- deletion of non-empty directories;
- deletion outside the exact frozen wrapper identity;
- any generic user-authored `rmdir_empty` operation.

### 5.1 Narrow authority requirements

The narrow cleanup may execute only when ALL conditions hold:

1. the item belongs to a frozen Utility `single_child_wrapper_collapse` Plan;
2. the immediately preceding paired MOVE item for the same candidate completed successfully;
3. the wrapper path is the exact wrapper bound by Preview/Generate/Freeze;
4. the wrapper is reopened using no-follow / identity-bound authority;
5. device/inode still match the frozen wrapper identity;
6. the wrapper is physically empty at execution time;
7. the wrapper remains inside the authoritative managed Index Root;
8. the wrapper is not within reserved Quarantine storage;
9. any rebind, symlink, special object, new child, or ambiguity fails closed;
10. deletion uses non-recursive empty-directory removal only.

If any object appears inside the wrapper after MOVE, cleanup MUST skip/fail closed and preserve both the wrapper and the new object.

### 5.2 Configuration boundary

Gate6-B implementation MAY introduce a narrowly-scoped execution authority for this exact structural cleanup so that global `ALLOW_DELETE=false` does not incorrectly suppress the frozen Utility contract.

That authority MUST NOT broaden the meaning of `ALLOW_DELETE` for historical operations. Existing `unlink`, purge, and unrelated `rmdir_empty` behavior remains unchanged unless separately frozen in another Gate.

The safest implementation shape is operation/context-specific authorization derived from the frozen Utility Plan metadata, not a global setting that enables deletion generally.

---

## 6. Preserved Gate6-B invariants

This amendment does NOT reopen or weaken the following:

- `mode="utility"` remains explicit.
- Utility V1 still supports only `single_child_wrapper_collapse`.
- scope remains authoritative managed Index Root + optional safe relative subpath.
- candidate discovery remains descriptor-bound / no-follow / identity-aware.
- target collision never overwrites, merges, or auto-renames.
- Preview performs zero filesystem mutation and zero Plan persistence.
- Generate may persist only explicitly selected current READY candidates.
- one Plan collapses at most one layer.
- Workflow remains compiler/orchestrator, never filesystem executor.
- existing Worker remains the sole execution authority.
- no second Worker/executor.
- Recursive Directory Balanced by Bytes semantics are unchanged.
- Amendment A Recursive Last-File authority is unchanged.
- Dedupe mutation remains Quarantine only.
- no new permanent regular-file delete path is added.
- data safety > correctness > recoverability > security > performance > UI > feature count.

---

## 7. Gate6-B closure semantics after Amendment B

Gate6-B may close only after a new post-Amendment-B candidate completes the full required chain.

On the target `zfuse.zfsv3` NAS, Gate6-B Utility acceptance is changed from "successful wrapper mutation" to "truthful unsupported COMPAT behavior with zero mutation".

Required real-NAS Utility acceptance for Gate6-B:

```text
1. discover the valid A/B/C wrapper topology read-only;
2. resolve filesystem mutation capability as COMPAT / no native no-replace;
3. expose explicit unsupported Utility mutation state;
4. do not create executable false authority for MOVE;
5. source payload remains present and identity/hash unchanged;
6. target remains absent;
7. wrapper remains present;
8. zero OperationJournal mutation;
9. no recursive delete / no permanent file delete;
10. production remains untouched.
```

A separate native-filesystem regression MUST continue to prove the full successful Utility path:

```text
MOVE C -> target
-> verify success
-> identity-bound reopen wrapper
-> empty-wrapper structural cleanup
```

Gate6-B closure does NOT claim that Single-Child Wrapper Collapse mutation works on `zfuse.zfsv3`. That claim is reserved for Gate6-B2.

---

## 8. Required post-amendment TDD / regression coverage

At minimum, the post-Amendment-B implementation must add or update tests for:

### 8.1 COMPAT capability truthfulness

- COMPAT filesystem candidate discovery remains read-only and explainable.
- COMPAT Utility mutation is marked unsupported before Worker filesystem mutation.
- no Draft/Ready/Execute state falsely claims executable mutation authority once unsupported capability is known.
- zero ordinary `rename()` fallback.
- zero filesystem mutation.
- zero OperationJournal mutation.
- stable explicit reason/code.

### 8.2 Native Utility execution

- existing native `RENAME_NOREPLACE` success path remains GREEN.
- target collision remains zero-overwrite.
- source/target identity ABA coverage remains GREEN.
- MOVE must complete before wrapper cleanup.
- third-party object after MOVE preserves wrapper.

### 8.3 Empty-wrapper narrow authority

- Utility paired `rmdir_empty` can execute under global `ALLOW_DELETE=false` only with exact frozen Utility cleanup authority.
- generic/unrelated `rmdir_empty` remains blocked under `ALLOW_DELETE=false`.
- `unlink`, purge, and file deletion remain blocked under `ALLOW_DELETE=false`.
- wrong Plan kind / wrong candidate binding / missing predecessor success fails closed.
- wrapper inode/dev change fails closed.
- symlink/rebind fails closed.
- non-empty wrapper fails closed.
- recursive removal is never used.

### 8.4 Historical regressions

- Gate5-E historical behavior not intentionally rewritten outside the narrow Utility context.
- Gate6-A / Gate6-A2 Quarantine/Restore/Purge authority unchanged.
- Amendment A recursive Last-File behavior unchanged.
- reserved Quarantine exclusion regression remains GREEN.
- frontend/API communicate the unsupported COMPAT state truthfully.

---

## 9. Review and validation reset

The previous exact candidate:

```text
fb120bfe2a760c1294c0ed650f95988dac1410ce
```

remains valid historical evidence for the work already reviewed and for the NAS acceptance observations obtained against that exact source/image.

However, once Amendment B is committed and implementation changes begin, it is no longer closure authority for Gate6-B.

The post-Amendment-B candidate MUST rerun, in hard order:

```text
post-amendment Implementation Plan
-> Strict TDD RED/GREEN/REFACTOR
-> focused regression
-> full backend regression
-> frontend tests/typecheck/build if affected
-> baseline-to-new-candidate Coordinator Source Review
-> new Independent Review on exact new candidate
-> exact-candidate linux/amd64 Docker validation
-> real NAS small-data acceptance
-> Gate6-B PASS / CLOSED
```

Previously-passed NAS recursive scenarios may be reused as historical evidence only where the new source diff provably does not touch their authority chain; the Coordinator and Independent Reviewer must decide whether targeted reruns are sufficient. The affected Utility NAS acceptance MUST be rerun.

No merge, production deployment, or Gate closure is authorized merely by this amendment.

---

## 10. Gate ordering after Amendment B

The intended sequence becomes:

```text
Gate6-B
  Utility compiler/discovery + native strict execution boundary
  Recursive Directory Balanced by Bytes
  COMPAT Utility mutation truthfully unsupported
-> Gate6-B PASS / CLOSED
-> Gate6-B2
  COMPAT/zfuse Utility Move architecture + implementation
-> Gate6-B2 PASS / CLOSED
-> Gate6-C / subsequent v0.3.6 work
```

Gate6-B2 may be renamed during its own Freeze, but it MUST remain a distinct architecture decision point before the project can claim target-zfuse Single-Child Wrapper Collapse mutation support.

---

## 11. Non-goals of Amendment B

This amendment does NOT authorize:

- ordinary `rename()` fallback on zfuse;
- weakening `NEVER overwrite`;
- copy-then-delete directory migration;
- recursive tree migration;
- implicit merge;
- automatic target rename;
- second Worker/executor;
- widening `ALLOW_DELETE` globally;
- file unlink under the empty-wrapper cleanup authority;
- secure erase;
- reimplementation of Quarantine/Restore transactional semantics for directories inside Gate6-B;
- claiming zfuse Utility mutation support before Gate6-B2 passes real-NAS acceptance.

---

## 12. Closure statement

Amendment B chooses safety-preserving scope reduction over a misleading or weaker COMPAT fallback.

Gate6-B keeps its strict no-overwrite semantics and may complete with truthful COMPAT Utility non-support on the target `zfuse.zfsv3` platform. Actual COMPAT Single-Child Wrapper Collapse mutation becomes Gate6-B2 and requires a new Architecture Freeze.

The only deletion-authority change inside Gate6-B is the narrowly bound `EMPTY_WRAPPER_STRUCTURAL_CLEANUP` that may remove the exact verified-empty wrapper directory after its paired Utility MOVE succeeds. It grants no authority over regular files, payloads, purge, recursive deletion, or unrelated directories.
