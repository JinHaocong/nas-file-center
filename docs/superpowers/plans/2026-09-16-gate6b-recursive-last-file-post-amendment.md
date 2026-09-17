# Gate6-B Recursive Last-File Post-Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Architecture Amendment A so `recursive_directory_balanced_by_bytes` carries exact Recursive Last-File Protection authority through Generate → Freeze → Validate and performs a descriptor-bound live protection preflight immediately before each Worker Quarantine mutation.

**Architecture:** Preview/Generate remain descriptor-bound sampled snapshots and keep their existing stale-preview digest authority. Generate persists an immutable recursive-protection authority envelope in each recursive-mode Quarantine `BatchPlanItem.metadata_json`; Freeze validates and seals that exact scope; Validate re-evaluates it against the current filesystem; the existing `BatchPlanExecuteHandler` performs the final live preflight immediately before calling the existing executor. No DB migration, second executor, second Worker, permanent-delete path, or external-writer atomicity claim is introduced.

**Tech Stack:** Python 3, FastAPI/service layer, SQLAlchemy/SQLite, pytest, existing BatchPlan/Worker/Quarantine lifecycle, descriptor-relative POSIX filesystem operations (`O_DIRECTORY`, `O_NOFOLLOW`, `dir_fd`), existing Gate6-B GitHub Actions lane.

**Spec:**
- `docs/superpowers/specs/2026-09-16-gate6b-utility-recursive-dirbal-architecture-freeze.md`
- `docs/superpowers/specs/2026-09-16-gate6b-recursive-last-file-concurrency-amendment-a.md`

## Global Constraints

- Work only on canonical branch `v0.3.6-gate6b-utility-recursive-dirbal`; do not create a parallel Gate6-B implementation branch.
- Before the first code change, re-read PR #10 head and compare it to the plan-creation head. If the branch moved, classify every intervening commit before continuing.
- Amendment A is `APPROVED / FROZEN`; implementation may not weaken or reinterpret it without another explicit architecture amendment.
- Strict TDD: tests-only RED commit first for each behavioral task, then the minimum GREEN production change, then refactor only while all focused tests stay green.
- No database migration. `BatchPlanItem.metadata_json` is the persistence surface for recursive-protection authority.
- No second executor / Worker. Execute remains `BatchPlanExecuteHandler -> execute_item -> existing Quarantine authority`.
- New recursive protection applies only to `selection_mode == "recursive_directory_balanced_by_bytes"`. Historical `weighted`, `balanced_by_bytes`, and non-recursive `protected_dir` behavior remain compatible.
- Dedupe mutation remains Quarantine only. No permanent delete, recursive directory deletion, implicit merge, or lower-score fallback.
- `ctime` remains diagnostic/non-authoritative where frozen SHA256 is authoritative.
- Preview/Generate sampled snapshots must remain read-only and Preview persists zero Draft rows.
- External writers are not atomically excluded. Detect observable instability and fail closed; do not add a finite rebind loop as the safety proof.
- Production NAS is outside implementation authority.

---

## Task 0 — Exact source lock and concurrent-work audit

**Production files:** none.

- [ ] Re-read PR #10 and record exact branch HEAD before implementation.
- [ ] Verify both frozen specs are present at that HEAD and still `APPROVED / FROZEN`.
- [ ] Compare the implementation-start HEAD against the plan-creation line. Review any intervening commits, especially the independent Utility ABA test work, and confirm they do not change Amendment A authority.
- [ ] Confirm `main` still uses Gate6-A2 baseline `7d9e248dae25d706d65a36bc864fb86f9a613d4d`; do not rebase or merge main into the Gate6-B branch merely to start this work.
- [ ] Record the exact implementation-start SHA in the first RED commit / PR comment.

**Verify:** no source mutation occurs in this task.

---

## Task 1 — Extract one shared descriptor-bound recursive protection reader

**Create:**
- `app/planning/recursive_protection.py`
- `tests/test_gate6b_recursive_protection_reader.py`

**Modify:**
- `app/planning/dedupe_preview.py`
- existing snapshot-authority tests only as import paths require; do not weaken their assertions.

### RED

- [ ] Add tests for a public immutable snapshot result containing at least `count`, `stable`, root `device`, root `inode`, and deterministic `tree_identity_digest`.
- [ ] Assert symlink files and symlink directories are excluded and never traversed.
- [ ] Assert a missing, symlinked, or descriptor/identity-unstable protected directory returns `stable=False` and an unusable count, never a permissive count.
- [ ] Preserve the existing protected-root, intermediate-parent, descendant-detach, verification-pass, and final-rebind adversarial regressions.
- [ ] Assert the same stable tree produces the same identity digest and that no `ctime` field enters the digest payload.

Run RED with the new module absent/public API absent:

```bash
pytest \
  tests/test_gate6b_recursive_protection_reader.py \
  tests/test_gate6b_recursive_dirbal_snapshot_authority.py \
  tests/test_gate6b_recursive_dirbal_final_rebind_aba.py \
  -q
```

Expected RED: only the new public/shared-reader contract is missing; existing regressions must not newly fail.

### GREEN

- [ ] Move/reuse the current descriptor-bound helpers from `app/planning/dedupe_preview.py` into `app/planning/recursive_protection.py` without changing their sampled-snapshot meaning.
- [ ] Expose a small public API, e.g. `snapshot_recursive_regular_files(path) -> RecursiveProtectionSnapshot`; keep fd lifetime and fail-closed behavior explicit.
- [ ] Keep the current finite second-pass / row-rebind logic only as defense in depth. Add a comment pointing to Amendment A and explicitly state it is not an atomicity guarantee.
- [ ] Make `dedupe_preview.py` consume the shared helper so Preview semantics remain byte-for-byte equivalent at the contract level.

### Verify

```bash
pytest \
  tests/test_gate6b_recursive_protection_reader.py \
  tests/test_gate6b_recursive_dirbal_snapshot_authority.py \
  tests/test_gate6b_recursive_dirbal_final_rebind_aba.py \
  tests/test_gate6b_recursive_dirbal_last_file.py \
  tests/test_gate6b_recursive_dirbal_preview.py \
  -q
```

Commit only after GREEN.

---

## Task 2 — Persist exact recursive-protection authority at Generate

**Modify:**
- `app/planning/dedupe_generate.py`
- `tests/test_gate6b_recursive_dirbal_generate.py`

**Reuse:**
- `app/planning/dedupe_engine.py::directory_ancestors_to_scan_root`
- `DedupePreviewCompilation.source_snapshot_digest`
- `DedupePreviewCompilation.db_lineage_digest`

### Authority envelope

For every Quarantine intent generated by exactly `recursive_directory_balanced_by_bytes`, persist an immutable object under `metadata_json["recursive_protection"]` with this V1 shape:

```json
{
  "schema_version": 1,
  "selection_mode": "recursive_directory_balanced_by_bytes",
  "scan_job_id": 123,
  "scan_root_index": 0,
  "scan_root_path": "/authoritative/root",
  "source_path": "/authoritative/root/a/b/dup.bin",
  "protected_ancestors": [
    "/authoritative/root/a/b",
    "/authoritative/root/a",
    "/authoritative/root"
  ],
  "group_provenance_id": "...",
  "group_decision_fingerprint": "...",
  "preview_source_snapshot_digest": "...",
  "preview_db_lineage_digest": "..."
}
```

`protected_ancestors` order is frozen as source parent → ... → authoritative Scan Root, exactly matching `directory_ancestors_to_scan_root()`.

### RED

- [ ] Recursive-mode Generate writes the complete envelope for every planned Quarantine.
- [ ] The persisted source path exactly equals the `BatchPlanItem.source_path` to be created.
- [ ] The persisted root/index exactly match the member's authoritative Scan Root.
- [ ] Protected ancestors include every real lexical ancestor through the Scan Root and no broader path.
- [ ] Preview source and DB lineage digests are persisted.
- [ ] Group provenance/fingerprint are persisted.
- [ ] Malformed source/root ancestry cannot produce an intent.
- [ ] Historical `weighted` / `balanced_by_bytes` metadata stays unchanged; do not silently add the new envelope to old modes.
- [ ] Existing Preview → Generate `PREVIEW_CHANGED -> zero Draft` tests remain unchanged.

Run RED:

```bash
pytest \
  tests/test_gate6b_recursive_dirbal_generate.py \
  tests/test_gate5d_dedupe_generate.py \
  -q
```

### GREEN

- [ ] Branch only on `compilation.scorer_config.selection_mode == "recursive_directory_balanced_by_bytes"` (or the existing canonical equivalent).
- [ ] Construct ancestors from the frozen source path and authoritative Scan Root with `directory_ancestors_to_scan_root()`; never infer a broader Execute-time scope.
- [ ] Keep legacy `protected_dir` behavior only where required for historical modes. The new recursive envelope is the Amendment A authority.

### Verify

```bash
pytest \
  tests/test_gate6b_recursive_dirbal_generate.py \
  tests/test_gate5d_dedupe_generate.py \
  tests/test_gate6b_recursive_dirbal_api.py \
  -q
```

---

## Task 3 — Add strict parser/reconstruction for frozen recursive authority

**Create:**
- `app/planning/recursive_protection_authority.py`
- `tests/test_gate6b_recursive_protection_authority.py`

### RED

- [ ] Parse only `schema_version == 1` and exact recursive selection token.
- [ ] Reject missing/non-string source/root fields, invalid scan-root index, empty/duplicate ancestors, relative ancestors, and malformed digest/provenance fields.
- [ ] Reject metadata whose `source_path` disagrees with `BatchPlanItem.source_path`.
- [ ] Recompute `directory_ancestors_to_scan_root(source_path, scan_root_path)` and require exact equality with the persisted ancestor list; no broader/narrower/reordered scope is accepted.
- [ ] Require `scan_root_path` and every protected ancestor to remain within configured allowed roots and outside reserved quarantine storage.
- [ ] Produce a deterministic `scope_digest` from the immutable V1 authority fields, excluding live counts and `ctime`.

### GREEN

Implement immutable dataclasses / parser functions with no filesystem mutation. Suggested API:

```python
@dataclass(frozen=True)
class RecursiveProtectionAuthority:
    ...


def parse_recursive_protection_authority(
    metadata_json: str,
    *,
    expected_source_path: str,
    allowed_roots: Sequence[Path | str],
    quarantine_root: Path | str | None,
) -> RecursiveProtectionAuthority | None:
    ...
```

Return `None` only when the item is not a recursive-mode item. If the recursive marker is present but malformed, raise a dedicated fail-closed authority error.

### Verify

```bash
pytest tests/test_gate6b_recursive_protection_authority.py -q
```

---

## Task 4 — Freeze seals exact protection scope and samples current live state

**Modify:**
- `app/service.py` (`freeze_plan` existing BatchPlan lifecycle)
- `app/planning/recursive_protection_authority.py`
- `tests/test_gate6b_recursive_dirbal_freeze_validate.py`

### Frozen metadata addition

For each recursive-mode Quarantine item, Freeze must append a `frozen_recursive_protection` object containing at least:

```json
{
  "schema_version": 1,
  "scope_digest": "sha256-of-immutable-authority",
  "frozen_ancestors": {
    "/root/a/b": {"count": 2, "device": 1, "inode": 2, "tree_identity_digest": "..."},
    "/root/a": {"count": 3, "device": 1, "inode": 3, "tree_identity_digest": "..."},
    "/root": {"count": 10, "device": 1, "inode": 4, "tree_identity_digest": "..."}
  }
}
```

The frozen counts are evidence/audit context, not Execute authority.

### RED

- [ ] Freeze rejects a recursive item with missing/malformed/unreconstructable authority before setting the plan frozen.
- [ ] Freeze rejects any ancestor sample with `stable=False` using `RECURSIVE_PROTECTION_UNSTABLE` semantics.
- [ ] Freeze rejects a trustworthy ancestor whose `live_count - 1 < 1` using `RECURSIVE_PROTECT_LAST_FILE` semantics.
- [ ] Freeze stores the exact scope digest and sampled identities/counts for every ancestor when safe.
- [ ] Freeze never broadens/reorders the persisted ancestor list.
- [ ] Non-recursive plans follow their historical Freeze path unchanged.

Run RED:

```bash
pytest \
  tests/test_gate6b_recursive_dirbal_freeze_validate.py \
  tests/test_gate3_stale_plan.py \
  -q
```

### GREEN

- [ ] Parse/reconstruct authority outside the write transaction where practical.
- [ ] Use the shared descriptor-bound reader for every persisted protected ancestor.
- [ ] Apply current-item V1 invariant `snapshot.count - 1 >= 1`.
- [ ] Persist only after all recursive authority checks succeed; no partial frozen authority.
- [ ] Preserve existing source identity / SHA256 Freeze behavior unchanged.

### Verify

```bash
pytest \
  tests/test_gate6b_recursive_dirbal_freeze_validate.py \
  tests/test_gate3_stale_plan.py \
  tests/test_gate5d_dedupe_generate.py \
  -q
```

---

## Task 5 — Validate rechecks authority and current Last-File state

**Modify:**
- `app/service.py` (existing plan validation loop)
- `app/planning/recursive_protection_authority.py`
- `tests/test_gate6b_recursive_dirbal_freeze_validate.py`

### RED

- [ ] Authority tampering after Freeze (source/root/ancestor/scope digest change) fails closed.
- [ ] Missing or malformed `frozen_recursive_protection` fails closed for recursive mode.
- [ ] An ancestor changed from live count `2` at Freeze to `1` before Validate blocks Validate.
- [ ] Symlink/replacement/unstable ancestry at Validate yields `RECURSIVE_PROTECTION_UNSTABLE`.
- [ ] A safe current count validates even when the sampled tree identity differs from Freeze for a benign external change, provided the immutable authority scope is unchanged and the current live protection invariant still holds. Amendment A requires current safety, not equality to an old recursive snapshot.
- [ ] No lower-score KEEP alternative is selected; Validate only accepts/rejects the frozen item.
- [ ] Historical plan validation remains unchanged.

### GREEN

- [ ] Add a single shared evaluator, e.g. `evaluate_live_recursive_protection(authority)`, that returns a structured result with reason and per-ancestor current snapshots.
- [ ] Invoke it in the existing Validate path after normal item freshness/identity checks and before marking the item validated.
- [ ] Map trustworthy last-file violation to `RECURSIVE_PROTECT_LAST_FILE`; map untrustworthy scope/read to `RECURSIVE_PROTECTION_UNSTABLE`.
- [ ] Keep plan/item state semantics consistent with existing stale/fail-closed lifecycle; do not invent a new executor state machine.

### Verify

```bash
pytest \
  tests/test_gate6b_recursive_dirbal_freeze_validate.py \
  tests/test_gate3_stale_plan.py \
  -q
```

---

## Task 6 — Worker Execute live preflight immediately before Quarantine

**Modify:**
- `app/tasks/handlers_base.py` (`BatchPlanExecuteHandler.run`)
- `app/batch/plans.py` only if a typed `OperationItem` field is required; prefer keeping recursive authority out of the generic executor object.
- `app/service.py` direct compatibility execution path only to prevent bypass.
- `tests/test_gate6b_recursive_dirbal_execute_preflight.py`

**Do not make `app/execution/executor.py` the authority owner.** Its legacy `protected_dir` / `_count_regular_files()` compatibility behavior is not the Amendment A safety proof.

### RED

- [ ] Recursive item validates with count `2`, then external/NFC state changes to count `1` before Execute: Worker blocks before `execute_item()` and source remains in place.
- [ ] Count `2` immediately before mutation allows one Quarantine.
- [ ] Two sequential recursive Quarantine items share a protected ancestor: first sees `2` and completes; second sees the resulting live `1` and is blocked. No double-subtraction of the first item occurs.
- [ ] Any protected ancestor returning unstable/untrustworthy at preflight blocks mutation with `RECURSIVE_PROTECTION_UNSTABLE`.
- [ ] Current trustworthy count `1` blocks with `RECURSIVE_PROTECT_LAST_FILE`.
- [ ] Preflight runs after worker lease fencing and final source freshness, but before `execute_item()` / Quarantine filesystem mutation.
- [ ] Preflight failure creates no Quarantine mutation and does not call a lower-score replanner.
- [ ] Existing Quarantine transactional authority remains the only mutation implementation.
- [ ] A recursive-mode plan cannot bypass the Worker via the legacy synchronous `FileCenterService.execute_plan` path. That path must fail closed for recursive protection (or delegate through the same Worker-authoritative preflight) before any mutation.
- [ ] Non-recursive direct execution behavior remains compatible.

Run RED:

```bash
pytest \
  tests/test_gate6b_recursive_dirbal_execute_preflight.py \
  tests/test_gate2_worker_execution.py \
  tests/test_execution.py \
  -q
```

### GREEN

- [ ] In `BatchPlanExecuteHandler.run`, immediately after the existing active-worker lease fence and final item freshness check, parse the frozen recursive authority and run the live evaluator.
- [ ] On failure, mark the item failed/skipped according to existing BatchPlan fail-closed conventions, persist the explicit reason, write AuditEvent evidence, and do not call `execute_item()`.
- [ ] On success, call the existing `execute_item()` unchanged for the Quarantine mutation.
- [ ] For new recursive-mode items, do not rely on legacy `OperationItem.protected_dir`; preserve that field for historical/non-recursive compatibility only.
- [ ] Ensure already completed NFC mutations are represented only by the live filesystem count; never subtract them again from the live count.

### Verify

```bash
pytest \
  tests/test_gate6b_recursive_dirbal_execute_preflight.py \
  tests/test_gate2_worker_execution.py \
  tests/test_execution.py \
  tests/test_gate3_stale_plan.py \
  -q
```

---

## Task 7 — Prove existing Worker serialization; do not invent another lock

**Modify tests first:**
- `tests/test_gate6b_recursive_dirbal_execute_preflight.py`
- existing Worker recovery/lease tests only if needed.

**Production files:** none unless the RED proves the current single-worker lease model does not serialize supported execution.

### RED / evidence cases

- [ ] Demonstrate that the supported Worker model has one active worker ownership lease and processes claimed WorkJobs sequentially.
- [ ] Demonstrate two overlapping recursive BatchPlan executions cannot simultaneously cross the mutation boundary under one valid worker authority.
- [ ] Demonstrate lease loss prevents the stale worker from performing the next mutation.

The current architecture is intentionally stronger than per-scope locking: one authoritative Worker processes one claimed job at a time. If these tests pass without source changes, record **no production change required** for serialization. Do not add a second lock, process, executor, or Worker merely for this amendment.

### Verify

```bash
pytest \
  tests/test_gate6b_recursive_dirbal_execute_preflight.py \
  tests/test_gate2_worker_execution.py \
  tests/test_gate4_worker_recovery.py \
  -q
```

Use the actual existing recovery-test filename if the repository names it differently; do not create a duplicate suite solely to satisfy this command.

---

## Task 8 — Preserve Preview/Generate sampled-snapshot semantics

**Modify:** only if tests expose an actual regression.

**Tests:**
- `tests/test_gate6b_recursive_dirbal_snapshot_authority.py`
- `tests/test_gate6b_recursive_dirbal_final_rebind_aba.py`
- `tests/test_gate6b_recursive_dirbal_preview.py`
- `tests/test_gate6b_recursive_dirbal_generate.py`

- [ ] Keep `source_snapshot_digest` binding recursive counts and tree identities.
- [ ] Keep observed Preview → Generate changes as `PREVIEW_CHANGED -> zero Draft`.
- [ ] Keep the current `33e94c29...` double row-rebind behavior as defense in depth unless refactoring into the shared reader makes it redundant; do not add another finite rebind pass.
- [ ] If simplifying/removing that defense-in-depth code, first add equivalence tests proving all existing sampled-snapshot regressions remain fail-closed.
- [ ] Update comments/docs so no code claims the sampled snapshot is atomic against arbitrary external writers.

### Verify

```bash
pytest \
  tests/test_gate6b_recursive_dirbal_snapshot_authority.py \
  tests/test_gate6b_recursive_dirbal_final_rebind_aba.py \
  tests/test_gate6b_recursive_dirbal_preview.py \
  tests/test_gate6b_recursive_dirbal_generate.py \
  -q
```

---

## Task 9 — Full Amendment A lifecycle regression

**Create or extend:**
- `tests/test_gate6b_recursive_dirbal_amendment_a_lifecycle.py`

### Required end-to-end cases

- [ ] Generate recursive draft with exact authority envelope.
- [ ] Freeze seals scope and file identity/hash.
- [ ] Validate succeeds while live state is safe.
- [ ] Execute preflight succeeds and one duplicate is quarantined.
- [ ] Same ancestry now at one live regular file blocks a later planned Quarantine.
- [ ] Change after Generate but before Validate is blocked.
- [ ] Change after Validate but before Execute is blocked by live preflight.
- [ ] Unstable/symlinked ancestry fails closed.
- [ ] No permanent delete occurs.
- [ ] No automatic empty-directory removal occurs.
- [ ] No lower-score replanning occurs after Generate.
- [ ] Quarantine undo/recoverability semantics remain available for the item that did complete.

### Verify focused Gate6-B

```bash
pytest \
  tests/test_gate6b_recursive_protection_reader.py \
  tests/test_gate6b_recursive_protection_authority.py \
  tests/test_gate6b_recursive_dirbal_*.py \
  -q
```

---

## Task 10 — Preserved Gate regressions and frontend contract

No new frontend feature is required by Amendment A. Existing status/reason rendering should receive existing plan item failure text through current APIs.

### Backend preserved lanes

```bash
pytest \
  tests/test_workflow_validation.py \
  tests/test_gate5d_advanced_dedupe_core.py \
  tests/test_gate5d_dedupe_preview_compiler.py \
  tests/test_gate5d_dedupe_generate.py \
  tests/test_gate5e_e4_preflight.py \
  tests/test_gate3_stale_plan.py \
  tests/test_gate2_worker_execution.py \
  -q
```

Then:

```bash
pytest -q
```

### Frontend preservation

Run the repository's existing Gate6-B CI commands exactly as configured in `.github/workflows/gate6b-tdd.yml`:

```bash
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

If the workflow uses a different exact script spelling, the workflow is authoritative; do not invent a new frontend lane.

---

## Task 11 — Source review, independent review, and release gates

After all implementation/regression tasks are green:

- [ ] Re-read PR #10 current HEAD; stop if it moved during final review.
- [ ] Compare the post-amendment implementation-start SHA to exact candidate HEAD.
- [ ] Verify no DB migration, second Worker/executor, permanent-delete path, historical mode semantic change, or new external-writer atomicity claim entered the diff.
- [ ] Verify all recursive-mode Quarantine items carry frozen scope authority and every mutation crosses the live Worker preflight.
- [ ] Verify direct synchronous execution cannot bypass recursive preflight.
- [ ] Verify Utility concurrent test work is independently green and was not silently changed to make Amendment A pass.
- [ ] Run focused + full backend + frontend evidence on the exact candidate.
- [ ] Create a new authoritative independent-review handoff locked to that exact candidate. CI is evidence only.
- [ ] Only after independent `PASS`: build exact-candidate `linux/amd64` release image.
- [ ] Only after image evidence: perform real NAS small-data acceptance with **no intentionally concurrent independent writer** in the acceptance scope.
- [ ] Only after NAS acceptance PASS: Gate6-B PASS/CLOSED and merge as the closure process authorizes.

## Acceptance Matrix

The post-amendment implementation is complete only when all statements below are true:

- [ ] Preview/Generate remain sampled, read-only, digest-bound, and stale changes persist zero Draft.
- [ ] Generate persists exact protected ancestors/source/root/lineage authority for recursive-mode Quarantine.
- [ ] Freeze rejects malformed/untrustworthy/last-file-unsafe protection scope and seals a deterministic scope digest.
- [ ] Validate rechecks the same immutable scope against live filesystem state.
- [ ] Worker Execute rechecks every required ancestor immediately before mutation.
- [ ] Live count `1` blocks; live count `2` permits exactly one current-item Quarantine.
- [ ] Prior completed NFC mutations are not double-subtracted.
- [ ] Observable instability fails closed.
- [ ] Existing Worker ownership provides NFC mutation serialization; no second executor/Worker exists.
- [ ] External final-syscall-gap atomicity is explicitly not claimed.
- [ ] Historical `weighted` / `balanced_by_bytes` remain unchanged.
- [ ] Utility semantics remain unchanged by this amendment.
- [ ] Dedupe remains Quarantine-only; zero permanent delete.
- [ ] `ctime` is not reintroduced as frozen mutation/snapshot authority.
- [ ] Exact-candidate Independent Review PASS precedes Docker/NAS release evidence.
