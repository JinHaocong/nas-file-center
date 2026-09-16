# Gate6-B Amendment B Implementation Plan v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** AUTHORITATIVE EXECUTION PLAN — supersedes `2026-09-16-gate6b-utility-zfuse-post-amendment-b.md`.

**Goal:** Make Utility Preview truthfully classify COMPAT/zfuse storage as non-executable before Draft creation, preserve strict native no-replace MOVE behavior, and permit only the exact paired verified-empty wrapper cleanup under `ALLOW_DELETE=false`.

**Architecture:** Add a zero-namespace-mutation capability probe in `app/fs_ops.py` using `renameat2(..., RENAME_NOREPLACE)` with the same existing directory entry as source and destination. Feed that result into Single-Child Wrapper discovery so unsupported topology is visible but non-selectable. Generate explicitly rejects forced unsupported selection before persistence. Executor gains one narrow DB-backed authority check that exempts only the paired Utility `rmdir_empty` item from the broad delete gate.

**Tech Stack:** Python 3, SQLAlchemy, pytest, Linux `renameat2`, FastAPI workflow service, React/TypeScript/Ant Design.

**Spec:** `docs/superpowers/specs/2026-09-16-gate6b-utility-zfuse-deferral-amendment-b.md`, frozen by `docs/superpowers/specs/2026-09-16-gate6b-utility-zfuse-deferral-amendment-b-approval.md`.

## Global Constraints

- Baseline: `main@7d9e248dae25d706d65a36bc864fb86f9a613d4d`.
- Historical pre-Amendment-B candidate: `fb120bfe2a760c1294c0ed650f95988dac1410ce`.
- No ordinary `rename()` fallback for Utility MOVE.
- Preview performs zero namespace mutation and zero BatchPlan persistence.
- Unsupported candidate state: `UNSUPPORTED_FILESYSTEM`.
- Stable reason/API code: `UTILITY_MOVE_UNSUPPORTED_FILESYSTEM`.
- Unsupported candidate is never selectable and cannot persist Draft/items.
- Native `rename_noreplace` execution path remains unchanged.
- Narrow empty-wrapper authority never enables `unlink`, purge, recursive delete, non-empty directory removal, or generic `rmdir_empty`.
- Amendment A recursive Last-File and reserved-Quarantine code paths are unchanged.

---

### Task 1: Zero-mutation native capability probe

**Files:**
- Modify: `app/fs_ops.py`
- Create: `tests/test_gate6b_utility_fs_capability.py`

**Produces:**
```python
probe_existing_noreplace_capability_at(dir_fd: int, entry_name: str) -> bool | None
```

- [ ] **Step 1: Add RED tests**

Create `tests/test_gate6b_utility_fs_capability.py` with these tests:

```python
from __future__ import annotations

import ctypes
import errno
import os

import app.fs_ops as fs_ops


def _open_dir(path):
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def test_probe_eexist_means_native_support_and_does_not_change_namespace(tmp_path, monkeypatch):
    child = tmp_path / "C"
    child.mkdir()
    before = os.lstat(child)

    def fake_rename_at(source_fd, source_name, target_fd, target_name):
        assert source_fd == target_fd
        assert source_name == b"C"
        assert target_name == b"C"
        ctypes.set_errno(errno.EEXIST)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    fd = _open_dir(tmp_path)
    try:
        result = fs_ops.probe_existing_noreplace_capability_at(fd, "C")
    finally:
        os.close(fd)

    after = os.lstat(child)
    assert result is True
    assert (after.st_dev, after.st_ino, after.st_mode) == (before.st_dev, before.st_ino, before.st_mode)
    assert [entry.name for entry in os.scandir(tmp_path)] == ["C"]


def test_probe_eopnotsupp_means_unsupported(tmp_path, monkeypatch):
    (tmp_path / "C").mkdir()

    def fake_rename_at(source_fd, source_name, target_fd, target_name):
        ctypes.set_errno(errno.EOPNOTSUPP)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    fd = _open_dir(tmp_path)
    try:
        result = fs_ops.probe_existing_noreplace_capability_at(fd, "C")
    finally:
        os.close(fd)
    assert result is False


def test_probe_unknown_errno_returns_none(tmp_path, monkeypatch):
    (tmp_path / "C").mkdir()

    def fake_rename_at(source_fd, source_name, target_fd, target_name):
        ctypes.set_errno(errno.EIO)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    fd = _open_dir(tmp_path)
    try:
        result = fs_ops.probe_existing_noreplace_capability_at(fd, "C")
    finally:
        os.close(fd)
    assert result is None
```

- [ ] **Step 2: Verify RED**

```bash
pytest -q tests/test_gate6b_utility_fs_capability.py
```

Expected: import/attribute failure because the new function is absent.

- [ ] **Step 3: Implement minimal probe**

In `app/fs_ops.py`, add the function to `__all__` and add:

```python
def probe_existing_noreplace_capability_at(dir_fd: int, entry_name: str) -> bool | None:
    if _RENAME_AT_IMPL is None:
        return False
    try:
        before = os.stat(entry_name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return None

    ctypes.set_errno(0)
    result = _RENAME_AT_IMPL(
        dir_fd,
        os.fsencode(entry_name),
        dir_fd,
        os.fsencode(entry_name),
    )
    if result == 0:
        try:
            after = os.stat(entry_name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError:
            return None
        before_identity = (before.st_dev, before.st_ino, stat.S_IFMT(before.st_mode))
        after_identity = (after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode))
        return True if after_identity == before_identity else None

    err = ctypes.get_errno()
    if err in (errno.EEXIST, errno.ENOTEMPTY):
        return True
    if err in (
        errno.ENOSYS,
        errno.EOPNOTSUPP,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
    ):
        return False
    return None
```

- [ ] **Step 4: Verify GREEN**

```bash
pytest -q tests/test_gate6b_utility_fs_capability.py
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add app/fs_ops.py tests/test_gate6b_utility_fs_capability.py
git commit -m "test: add zero-mutation utility capability probe"
```

---

### Task 2: Preview classification + Generate zero-Draft rejection

**Files:**
- Modify: `app/batch_utilities/single_child_wrapper.py`
- Modify: `app/workflows/compiler.py`
- Modify: `tests/test_gate6b_utility_discovery.py`
- Modify: `tests/test_gate6b_utility_preview_compile.py`
- Modify: `tests/test_gate6b_utility_generate.py`
- Modify: `tests/test_gate6b_utility_api.py`

**Produces:** candidate fields `state`, `selectable`, and `capability_reason` with unsupported state/reason frozen by Amendment B.

- [ ] **Step 1: Add RED discovery test**

Add this exact behavior to `tests/test_gate6b_utility_discovery.py` using the repository's existing discovery fixture/helpers:

```python
def test_native_noreplace_unsupported_turns_valid_topology_into_nonselectable_candidate(tmp_path, monkeypatch):
    root = tmp_path / "root"
    scope = root / "A"
    (scope / "B" / "C").mkdir(parents=True)
    monkeypatch.setattr(
        "app.batch_utilities.single_child_wrapper.probe_existing_noreplace_capability_at",
        lambda dir_fd, entry_name: False,
        raising=False,
    )

    rows = discover_single_child_wrappers(str(scope), str(root))
    assert len(rows) == 1
    assert rows[0].state == "UNSUPPORTED_FILESYSTEM"
    assert rows[0].selectable is False
    assert rows[0].capability_reason == "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
```

Add a second case where the monkeypatch returns `None`; expected state/reason are identical. Update existing READY tests to monkeypatch the probe to return `True` so the test intent is independent of the CI filesystem.

- [ ] **Step 2: Add RED Preview/Generate assertions**

In Preview tests assert:

```python
candidate = preview["utility_summary"]["candidates"][0]
assert candidate["state"] == "UNSUPPORTED_FILESYSTEM"
assert candidate["selectable"] is False
assert candidate["selected"] is False
assert candidate["capability_reason"] == "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
assert preview["utility_summary"]["ready_count"] == 0
assert preview["utility_summary"]["selected_candidate_ids"] == []
assert preview["planned_operations_count"] == 0
```

In Generate tests capture DB counts immediately before the request and assert forced selection raises `WorkflowValidationError` with code `UTILITY_MOVE_UNSUPPORTED_FILESYSTEM`, then assert both counts are unchanged.

- [ ] **Step 3: Verify RED**

```bash
pytest -q \
  tests/test_gate6b_utility_discovery.py \
  tests/test_gate6b_utility_preview_compile.py \
  tests/test_gate6b_utility_generate.py \
  tests/test_gate6b_utility_api.py
```

Expected: new unsupported-capability assertions fail.

- [ ] **Step 4: Extend decision model and identity binding**

In `SingleChildWrapperDecision` add:

```python
capability_reason: str | None = None
```

Import:

```python
from app.fs_ops import probe_existing_noreplace_capability_at
```

Extend `_decision()` with a `capability_reason` argument and pass it into the dataclass. In `discover_single_child_wrappers()`, preserve current symlink/special/target collision precedence. Only in the branch that would otherwise set `READY`, execute:

```python
capability_reason = None
if int(child_st.st_dev) != int(scope_st.st_dev):
    state = "UNSUPPORTED_FILESYSTEM"
    capability_reason = "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
else:
    native_noreplace = probe_existing_noreplace_capability_at(wrapper_fd, child.name)
    if native_noreplace is True:
        state = "READY"
    else:
        state = "UNSUPPORTED_FILESYSTEM"
        capability_reason = "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
```

Pass `capability_reason` into `_decision()` and include it in compiler `identity_rows` and `candidate_rows`. Because `selectable` is still exactly `state == "READY"`, unsupported candidates produce zero planned operations during Preview.

- [ ] **Step 5: Add explicit unsupported Generate rejection**

In `_compile_utility_workflow()`, after unknown candidate-id rejection and before generic non-READY rejection:

```python
unsupported_ids = [
    candidate_id
    for candidate_id in selected_candidate_ids or []
    if candidate_id in decision_by_id
    and decision_by_id[candidate_id].state == "UNSUPPORTED_FILESYSTEM"
]
if unsupported_ids:
    raise WorkflowValidationError(
        "Utility MOVE is unsupported on this filesystem",
        code="UTILITY_MOVE_UNSUPPORTED_FILESYSTEM",
        status_code=422,
        details={"candidate_ids": unsupported_ids},
    )
```

This occurs inside the existing Phase-A recompile, before `generate_plan()` persists a `BatchPlan`.

- [ ] **Step 6: Verify GREEN**

```bash
pytest -q \
  tests/test_gate6b_utility_discovery.py \
  tests/test_gate6b_utility_preview_compile.py \
  tests/test_gate6b_utility_generate.py \
  tests/test_gate6b_utility_api.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add \
  app/batch_utilities/single_child_wrapper.py \
  app/workflows/compiler.py \
  tests/test_gate6b_utility_discovery.py \
  tests/test_gate6b_utility_preview_compile.py \
  tests/test_gate6b_utility_generate.py \
  tests/test_gate6b_utility_api.py
git commit -m "fix: fail closed unsupported utility filesystems at preview"
```

---

### Task 3: Narrow paired empty-wrapper cleanup authority

**Files:**
- Modify: `app/execution/executor.py`
- Modify: `tests/test_gate6b_utility_execution_safety.py`

**Produces:** private resolver `_resolve_utility_empty_wrapper_cleanup_authority()`; no public API change.

- [ ] **Step 1: Add RED authorization tests**

Extend the existing Utility execution fixture so the generated Plan is frozen and validated, then load both DB rows. In the positive test, mark the MOVE row `completed` exactly as the real Worker would after successful native MOVE, ensure the wrapper is physically empty, and call `execute_item()` for the paired `rmdir_empty` with `allow_delete=False`, `session_factory=service.SessionLocal`, and the exact numeric plan id. Assert the result is `completed` and the source wrapper path no longer exists.

Add negative tests that each call `execute_item(... allow_delete=False ...)` and assert `skipped / permanent deletion is disabled` for:

```text
rmdir_empty with no session_factory
rmdir_empty under a non-workflow plan
rmdir_empty when predecessor MOVE is not completed
rmdir_empty with different candidate_id than predecessor
unlink under the same Utility plan
```

Keep the existing third-party-child test and run it through the same narrow-authority path; the new child must survive and the wrapper must remain.

- [ ] **Step 2: Verify RED**

```bash
pytest -q tests/test_gate6b_utility_execution_safety.py
```

Expected: positive `ALLOW_DELETE=false` paired-cleanup case is skipped before the `rmdir_empty` primitive.

- [ ] **Step 3: Implement DB-backed exact authority resolver**

Add this signature above `execute_item()`:

```python
def _resolve_utility_empty_wrapper_cleanup_authority(
    item: OperationItem,
    *,
    plan_id: str,
    session_factory: Any,
) -> bool:
```

The resolver must return `False` unless all checks pass:

```text
plan_id parses to int
BatchPlan exists
plan metadata parses as dict
metadata.source == workflow
metadata.workflow_mode == utility
metadata.compile_context.utility_action == single_child_wrapper_collapse
current BatchPlanItem exists uniquely at item.sequence
current.operation == rmdir_empty
current.source_path == item.source
current.expected_device == item.expected_device
current.expected_inode == item.expected_inode
current metadata candidate_id is nonempty
current metadata wrapper_path == current.source_path
preceding item sequence == current.sequence - 1
preceding.operation == move
preceding.state == completed
preceding metadata candidate_id == current candidate_id
preceding metadata wrapper_path == current wrapper_path
preceding metadata target_path == current metadata target_path
```

Use `select(BatchPlanItem)` rather than live filesystem inference. Any parse/missing/mismatch returns `False`.

- [ ] **Step 4: Narrow the broad delete gate**

Immediately after the `allow_mutation` check:

```python
utility_empty_cleanup_authorized = False
if item.operation == "rmdir_empty" and not allow_delete and session_factory is not None:
    utility_empty_cleanup_authorized = _resolve_utility_empty_wrapper_cleanup_authority(
        item,
        plan_id=plan_id,
        session_factory=session_factory,
    )

if (
    item.operation in {"unlink", "rmdir_empty", "quarantine_purge", "quarantine_unlink_purge"}
    and not allow_delete
    and not utility_empty_cleanup_authorized
):
    return _skip("permanent deletion is disabled")
```

Do not modify the later reserved-Quarantine, symlink, directory-type, expected dev/inode, or physically-empty checks and do not add any `unlink`/recursive-delete primitive.

- [ ] **Step 5: Verify GREEN**

```bash
pytest -q tests/test_gate6b_utility_execution_safety.py
```

Expected: positive pair passes; every unrelated delete case remains blocked; third-party object survives.

- [ ] **Step 6: Commit**

```bash
git add app/execution/executor.py tests/test_gate6b_utility_execution_safety.py
git commit -m "fix: narrowly authorize utility empty-wrapper cleanup"
```

---

### Task 4: Frontend truthfulness and full verification

**Files:**
- Modify: `frontend/src/types/workflow.ts`
- Modify: `frontend/src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx`
- Modify: `frontend/tests/gate6b_frontend.test.ts`
- Evidence: PR #10 exact-candidate handoff

- [ ] **Step 1: Add RED frontend assertions**

Extend the Gate6-B frontend fixture with:

```ts
const unsupportedCandidate = {
  candidate_id: 'a'.repeat(64),
  wrapper_path: '/data/utility/A/B',
  child_path: '/data/utility/A/B/C',
  target_path: '/data/utility/A/C',
  state: 'UNSUPPORTED_FILESYSTEM',
  selectable: false,
  selected: false,
  capability_reason: 'UTILITY_MOVE_UNSUPPORTED_FILESYSTEM',
};
```

Assert the state renders as non-selectable, an explicit unsupported-filesystem warning is present, and Generate is disabled when `selectedCandidateIds.length === 0`.

- [ ] **Step 2: Extend transport type**

In `WorkflowUtilityCandidate` add:

```ts
capability_reason?: string | null;
```

- [ ] **Step 3: Render warning and prevent empty unsupported Generate**

In `UtilityWorkflowPreviewPanel.tsx` derive:

```ts
const unsupportedCandidates = candidates.filter(
  (candidate) =>
    candidate.state === 'UNSUPPORTED_FILESYSTEM' ||
    candidate.capability_reason === 'UTILITY_MOVE_UNSUPPORTED_FILESYSTEM'
);
```

Add `selectedCandidateIds.length > 0` to `canDraft`. Render an `Alert` when `unsupportedCandidates.length > 0` stating that topology discovery is read-only, strict no-overwrite MOVE is unsupported on the current filesystem in Gate6-B, and no compatibility rename fallback will be attempted.

- [ ] **Step 4: Run frontend verification**

```bash
cd frontend
npm test
npm run typecheck
npm run build
```

Expected: all pass.

- [ ] **Step 5: Run backend focused + preserved recursive regressions**

```bash
pytest -q \
  tests/test_gate6b_utility_fs_capability.py \
  tests/test_gate6b_utility_discovery.py \
  tests/test_gate6b_utility_preview_compile.py \
  tests/test_gate6b_utility_generate.py \
  tests/test_gate6b_utility_api.py \
  tests/test_gate6b_utility_execution_safety.py \
  tests/test_gate6b_recursive_dirbal_amendment_a_lifecycle.py \
  tests/test_gate6b_recursive_dirbal_execute_preflight.py \
  tests/test_gate6b_recursive_dirbal_freeze_validate.py \
  tests/test_gate6b_recursive_protection_reader.py
```

Expected: all pass.

- [ ] **Step 6: Run full backend**

```bash
pytest -q
```

Expected: pass.

- [ ] **Step 7: Commit frontend changes**

```bash
git add frontend/src/types/workflow.ts frontend/src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx frontend/tests/gate6b_frontend.test.ts
git commit -m "feat: surface unsupported utility filesystem state"
```

- [ ] **Step 8: Reset exact-candidate authority**

Record the new HEAD. Coordinator Source Review must inspect baseline→new HEAD and the Amendment-B-only diff. Then create a new Independent Review handoff for that exact SHA, followed by new linux/amd64 Docker evidence and affected real-NAS acceptance.

Required target-zfuse NAS terminal evidence:

```text
candidate state = UNSUPPORTED_FILESYSTEM
selectable = false
capability_reason = UTILITY_MOVE_UNSUPPORTED_FILESYSTEM
selected_candidate_ids = []
forced Generate = HTTP 422 / UTILITY_MOVE_UNSUPPORTED_FILESYSTEM
BatchPlan delta = 0
BatchPlanItem delta = 0
A/B/C source SHA + device/inode unchanged
A/C target absent
A/B wrapper present
OperationJournal delta = 0
production container IDs unchanged
```

Native-filesystem regression must still prove READY → Generate → Freeze → Validate → Worker MOVE → paired empty-wrapper cleanup under `ALLOW_DELETE=false`.
