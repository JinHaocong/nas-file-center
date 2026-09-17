# Gate6-B Amendment B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Gate6-B Utility truthfully fail closed at Preview on COMPAT/zfuse filesystems that lack native atomic no-replace rename, while preserving native Utility execution and allowing only the exact paired verified-empty wrapper cleanup under global `ALLOW_DELETE=false`.

**Architecture:** Add a non-mutating native `RENAME_NOREPLACE` capability probe that uses an existing directory binding with source==target, then bind that capability into Single-Child Wrapper discovery. Unsupported COMPAT candidates remain explainable but become `UNSUPPORTED_FILESYSTEM`, `selectable=false`, and cannot produce a Draft. Keep the executor's strict native MOVE unchanged. Separately add an executor-side narrow authority resolver for the paired Utility `rmdir_empty` item so global delete disablement does not suppress structural wrapper cleanup, without widening unrelated delete authority.

**Tech Stack:** Python 3, FastAPI/service layer, SQLAlchemy, pytest, Linux `renameat2`, React + TypeScript + Ant Design, existing GitHub Actions Gate6-B workflow.

**Spec:** `docs/superpowers/specs/2026-09-16-gate6b-utility-zfuse-deferral-amendment-b.md` (frozen by `docs/superpowers/specs/2026-09-16-gate6b-utility-zfuse-deferral-amendment-b-approval.md`)

## Global Constraints

- Canonical baseline remains `main@7d9e248dae25d706d65a36bc864fb86f9a613d4d`.
- Pre-Amendment-B exact candidate `fb120bfe2a760c1294c0ed650f95988dac1410ce` is historical evidence only.
- No ordinary `rename()` fallback is authorized for Utility MOVE on COMPAT/zfuse.
- Preview must perform zero filesystem mutation and zero BatchPlan persistence.
- Unsupported COMPAT candidate state is `UNSUPPORTED_FILESYSTEM`, `selectable=false`, stable code/reason `UTILITY_MOVE_UNSUPPORTED_FILESYSTEM`.
- Forced Generate of an unsupported candidate must return an explicit rejection and persist zero Draft/items.
- Native strict `RENAME_NOREPLACE` execution behavior remains unchanged.
- Utility paired empty-wrapper cleanup may bypass global `ALLOW_DELETE=false` only with exact frozen Utility authority; generic `rmdir_empty`, `unlink`, purge, and recursive deletion remain blocked.
- No second Worker/executor and no new recursive directory-migration subsystem.
- Amendment A recursive Last-File and reserved Quarantine semantics remain unchanged.
- Real zfuse Utility acceptance for Gate6-B proves truthful unsupported behavior, not successful wrapper mutation.

---

### Task 1: Add a zero-mutation native no-replace capability probe

**Files:**
- Modify: `app/fs_ops.py`
- Create/Test: `tests/test_gate6b_utility_fs_capability.py`

**Interfaces:**
- Produces: `probe_existing_noreplace_capability_at(dir_fd: int, entry_name: str) -> bool | None`
- Meaning: `True` = native atomic no-replace positively supported; `False` = filesystem positively rejects the capability; `None` = cannot safely determine, fail closed at Utility layer.

- [ ] **Step 1: Write RED tests for native support, unsupported errno, and zero namespace mutation**

```python
from __future__ import annotations

import ctypes
import errno
import os

import app.fs_ops as fs_ops


def test_existing_binding_probe_treats_eexist_as_native_support(tmp_path, monkeypatch):
    child = tmp_path / "C"
    child.mkdir()
    before = os.lstat(child)

    def fake_rename_at(sfd, src, dfd, dst):
        assert src == b"C"
        assert dst == b"C"
        ctypes.set_errno(errno.EEXIST)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert fs_ops.probe_existing_noreplace_capability_at(fd, "C") is True
    finally:
        os.close(fd)

    after = os.lstat(child)
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["C"]


def test_existing_binding_probe_treats_eopnotsupp_as_unsupported(tmp_path, monkeypatch):
    (tmp_path / "C").mkdir()

    def fake_rename_at(*_args):
        ctypes.set_errno(errno.EOPNOTSUPP)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert fs_ops.probe_existing_noreplace_capability_at(fd, "C") is False
    finally:
        os.close(fd)


def test_existing_binding_probe_unknown_error_fails_closed(tmp_path, monkeypatch):
    (tmp_path / "C").mkdir()

    def fake_rename_at(*_args):
        ctypes.set_errno(errno.EIO)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_AT_IMPL", fake_rename_at)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert fs_ops.probe_existing_noreplace_capability_at(fd, "C") is None
    finally:
        os.close(fd)
```

- [ ] **Step 2: Run the RED tests**

Run:
```bash
pytest -q tests/test_gate6b_utility_fs_capability.py
```
Expected: FAIL because `probe_existing_noreplace_capability_at` does not exist.

- [ ] **Step 3: Implement the non-mutating probe**

Add to `app/fs_ops.py` and export it:

```python
def probe_existing_noreplace_capability_at(dir_fd: int, entry_name: str) -> bool | None:
    """Probe native NOREPLACE support without creating, removing, or moving a pathname.

    The syscall uses the same existing binding as both source and destination.
    A conforming native implementation reports EEXIST/ENOTEMPTY (or a no-op
    success); unsupported flag handling reports ENOSYS/EOPNOTSUPP/ENOTSUP.
    Unknown results fail closed.
    """
    if _RENAME_AT_IMPL is None:
        return False

    try:
        before = os.stat(entry_name, dir_fd=dir_fd, follow_symlinks=False)
    except OSError:
        return None

    ctypes.set_errno(0)
    res = _RENAME_AT_IMPL(
        dir_fd,
        os.fsencode(entry_name),
        dir_fd,
        os.fsencode(entry_name),
    )
    if res == 0:
        try:
            after = os.stat(entry_name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError:
            return None
        if (after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode)) != (
            before.st_dev,
            before.st_ino,
            stat.S_IFMT(before.st_mode),
        ):
            return None
        return True

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

Do **not** call `_probe_rename_noreplace_supported()` from Utility Preview because that legacy probe creates disposable files.

- [ ] **Step 4: Run the focused capability tests**

Run:
```bash
pytest -q tests/test_gate6b_utility_fs_capability.py
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/fs_ops.py tests/test_gate6b_utility_fs_capability.py
git commit -m "test: define zero-mutation utility move capability probe"
```

---

### Task 2: Bind filesystem capability into Utility discovery and Preview

**Files:**
- Modify: `app/batch_utilities/single_child_wrapper.py`
- Modify: `app/workflows/compiler.py`
- Modify/Test: `tests/test_gate6b_utility_discovery.py`
- Modify/Test: `tests/test_gate6b_utility_preview_compile.py`

**Interfaces:**
- `SingleChildWrapperDecision.state`: adds `UNSUPPORTED_FILESYSTEM`.
- `SingleChildWrapperDecision.selectable`: remains `state == "READY"`.
- Candidate row: adds `capability_reason: str | None`; unsupported candidates use `UTILITY_MOVE_UNSUPPORTED_FILESYSTEM`.

- [ ] **Step 1: Write RED discovery tests that force unsupported/native probe results**

Add tests that monkeypatch `app.batch_utilities.single_child_wrapper.probe_existing_noreplace_capability_at`:

```python
def test_valid_topology_is_nonselectable_when_native_noreplace_is_unsupported(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "A" / "B" / "C").mkdir(parents=True)
    monkeypatch.setattr(
        "app.batch_utilities.single_child_wrapper.probe_existing_noreplace_capability_at",
        lambda *_a, **_k: False,
    )

    rows = discover_single_child_wrappers(str(root / "A"), str(root))
    assert len(rows) == 1
    assert rows[0].state == "UNSUPPORTED_FILESYSTEM"
    assert rows[0].selectable is False
    assert rows[0].capability_reason == "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"


def test_valid_topology_remains_ready_when_native_noreplace_is_supported(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "A" / "B" / "C").mkdir(parents=True)
    monkeypatch.setattr(
        "app.batch_utilities.single_child_wrapper.probe_existing_noreplace_capability_at",
        lambda *_a, **_k: True,
    )

    rows = discover_single_child_wrappers(str(root / "A"), str(root))
    assert rows[0].state == "READY"
    assert rows[0].selectable is True
    assert rows[0].capability_reason is None
```

Also assert capability `None` fails closed as `UNSUPPORTED_FILESYSTEM`.

- [ ] **Step 2: Run RED discovery tests**

Run:
```bash
pytest -q tests/test_gate6b_utility_discovery.py tests/test_gate6b_utility_preview_compile.py
```
Expected: FAIL because capability is not yet part of the decision model.

- [ ] **Step 3: Extend discovery without weakening existing topology checks**

Update the decision dataclass:

```python
@dataclass(frozen=True)
class SingleChildWrapperDecision:
    ...
    capability_reason: str | None = None
```

Import the new probe:

```python
from app.fs_ops import probe_existing_noreplace_capability_at
```

Inside the existing wrapper-fd block, only after the child is proven to be a real directory and target is absent:

```python
if child_st.st_dev != scope_st.st_dev:
    state = "UNSUPPORTED_FILESYSTEM"
    capability_reason = "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
else:
    native_capability = probe_existing_noreplace_capability_at(wrapper_fd, child.name)
    if native_capability is True:
        state = "READY"
        capability_reason = None
    else:
        state = "UNSUPPORTED_FILESYSTEM"
        capability_reason = "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
```

Keep symlink/special/target-exists states higher priority than capability classification. Include `capability_reason` in candidate identity/digest rows so Preview→Generate identity binds the capability decision.

- [ ] **Step 4: Expose the reason in compiler Preview rows**

In `app/workflows/compiler.py`, include:

```python
"capability_reason": decision.capability_reason,
```

in both `identity_rows` and `candidate_rows`. `default_selected_ids` continues to use `decision.selectable`, so unsupported candidates default unselected and generate zero planned operations.

- [ ] **Step 5: Run discovery/Preview tests**

Run:
```bash
pytest -q \
  tests/test_gate6b_utility_discovery.py \
  tests/test_gate6b_utility_preview_compile.py
```
Expected: PASS, including legacy READY/collision/symlink cases under a mocked native-capable filesystem.

- [ ] **Step 6: Commit**

```bash
git add app/batch_utilities/single_child_wrapper.py app/workflows/compiler.py tests/test_gate6b_utility_discovery.py tests/test_gate6b_utility_preview_compile.py
git commit -m "feat: expose unsupported utility move capability at preview"
```

---

### Task 3: Reject unsupported Utility Generate with zero Draft persistence

**Files:**
- Modify: `app/workflows/compiler.py`
- Modify: `app/workflows/service.py`
- Modify/Test: `tests/test_gate6b_utility_generate.py`
- Modify/Test: `tests/test_gate6b_utility_api.py`

**Interfaces:**
- Stable API error code: `UTILITY_MOVE_UNSUPPORTED_FILESYSTEM`.
- Forced selection of a current unsupported candidate returns HTTP 422 and creates zero `BatchPlan` / zero `BatchPlanItem` rows.

- [ ] **Step 1: Write RED service and API tests**

Core assertion:

```python
before_plan_count = session.scalar(select(func.count(BatchPlan.id)))
before_item_count = session.scalar(select(func.count(BatchPlanItem.id)))

with pytest.raises(WorkflowValidationError) as exc:
    service.workflow_service.generate_plan(
        None,
        workflow_id,
        WorkflowGeneratePlanRequest(
            expected_compile_digest=preview["compile_digest"],
            selected_candidate_ids=[unsupported["candidate_id"]],
        ),
    )

assert exc.value.code == "UTILITY_MOVE_UNSUPPORTED_FILESYSTEM"
assert current_plan_count() == before_plan_count
assert current_item_count() == before_item_count
```

API test must assert HTTP 422 and response error code `UTILITY_MOVE_UNSUPPORTED_FILESYSTEM`.

- [ ] **Step 2: Run RED Generate/API tests**

Run:
```bash
pytest -q tests/test_gate6b_utility_generate.py tests/test_gate6b_utility_api.py
```
Expected: FAIL because current compiler maps every non-selectable current candidate to generic Preview mismatch.

- [ ] **Step 3: Add explicit current-preview unsupported rejection before generic not-ready handling**

In `_compile_utility_workflow`:

```python
unsupported_ids = [
    candidate_id
    for candidate_id in selected_candidate_ids
    if decision_by_id[candidate_id].state == "UNSUPPORTED_FILESYSTEM"
]
if unsupported_ids:
    raise WorkflowValidationError(
        "Utility MOVE is unsupported on this filesystem",
        code="UTILITY_MOVE_UNSUPPORTED_FILESYSTEM",
        status_code=422,
        details={"candidate_ids": unsupported_ids},
    )
```

This executes during Phase A read-only recompile, before `generate_plan()` enters persistence Phase B. Preserve `PREVIEW_CHANGED` for identities/states that actually changed between Preview and Generate.

- [ ] **Step 4: Run Generate/API tests and verify zero Draft**

Run:
```bash
pytest -q tests/test_gate6b_utility_generate.py tests/test_gate6b_utility_api.py
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/workflows/compiler.py app/workflows/service.py tests/test_gate6b_utility_generate.py tests/test_gate6b_utility_api.py
git commit -m "fix: reject unsupported utility move before draft persistence"
```

---

### Task 4: Add narrow paired Utility empty-wrapper cleanup authority

**Files:**
- Modify: `app/execution/executor.py`
- Modify: `app/tasks/handlers_base.py` only if the executor needs the existing Worker session/plan context passed explicitly
- Modify/Test: `tests/test_gate6b_utility_execution_safety.py`

**Interfaces:**
- Private helper: `_resolve_utility_empty_wrapper_cleanup_authority(item, *, plan_id, session_factory) -> tuple[bool, str | None]`.
- Authority is true only for the exact frozen/executing Utility `rmdir_empty` row whose preceding same-candidate MOVE row is already `completed`.

- [ ] **Step 1: Write RED tests for the allowed exact pair and blocked unrelated deletes**

Add cases:

```python
def test_paired_utility_empty_wrapper_cleanup_can_run_with_allow_delete_false(...):
    # Build native-capable Utility Plan, Freeze, Validate.
    # Mark/execute MOVE successfully first through the real plan execution path.
    # Execute paired rmdir_empty with allow_delete=False.
    assert result.state == "completed"
    assert not wrapper.exists()


def test_generic_rmdir_empty_stays_blocked_with_allow_delete_false(...):
    result = execute_item(
        unrelated_item,
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=quarantine,
        plan_id="999",
        session_factory=service.SessionLocal,
    )
    assert result.state == "skipped"
    assert result.reason == "permanent deletion is disabled"


def test_unlink_stays_blocked_with_allow_delete_false(...):
    ...
    assert result.reason == "permanent deletion is disabled"
```

Also add fail-closed tests for missing session authority, wrong plan kind/workflow mode, candidate-id mismatch, predecessor MOVE not completed, wrapper dev/inode change, and a third-party child appearing after MOVE.

- [ ] **Step 2: Run RED executor tests**

Run:
```bash
pytest -q tests/test_gate6b_utility_execution_safety.py
```
Expected: paired cleanup still SKIPPED under `ALLOW_DELETE=false`.

- [ ] **Step 3: Resolve narrow authority before the broad delete gate**

In `execute_item()` compute:

```python
utility_empty_cleanup_authorized = False
if item.operation == "rmdir_empty" and not allow_delete:
    utility_empty_cleanup_authorized, _authority_error = (
        _resolve_utility_empty_wrapper_cleanup_authority(
            item,
            plan_id=plan_id,
            session_factory=session_factory,
        )
    )

if (
    item.operation in {"unlink", "rmdir_empty", "quarantine_purge", "quarantine_unlink_purge"}
    and not allow_delete
    and not (item.operation == "rmdir_empty" and utility_empty_cleanup_authorized)
):
    return _skip("permanent deletion is disabled")
```

The resolver must load the exact `BatchPlan` and current `BatchPlanItem` by plan id + sequence, require:

```python
plan.kind.startswith("workflow-")
plan_metadata["source"] == "workflow"
plan_metadata["workflow_mode"] == "utility"
plan_metadata["compile_context"]["utility_action"] == "single_child_wrapper_collapse"
current.operation == "rmdir_empty"
current.source_path == str(item.source)
current.expected_device == item.expected_device
current.expected_inode == item.expected_inode
current metadata candidate_id is a nonempty string
preceding.sequence == current.sequence - 1
preceding.operation == "move"
preceding.state == "completed"
preceding metadata candidate_id == current candidate_id
preceding.target_path == current metadata target_path
current source == current metadata wrapper_path
```

Do not create a global setting and do not exempt `unlink` or purge.

- [ ] **Step 4: Preserve the existing runtime wrapper safety checks**

Do not bypass the current `rmdir_empty` checks for reserved Quarantine, symlink, directory type, expected dev/inode, or the existing empty-directory primitive. The narrow authority changes only the early global delete gate.

- [ ] **Step 5: Run executor safety tests**

Run:
```bash
pytest -q tests/test_gate6b_utility_execution_safety.py
```
Expected: PASS; generic delete behavior remains blocked.

- [ ] **Step 6: Commit**

```bash
git add app/execution/executor.py app/tasks/handlers_base.py tests/test_gate6b_utility_execution_safety.py
git commit -m "fix: authorize only paired utility empty-wrapper cleanup"
```

---

### Task 5: Make frontend capability state explicit and non-generatable

**Files:**
- Modify: `frontend/src/types/workflow.ts`
- Modify: `frontend/src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx`
- Modify/Test: `frontend/tests/gate6b_frontend.test.ts`

**Interfaces:**
- `WorkflowUtilityCandidate.capability_reason?: string | null`.
- UI must show `UNSUPPORTED_FILESYSTEM / 不可选` and an explicit warning for `UTILITY_MOVE_UNSUPPORTED_FILESYSTEM`.
- Generate button must not become an executable path when the current Preview has unsupported COMPAT candidates and no READY selection.

- [ ] **Step 1: Add RED frontend contract tests**

Test fixture:

```ts
const unsupported = {
  candidate_id: 'a'.repeat(64),
  wrapper_path: '/data/A/B',
  child_path: '/data/A/B/C',
  target_path: '/data/A/C',
  state: 'UNSUPPORTED_FILESYSTEM',
  selectable: false,
  selected: false,
  capability_reason: 'UTILITY_MOVE_UNSUPPORTED_FILESYSTEM',
};
```

Assert candidate checkbox is disabled, warning copy mentions unsupported filesystem/no mutation, and Generate is disabled when there is no READY selected candidate.

- [ ] **Step 2: Run RED frontend tests**

Run:
```bash
cd frontend && npm test -- --runInBand
```
Expected: new Amendment-B assertions fail.

- [ ] **Step 3: Extend TypeScript transport types**

```ts
export interface WorkflowUtilityCandidate {
  ...
  capability_reason?: string | null;
}
```

- [ ] **Step 4: Render truthful unsupported state**

In `UtilityWorkflowPreviewPanel.tsx`:

```ts
const unsupportedCandidates = candidates.filter(
  (candidate) => candidate.state === 'UNSUPPORTED_FILESYSTEM' ||
    candidate.capability_reason === 'UTILITY_MOVE_UNSUPPORTED_FILESYSTEM'
);

const canDraft = canGenerateDraft(isArchived)
  && !isDirty
  && Boolean(previewData?.compile_digest)
  && selectedCandidateIds.length > 0
  && !previewMutation.isPending
  && !generateMutation.isPending;
```

Render a warning Alert when `unsupportedCandidates.length > 0` explaining that topology discovery is read-only but this filesystem cannot execute the strict no-overwrite MOVE in Gate6-B; no compatibility rename fallback is used.

- [ ] **Step 5: Run frontend tests/typecheck/build**

Run:
```bash
cd frontend
npm test
npm run typecheck
npm run build
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/workflow.ts frontend/src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx frontend/tests/gate6b_frontend.test.ts
git commit -m "feat: show unsupported utility filesystem capability"
```

---

### Task 6: Full Gate6-B post-Amendment-B verification and handoff reset

**Files:**
- Modify if needed: `.github/workflows/gate6b-tdd.yml`
- Evidence only: PR #10 discussion / exact-candidate handoff

**Interfaces:**
- Produces one new exact candidate SHA after all code/tests are committed.
- Old `fb120bfe...` Independent Review and Docker results are historical only.

- [ ] **Step 1: Run focused backend Amendment-B matrix**

Run:
```bash
pytest -q \
  tests/test_gate6b_utility_fs_capability.py \
  tests/test_gate6b_utility_discovery.py \
  tests/test_gate6b_utility_preview_compile.py \
  tests/test_gate6b_utility_generate.py \
  tests/test_gate6b_utility_api.py \
  tests/test_gate6b_utility_execution_safety.py
```
Expected: all PASS.

- [ ] **Step 2: Run preserved Gate6-B recursive regression**

Run:
```bash
pytest -q \
  tests/test_gate6b_recursive_dirbal_amendment_a_lifecycle.py \
  tests/test_gate6b_recursive_dirbal_execute_preflight.py \
  tests/test_gate6b_recursive_dirbal_freeze_validate.py \
  tests/test_gate6b_recursive_protection_reader.py
```
Expected: all PASS.

- [ ] **Step 3: Run full backend regression**

Run:
```bash
pytest -q
```
Expected: PASS.

- [ ] **Step 4: Run frontend verification**

Run:
```bash
cd frontend
npm test
npm run typecheck
npm run build
```
Expected: PASS.

- [ ] **Step 5: Fresh-lock the new candidate SHA and verify PR identity**

Record:
```bash
git rev-parse HEAD
git diff --stat 7d9e248dae25d706d65a36bc864fb86f9a613d4d..HEAD
```
PR #10 HEAD must equal that exact SHA before review handoff.

- [ ] **Step 6: Coordinator Source Review**

Review baseline→new candidate and specifically verify:
- zero ordinary rename fallback;
- Preview capability probe has zero namespace mutation;
- unsupported candidate cannot produce Draft authority;
- empty-wrapper bypass is limited to exact paired Utility context;
- no change to Recursive Amendment A / reserved Quarantine authority;
- no widening of delete/purge authority.

- [ ] **Step 7: New Independent Review**

Create a fresh exact-candidate handoff. Reviewer must independently inspect Amendment B and the old real-NAS blocker disposition. Previous PASS on `fb120bfe...` is not inherited.

- [ ] **Step 8: New exact-candidate linux/amd64 Docker evidence**

Build/test the exact reviewed SHA on linux/amd64 and record image ID/platform.

- [ ] **Step 9: Target zfuse NAS acceptance — affected Utility scenario**

Required expected result on the isolated zfuse fixture:

```text
Preview candidate state=UNSUPPORTED_FILESYSTEM
selectable=false
capability_reason=UTILITY_MOVE_UNSUPPORTED_FILESYSTEM
selected_candidate_ids=[]
Generate forced candidate -> HTTP 422 UTILITY_MOVE_UNSUPPORTED_FILESYSTEM
BatchPlan count delta=0
BatchPlanItem count delta=0
source A/B/C present with unchanged SHA + dev/inode
A/C absent
wrapper A/B present
OperationJournal delta=0
production containers unchanged
```

No Utility filesystem mutation is attempted on zfuse in Gate6-B.

- [ ] **Step 10: Native-filesystem acceptance/regression**

Prove on a filesystem with positive native no-replace support:

```text
Preview READY
Generate Draft
Freeze
Validate
Worker Execute
MOVE completed
paired rmdir_empty completed with ALLOW_DELETE=false via narrow authority
payload identity/hash preserved
third-party-after-MOVE case preserves wrapper
```

- [ ] **Step 11: Gate decision**

Only after the renewed review/Docker/NAS evidence may Gate6-B be marked PASS/CLOSED. Actual zfuse Utility mutation remains Gate6-B2 and must not be claimed as delivered.
