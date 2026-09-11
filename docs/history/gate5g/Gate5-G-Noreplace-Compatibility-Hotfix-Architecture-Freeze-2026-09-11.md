# Gate5-G NOREPLACE Compatibility Hotfix — Architecture Freeze

Date: 2026-09-11

Status: APPROVED DESIGN / IMPLEMENTATION NOT YET AUTHORIZED

Base candidate SHA: `6ab7e76b133cc03b02df4b3cb9ce7423cbdcb380`

Target platform: 极空间 NAS / Linux amd64 / Docker / `zfuse.zfsv3`

Project safety priority: 数据安全 > 正确性 > 可恢复性 > 性能 > UI > 功能

## 1. Incident / blocker summary

Gate5-G real-NAS G7 failed during the first real mutation Execute of the immutable candidate `6ab7e76b133cc03b02df4b3cb9ce7423cbdcb380`.

Observed execution result:

- Batch execute WorkJob completed its processing loop but reported plan result `stale`.
- Source file remained present.
- Keep file remained present.
- QuarantineEntry became `abandoned`.
- QuarantineEntry `last_error` was `[Errno 22] Invalid argument: '/workspace/data/group1_fileA.dat'`.
- No destructive mutation occurred.

Real-NAS filesystem capability probes established:

- data and quarantine are on the same `st_dev` (`74`);
- ordinary `os.rename` succeeds in both directions;
- `renameat2(flags=0)` succeeds;
- `renameat2(RENAME_NOREPLACE)` returns `EINVAL` for regular files;
- `renameat2(RENAME_NOREPLACE)` returns `EINVAL` for directories, including same-directory tests;
- hard-link creation succeeds for regular files;
- hard-link collision correctly refuses an existing destination without altering either source or target;
- hard-link source and target share the same inode and content;
- after unlinking the original source name, the target preserves inode and content;
- `O_CREAT|O_EXCL` is supported.

Root cause is therefore frozen as:

> `zfuse.zfsv3` supports `renameat2` itself but does not support the `RENAME_NOREPLACE` flag. The current implementation requires that flag for safe no-overwrite relocation.

This is a target-filesystem compatibility blocker, not a cross-filesystem error, topology error, candidate drift, or accidental destructive mutation.

## 2. Scope decision

Approved scope: full compatibility treatment for every currently supported mutation path that depends on strict no-replace relocation semantics.

This means:

- regular-file `rename`;
- regular-file `move`;
- regular-file `quarantine`;
- regular-file `restore`;
- empty-directory quarantine relocation;
- empty-directory restore;
- empty-directory rollback/reconciliation paths.

"Full compatibility" does **not** mean forcing every path to succeed on `zfuse.zfsv3`. A path may remain explicitly fail-closed if the target filesystem cannot provide an equivalent safety primitive without weakening a CLOSED contract.

## 3. Frozen architecture choice

### 3.1 Native fast path remains unchanged

On filesystems where strict atomic no-replace is supported, the current native path remains authoritative:

```text
renameat2(RENAME_NOREPLACE)
    success            -> completed
    EEXIST/ENOTEMPTY   -> collision, preserve target
    EXDEV              -> cross-filesystem fail-closed
    capability-unsupported errno -> compatibility decision
    all other errno    -> fail-closed with original error class
```

The hotfix must not route successful native-capability filesystems through the compatibility path.

### 3.2 Unsupported capability classification

Introduce a distinct internal filesystem capability error, conceptually:

```text
NoReplaceUnsupportedError
```

It may be produced only when native no-replace returns an errno that means the primitive is unavailable for this path/filesystem:

- `EINVAL`;
- `EOPNOTSUPP` / `ENOTSUP`;
- `ENOSYS`.

The following must **not** trigger compatibility fallback:

- `EEXIST` / `ENOTEMPTY`;
- `EXDEV`;
- `EACCES` / `EPERM`;
- `EROFS`;
- `EIO`;
- `ENOSPC`;
- other unrelated operational errors.

## 4. Regular-file compatibility path

### 4.1 Primitive

For regular files only, when native no-replace is explicitly unsupported, use:

```text
link(source, target)
    -> durable DB marker: LINKED
    -> revalidate frozen evidence and worker lease
    -> unlink(source)
```

`link()` provides the required no-overwrite property because an existing target is rejected atomically rather than overwritten.

The compatibility path is forbidden for:

- directories;
- symlinks;
- sockets;
- devices;
- FIFOs;
- other special filesystem objects.

### 4.2 No hidden black-box transition

The compatibility sequence must **not** be implemented as a single opaque `link()+unlink()` helper with no durable state.

After `link()` succeeds and before `unlink(source)`, execution must persist a durable recovery marker using existing `BatchPlanItem.metadata_json.execution`; no DB schema migration is allowed.

Conceptual marker:

```json
{
  "noreplace_transition": {
    "version": 1,
    "strategy": "hardlink_unlink",
    "phase": "linked",
    "source": "...",
    "target": "...",
    "device": 74,
    "inode": 12345
  }
}
```

The exact serialized shape may vary minimally during implementation, but it must preserve all frozen semantics below.

### 4.3 Frozen evidence revalidation

Before final `unlink(source)`, revalidate the operation's frozen evidence and safety state.

At minimum consume/verify, as applicable:

- device;
- inode;
- size;
- mtime_ns;
- expected hash when present;
- operation-specific duplicate/restore integrity requirements;
- source and target must resolve to the same expected inode for the linked transition.

If any required evidence is stale or mismatched:

```text
DO NOT unlink source
preserve source + target
mark fail/conflict
```

### 4.4 Worker lease fencing

Mutation authority must be checked twice:

```text
before link              -> active worker lease required
after durable LINKED commit
before unlink(source)    -> active worker lease required again
```

If the original Worker loses the lease after link but before unlink, it must not complete the second filesystem mutation. Recovery under the new authoritative Worker owns the decision.

## 5. Crash-recovery contract for regular files

The following states are frozen:

| Disk state | Durable marker | Required recovery |
| --- | --- | --- |
| source exists / target absent | none or not-linked | return to planned/retry when otherwise safe |
| source absent / target exists and frozen identity is valid | any | reconcile completed using existing evidence rules |
| source exists / target exists / same expected inode | `phase=linked`, marker identity matches, fresh evidence valid | authoritative Worker may finish `unlink(source)` then complete |
| source exists / target exists / same inode | **no durable linked marker** | conflict; preserve both; never guess |
| source exists / target exists / different inode | any | conflict; preserve both |
| target identity/hash stale or marker mismatch | any | conflict/fail; preserve data |
| both absent | any | failed; data-safety alarm |

A specific crash window is intentionally fail-closed:

```text
link() succeeds
crash occurs before LINKED marker is durably committed
```

After restart, both names may exist and point to the same inode, but without the durable marker the system must **not** infer ownership of the hard-link transition. It must preserve both and report conflict.

This prioritizes data safety over automatic cleanup.

### 5.1 Evidence preparation and SQLite lock discipline

Existing recovery rules remain binding:

- expensive hash/evidence preparation occurs outside the SQLite write transaction;
- `BEGIN IMMEDIATE` consumes already-prepared evidence only;
- the hotfix must not move content hashing into a long write transaction;
- stale precomputed evidence must fail closed.

Repeated reconciliation must remain idempotent and must not emit duplicate successful journals.

## 6. Directory behavior on unsupported filesystems

Approved policy: explicit fail-closed.

For empty-directory quarantine / restore / rollback, `zfuse.zfsv3` does not provide an equivalent hard-link primitive and the CLOSED Gate5-E E4 architecture requires atomic no-replace relocation/rollback semantics.

Therefore the hotfix must **not** replace directory relocation with:

- plain `rename()` after a precheck;
- check-then-rename sequences;
- delete/recreate;
- copy/remove;
- any fallback that can overwrite a concurrently created target;
- any fallback that weakens the zero-permanent-delete preservation contract.

On a filesystem that returns a capability-unsupported errno for directory `RENAME_NOREPLACE`:

- fail explicitly with a filesystem capability reason;
- preserve the source;
- preserve any pre-existing target;
- produce zero successful mutation journal;
- perform no permanent delete;
- do not pretend the operation succeeded.

The existing Gate5-E E4 directory relocation architecture is not reopened.

## 7. Component boundaries / production-code whitelist

Production-code modifications are frozen to at most:

- `app/fs_ops.py`
- `app/execution/executor.py`
- `app/tasks/handlers.py`
- `app/batch_utilities/empty_dir_quarantine.py`

Responsibilities:

### `app/fs_ops.py`

- native no-replace implementation remains;
- classify unsupported capability distinctly;
- provide pure regular-file hard-link no-replace primitive(s);
- no database knowledge;
- preserve existing collision/cross-device/error contracts.

### `app/execution/executor.py`

- preserve native path behavior;
- enforce source object-type eligibility;
- never hard-link fallback a directory/symlink/special object;
- propagate compatibility-required/capability-failure state to orchestration;
- no DB recovery state machine inside this module.

### `app/tasks/handlers.py`

- owns durable LINKED transition marker;
- owns two-phase regular-file compatibility orchestration;
- owns worker lease fencing around both mutation steps;
- extends crash reconciliation for the durable hard-link transition;
- preserves evidence-precompute-outside-write-transaction rule;
- keeps final journal / QuarantineEntry semantics consistent with successful native execution.

### `app/batch_utilities/empty_dir_quarantine.py`

- no relocation algorithm redesign;
- no unsafe plain-rename fallback;
- normalize unsupported no-replace into an explicit capability failure;
- preserve existing rollback/preservation guarantees.

## 8. Explicitly prohibited changes

This hotfix must not modify:

- DB schema or migrations;
- API request/response schema;
- frontend behavior;
- Docker / compose semantics;
- Gate3 physical identity model;
- QuarantineEntry schema;
- Worker protocol;
- Dedupe compiler semantics;
- planning semantics;
- Gate5-E E4 directory relocation architecture;
- closed Gate5 A-F behavior unrelated to the blocker;
- permanent deletion policy;
- unrelated refactors.

No automatic Freeze/Validate/Execute is introduced.

## 9. TDD / RED matrix

Implementation must use strict RED -> GREEN -> REFACTOR -> focused regression -> full regression.

Minimum required coverage:

### 9.1 Native fast path

- native `RENAME_NOREPLACE` success;
- collision remains no-overwrite;
- native-capable filesystem never enters hard-link fallback.

### 9.2 Unsupported capability simulation

- `EINVAL` -> unsupported capability classification;
- `EOPNOTSUPP/ENOTSUP` -> unsupported capability classification;
- `ENOSYS` -> unsupported capability classification;
- unrelated errno does not trigger fallback;
- only regular files are compatibility-eligible.

### 9.3 Normal hard-link transition

- target created atomically without overwrite;
- source and target have same expected inode;
- durable LINKED marker committed before source unlink;
- frozen evidence revalidated;
- worker lease revalidated;
- source unlinked only after all gates pass;
- native-equivalent final journal / QuarantineEntry state.

### 9.4 Collision

- pre-existing target -> correctly refused;
- source unchanged;
- target byte-for-byte unchanged;
- no successful journal;
- no overwrite.

### 9.5 Crash windows

- crash before link -> planned/retry;
- crash after link before durable marker -> preserve both/conflict;
- crash after durable marker before unlink -> authoritative recovery safely completes;
- crash after unlink before final DB commit -> existing reconciliation completes;
- repeated recovery idempotent, exactly one success journal.

### 9.6 Adversarial races

- inode mismatch;
- device mismatch;
- size/mtime stale;
- expected hash mismatch;
- target replacement;
- source mutation after link;
- lease loss after link;
- Worker takeover;
- none may incorrectly unlink source.

### 9.7 Operation coverage

Regular-file compatibility coverage must include:

- quarantine;
- restore;
- rename;
- move.

### 9.8 Directory fail-closed coverage

- unsupported directory NOREPLACE -> explicit capability error;
- empty-directory quarantine -> zero mutation fail-closed;
- empty-directory restore -> zero mutation fail-closed;
- rollback path does not use unsafe fallback;
- existing Gate5-E E4 native tests remain green.

## 10. Regression gate before producing a new candidate

At minimum run:

- new focused compatibility tests;
- Gate2 execution/recovery/quarantine suites;
- Gate3 stale/freeze suites;
- Gate5-E E4 lifecycle/recovery/hotfix suites;
- Gate5-D dedupe lifecycle/generate suites;
- Gate5 A-F focused regression;
- full backend regression;
- frontend typecheck;
- frontend tests;
- frontend production build.

The implementation walkthrough must include:

- modified files;
- RED -> GREEN evidence;
- focused and full regression results;
- architecture compliance statement;
- known limitations;
- REAL_HEAD;
- clean worktree status;
- artifact ZIP SHA256;
- ZIP comment / candidate identity when applicable.

## 11. Candidate reset rule

The failed immutable candidate evaluation is closed as historical evidence:

```text
candidate 6ab7e76b133cc03b02df4b3cb9ce7423cbdcb380
G0-G6 = historical PASS/CLOSED for that SHA
G7 = FAIL
candidate evaluation = TERMINATED
G8 = NOT AUTHORIZED
v0.3.5 = NOT CLOSED
```

Any production-code hotfix creates a new immutable candidate.

For the new candidate:

```text
NEW_HEAD
-> G0 restart
-> G1 source/frontend regression
-> G2 clean Linux amd64 image build and exact tar binding
-> G3 isolated API/Worker smoke
-> G4 fresh + historical DB migration validation
-> G5 SQLite integrity/schema/index validation
-> G6 synthetic filesystem lifecycle
-> G7 real 极空间 NAS lifecycle
-> G8 immutable evidence audit
```

No old candidate PASS may be represented as a PASS for the new SHA.

The previous G7 execution errata/methodology (E1-E5 and testbed topology lessons) may be reused as test method guidance only.

The old image/tar is not valid for the new candidate.

## 12. Acceptance criteria for this hotfix architecture

The implementation is acceptable for independent review only when all of the following hold:

1. Native-capable filesystems retain existing strict no-replace behavior.
2. On `zfuse.zfsv3`, regular-file quarantine/restore/rename/move can complete using the approved compatibility transition without target overwrite.
3. Crash after hard-link creation cannot cause an unowned or stale Worker to unlink source.
4. Crash reconciliation never guesses ownership of a two-name state without a durable linked marker.
5. All stale identity/hash cases preserve data and fail closed.
6. Directory paths on unsupported no-replace filesystems fail explicitly and safely with zero destructive mutation.
7. Gate5-E E4 directory architecture remains unchanged.
8. No schema/API/frontend/protocol changes are introduced.
9. Full regression remains green.
10. A new immutable candidate is created and Gate5-G restarts at G0.

## 13. Architecture status

Approved sections:

- Section 1 — scope + directory fail-closed: APPROVED
- Section 2 — regular-file compatibility + crash semantics: APPROVED
- Section 3 — error model + boundaries + TDD + candidate reset: APPROVED

Implementation status:

```text
ARCHITECTURE FREEZE = APPROVED
IMPLEMENTATION = NOT YET AUTHORIZED
G8 = NOT AUTHORIZED
v0.3.5 = NOT CLOSED
```
