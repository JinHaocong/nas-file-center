# Gate6-B Architecture Amendment A — Recursive Last-File Concurrency Contract

**Status:** APPROVED / FROZEN  
**Design approval date:** 2026-09-16  
**Final spec approval date:** 2026-09-16  
**Applies to:** Gate6-B Architecture Freeze `2026-09-16-gate6b-utility-recursive-dirbal-architecture-freeze.md`  
**Canonical branch:** `v0.3.6-gate6b-utility-recursive-dirbal`  
**Reason:** Repeated adversarial RED tests proved that finite user-space revalidation cannot provide an atomic recursive-tree snapshot against an uncooperative external writer that may mutate the tree between syscalls.

## 1. Amendment scope and precedence

This amendment changes only the concurrency and mutation-authority contract for Gate6-B **Recursive Last-File Protection** under `recursive_directory_balanced_by_bytes`.

It does **not** reopen or change:

- Utility `single_child_wrapper_collapse` semantics;
- historical `weighted` / `balanced_by_bytes` behavior;
- scorer precedence;
- Scan Root balance / recursive directory balance ordering;
- LCA / `LCA_DIRECT` semantics;
- Quarantine-only mutation authority;
- existing candidate file identity / SHA256 authority;
- the rule that Workflow is not an executor;
- the prohibition on a second executor / Worker;
- `ctime = diagnostic-only / non-authoritative` semantics.

This approved amendment takes precedence over conflicting interpretations of Sections 4, 5, 6, 8, and 10 of the original Gate6-B Architecture Freeze. All unaffected clauses of the original Freeze remain authoritative.

## 2. Problem statement

Gate6-B originally requires a read-only recursive filesystem snapshot for Last-File Protection and binds recursive counts / tree identity into Preview identity.

Adversarial testing established several progressively narrower races:

1. protected root / intermediate parent pathname replacement;
2. descendant directory detachment after fd open;
3. descendant detachment during a verification collection;
4. descendant parent detachment during the final identity-row rebind.

Descriptor-bound / no-follow traversal is still required and materially improves safety. However, under an uncontrolled filesystem, no finite sequence of user-space `open` / `fstat` / `scandir` / identity checks can make a recursive tree read linearizable against an unrelated writer that may rename, unlink, or replace an entry between any two syscalls.

Therefore Gate6-B V1 must not claim an impossible atomic snapshot guarantee against arbitrary third-party concurrent mutation.

## 3. Concurrency model

Gate6-B distinguishes two mutation domains.

### 3.1 NFC-controlled mutation

NFC controls its own BatchPlan / Worker mutations.

For `recursive_directory_balanced_by_bytes`, overlapping NFC mutations affecting the same protected ancestry must not execute concurrently. This requirement may be satisfied by the existing Worker serialization if it already provides the needed ordering, or by minimal scope serialization inside the existing execution authority.

This amendment does not authorize a second Worker or second executor.

### 3.2 External third-party mutation

A user, NAS OS process, application, sync service, or other process outside NFC may mutate the same directory tree concurrently.

Gate6-B V1 treats such mutation as **external instability**.

NFC must detect and fail closed when instability is observable, but does not claim that an uncooperative external writer can be excluded from the final syscall gap without filesystem-supported transaction, snapshot, or mandatory-lock semantics.

Real-NAS Gate6-B acceptance must therefore run with no independent writer intentionally mutating the acceptance scope concurrently.

## 4. Preview / Generate snapshot semantics

Recursive Last-File Protection at Preview / Generate remains a **descriptor-bound, no-follow, identity-bound sampled filesystem snapshot**.

Required properties remain:

- protected-root acquisition is descriptor-relative and no-follow;
- relevant parent components are descriptor-bound;
- descendant symlinks are never traversed or counted as protected regular files;
- real regular files are counted only after type / identity verification;
- protected directory / tree physical identity remains part of recursive Preview authority;
- recursive protection data remains bound into `source_snapshot_digest`;
- Preview remains read-only and persists zero BatchPlan rows;
- Generate recompiles against the current filesystem state;
- any observed Preview -> Generate change that affects protection or decisions yields `PREVIEW_CHANGED` and persists zero Draft.

The explicit limitation is:

> Preview / Generate does not provide a linearizable or atomic recursive-tree snapshot against an uncooperative external writer racing inside the final syscall window.

A finite number of rebind / recheck passes may be retained as defense in depth, but Gate6-B safety closure must not depend on the number of such passes.

## 5. Protection scope carried into plan authority

Every planned QUARANTINE produced by `recursive_directory_balanced_by_bytes` must carry enough immutable metadata for Freeze / Validate / Execute to reconstruct the exact Recursive Last-File Protection scope required by the frozen planning decision.

At minimum, this authority must identify:

- selection mode = `recursive_directory_balanced_by_bytes`;
- authoritative Scan Root / provenance root;
- source file identity used by the plan;
- the relevant protected ancestor paths for that source under the frozen Gate6-B ancestry rules;
- enough lineage / revision data to reject a plan whose protection scope cannot be reconstructed consistently.

The implementation plan may choose the concrete schema, but may not silently derive a broader or different mutation scope at Execute time.

## 6. Freeze / Validate contract

Freeze remains the physical identity / SHA256 authority for planned file mutation.

For recursive directory balance, Freeze / Validate additionally carry and revalidate the Recursive Last-File Protection scope required by each planned QUARANTINE.

Validate must fail closed when any of the following is observed:

- required protected scope cannot be reconstructed from frozen plan authority;
- authoritative root / ancestry binding is no longer valid;
- required protected scope is symlinked, missing, or identity-unstable in a way that prevents a trustworthy current read;
- a live protection check already shows that the planned mutation would violate Last-File Protection.

Passing Validate is necessary but not sufficient for the later destructive step because external mutation may occur after Validate.

## 7. Execute preflight becomes the final Last-File mutation authority

Immediately before each actual QUARANTINE mutation for `recursive_directory_balanced_by_bytes`, the existing Worker must perform a **live Recursive Last-File Protection preflight** using the current real filesystem.

For every required protected ancestor of the item:

1. obtain the current real regular-file count using descriptor-bound / no-follow traversal;
2. treat any unstable / untrustworthy read as fail-closed;
3. evaluate the current mutation against the live state.

At Execute time, earlier NFC mutations already completed in the same scope are reflected in the live filesystem count and must not be subtracted a second time.

For a single-file Quarantine item, the invariant is effectively:

```text
live_current_regular_file_count - current_proposed_quarantine_count >= 1
```

where `current_proposed_quarantine_count = 1` for the current item in V1.

If any required ancestor would fall below one real regular file, the current mutation must not execute.

No lower-score fallback is allowed at Execute. Execute is validating the already-frozen decision, not replanning.

## 8. Failure semantics

Two failure reasons are distinguished conceptually:

```text
RECURSIVE_PROTECT_LAST_FILE
RECURSIVE_PROTECTION_UNSTABLE
```

- `RECURSIVE_PROTECT_LAST_FILE`: a trustworthy live count shows that the current Quarantine would violate the protection invariant.
- `RECURSIVE_PROTECTION_UNSTABLE`: NFC cannot obtain or verify a trustworthy current protection snapshot / ancestry binding.

Both are fail-closed for the current mutation.

Existing Worker / BatchPlan failure semantics remain in force. This amendment does not introduce recursive deletion, permanent deletion, or implicit rollback of already completed Quarantine operations.

## 9. Interaction with external mutation during the final Execute syscall gap

Even Execute preflight cannot create a cross-process atomic transaction if an external writer mutates the same scope after the final successful preflight read but before NFC performs Quarantine.

Gate6-B V1 therefore guarantees:

- NFC serializes its own overlapping protected-scope mutations;
- NFC uses descriptor-bound / no-follow reads;
- NFC revalidates Last-File Protection at Validate and immediately before mutation;
- NFC fails closed on observable instability;
- NFC never claims atomic exclusion of arbitrary external writers without filesystem support.

This is the explicit concurrency boundary of Gate6-B V1.

## 10. Digest / stale-preview semantics remain important but are no longer sole mutation authority

`source_snapshot_digest` remains required to bind the sampled recursive protection state used by Preview / Generate.

It continues to protect against ordinary stale-plan changes and identity-only ABA that are observable during recompilation.

However, digest equality alone no longer authorizes the final Quarantine mutation. Execute preflight is an additional mandatory safety gate for recursive Last-File Protection.

The authority chain becomes:

```text
Completed Scan Snapshot
-> Read-only Preview / sampled protection compile
-> Explicit Generate BatchPlan(draft)
-> Freeze file identity/hash + protection scope authority
-> Validate file identity/hash + current protection scope
-> Execute live protection preflight
-> existing Quarantine mutation
```

No second executor is introduced.

## 11. Treatment of current experimental GREEN commit

Commit `33e94c29fdf12457005953ec3be821f8c55cd934` added another finite final-row rebind pass after strict RED `b285ef42250f2599f7b59dcbc79b5c47b123c57d`.

That work may remain as defense in depth if the later implementation review finds it correct and non-regressive, but it is **not** sufficient architecture authority for Gate6-B closure and must not be used to claim an atomic recursive snapshot guarantee.

The post-amendment implementation plan must explicitly decide whether to retain, simplify, or remove that defense-in-depth logic. Safety acceptance must depend on the amended Validate / Execute contract, not on a finite rebind count.

## 12. Required TDD / regression coverage after final re-freeze

The new implementation plan must add strict RED -> GREEN coverage for at least:

1. plan metadata carries the exact recursive protection scope required by each planned Quarantine;
2. malformed / stale / unreconstructable protection authority fails closed in Validate;
3. Last-File state changes after Generate but before Validate are blocked;
4. Last-File state changes after Validate but before Execute are blocked by Execute preflight;
5. live count `1` before a planned Quarantine blocks that mutation;
6. live count `2` allows one Quarantine and subsequent live count `1` blocks a second mutation affecting the same protected ancestry;
7. already completed NFC mutations are reflected through live filesystem state and are not double-subtracted;
8. overlapping NFC mutations against the same protected scope are serialized by the existing execution authority;
9. symlink / ancestry instability during Execute preflight yields fail-closed behavior;
10. no lower-score fallback occurs at Validate / Execute;
11. stale Preview / Generate behavior remains `PREVIEW_CHANGED -> zero Draft` where the change is observed during Generate recompilation;
12. historical `weighted` / `balanced_by_bytes` tests remain unchanged;
13. Utility tests remain unchanged;
14. Quarantine-only / zero permanent-delete regressions remain green;
15. full Generate -> Freeze -> Validate -> Execute regression covers the new protection authority chain.

Adversarial tests may continue to exercise final-syscall races, but they must assert the documented concurrency contract rather than require impossible external-writer atomicity from a finite user-space snapshot loop.

## 13. Real-NAS acceptance contract

Gate6-B real-NAS small-data acceptance must document that the acceptance scope has no intentionally concurrent independent writer.

Acceptance must verify at least:

- recursive Last-File Preview / Generate behavior;
- Freeze / Validate protection-scope authority;
- Execute live preflight;
- safe Quarantine of an allowed duplicate;
- fail-closed behavior when the current live count would remove the last real regular file;
- no permanent delete;
- no unexpected directory removal;
- existing Utility behavior remains intact.

The acceptance evidence must state the exact candidate SHA and image identity as before.

## 14. Updated closure sequence

Gate6-B closure now requires:

```text
Architecture Amendment A APPROVED / FROZEN
-> new post-amendment Implementation Plan
-> Strict TDD (RED -> GREEN -> REFACTOR)
-> focused regression
-> full backend regression
-> frontend tests/typecheck/build
-> baseline-to-candidate source review
-> independent review
-> exact-candidate validation
-> linux/amd64 Docker
-> real NAS small-data acceptance under documented no-independent-writer condition
-> Gate6-B PASS / CLOSED
```

This amendment is **APPROVED / FROZEN**. The next authorized stage is the post-amendment Implementation Plan. Production implementation, merge, release Docker evidence, deployment, and NAS mutation remain unauthorized until the post-amendment plan is written and implementation resumes under Strict TDD.
