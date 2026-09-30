# Storage Optimization — Hardlink / Reflink H0 Architecture Freeze

Status: **H0 CLOSED BY PRODUCT DECISION / IMPLEMENTATION AUTHORIZED**
Source baseline: `main@22f430698aa089a484e21f572a8c9739466ff893`
Product baseline: **v0.4.7**

## 1. Scope decision

The next product track is **explicit exact-duplicate storage optimization** using
Hardlink and Reflink where the actual target filesystem positively proves the
required capability.

This track does **not** replace the current dedupe default. Existing dedupe
continues to mean:

```text
Exact duplicate Scan
→ Preview
→ Draft Plan
→ Freeze
→ Validate
→ Execute
→ Quarantine
```

Hardlink / Reflink are opt-in alternatives exposed only when the user explicitly
selects the storage-optimization mode.

V1 is intentionally limited to already-proven exact duplicate files. It is not a
generic copy, clone, file-conversion or directory feature.

## 2. Non-negotiable authority boundary

Hardlink / Reflink MUST:

- reuse the existing BatchPlan / Freeze / Validate / Worker Execute lifecycle;
- reuse PathGuard, allowed roots, symlink rejection, stale identity checks and
  Worker lease fencing;
- require `ALLOW_MUTATION=true`;
- remain disabled by default;
- require explicit user selection for every generated Plan;
- re-run full SHA-256 duplicate verification at Validate and immediately before
  the mutation boundary;
- preserve at least one authorized content path;
- fail closed when capability is unsupported, ambiguous or changes;
- never become an automatic Scheduler target;
- never become a hidden Workflow side effect;
- never silently change existing `quarantine` dedupe semantics.

This track MUST NOT introduce a second filesystem executor or shell out to
`fclones link` / `fclones dedupe` as mutation authority.

## 3. V1 operations

Two new explicit BatchPlan item operations are allowed:

```text
hardlink_optimize
reflink_optimize
```

They are generated only from an exact duplicate group with one existing KEEP
path and one or more independently frozen duplicate source paths.

### 3.1 Hardlink result

For one source path:

```text
before:
KEEP  -> inode A
SOURCE -> inode B
SHA256(A) == SHA256(B)

after:
KEEP  -> inode A
SOURCE -> inode A
```

The pathname remains, but the independent SOURCE inode is retired.

UI must state clearly that future writes through either path affect the same
inode. Hardlink optimization must never be presented as two independent copies.

### 3.2 Reflink result

For one source path:

```text
before:
KEEP  -> inode A
SOURCE -> inode B

after:
KEEP  -> inode A
SOURCE -> inode C
inode C != inode A
content SHA256 unchanged
clone relationship = filesystem CoW implementation detail
```

The pathname remains an independently addressable inode. The filesystem may
share physical blocks until one copy changes.

## 4. Eligibility

Common eligibility:

- KEEP and SOURCE are regular files;
- neither path is a symlink;
- both resolve inside current allowed roots;
- both exist at Preview / Freeze / Validate / Execute;
- same size;
- full SHA-256 equal;
- KEEP and SOURCE are different filesystem entries before optimization;
- source path is not inside reserved quarantine storage;
- current Plan / Scan provenance remains valid;
- no operation may target the last remaining authorized content path.

Hardlink additionally requires:

- KEEP and SOURCE support hard links to the SOURCE parent;
- runtime capability probe succeeds on the actual destination parent;
- KEEP and SOURCE metadata that becomes inode-shared is compatible under the
  frozen metadata policy in section 7.

Reflink additionally requires:

- Linux `FICLONE` (or a future explicitly frozen equivalent) succeeds in a
  disposable runtime probe on the actual SOURCE parent;
- created clone is a new inode;
- cloned content verifies to the frozen SHA-256.

## 5. Runtime capability model

Filesystem names, mount labels and `st_dev` equality are not sufficient proof.

Capability states:

```text
SUPPORTED
UNSUPPORTED
UNKNOWN
```

`UNKNOWN` is fail-closed.

### Hardlink probe

The probe uses disposable NFC-owned files in the target parent:

1. create source probe file with `O_CREAT|O_EXCL`;
2. create hardlink at a unique destination name;
3. prove both paths share `dev + inode`;
4. prove the probe bytes are intact;
5. remove only NFC-owned probe paths;
6. prove zero probe residue.

Any cleanup uncertainty returns `UNKNOWN`.

### Reflink probe

The probe uses two disposable NFC-owned files in the target parent:

1. create source probe with known bytes;
2. create destination with `O_CREAT|O_EXCL`;
3. issue `ioctl(FICLONE)`;
4. prove destination is a different inode;
5. prove destination bytes equal source bytes;
6. mutate the destination probe and prove the source bytes do not change;
7. remove only NFC-owned probe paths;
8. prove zero probe residue.

The destination-mutation step is required to prove copy-on-write independence,
not merely successful ioctl return.

Capability results may be request-local cached only for the exact probed parent
identity. A cached positive result is never permanent authority for Execute;
Execute re-probes or uses an equivalently strong short-lived proof.

## 6. Preview / Generate contract

Advanced Dedupe gains one explicit `storage_action`:

```text
quarantine   # existing default
hardlink
reflink
```

Default remains `quarantine`.

Preview must show per item:

- KEEP path;
- SOURCE path;
- selected storage action;
- capability state;
- bytes potentially reclaimed;
- whether metadata is hardlink-compatible;
- warning when Hardlink will create shared-inode semantics;
- blocking reason when unsupported.

Generate accepts only items from the exact Preview digest.

The Preview digest must bind at least:

- scan/group provenance;
- KEEP/SOURCE selection;
- content hash / size facts used by the preview;
- storage action;
- capability result and probed parent identity;
- hardlink metadata-compatibility result;
- safety policy snapshot.

Any decision-affecting change requires a fresh Preview.

## 7. Metadata policy

Hardlink makes inode metadata shared. V1 therefore refuses Hardlink optimization
unless KEEP and SOURCE have compatible inode-level metadata.

Required equality before Hardlink:

- file type;
- permission mode bits;
- uid;
- gid;
- file size;
- content SHA-256;
- supported extended attributes when they can be read safely.

mtime does not need to be equal because content verification remains the
authority, but the UI must state that the resulting shared inode uses KEEP inode
metadata.

If extended-attribute enumeration/read is unsupported or ambiguous, Hardlink is
`UNKNOWN` / blocked for that item rather than silently discarding SOURCE
metadata semantics.

Reflink V1 preserves SOURCE-facing metadata on the replacement inode:

- mode;
- uid/gid where permitted without privilege expansion;
- atime/mtime;
- safely readable xattrs.

If required metadata cannot be preserved, the item fails closed before retiring
the original SOURCE inode.

## 8. Transaction protocol

Neither operation may be implemented as:

```text
unlink(source)
→ create replacement
```

V1 uses a per-item durable transaction id persisted in BatchPlan item metadata.

Inside the SOURCE parent, NFC owns two unique sibling transaction names:

```text
.__nfc_opt_<transaction_id>.new
.__nfc_opt_<transaction_id>.old
```

Protocol:

1. revalidate Worker lease;
2. revalidate KEEP and SOURCE frozen identities;
3. full SHA-256 verify KEEP == SOURCE == frozen expected hash;
4. prove selected capability on the current SOURCE parent;
5. create `.new` using hardlink or reflink semantics;
6. verify `.new` content and required identity/metadata;
7. capture SOURCE to `.old` using no-clobber rename authority;
8. publish `.new` to the original SOURCE pathname using no-clobber authority;
9. fsync parent where supported;
10. verify published pathname matches the intended optimized result;
11. only then retire NFC-owned `.old`;
12. write terminal audit / journal state.

No step may overwrite an unrelated path.

## 9. Crash / restart convergence

Recovery must distinguish these states:

- nothing created;
- `.new` exists, SOURCE unchanged;
- SOURCE captured to `.old`, `.new` ready;
- optimized SOURCE published, `.old` remains;
- terminal success.

Recovery may only operate on transaction names bound to the exact frozen
transaction id and frozen SOURCE/KEEP identities.

If ownership or identity is ambiguous:

```text
preserve all payload-bearing paths
→ mark failed/conflict
→ zero guessed unlink
```

A stale Worker may not publish success or retire `.old`.

## 10. Delete and data-safety semantics

These operations retire one independently stored exact duplicate payload, but
the original pathname remains present with verified content.

V1 therefore remains under `ALLOW_MUTATION`, not the generic permanent-delete
API. It does not grant arbitrary unlink authority.

The only unlink authority is the NFC-owned `.old` transaction path created by
the same frozen item after the optimized SOURCE pathname has been published and
verified.

The operation must never unlink KEEP.

## 11. API / RBAC / UI

- authenticated users may view capability state;
- only admin may generate or execute Hardlink/Reflink optimization Plans;
- existing CSRF/origin protection applies;
- no arbitrary path mutation endpoint is introduced;
- capability probing accepts only paths already represented by an authorized
  scan/dedupe context or an allowed-root admin capability check;
- mobile and desktop must both expose the selected storage action and warning.

Hardlink UI requires an explicit warning acknowledgement at Generate time:

```text
The optimized paths will share one inode. Future writes through either path
change the same file content.
```

## 12. Workflow / Scheduler boundary

V1 direct Advanced Dedupe UI/API only.

Not included:

- Workflow Hardlink/Reflink step;
- Scheduler Hardlink/Reflink target;
- automatic post-scan optimization;
- automatic conversion of existing Dedupe Plans.

A later expansion requires a new amendment.

## 13. Database / migration

Prefer additive metadata on existing BatchPlan items where possible.

If durable recovery requires new tables, they must be additive and migration
must preserve existing databases.

No migration may reinterpret historical `quarantine` or `unlink` items as
Hardlink/Reflink operations.

## 14. TDD matrix

H1 — capability primitives:

- hardlink positive probe;
- hardlink cross-filesystem / unsupported;
- hardlink cleanup failure => UNKNOWN;
- reflink positive probe;
- FICLONE unsupported => UNSUPPORTED;
- reflink ioctl success but shared-write behavior wrong => UNKNOWN;
- probe residue = zero;
- symlink / outside-root rejected.

H2 — Preview / Generate / Freeze / Validate:

- default storage action remains quarantine;
- unsupported action blocked;
- exact Preview digest binding;
- full SHA-256 equality required;
- same-inode preexisting hardlink is not an independent optimization candidate;
- metadata mismatch blocks Hardlink;
- stale KEEP/SOURCE blocks Validate;
- zero Draft on changed Preview.

H3 — execution / recovery:

- successful hardlink transaction;
- successful reflink transaction;
- target collision;
- SOURCE ABA;
- KEEP change;
- lease loss at each transaction boundary;
- crash after `.new`;
- crash after SOURCE capture;
- crash after publication before `.old` retirement;
- foreign transaction path preserved;
- zero unrelated unlink;
- restart convergence.

H4 — product / closure:

- frontend action selector and warnings;
- full backend regression;
- frontend tests / typecheck / build;
- linux/amd64 Docker;
- isolated filesystem acceptance;
- real NAS capability probe evidence when the user chooses to perform it.

Real-NAS evidence is required to claim the feature supported on that NAS
filesystem, but lack of such evidence does not authorize capability guessing.

## 15. Implementation sequence

```text
H0  Scope + Architecture Freeze                         CLOSED
H1  Runtime hardlink/reflink capability primitives     NEXT
H2  Dedupe Preview/Generate/Freeze/Validate integration
H3  Transactional Worker execution + restart recovery
H4  UI + Docker + closure / filesystem acceptance
```

## 16. Existing closure independence

Organizer C5 and Scheduler S5 remain independently pending real-NAS acceptance.

Starting this track does not fabricate or imply those acceptance results.
Similarity and Notifications/Webhook remain cancelled by product decision.
Advanced Auth remains deferred.
