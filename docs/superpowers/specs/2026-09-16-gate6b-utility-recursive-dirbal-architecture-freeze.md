# Gate6-B Architecture Freeze — Utility Workflow + Recursive Directory Balanced Dedupe

**Status:** APPROVED / FROZEN  
**Approval date:** 2026-09-16  
**Baseline:** `7d9e248dae25d706d65a36bc864fb86f9a613d4d`  
**Canonical branch:** `v0.3.6-gate6b-utility-recursive-dirbal`

## 1. Scope

Gate6-B adds two capability domains without reopening CLOSED Gate5-D / Gate5-E semantics:

1. Workflow Utility Integration for **Single-Child Wrapper Collapse Option B**.
2. Advanced Dedupe **Recursive Directory Balanced by Bytes** with mandatory **Recursive Last-File Protection**.

The already-working TXT/URL cleanup flow (`Scan -> Filter(extension in [txt,url]) -> Quarantine`) is historical capability and is **not reimplemented** in Gate6-B.

Safety priority remains: data safety > correctness > recoverability > security > performance > UI > feature count.

## 2. Utility Workflow Integration

### 2.1 Product/schema shape

Add an explicit Workflow mode:

```text
mode = "utility"
```

Existing `file`, `organizer`, and `dedupe` modes retain their historical behavior. V1 does not introduce a free-form Utility Builder. V1 Utility supports exactly one utility kind:

```text
single_child_wrapper_collapse
```

### 2.2 Scope authority

Product input is restricted to an authoritative managed Index Root plus optional subpath:

```text
Index Root + optional subpath
```

The product surface must not accept arbitrary absolute NAS paths. Scope may not escape or cross the authoritative root.

### 2.3 Candidate discovery

For selected scope directory `A`, only direct child directory `B` may become a candidate. `A/B/C -> A/C` is READY only when all conditions hold:

- `B` is a real directory and direct child of `A`.
- `B` is not a symlink.
- `B`'s real direct filesystem entry count is exactly 1.
- The sole entry `C` is a real directory.
- `C` is not a symlink or special inode.
- `B` contains no regular file, hidden file, second directory, or other object.
- Target `A/C` does not exist.
- Source and target remain inside the authoritative root.
- No overwrite, implicit merge, or automatic rename is allowed.

Directory discovery is its own explicit/testable semantic layer. It must not be disguised as the existing file-stream candidate model and must not change generic Gate5-E `flatten_one_level` behavior.

### 2.4 Candidate states and partial conflicts

A target collision yields an explicit non-ready state such as:

```text
TARGET_EXISTS
```

That candidate is skipped with zero mutation. Other healthy READY candidates in the same Preview may continue. A collision must never produce overwrite, merge, or auto-rename behavior.

### 2.5 Preview selection contract

Preview defaults all READY candidates to selected. The user may deselect individual READY candidates. Unsafe/conflicting candidates are not selectable.

Generate may accept only candidate IDs that:

1. belong to the exact current Preview,
2. are still READY under that Preview identity, and
3. are explicitly selected by the user.

### 2.6 Compilation and execution contract

Each selected candidate compiles to exactly this ordered pair:

```text
1. MOVE A/B/C -> A/C
2. REMOVE_EMPTY_DIR A/B
```

Execution semantics are fixed:

```text
MOVE C first
-> verify MOVE completed
-> reopen/re-check B
-> REMOVE_EMPTY_DIR B only if B is physically empty now
```

If a third party creates any object in `B` after MOVE, empty-dir removal fails closed / skips. `B` and the new object remain. Recursive delete is forbidden.

Each Plan may collapse at most one layer. A second layer requires a new Preview and new Generate.

### 2.7 Reuse boundary

Gate6-B must reuse the CLOSED lower-level safety chain and actions, including existing BatchPlan / Freeze / Validate / Worker / PathGuard and Gate5-E MOVE / empty-directory primitives. Workflow is a compiler/orchestrator, never a filesystem executor. No second executor is allowed.

## 3. Recursive Directory Balanced by Bytes

### 3.1 New selection mode without historical rewrite

Existing mode remains unchanged:

```text
balanced_by_bytes = Balanced by Scan Root
```

New explicit mode:

```text
recursive_directory_balanced_by_bytes
```

UI label:

```text
Recursive Directory Balanced by Bytes
```

The new mode must not silently alter historical `balanced_by_bytes` results or API semantics.

### 3.2 Selection precedence

Decision precedence is frozen as:

```text
Safety / provenance
-> Scorer
-> Scan Root Balance
-> Recursive Directory Balance
-> deterministic normalized-path tie-break
```

Recursive balance acts only among safe highest-score KEEP candidates. It must never override `path_priority`, `preferred_extension`, `mtime`, or future frozen scorer factors. A unique highest-score candidate is kept directly.

### 3.3 Cross-root groups

A duplicate group spanning multiple authoritative Scan Roots must never compute a lexical LCA across roots.

For tied highest-score candidates:

1. existing Scan Root released-bytes balance chooses the KEEP root,
2. if multiple tied candidates remain inside that chosen root, recursive directory balance chooses the concrete KEEP candidate inside that root.

Root authority/provenance boundaries remain intact.

### 3.4 Same-root dynamic LCA buckets

For a duplicate group's candidates within one authoritative root:

1. take candidate parent directories,
2. calculate their Lowest Common Ancestor (LCA),
3. for each candidate, take the first real child directory from LCA toward that candidate,
4. use that child directory as the candidate's balance bucket.

The bucket may be deeper than Scan Root first-level; it follows the group's real branch point.

### 3.5 `LCA_DIRECT`

When a candidate's parent directory is the LCA itself, use a synthetic algorithm/UI bucket:

```text
LCA_DIRECT
```

`LCA_DIRECT` is not a filesystem directory, creates no object, and authorizes no filesystem operation. Its counter contains only planned released bytes from files directly under the LCA.

### 3.6 Recursive released-bytes accounting

For every file planned for Quarantine, add `file_size` to the file's parent-directory counter and every real ancestor counter up to and including its authoritative Scan Root. Later groups therefore observe planned release already assigned to every affected branch.

### 3.7 Objective

For each safe highest-score candidate simulated as KEEP, all other duplicate members become planned Quarantine for the simulation. Candidate options are ranked by:

```text
1. minimize spread = max(projected released bytes) - min(projected released bytes)
2. if tied, minimize sum of squares
3. if tied, normalized-path deterministic tie-break
```

Forbidden interpretations include item-count 50/50, alternating roots/directories, random choice, or overriding a higher scorer for balance.

### 3.8 Deterministic group order

Reuse existing Advanced Dedupe group order unchanged:

```text
file_size DESC
-> content_hash ASC
-> stable member-path fingerprint ASC
```

DB incidental order must not affect results. Identical Scan Snapshot + scorer config + safety policy must yield identical group order, decisions, and Preview digest.

## 4. Recursive Last-File Protection

`recursive_directory_balanced_by_bytes` always enables Recursive Last-File Protection in V1; no disable switch is provided.

For every relevant real directory in candidate/balance ancestry, use a read-only filesystem snapshot to count real regular files in the directory subtree. Symlinks do not count as protected regular files.

Before adding a new Quarantine decision, every relevant directory must satisfy:

```text
current_regular_file_count
- already_scheduled_quarantine_count
- proposed_quarantine_count
>= 1
```

If not, the candidate/choice is unsafe with explicit reason:

```text
RECURSIVE_PROTECT_LAST_FILE
```

If all highest-score choices are blocked, the duplicate group is SKIPPED / fail-closed with zero mutation.

This protection does not remove empty directories and must not implicitly invoke `remove_empty_dirs`.

## 5. Preview / Generate / Execute Safety Chain

The complete authority chain remains:

```text
Completed Scan Snapshot
-> Read-only Preview / Compile
-> Explicit Generate BatchPlan(draft)
-> Freeze
-> Validate
-> Execute
-> Quarantine
```

Hard requirements:

- Preview = zero filesystem mutation.
- Preview = zero BatchPlan persistence.
- Generate creates only `BatchPlan(draft)`.
- Freeze remains physical identity / SHA256 authority.
- stale Validate blocks Execute.
- Execute uses the existing Worker and existing Quarantine transactional authority.
- no second dedupe or utility executor.
- dedupe mutation remains Quarantine only; no permanent delete.

## 6. Preview Identity / Digest

Recursive Directory Balance Preview identity/digest must bind at least:

- authoritative scan / DB lineage,
- scorer configuration,
- selection mode and balance scope,
- authoritative Scan Roots,
- LCA derivation inputs,
- dynamic bucket derivation inputs,
- `LCA_DIRECT` inputs,
- recursive regular-file counts used for protection,
- Last-File Protection snapshot,
- safety policy snapshot,
- final KEEP / QUARANTINE decisions.

Any Preview-to-Generate change capable of affecting buckets, recursive counts, protection, released-bytes accounting, KEEP, or QUARANTINE decisions causes:

```text
PREVIEW_CHANGED
-> Generate rejected
-> 0 Draft persisted
```

The server must not silently recompute and accept a different result. The user must request a new Preview.

## 7. Explain / UI

Default Preview stays concise and shows status/result plus the key decision reason.

Expandable Explain for recursive directory balance must expose at least:

- selection mode,
- LCA,
- candidate balance bucket,
- `LCA_DIRECT` when applicable,
- bucket released bytes before,
- projected released bytes after,
- spread before / projected spread after,
- score and score factors,
- KEEP reason,
- QUARANTINE reason,
- Recursive Last-File Protection reason when triggered.

UI must distinguish clearly:

```text
Balanced by Scan Root
Recursive Directory Balanced by Bytes
```

## 8. Required boundary/regression coverage

Tests must cover at least:

- Utility schema/validation and immutable revision integration.
- Index Root + optional subpath authority and path escape rejection.
- strict single-child discovery, hidden files, second children, symlink/special-object rejection.
- target collision partial skip and zero overwrite/merge/rename.
- READY default selection, explicit deselection, Preview-bound candidate IDs.
- paired MOVE + REMOVE_EMPTY_DIR compilation and one-layer limit.
- third-party object after MOVE preserving wrapper directory.
- old `balanced_by_bytes` regression unchanged.
- same-root top-level and deep-branch recursive balance.
- 3+ buckets and multiple copies in one bucket.
- cross-root groups with root balance before recursive balance.
- `LCA_DIRECT`.
- different file sizes balanced by bytes, not item count.
- zero-byte deterministic ties.
- scorer priority wins over balance.
- recursive released-byte accumulation through multiple ancestors.
- Recursive Last-File Protection through multiple ancestors.
- all choices protected => group skipped / zero mutation.
- symlink files/directories excluded/blocked correctly.
- Unicode, spaces, and long legal paths.
- filesystem changes / identity ABA between Preview and Generate.
- deterministic Preview digest.
- `PREVIEW_CHANGED` persists zero Draft.
- full Generate -> Freeze -> Validate -> Execute regression.
- Quarantine only / zero permanent delete.

## 9. Explicit non-goals

Gate6-B does not implement or authorize:

- a second TXT/URL cleanup engine,
- permanent delete / secure erase,
- a second executor or worker,
- recursive wrapper fixpoint collapse inside one Plan,
- automatic target rename,
- implicit directory merge,
- overwrite,
- symlink traversal,
- cross-root lexical LCA,
- semantic changes to existing `balanced_by_bytes`,
- balance overriding scorer priority,
- automatic empty-directory cleanup during dedupe.

## 10. Closure sequence

```text
Architecture Freeze APPROVED
-> Implementation Plan
-> Strict TDD (RED -> GREEN -> REFACTOR)
-> focused regression
-> full backend regression
-> frontend tests/typecheck/build
-> baseline-to-candidate source review
-> independent review
-> exact-candidate validation
-> linux/amd64 Docker
-> real NAS small-data acceptance
-> Gate6-B PASS / CLOSED
```

Production NAS is outside development authority and is not touched during implementation.