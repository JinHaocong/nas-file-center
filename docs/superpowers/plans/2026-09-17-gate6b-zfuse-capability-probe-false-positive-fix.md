# Gate6-B zfuse Capability Probe False-Positive Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the real-NAS Gate6-B blocker where Utility Preview reports `READY` on `zfuse/fuseblk` even though real cross-entry `RENAME_NOREPLACE` is unsupported.

**Architecture:** Preserve Amendment B's Preview-time fail-closed boundary. The capability decision used by `single_child_wrapper_collapse` must not treat same-entry `EEXIST` as sufficient proof of cross-entry native no-replace support. Any positive capability grant must be justified by a probe whose semantics match the required different-name/different-parent rename capability while preserving the amendment's probe-safety rules.

**Tech Stack:** Python 3.12, pytest, Linux `renameat2(..., RENAME_NOREPLACE)`, FastAPI workflow compiler.

**Spec:** `docs/superpowers/specs/2026-09-16-gate6b-utility-zfuse-deferral-amendment-b.md`

## Global Constraints

- `COMPAT/zfuse` Utility mutation remains unsupported in Gate6-B.
- Preview must report `UNSUPPORTED_FILESYSTEM`, `selectable=false`, stable reason `UTILITY_MOVE_UNSUPPORTED_FILESYSTEM` when strict native no-replace support cannot be positively established.
- Generate must persist zero Draft for an unsupported candidate.
- No `os.rename` fallback, no check-then-rename, no overwrite, merge, auto-rename, copy-delete, recursive migration, or second executor.
- Capability detection must not mutate candidate wrapper/child/target/user payload and must not leave probe residue.
- Existing native-filesystem Utility behavior and Amendment A behavior remain unchanged.

---

### Task 1: Encode the real zfuse false-positive as a RED regression

**Files:**
- Modify: `tests/test_gate6b_utility_fs_capability.py`

**Interfaces:**
- Consumes: `app.fs_ops.probe_existing_noreplace_capability_at(dir_fd, entry_name)`.
- Produces: a regression proving that same-entry `EEXIST` alone cannot grant `True` when the filesystem's cross-name capability probe reports unsupported.

- [ ] **Step 1: Add the failing regression test**

Model the observed NAS behavior: same-entry `C -> C` returns `EEXIST`, while the independent cross-name capability check returns `False`. Assert that `probe_existing_noreplace_capability_at(...)` returns `False`, not `True`, and that the candidate namespace is unchanged.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
pytest -q tests/test_gate6b_utility_fs_capability.py
```

Expected before production fix: the new test fails because the current implementation returns `True` immediately for same-entry `EEXIST`.

- [ ] **Step 3: Commit RED only**

```bash
git add tests/test_gate6b_utility_fs_capability.py
git commit -m "test: reproduce zfuse utility capability false positive"
```

### Task 2: Implement the minimal fail-closed capability fix

**Files:**
- Modify: `app/fs_ops.py`
- Test: `tests/test_gate6b_utility_fs_capability.py`

**Interfaces:**
- Consumes: `_RENAME_AT_IMPL`, `_probe_rename_noreplace_supported(...)` and the existing descriptor-bound caller.
- Produces: `probe_existing_noreplace_capability_at(...) -> bool | None` where `True` is only returned after positive support is established; unsupported/ambiguous filesystems cannot receive Utility mutation authority.

- [ ] **Step 1: Make the smallest production change that satisfies the RED case**

Do not add a compatibility executor or ordinary rename fallback. Keep the change limited to capability resolution.

- [ ] **Step 2: Run focused capability tests and verify GREEN**

```bash
pytest -q tests/test_gate6b_utility_fs_capability.py
```

- [ ] **Step 3: Run Amendment-B Utility tests**

```bash
pytest -q tests/test_gate6b_utility_amendment_b.py tests/test_gate6b_utility_api.py
```

- [ ] **Step 4: Commit the minimal fix**

```bash
git add app/fs_ops.py tests/test_gate6b_utility_fs_capability.py
git commit -m "fix: fail closed on ambiguous utility noreplace capability"
```

### Task 3: Regression and CI verification

**Files:**
- No additional production files unless a test exposes a specific regression.

- [ ] **Step 1: Run preserved Gate6-B focused regressions**
- [ ] **Step 2: Run full backend pytest**
- [ ] **Step 3: Run frontend tests/typecheck/build**
- [ ] **Step 4: Record exact candidate SHA and CI run identity**

No PASS claim until all required checks are green on one exact SHA.

### Task 4: Renew review/evidence chain and real-NAS affected acceptance

**Files:**
- Evidence/comments only; no production edits during acceptance.

- [ ] **Step 1: Renew source/Independent Review for the new diff and exact SHA**
- [ ] **Step 2: Build exact-candidate linux/amd64 Docker evidence**
- [ ] **Step 3: Re-run zfuse acceptance**

Required real-NAS Preview result:

```text
state=UNSUPPORTED_FILESYSTEM
selectable=false
capability_reason=UTILITY_MOVE_UNSUPPORTED_FILESYSTEM
planned_operations_count=0
```

Forced Generate must return HTTP 422 with zero `BatchPlan`, zero `BatchPlanItem`, zero `OperationJournal`, zero `batch-plan-execute` job, and zero filesystem mutation.

- [ ] **Step 4: Only after zfuse PASS, run native filesystem regression**

Prove the full native chain remains valid with `ALLOW_DELETE=false`:

```text
READY -> Generate -> Freeze -> Validate -> Worker MOVE -> paired empty-wrapper cleanup
```

No merge/deploy authorization until both affected acceptance halves PASS.
