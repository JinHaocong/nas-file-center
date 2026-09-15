# Gate6-A Quarantine Bulk Operations Implementation Plan

> **For implementation agents:** REQUIRED SUB-SKILLS: use `superpowers:test-driven-development` for every behavior change, `superpowers:systematic-debugging` for failures, and `superpowers:verification-before-completion` before any completion claim.

**Goal:** Implement v0.3.6 Gate6-A bulk quarantine restore and safe COMPAT transactional permanent purge while preserving Gate5-G CLOSED safety invariants and the v0.3.5.1 zfuse ctime compatibility semantics.

**Architecture:** Frozen in `docs/superpowers/specs/2026-09-13-gate6a-quarantine-bulk-operations-architecture-freeze.md`. Bulk actions use Preview -> Generate Draft -> Freeze -> Validate -> Worker Execute. Restore reuses existing transactional restore. Purge adds a narrowly scoped Worker-owned capture-before-destroy transaction engine; direct transactional purge remains guarded/refused.

**Baseline:** `8e7e2a669268117c2b7f0c83e14e6e32199fc8ba` (`v0.3.5.1`)  
**Canonical Branch:** `v0.3.6-gate6a-quarantine-bulk-operations`  
**Target:** Python backend + SQLite + SQLAlchemy + pytest; React/TypeScript frontend; Linux amd64 Docker; 极空间 zfuse NAS.

---

## Global Constraints

1. Do NOT modify `main` during implementation.
2. Do NOT reopen Gate5-G quarantine/restore architecture.
3. Do NOT remove or weaken `safe_quarantine_purge_guard()` for direct transactional purge.
4. Do NOT use `st_nlink` as purge authority, completeness proof, or last-link test.
5. Do NOT reintroduce ctime equality as authoritative identity for SHA-backed regular files on zfuse.
6. Do NOT add blind `rmtree` / recursive payload cleanup.
7. Do NOT hold SQLite write transactions across FUSE filesystem syscalls.
8. Every payload-affecting syscall must be Worker lease fenced.
9. Preview is zero mutation.
10. Generate on `PREVIEW_CHANGED` creates zero `BatchPlan` and zero `BatchPlanItem`.
11. A blocked member makes the entire Generate fail closed; do not silently drop members.
12. Bulk execution is serial per entry and has no fake rollback.
13. No DB migration unless a RED test proves the frozen model cannot be implemented with current columns; if that occurs, STOP and return to Architecture Review before migration.
14. Existing single-entry APIs remain compatible.
15. No PASS/CLOSED status until full regression + Docker + real NAS acceptance evidence exists.

---

## Codebase Reality Map

Verified against baseline `8e7e2a6`:

| File | Existing role | Gate6-A role |
|---|---|---|
| `app/models.py` | `QuarantineEntry`, `BatchPlan`, `BatchPlanItem`, `AuditEvent` | Reuse string states/metadata; no schema change expected |
| `app/service.py` | quarantine list/single restore/purge + plan lifecycle | Add bulk preview/generate orchestration; minimal lifecycle hooks |
| `app/api/router.py` | current `/quarantine` APIs | Add `/quarantine/bulk-preview` and `/quarantine/bulk-plan` |
| `app/quarantine/restore.py` | transactional COMPAT restore | Reuse unchanged where possible; bulk target is frozen by plan |
| `app/quarantine/paths.py` | deterministic restore rename helper | Reuse `build_restore_rename_path()` |
| `app/quarantine/cleanup_gate.py` | direct COMPAT purge refusal | Preserve unchanged semantics |
| `app/quarantine/tx_allocator.py` | monotonic exclusive attempt generation | Reuse for purge generation |
| `app/quarantine/candidate.py` | descriptor-bound payload qualification | Reuse/adapt with v0.3.5.1 ctime semantics |
| `app/quarantine/reconcile.py` | transactional recovery | Extend only where purge recovery is required |
| `app/execution/executor.py` | Worker plan item execution | Add `quarantine_purge` operation and bulk restore metadata integration |
| `app/tasks/handlers.py` | plan/WorkJob execution | Pass purge metadata/worker authority, aggregate item outcomes |
| `app/tasks/recovery.py` | Worker lease authority | Reuse Pattern A/B fences |
| `frontend/src/api/quarantine.ts` | single quarantine API | Add bulk preview/generate clients |
| `frontend/src/types/quarantine.ts` | quarantine API types | Add bulk request/preview/result types |
| `frontend/src/pages/Quarantine/index.tsx` | quarantine list/actions | selection + bulk action entry points |
| `frontend/src/pages/Quarantine/RestoreModal.tsx` | single restore modal | Keep single-item behavior; create or adapt bulk restore modal |
| `frontend/src/pages/Quarantine/PurgeConfirmModal.tsx` | single purge confirmation | Keep single-item behavior; create or adapt bulk purge draft modal |

New modules preferred to avoid expanding `service.py` with filesystem algorithms:

- `app/quarantine/bulk.py` — canonical selection, Preview manifests/digest, bulk plan builders.
- `app/quarantine/purge.py` — COMPAT transactional purge topology classification, capture, qualification, destruction, reconciliation helpers.

New tests preferred:

- `tests/test_gate6a_bulk_preview_api.py`
- `tests/test_gate6a_bulk_restore.py`
- `tests/test_gate6a_transactional_purge.py`
- `tests/test_gate6a_purge_recovery.py`
- `frontend/tests/gate6a_quarantine_bulk.test.ts` (or project-equivalent frontend test pattern).

---

## Task 0 — Baseline Verification Before Code Changes

- [ ] Confirm branch HEAD is descendant of exact baseline `8e7e2a669268117c2b7f0c83e14e6e32199fc8ba` and contains only Gate6-A docs before implementation.
- [ ] Confirm `main` still points to the approved production baseline or a separately authorized later fast-forward; if not, STOP and reconcile baseline.
- [ ] Capture `git diff baseline...HEAD` before code.
- [ ] Run existing focused quarantine/Gate5-G tests in the available Linux/Python test environment before first RED.

Recommended baseline commands when local/CI shell is available:

```bash
git fetch origin --prune
git switch v0.3.6-gate6a-quarantine-bulk-operations
git status --short
git merge-base --is-ancestor 8e7e2a669268117c2b7f0c83e14e6e32199fc8ba HEAD
pytest -q tests/test_quarantine_api.py tests/test_quarantine_core.py tests/test_quarantine_hardening.py
pytest -q tests/test_gate5g_g7_task11_cleanup_gate.py tests/test_gate5g_g7_task8_restore.py tests/test_v0351_zfuse_ctime_stability.py
```

Do not claim baseline tests passed unless their output was actually observed.

---

## Task 1 — Bulk Preview Contract and Canonical Digest (RED -> GREEN)

### Files

**Create:** `app/quarantine/bulk.py`  
**Modify:** `app/api/router.py`, `app/service.py`  
**Create tests:** `tests/test_gate6a_bulk_preview_api.py`

### RED tests first

- [ ] empty `entry_ids` rejected;
- [ ] duplicate IDs rejected (422; no silent dedupe);
- [ ] unsupported action rejected;
- [ ] restore allows only `skip|rename`;
- [ ] purge rejects restore-only conflict-policy/custom-target fields;
- [ ] preview with missing/non-active member marks selection blocked/fail-closed according to frozen response contract;
- [ ] identical selected set in different input order yields identical digest;
- [ ] Preview creates zero plans/items and does not mutate quarantine state/generation;
- [ ] restore `rename` preview freezes exact deterministic target;
- [ ] purge preview includes canonical topology manifest sufficient to detect historical conflict aliases and blockers;
- [ ] `st_nlink` differences do not change authoritative eligibility logic;
- [ ] digest changes when any digest-bound DB identity/path/topology/restore-target fact changes.

### Minimal implementation

Implement pure helpers in `app/quarantine/bulk.py`:

```python
canonicalize_entry_ids(...)
build_bulk_restore_preview(...)
build_bulk_purge_preview(...)
canonical_preview_digest(...)
```

Rules:

- canonical ID sort is ascending after duplicate validation;
- stable JSON serialization (`sort_keys=True`, compact separators, UTF-8);
- max IDs initially 5000;
- manifest includes the exact frozen identity fields from the Architecture Freeze;
- topology discovery is read-only and path/namespace bounded to quarantine root `.tx`;
- do not hash payload during ordinary Preview if persisted authoritative SHA plus stat/path topology is sufficient to produce identity manifest; destructive qualification occurs later. If a test demonstrates Preview must hash for correctness, STOP and document the performance/safety implication before changing the freeze.

Add API models/routes:

```text
POST /api/quarantine/bulk-preview
```

Expected response fields at minimum:

```text
action
entry_ids
eligible_count
blocked_count
items[]
preview_digest
```

### Focused verification

```bash
pytest -q tests/test_gate6a_bulk_preview_api.py
```

Commit only after RED was observed and focused tests are GREEN.

---

## Task 2 — Bulk Generate Draft + Preview Identity Enforcement (RED -> GREEN)

### Files

**Modify:** `app/quarantine/bulk.py`, `app/service.py`, `app/api/router.py`  
**Tests:** extend `tests/test_gate6a_bulk_preview_api.py`

### RED tests first

- [ ] Generate requires `expected_preview_digest`;
- [ ] current Preview mismatch returns HTTP 409 `PREVIEW_CHANGED`;
- [ ] mismatch persists zero BatchPlan/BatchPlanItem;
- [ ] any missing/non-active/blocked selected member prevents plan creation;
- [ ] restore draft kind = `quarantine-bulk-restore`;
- [ ] purge draft kind = `quarantine-bulk-purge`;
- [ ] restore item target is exact frozen Preview target;
- [ ] purge item metadata persists exact purge topology manifest and preview digest;
- [ ] restore plan generation requires mutation enabled;
- [ ] purge plan generation requires admin + mutation + delete + confirmation `DELETE`;
- [ ] non-admin purge rejected;
- [ ] one confirmation is bound to exact digest; changed Preview requires reconfirmation.

### Implementation

Add:

```text
POST /api/quarantine/bulk-plan
```

Use a short SQLite write transaction only for plan creation after all Phase-A read-only work/digest verification has completed. Expensive topology walk/hash must not run while holding SQLite write lock.

Draft representation:

```text
quarantine-bulk-restore / operation=restore
quarantine-bulk-purge   / operation=quarantine_purge
```

Persist metadata required by Freeze/Validate/Worker recovery.

### Focused verification

```bash
pytest -q tests/test_gate6a_bulk_preview_api.py
```

---

## Task 3 — Freeze/Validate Integration for Bulk Restore and Purge (RED -> GREEN)

### Files

**Modify:** `app/service.py` and the smallest existing planning/validation modules actually owning BatchPlan Freeze/Validate logic  
**Tests:** `tests/test_gate6a_bulk_restore.py`, `tests/test_gate6a_transactional_purge.py`

### RED tests first

- [ ] Draft bulk restore freezes only while all selected entries remain active and identity-bound;
- [ ] restore frozen exact target becomes invalid if occupied by foreign object before Validate;
- [ ] purge Freeze/Validate rejects selection whose topology/owner classification changed;
- [ ] purge rejects another active owner (`SHARED_ACTIVE_PAYLOAD`);
- [ ] purge rejects unknown owner/unrecognized namespace;
- [ ] Freeze/Validate never modifies payloads or quarantine states;
- [ ] current Gate3/BatchPlan plan state transitions remain unchanged for unrelated plan kinds.

### Implementation

Reuse existing BatchPlan lifecycle. Add only plan-kind-specific validation hooks necessary for `restore` and `quarantine_purge` metadata.

Freeze persists physical identity in the existing plan item fields where appropriate. Purge topology manifest remains in item metadata; live Validate re-checks it rather than trusting stale JSON.

No automatic Execute.

### Focused verification

```bash
pytest -q tests/test_gate6a_bulk_restore.py tests/test_gate6a_transactional_purge.py
pytest -q tests/test_planning.py tests/test_gate3*  # adapt glob to shell/test environment
```

---

## Task 4 — Bulk Restore Worker Execution (RED -> GREEN)

### Files

**Modify:** `app/execution/executor.py`, `app/tasks/handlers.py` only as required  
**Prefer no changes:** `app/quarantine/restore.py` unless a failing test exposes a real incompatibility  
**Tests:** `tests/test_gate6a_bulk_restore.py`

### RED tests first

- [ ] bulk plan restore calls Worker-owned transactional restore for COMPAT row;
- [ ] API/direct unauthenticated transactional mutation still rejected;
- [ ] skip policy produces per-entry skipped result without overwrite;
- [ ] rename uses frozen plan target; if occupied later, fail/skip closed and never generate a new target at Execute;
- [ ] serial partial failure: earlier completed item remains completed, later items continue;
- [ ] audit emitted per restored entry;
- [ ] non-active row at execution fails without mutation.

### Implementation

Pass `quarantine_entry_id` from plan item metadata through the existing Worker executor. Do not implement an API-side loop.

Ensure `operation='restore'` handling uses exact frozen `target_path` for Gate6-A plans instead of re-running rename target selection.

### Regression

```bash
pytest -q tests/test_gate6a_bulk_restore.py
pytest -q tests/test_gate5g_g7_task8_restore.py tests/test_gate5g_g7_hotfix2_worker_restore_authority.py tests/test_gate5g_g7_hotfix3_restore_takeover_generation.py
```

---

## Task 5 — Transactional Purge Topology Classifier (RED -> GREEN, zero destruction first)

### Files

**Create:** `app/quarantine/purge.py`  
**Tests:** `tests/test_gate6a_transactional_purge.py`

### RED tests first

Construct isolated temp namespaces representing:

- [ ] normal active entry: anchor + captured_source + public view;
- [ ] zfuse-like misleading `st_nlink` values via monkeypatch; classifier output unchanged;
- [ ] historical conflict candidate owned by conflict row; eligible only when non-authoritative and payload matches;
- [ ] same payload owned by another active row -> `SHARED_ACTIVE_PAYLOAD`;
- [ ] owner DB row missing -> blocked;
- [ ] unrecognized same-entry/private pathname -> blocked;
- [ ] foreign inode at expected public path -> blocked/preserve;
- [ ] symlink anywhere in payload alias set -> blocked;
- [ ] path outside quarantine root -> blocked;
- [ ] ctime-only variation does not alter SHA-backed authoritative classification;
- [ ] mtime/size/hash/device/inode mismatch blocks.

### Implementation

Pure/read-only classifier first:

```python
build_purge_topology_manifest(...)
validate_purge_topology_manifest(...)
classify_cross_entry_alias_owner(...)
```

Manifest must use explicit owned path roles; never infer safety from link count.

No unlink/rename in this task.

### Focused verification

```bash
pytest -q tests/test_gate6a_transactional_purge.py -k 'topology or classify or nlink or shared or foreign'
```

---

## Task 6 — Transactional Purge Capture Phase (RED -> GREEN)

### Files

**Modify:** `app/quarantine/purge.py`  
**Reuse:** `app/quarantine/tx_allocator.py`, `app/tasks/recovery.py`, safe descriptor traversal helpers  
**Tests:** extend `tests/test_gate6a_transactional_purge.py`

### RED tests first

- [ ] valid Worker authority required;
- [ ] entry must still be active before durable `purging` transition;
- [ ] restoring entry cannot enter purge;
- [ ] `purging` transition committed before first destructive-intent capture;
- [ ] new attempt generation is monotonic and exclusive;
- [ ] every alias is captured by exactly one rename into deterministic unique purge slot;
- [ ] lease fence occurs before every rename;
- [ ] no SQLite write transaction held across rename;
- [ ] occupied purge slot is never overwritten/reused;
- [ ] source replacement race captures the replacement but post-capture qualification identifies it foreign and preserves it;
- [ ] no unlink occurs during capture phase.

### Implementation

Suggested entry point:

```python
execute_transactional_purge_capture(
    session_factory,
    entry_id,
    worker_id,
    frozen_manifest,
    quarantine_root,
    allowed_roots,
)
```

Persist/recover generation + manifest reference through current row/plan metadata without schema change. If this proves impossible under crash recovery tests, STOP and return to Architecture Review.

Capture destination example:

```text
attempt-<gen>/purge/public-view
attempt-<gen>/purge/current-anchor
attempt-<gen>/purge/captured-source
attempt-<gen>/purge/linked-conflict-<id>-anchor
```

No check-then-rename reuse.

---

## Task 7 — Post-Capture Qualification + Destructive Purge Phase (RED -> GREEN)

### Files

**Modify:** `app/quarantine/purge.py`, `app/execution/executor.py`, `app/tasks/handlers.py`  
**Tests:** extend `tests/test_gate6a_transactional_purge.py`

### RED tests first

- [ ] captured expected alias fully qualifies then can be destroyed;
- [ ] captured foreign object => zero destructive unlink for that transaction after detection; preserve evidence and fail closed;
- [ ] `st_nlink` never read/used for authority (test by absurd values or monkeypatch);
- [ ] ctime-only read-induced changes pass for SHA-backed file;
- [ ] true mtime/size/hash/device/inode change fails;
- [ ] each unlink has lease fence;
- [ ] no blind recursive delete;
- [ ] historical conflict candidate alias destroyed only after requalification;
- [ ] historical conflict row remains `conflict` and receives audit linkage, not state rewrite;
- [ ] entry becomes `purged` only after all NFC-owned manifest aliases are gone/closed;
- [ ] `purged_at` set only at terminal closure;
- [ ] per-entry `quarantine.purge` audit remains present/compatible and includes transaction/digest context.

### Implementation

Add Worker-only operation:

```text
operation = quarantine_purge
```

`app/execution/executor.py` routes it only when `session_factory`, `worker_id`, and `quarantine_entry_id` are present.

Direct `service.purge_quarantine_entry()` behavior for transactional rows MUST still hit `safe_quarantine_purge_guard()` and EOPNOTSUPP.

Destructive helper must unlink exact known captured slot paths only.

### Focused verification

```bash
pytest -q tests/test_gate6a_transactional_purge.py
pytest -q tests/test_gate5g_g7_task11_cleanup_gate.py
```

---

## Task 8 — Purge Crash Recovery / Reconciliation (RED -> GREEN)

### Files

**Modify:** `app/quarantine/purge.py`, `app/quarantine/reconcile.py` and Worker startup/recovery integration only as necessary  
**Tests:** `tests/test_gate6a_purge_recovery.py`

### RED tests first

Inject crash/exception boundaries at least:

- [ ] after durable `purging`, before generation allocation;
- [ ] after generation allocation, before mkdir;
- [ ] after each alias capture, before DB/checkpoint observation;
- [ ] after all capture, before qualification;
- [ ] after some qualified alias destruction;
- [ ] after all destruction, before terminal DB `purged` commit;
- [ ] stale worker takeover between mutations;
- [ ] restart sees foreign/unknown object in purge slot;
- [ ] rerunning reconciliation is idempotent.

Expected invariant:

```text
no crash path may cause blind deletion,
no unknown object is destroyed,
no completed destructive step is falsely rolled back to active,
and terminal purged is committed only when closure is proven.
```

### Implementation

Reconciler classifies evidence before mutations. Existing write-once slots are never overwritten. Retry requiring a new rename destination allocates a new generation/slot as required by the frozen write-once model.

### Focused verification

```bash
pytest -q tests/test_gate6a_purge_recovery.py
pytest -q tests/test_gate5g_g7_task10_reconcile.py tests/test_gate5g_g7_g7_races.py
```

Use exact existing filenames discovered in repository if glob names differ.

---

## Task 9 — Bulk Result Aggregation and Audit Contract (RED -> GREEN)

### Files

**Modify:** smallest owning Worker/job handler and service serialization code  
**Tests:** extend restore/purge Gate6-A tests

### RED tests first

- [ ] per-item result: `succeeded|skipped|failed|blocked`;
- [ ] aggregate counts exact;
- [ ] continue-on-item-failure;
- [ ] Worker lease loss stops job-level continuation appropriately rather than pretending ordinary item failure;
- [ ] already completed item not repeated on retry;
- [ ] audit exists for each successful mutation and cross-entry historical alias retirement;
- [ ] no synthetic rollback events.

Do not add a second parallel job protocol if existing WorkJob/BatchPlan execution can represent this safely.

---

## Task 10 — Frontend Multi-Select + Bulk Restore/Purge Draft UX (RED -> GREEN)

### Files

**Modify:**
- `frontend/src/api/quarantine.ts`
- `frontend/src/types/quarantine.ts`
- `frontend/src/pages/Quarantine/index.tsx`

**Create or minimally adapt:**
- `frontend/src/pages/Quarantine/BulkRestoreModal.tsx`
- `frontend/src/pages/Quarantine/BulkPurgeConfirmModal.tsx`

**Tests:** `frontend/tests/gate6a_quarantine_bulk.test.ts` or existing frontend test framework equivalent.

### RED tests / type-level checks

- [ ] only active rows are selectable for bulk mutation;
- [ ] select current page;
- [ ] select all current filtered results resolves to explicit IDs before Preview;
- [ ] changing filter/selection invalidates stale Preview/digest;
- [ ] restore modal exposes only skip/rename;
- [ ] purge modal shows selected count + irreversible warning;
- [ ] purge confirm generates Draft; it does not call direct single purge endpoint repeatedly;
- [ ] blocked preview items prevent Generate and surface reasons;
- [ ] successful Draft navigates/links into normal plan lifecycle.

### Verification

```bash
cd frontend
npm run typecheck
npm run build
```

If frontend test command exists, run it before typecheck/build and record exact output.

---

## Task 11 — Focused Regression Matrix

Run all new Gate6-A tests plus the existing safety families most likely to regress:

```bash
pytest -q \
  tests/test_gate6a_bulk_preview_api.py \
  tests/test_gate6a_bulk_restore.py \
  tests/test_gate6a_transactional_purge.py \
  tests/test_gate6a_purge_recovery.py

pytest -q \
  tests/test_quarantine_api.py \
  tests/test_quarantine_core.py \
  tests/test_quarantine_hardening.py

pytest -q tests/test_gate5g* tests/test_v0351_zfuse_ctime_stability.py

pytest -q tests/test_planning.py tests/test_gate3*
```

Adjust shell glob quoting only as required by actual environment. Any failure requires systematic root-cause investigation before code changes.

---

## Task 12 — Full Regression + Build Verification

Before implementation-complete claim:

```bash
pytest --disable-warnings -q
cd frontend && npm run typecheck && npm run build
```

Also run repository lint/static checks if currently defined in package/project configuration.

Record exact pass counts, warning counts, and elapsed times. Never infer results.

---

## Task 13 — Diff / Scope / Security Review

Compare exact baseline to candidate HEAD:

```bash
git diff --check 8e7e2a669268117c2b7f0c83e14e6e32199fc8ba...HEAD
git diff --stat 8e7e2a669268117c2b7f0c83e14e6e32199fc8ba...HEAD
git diff 8e7e2a669268117c2b7f0c83e14e6e32199fc8ba...HEAD -- \
  app/quarantine app/api/router.py app/service.py app/execution app/tasks frontend tests
```

Review specifically for:

- accidental weakening of `cleanup_gate`;
- new unlink/rmtree calls outside `app/quarantine/purge.py`;
- any `st_nlink` safety decision;
- any ctime authority regression;
- direct API transactional mutation;
- missing worker lease fences;
- SQLite transaction held during filesystem syscall;
- silent selection member dropping;
- automatic execute after purge confirmation;
- unrelated refactor.

---

## Task 14 — Linux amd64 Docker Verification

Build from exact candidate HEAD and immutable tag. Verify API and Worker use the same image identity.

Do not overwrite production tag during pre-release validation. Use a Gate6-A candidate tag, e.g.:

```text
kerwinjhc/nas-file-center:0.3.6-gate6a-<sha7>
```

Record registry index digest + linux/amd64 child manifest/config identity as available.

---

## Task 15 — Real NAS Acceptance

This task requires user-controlled NAS execution. Never infer PASS from unit tests.

Use an isolated, explicitly approved quarantine test selection. Capture read-only baseline before mutation.

### Restore acceptance

- [ ] select a small active transactional batch;
- [ ] Preview digest;
- [ ] Generate Draft;
- [ ] Freeze;
- [ ] Validate;
- [ ] Execute;
- [ ] prove restored paths and row states;
- [ ] prove no overwrite and audit.

### Purge acceptance

- [ ] select a small active transactional batch whose deletion is explicitly safe;
- [ ] preferably include one payload with a historical conflict candidate alias if available and authorized;
- [ ] Preview topology/digest;
- [ ] Generate Draft with admin + delete + `DELETE` confirmation;
- [ ] Freeze;
- [ ] Validate;
- [ ] Execute;
- [ ] prove selected row `purged`;
- [ ] prove known NFC-owned aliases are gone;
- [ ] prove historical conflict row remains historical conflict while its qualified candidate alias is retired;
- [ ] prove no new unknown/foreign-loss evidence;
- [ ] prove audit entries.

Only after this may Gate6-A be considered for PASS/CLOSED.

---

## Task 16 — Completion Artifact / Handoff

Produce an independent walkthrough in-repo containing:

- exact baseline;
- canonical branch;
- candidate HEAD;
- commit list;
- modified files;
- RED evidence per major task;
- GREEN focused test results;
- full backend regression result;
- frontend typecheck/build result;
- Docker image/digests;
- architecture compliance checklist;
- known limitations;
- exact NAS acceptance evidence summary;
- statement that `st_nlink` was never used as purge authority;
- statement that direct transactional purge guard remains intact;
- real HEAD and artifact provenance if a ZIP is produced.

Allowed pre-review status language after implementation/tests but before independent/NAS closure:

```text
Gate6-A IMPLEMENTATION COMPLETE
READY FOR INDEPENDENT REVIEW / REAL NAS ACCEPTANCE
```

Do not self-declare PASS/CLOSED before the acceptance gate.

---

## Recommended Commit Sequence

Keep commits small and reviewable, roughly:

```text
test(gate6a): specify bulk preview and digest contract
feat(gate6a): add quarantine bulk preview and draft generation
feat(gate6a): integrate bulk restore plan execution
test(gate6a): specify compat transactional purge topology
feat(gate6a): add purge capture and qualification engine
feat(gate6a): add purge destruction and recovery
feat(gate6a): add bulk result audit contract
feat(frontend): add quarantine bulk restore and purge workflow
docs(gate6a): add implementation walkthrough
```

The exact grouping may change to preserve RED -> GREEN integrity, but unrelated refactors are forbidden.
