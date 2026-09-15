# Gate6-B Utility + Recursive Directory Balance Implementation Plan

**Architecture authority:** `docs/superpowers/specs/2026-09-16-gate6b-utility-recursive-dirbal-architecture-freeze.md`  
**Baseline:** `7d9e248dae25d706d65a36bc864fb86f9a613d4d`  
**Branch:** `v0.3.6-gate6b-utility-recursive-dirbal`  
**Method:** strict RED -> GREEN -> REFACTOR, then regression/review/release gates.

## Guardrails

- Never alter existing `balanced_by_bytes` semantics.
- Never change CLOSED generic Gate5-E flatten behavior to make Utility work.
- No Preview filesystem mutation and no Preview BatchPlan persistence.
- Generate creates draft only.
- No second executor/worker.
- Recursive dedupe generates Quarantine actions only, never permanent delete.
- Production NAS is outside implementation authority.

## Task 0 — Gate6-B CI lane

**Create:** `.github/workflows/gate6b-tdd.yml`

The workflow triggers on the canonical Gate6-B branch and runs:

```bash
pytest \
  tests/test_gate6b_utility_*.py \
  tests/test_gate6b_recursive_dirbal_*.py \
  tests/test_workflow_validation.py \
  tests/test_gate5d_advanced_dedupe_core.py \
  tests/test_gate5d_dedupe_preview_compiler.py \
  tests/test_gate5d_dedupe_generate.py \
  -q
```

It also runs existing frontend tests after Node 22 + `npm ci`.

This lane is evidence only; CI green is not sufficient for Gate closure.

## Task 1 — Utility schema and validation (RED first)

**Tests create:**
- `tests/test_gate6b_utility_schema_validation.py`

**Production files:**
- `app/workflows/schema.py`
- `app/workflows/validation.py`

### RED cases

1. `WorkflowDefinition(mode="utility", ...)` is accepted only for the frozen Utility shape.
2. Utility V1 accepts only `single_child_wrapper_collapse`.
3. file/organizer/dedupe behavior remains unchanged.
4. arbitrary existing file-stream/action steps are rejected in utility mode.
5. schema requires authoritative Index Root input plus optional subpath; product schema does not expose an arbitrary absolute path field.

### GREEN implementation

Add the minimum explicit utility definition/config model needed by Workflow immutable revisions. Keep utility semantics separate from `WorkflowStep` file-stream grammar if that provides the cleanest compatibility path; do not fake directory candidates as file candidates.

### Verify

```bash
pytest tests/test_gate6b_utility_schema_validation.py tests/test_workflow_validation.py -q
```

## Task 2 — Single-child wrapper discovery (RED first)

**Tests create:**
- `tests/test_gate6b_utility_discovery.py`

**Production files:**
- `app/batch_utilities/flatten.py` only for reuse if no historical semantic change is required
- preferably create `app/batch_utilities/single_child_wrapper.py` for the dedicated discovery semantic
- `app/batch_utilities/__init__.py`

### RED cases

Build temporary directory fixtures for:

- `A/B/C` strict READY case.
- multiple sibling wrappers under A.
- B containing one regular file => not candidate.
- B containing C plus hidden file => not candidate.
- B containing two child directories => not candidate.
- B symlink => blocked.
- C symlink => blocked.
- C special object => blocked/fail closed.
- target `A/C` exists => `TARGET_EXISTS` and only that candidate is skipped.
- Unicode/spaces/long legal names.
- candidate IDs/digests deterministic for identical read-only snapshot.

Discovery must perform zero mutation.

### GREEN implementation

Implement dedicated read-only discovery using descriptor/no-follow semantics already used by Gate5-E. Return explicit directory candidates with stable candidate IDs, physical snapshot inputs, readiness state, conflict reason, source/target, wrapper identity and child identity.

### Verify

```bash
pytest tests/test_gate6b_utility_discovery.py tests/test_gate5e_e4_discovery.py -q
```

## Task 3 — Utility Preview / selection / compile / Generate (RED first)

**Tests create:**
- `tests/test_gate6b_utility_preview_compile.py`
- `tests/test_gate6b_utility_generate.py`
- `tests/test_gate6b_utility_api.py`

**Production files likely touched:**
- `app/workflows/compiler.py`
- `app/workflows/service.py`
- `app/api/router.py`
- existing Batch Utility compiler/service modules under `app/batch_utilities/`
- existing plan/digest helpers as appropriate

### RED contract

- Preview defaults every READY candidate to selected in response metadata without persisting a Plan.
- unsafe/conflict candidates are nonselectable.
- Generate receives explicit selected candidate IDs.
- deselected candidate produces no PlanItem.
- candidate ID from another Preview is rejected.
- any discovery-affecting change Preview -> Generate returns `PREVIEW_CHANGED` and persists zero draft.
- selected READY candidate compiles exactly:
  1. MOVE `A/B/C -> A/C`
  2. REMOVE_EMPTY_DIR `A/B`
- no overwrite/merge/rename fallback.
- one generated Plan collapses at most one wrapper layer.
- generated plan status is draft.

### GREEN implementation

Add utility compiler/preview/generate orchestration while delegating actual actions to existing Gate5-E/BatchPlan lifecycle. Bind Preview identity to root/subpath, wrapper/child physical snapshot, target nonexistence and selected decisions.

### Verify

```bash
pytest tests/test_gate6b_utility_*.py -q
```

## Task 4 — Utility execution safety regression

**Tests create:**
- `tests/test_gate6b_utility_execution_safety.py`

**Production files:** only if a compatibility adapter is required; do not add a new executor.

### RED/Regression cases

- after MOVE succeeds, third-party object appears in B before REMOVE_EMPTY_DIR => B preserved, object preserved.
- target appears/stales before Execute => existing Freeze/Validate prevents overwrite.
- symlink/path ABA fails closed.
- no recursive delete path exists.

### Verify

```bash
pytest \
  tests/test_gate6b_utility_execution_safety.py \
  tests/test_gate5e_e4_lifecycle.py \
  tests/test_gate5e_e4_hotfix2.py \
  tests/test_gate3_stale_plan.py \
  -q
```

## Task 5 — New recursive selection token + old-mode regression (RED first)

**Tests create:**
- `tests/test_gate6b_recursive_dirbal_config.py`
- `tests/test_gate6b_recursive_dirbal_core.py`

**Production files:**
- `app/planning/dedupe_config.py`
- `app/planning/dedupe_engine.py`

### RED cases

- `recursive_directory_balanced_by_bytes` validates as an explicit new selection mode.
- old `weighted` and `balanced_by_bytes` produce exactly preserved behavior on existing fixtures.
- unique highest scorer wins even if it worsens balance.
- explicit `path_priority` beats recursive balance.

### GREEN implementation

Extend config token only; route the new token to new logic while preserving old branches byte-for-byte semantically.

### Verify

```bash
pytest tests/test_gate6b_recursive_dirbal_config.py tests/test_gate5d_advanced_dedupe_core.py -q
```

## Task 6 — LCA / dynamic buckets / recursive released bytes (RED first)

**Tests:** extend `tests/test_gate6b_recursive_dirbal_core.py`

**Production file:**
- `app/planning/dedupe_engine.py`

### RED cases

- same root / two top-level branches.
- deeper same-branch split where LCA is below Scan Root.
- 3+ buckets.
- 2+ copies in the same bucket.
- candidate parent equals LCA => synthetic `LCA_DIRECT`.
- LCA_DIRECT counter does not double-count descendant buckets.
- planned Quarantine bytes accumulate parent -> all ancestors -> Scan Root.
- different file sizes prove byte balancing rather than item counts.
- zero-byte ties resolve deterministically.
- Unicode/spaces/long legal paths.

### GREEN implementation

Add pure helpers for normalized ancestor traversal, same-root LCA, bucket derivation, synthetic direct bucket identity, recursive counters and projected balance simulation. Keep them deterministic and filesystem-independent; filesystem safety snapshot comes from Preview layer.

### Verify

```bash
pytest tests/test_gate6b_recursive_dirbal_core.py tests/test_gate5d_advanced_dedupe_core.py -q
```

## Task 7 — Cross-root hierarchical balance (RED first)

**Tests:** extend `tests/test_gate6b_recursive_dirbal_core.py`

**Production:** `app/planning/dedupe_engine.py`

### RED cases

- cross-root duplicate group never creates a cross-root LCA.
- scorer ties first select root by existing Scan Root released-byte objective.
- only then recursively balance among tied candidates inside chosen root.
- deterministic normalized-path tie-break after both balance layers.
- accumulated root and directory counters stay consistent.

### Verify

```bash
pytest tests/test_gate6b_recursive_dirbal_core.py -q
```

## Task 8 — Recursive Last-File Protection (RED first)

**Tests create:**
- `tests/test_gate6b_recursive_dirbal_last_file.py`

**Production files:**
- `app/planning/dedupe_engine.py`
- `app/planning/dedupe_preview.py`

### RED cases

- protection evaluates every relevant real ancestor, not just top-level dir.
- subtree regular files are counted recursively.
- symlink file/dir does not count as a protected regular file.
- already-scheduled quarantine is subtracted.
- proposed quarantine is subtracted.
- exact threshold must remain `>= 1`.
- unsafe choice carries `RECURSIVE_PROTECT_LAST_FILE`.
- if every highest-score choice is unsafe, group is SKIPPED with no quarantine candidates.
- mandatory protection cannot be disabled in the new mode.
- existing old-mode protection behavior remains compatible.

### GREEN implementation

Build the read-only protection snapshot in Preview and pass explicit directory-count data into the pure decision engine. Avoid hidden filesystem reads in the pure scoring function where possible.

### Verify

```bash
pytest tests/test_gate6b_recursive_dirbal_last_file.py tests/test_gate5d_advanced_dedupe_core.py -q
```

## Task 9 — Preview explain + digest + PREVIEW_CHANGED (RED first)

**Tests create:**
- `tests/test_gate6b_recursive_dirbal_preview.py`
- `tests/test_gate6b_recursive_dirbal_generate.py`

**Production files:**
- `app/planning/dedupe_preview.py`
- `app/planning/dedupe_generate.py`
- `app/planning/stale.py` only if the existing stale primitive needs a new bound field, without weakening old semantics

### RED cases

Preview Explain binds/exposes:

- mode,
- LCA,
- bucket / LCA_DIRECT,
- released bytes before/after,
- spread before/after,
- score/factors,
- KEEP/QUARANTINE reason,
- Recursive Last-File Protection reason.

Digest changes when any frozen input changes: scan/DB lineage, scorer config, root scope, LCA/bucket inputs, recursive regular-file counts, safety snapshot, final decisions.

Generate with a changed input returns `PREVIEW_CHANGED` and **zero new BatchPlan rows/items**.

### Verify

```bash
pytest \
  tests/test_gate6b_recursive_dirbal_preview.py \
  tests/test_gate6b_recursive_dirbal_generate.py \
  tests/test_gate5d_dedupe_preview_compiler.py \
  tests/test_gate5d_dedupe_generate.py \
  -q
```

## Task 10 — API and Workflow Dedupe integration

**Tests create:**
- `tests/test_gate6b_recursive_dirbal_api.py`

**Production files:**
- `app/api/router.py`
- `app/workflows/schema.py` / compiler only as required for existing dedupe workflow config transport

### RED cases

- API accepts the explicit new mode and returns Explain fields.
- old mode labels/tokens remain valid.
- invalid attempts to disable mandatory recursive protection fail closed.
- API Preview stays read-only.
- Generate stale response is explicit and creates zero draft.

### Verify

```bash
pytest tests/test_gate6b_recursive_dirbal_api.py tests/test_gate5d_dedupe_preview_api.py tests/test_gate5d_dedupe_generate_api.py -q
```

## Task 11 — Frontend labels, Utility controls, Explain UI (RED first)

**Frontend files likely touched:**
- `frontend/src/api/workflows.ts`
- `frontend/src/api/domain.ts`
- `frontend/src/pages/Workflows/WorkflowBuilder.tsx`
- `frontend/src/pages/Workflows/WorkflowPreviewPanel.tsx`
- related frontend tests under `frontend/tests/`

First inspect the existing test filenames and follow their current Testing Library/Vitest style before writing new tests.

### RED UI cases

- Builder offers explicit Utility mode and only the frozen single-child wrapper utility configuration.
- utility scope uses managed Index Root + optional subpath, not arbitrary absolute path entry.
- Utility Preview renders READY/conflict states, defaults READY selection, permits deselection, and cannot select conflict candidates.
- Advanced Dedupe selection choices distinguish `Balanced by Scan Root` and `Recursive Directory Balanced by Bytes`.
- new mode shows mandatory protection, not a disable switch.
- Preview shows concise result and expandable balance Explain.

### Verify

```bash
cd frontend
npm test
npm run typecheck
npm run build
```

## Task 12 — Full regression and self-review

Run focused Gate6-B tests first, then full backend and frontend suites.

```bash
pytest -q
cd frontend && npm test && npm run typecheck && npm run build
```

Then compare exact baseline to candidate and review for:

- any change to old `balanced_by_bytes` behavior,
- accidental second executor,
- Preview mutation/persistence,
- permanent delete path,
- cross-root LCA,
- symlink following,
- last-file protection bypass,
- non-deterministic iteration/digest,
- Utility overwrite/merge/rename fallback.

## Task 13 — Independent review / exact candidate / release evidence

After implementation + regression self-review:

1. freeze exact candidate SHA,
2. create/update PR without merging,
3. prepare authoritative review handoff containing exact baseline and exact candidate,
4. obtain genuinely independent review,
5. revalidate exact candidate after review fixes (if any),
6. build linux/amd64 Docker from exact accepted candidate,
7. only after that prepare user-run small-data real NAS acceptance,
8. Gate6-B can be marked PASS/CLOSED only after all required evidence succeeds.

No production NAS mutation is part of Tasks 0–12.