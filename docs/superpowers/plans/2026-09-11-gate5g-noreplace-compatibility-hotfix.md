# Gate5-G NOREPLACE Compatibility Hotfix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make regular-file `rename`/`move`/`quarantine`/`restore` safely executable on 极空间 `zfuse.zfsv3` when `renameat2(RENAME_NOREPLACE)` is unsupported, without weakening no-overwrite, frozen-identity, crash-recovery, Worker-lease, or directory fail-closed guarantees.

**Architecture:** Preserve the native `RENAME_NOREPLACE` fast path. Only when native no-replace is explicitly unsupported, regular files use `link(source, target) -> durable LINKED marker -> frozen-evidence revalidation -> second Worker-lease fence -> unlink(source)`. Directory/symlink/special-object paths never use hard-link fallback and remain explicit fail-closed; crash recovery may finish only a durably marked, still-fresh linked transition.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.x, SQLite, pytest 8.x, Linux `renameat2`, POSIX hard links, React/Vite frontend regression only.

**Spec:** `docs/history/gate5g/Gate5-G-Noreplace-Compatibility-Hotfix-Architecture-Freeze-2026-09-11.md`

## Global Constraints

- Production baseline remains `6ab7e76b133cc03b02df4b3cb9ce7423cbdcb380`; the docs-only planning branch may be used as implementation base because it differs only by approved docs.
- Project priority is `数据安全 > 正确性 > 可恢复性 > 性能 > UI > 功能`.
- Target platform is 极空间 NAS / Linux amd64 / Docker / `zfuse.zfsv3`.
- Preserve `Preview -> Explicit Generate Draft -> Freeze -> Validate -> Execute`.
- Preview remains zero mutation.
- Gate3 remains the only physical-identity/SHA256 capture authority.
- Dedupe still quarantines; this hotfix introduces no permanent-delete behavior.
- No DB schema or migration change.
- No API request/response schema change.
- No frontend behavior change.
- No Docker/compose behavior change.
- No Worker protocol change.
- No Dedupe compiler or planning semantic change.
- No Gate5-E E4 directory architecture redesign.
- Production-code whitelist is exactly `app/fs_ops.py`, `app/execution/executor.py`, `app/tasks/handlers.py`, and `app/batch_utilities/empty_dir_quarantine.py`.
- A new focused test file may be created at `tests/test_gate5g_noreplace_compat.py`; existing safety tests may be extended only to protect already-frozen contracts.
- Native-capable filesystems must continue using native `RENAME_NOREPLACE`; do not route them through hard-link compatibility.
- Hard-link compatibility is regular-file-only.
- Unsupported directory no-replace remains explicit fail-closed with zero destructive mutation.
- Hash/evidence preparation must remain outside SQLite `BEGIN IMMEDIATE` write transactions.
- Worker lease must be valid before `link()` and revalidated after the durable LINKED marker and before `unlink(source)`.
- If `link()` succeeds but the LINKED marker is not durably committed before crash, recovery must preserve both names and report conflict; it must never guess ownership.
- Any production-code commit terminates evaluation of `6ab7e76...`, creates a new candidate, and requires Gate5-G G0 restart with a new image/tar.

---

## File Structure Lock

**Production files**

- `app/fs_ops.py`: classify unsupported native no-replace capability and provide a pure regular-file hard-link no-replace primitive. No DB knowledge.
- `app/execution/executor.py`: preserve path/integrity guards; signal internal compatibility-required state for regular files only; explicitly fail unsupported directories/special objects.
- `app/tasks/handlers.py`: own durable LINKED marker, live two-step orchestration, second lease fence, post-link frozen-evidence revalidation, and crash recovery.
- `app/batch_utilities/empty_dir_quarantine.py`: keep directory relocation/rollback algorithm unchanged and normalize unsupported no-replace into explicit fail-closed capability errors.

**Tests**

- Create `tests/test_gate5g_noreplace_compat.py`.
- Extend `tests/test_gate2_hotfix1_worker_fencing.py` for post-link lease loss.
- Extend `tests/test_gate2_hotfix2_reconciliation_identity.py` for linked-marker recovery identity cases.
- Extend `tests/test_gate5e_e4_hotfix2.py` for directory unsupported-capability zero-mutation assertions.

---

### Task 1: Add unsupported-capability classification and pure hard-link primitive

**Files:**
- Modify: `app/fs_ops.py`
- Create: `tests/test_gate5g_noreplace_compat.py`

**Interfaces:**
- Produces `class NoReplaceUnsupportedError(OSError)`.
- Produces `@dataclass(frozen=True) class HardlinkNoReplaceResult` with `device`, `inode`, `size`, `mtime_ns`.
- Produces `link_noreplace_regular_file(source, target, *, expected_device=None, expected_inode=None)`.
- `rename_noreplace()` and `rename_noreplace_at()` preserve current `FileExistsError`, `EXDEV`, `ENOENT`, and unrelated operational errors.
- Only `EINVAL`, `EOPNOTSUPP`/`ENOTSUP`, and `ENOSYS` map to unsupported capability.

- [ ] **Step 1: Write RED errno-classification tests**

Add tests that monkeypatch `_RENAME_IMPL` / `_RENAME_AT_IMPL`:

```python
@pytest.mark.parametrize("err", [errno.EINVAL, errno.EOPNOTSUPP, errno.ENOSYS])
def test_native_noreplace_unsupported_errno_is_classified(tmp_path, monkeypatch, err):
    import ctypes
    import app.fs_ops as fs_ops

    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.write_text("x")

    def unsupported(src_b, dst_b):
        ctypes.set_errno(err)
        return -1

    monkeypatch.setattr(fs_ops, "_RENAME_IMPL", unsupported)

    with pytest.raises(fs_ops.NoReplaceUnsupportedError) as exc:
        fs_ops.rename_noreplace(src, dst)

    assert exc.value.errno == err
    assert src.read_text() == "x"
    assert not dst.exists()
```

Add companion cases proving `EEXIST`, `EXDEV`, `EACCES`, `EROFS`, and `EIO` do **not** become `NoReplaceUnsupportedError`.

- [ ] **Step 2: Run RED classification tests**

```bash
python -m pytest tests/test_gate5g_noreplace_compat.py -k 'unsupported_errno or unrelated_errno' -v
```

Expected: FAIL because the dedicated exception does not exist yet.

- [ ] **Step 3: Implement minimal capability classification**

In `app/fs_ops.py` add:

```python
from dataclasses import dataclass
import stat

_UNSUPPORTED_NOREPLACE_ERRNOS = {errno.EINVAL, errno.EOPNOTSUPP, errno.ENOSYS}
if hasattr(errno, "ENOTSUP"):
    _UNSUPPORTED_NOREPLACE_ERRNOS.add(errno.ENOTSUP)

class NoReplaceUnsupportedError(OSError):
    """Filesystem/platform cannot provide strict native no-replace rename."""

@dataclass(frozen=True)
class HardlinkNoReplaceResult:
    device: int
    inode: int
    size: int
    mtime_ns: int
```

Both native wrappers must raise `NoReplaceUnsupportedError` only for the unsupported set. Missing native implementation also becomes `NoReplaceUnsupportedError(errno.ENOSYS, ...)`, not generic `NotImplementedError`.

- [ ] **Step 4: Run classification tests GREEN**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Write RED hard-link primitive tests**

```python
def test_link_noreplace_regular_file_creates_same_inode_without_unlink(tmp_path):
    from app.fs_ops import link_noreplace_regular_file

    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.bin"
    src.write_bytes(b"payload")
    st = src.stat(follow_symlinks=False)

    result = link_noreplace_regular_file(
        src,
        dst,
        expected_device=st.st_dev,
        expected_inode=st.st_ino,
    )

    assert src.exists()
    assert dst.exists()
    assert src.stat(follow_symlinks=False).st_ino == dst.stat(follow_symlinks=False).st_ino
    assert result.device == st.st_dev
    assert result.inode == st.st_ino
```

Also test target collision preserves both byte-for-byte, directory/symlink rejection, and expected device/inode mismatch produces zero target creation.

- [ ] **Step 6: Run RED primitive tests**

```bash
python -m pytest tests/test_gate5g_noreplace_compat.py -k 'link_noreplace_regular_file' -v
```

Expected: FAIL because the helper does not exist.

- [ ] **Step 7: Implement pure hard-link primitive**

Implement only target link creation and identity checks; never unlink source:

```python
def link_noreplace_regular_file(
    source: Path | str,
    target: Path | str,
    *,
    expected_device: int | None = None,
    expected_inode: int | None = None,
) -> HardlinkNoReplaceResult:
    src = Path(source)
    dst = Path(target)
    st_pre = os.lstat(src)
    if stat.S_ISLNK(st_pre.st_mode) or not stat.S_ISREG(st_pre.st_mode):
        raise ValueError("hard-link no-replace compatibility requires a regular file")
    if expected_device is not None and st_pre.st_dev != expected_device:
        raise ValueError("source device changed before hard-link transition")
    if expected_inode is not None and st_pre.st_ino != expected_inode:
        raise ValueError("source inode changed before hard-link transition")

    os.link(src, dst, follow_symlinks=False)

    st_src = os.lstat(src)
    st_dst = os.lstat(dst)
    if (
        st_src.st_dev != st_dst.st_dev
        or st_src.st_ino != st_dst.st_ino
        or st_src.st_dev != st_pre.st_dev
        or st_src.st_ino != st_pre.st_ino
    ):
        raise RuntimeError("hard-link transition identity mismatch; preserving both names")

    return HardlinkNoReplaceResult(
        device=st_src.st_dev,
        inode=st_src.st_ino,
        size=st_src.st_size,
        mtime_ns=getattr(st_src, "st_mtime_ns", int(st_src.st_mtime * 1e9)),
    )
```

Do not catch `EXDEV`.

- [ ] **Step 8: Run primitive + native regression GREEN**

```bash
python -m pytest tests/test_gate5g_noreplace_compat.py -k 'link_noreplace_regular_file or unsupported_errno or unrelated_errno' -v
python -m pytest tests/test_gate5e_e4_hotfix2.py -k 'rename_noreplace' -v
```

Expected: PASS.

- [ ] **Step 9: Commit Task 1**

```bash
git add app/fs_ops.py tests/test_gate5g_noreplace_compat.py
git commit -m "fix(fs): classify unsupported noreplace and add safe hardlink primitive"
```

---

### Task 2: Make executor signal compatibility-required without changing native behavior

**Files:**
- Modify: `app/execution/executor.py`
- Test: `tests/test_gate5g_noreplace_compat.py`
- Regression: `tests/test_execution.py`

**Interfaces:**
- Consumes `NoReplaceUnsupportedError`.
- Produces internal `ItemResult.state == "noreplace_compat_required"` for regular-file `rename`, `move`, `quarantine`, and `restore` only.
- `ItemResult.result_path` is the already-validated target path.
- Directory/symlink/special-object sources return failed state with an explicit atomic-no-replace capability reason.
- No DB or Worker-lease logic is added to executor.

- [ ] **Step 1: Write RED executor tests**

Representative case:

```python
def test_executor_regular_file_surfaces_compat_required(tmp_path, monkeypatch):
    from app.batch.plans import OperationItem
    import app.fs_ops as fs_ops
    from app.execution.executor import execute_item

    root = tmp_path / "root"
    root.mkdir()
    src = root / "src.txt"
    dst = root / "dst.txt"
    src.write_text("payload")

    def unsupported(*args, **kwargs):
        raise fs_ops.NoReplaceUnsupportedError(errno.EINVAL, "unsupported")

    monkeypatch.setattr(fs_ops, "rename_noreplace", unsupported)

    result = execute_item(
        OperationItem(1, "rename", src, target=dst),
        allowed_roots=[root],
        allow_mutation=True,
        allow_delete=False,
        quarantine_root=root / ".trash",
        plan_id="p1",
    )

    assert result.state == "noreplace_compat_required"
    assert result.result_path == dst
    assert src.exists()
    assert not dst.exists()
```

Add equivalent regular-file coverage for `move`, `quarantine`, and `restore`, plus a directory case that must return failed rather than compatibility-required.

- [ ] **Step 2: Run RED executor tests**

```bash
python -m pytest tests/test_gate5g_noreplace_compat.py -k 'executor_' -v
```

Expected: FAIL because unsupported capability is still converted to generic failed.

- [ ] **Step 3: Implement compatibility signaling**

Import `NoReplaceUnsupportedError` before generic `OSError` handling. Add a focused helper:

```python
def _noreplace_unsupported_result(source: Path, target: Path) -> ItemResult:
    st = os.lstat(source)
    if stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode):
        return ItemResult(
            "noreplace_compat_required",
            "native atomic no-replace is unsupported; regular-file compatibility required",
            target,
        )
    return ItemResult(
        "failed",
        "filesystem does not support atomic no-replace for this object type",
        source,
    )
```

Catch `NoReplaceUnsupportedError` separately in the native `rename`/`move`/`quarantine`/`restore` calls. Preserve all existing collision, EXDEV, path-safety, duplicate verification, restore integrity, and native success behavior.

- [ ] **Step 4: Run executor GREEN + regression**

```bash
python -m pytest tests/test_gate5g_noreplace_compat.py -k 'executor_' -v
python -m pytest tests/test_execution.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add app/execution/executor.py tests/test_gate5g_noreplace_compat.py
git commit -m "fix(execution): surface regular-file noreplace compatibility requirement"
```

---

### Task 3: Implement live LINKED transition with durable marker, fresh evidence, and second lease fence

**Files:**
- Modify: `app/tasks/handlers.py`
- Test: `tests/test_gate5g_noreplace_compat.py`
- Extend: `tests/test_gate2_hotfix1_worker_fencing.py`

**Interfaces:**
- Consumes `ItemResult.state == "noreplace_compat_required"` and `link_noreplace_regular_file()`.
- Produces durable marker under existing `BatchPlanItem.metadata_json.execution.noreplace_transition`.
- Does not duplicate Phase-3 journal/QuarantineEntry finalization; successful fallback must rejoin the existing normal completion path.

Durable marker shape is fixed as:

```json
{
  "version": 1,
  "strategy": "hardlink_unlink",
  "phase": "linked",
  "source": "/path/source",
  "target": "/path/target",
  "device": 1,
  "inode": 2,
  "size": 3,
  "mtime_ns": 4
}
```

- [ ] **Step 1: Write RED live quarantine test**

Force native no-replace unsupported, execute a Worker plan, and assert final source absent, quarantine target present, QuarantineEntry active, exactly one success journal, and a committed `phase == "linked"` marker.

Instrument source unlink so it asserts the marker is already committed before unlink is called.

- [ ] **Step 2: Run RED live-transition test**

```bash
python -m pytest tests/test_gate5g_noreplace_compat.py -k 'live_quarantine_linked_marker' -v
```

Expected: FAIL because the handler does not yet orchestrate fallback.

- [ ] **Step 3: Add internal marker helpers**

In `app/tasks/handlers.py` add:

```python
def _get_noreplace_transition(metadata_json: str | None) -> dict[str, Any] | None:
    meta = json.loads(metadata_json or "{}")
    execution = meta.get("execution") or {}
    transition = execution.get("noreplace_transition")
    return transition if isinstance(transition, dict) else None


def _build_linked_transition_marker(*, source: Path, target: Path, device: int, inode: int, size: int, mtime_ns: int) -> dict[str, Any]:
    return {
        "version": 1,
        "strategy": "hardlink_unlink",
        "phase": "linked",
        "source": str(source),
        "target": str(target),
        "device": device,
        "inode": inode,
        "size": size,
        "mtime_ns": mtime_ns,
    }
```

- [ ] **Step 4: Implement live compatibility orchestration immediately after `execute_item()`**

Only intercept `result.state == "noreplace_compat_required"`:

1. Require non-null logical target and regular non-symlink source.
2. Reassert/renew active Worker lease in a short `BEGIN IMMEDIATE` transaction.
3. Call `link_noreplace_regular_file(...)` outside DB lock, using frozen expected device/inode when nonzero.
4. Persist `execution.noreplace_transition.phase="linked"` in a short fenced write transaction and commit.
5. Outside write transaction, revalidate frozen operation evidence:
   - non-restore: call `_verify_plan_item_and_keep_freshness()` against a fresh DB row;
   - restore: call `verify_quarantine_source_integrity()` again with stored quarantine size/hash and `assert_source_unmodified()`;
   - source/target must remain regular non-symlinks with identical `st_dev/st_ino` equal to marker device/inode.
6. Reassert active Worker lease in another short `BEGIN IMMEDIATE`, renew `TaskLock.acquired_at`, commit.
7. Re-stat source/target immediately after the lease transaction; abort without unlink if identity changed.
8. `source.unlink()` outside DB lock.
9. Replace internal result with normal native-equivalent success: `moved`, `quarantined`, or `restored`, pointing at target.
10. Let existing Phase-3 finalization update row/journal/QuarantineEntry.

- [ ] **Step 5: Write and pass stale-after-link preservation test**

Mutate the source after marker commit but before unlink. Required state: both source and target preserved, same inode if the mutation was in-place, item non-success, zero success journal. The handler must not remove target as cleanup.

- [ ] **Step 6: Add second-lease-fence RED test**

Extend `tests/test_gate2_hotfix1_worker_fencing.py` so the old Worker loses `TaskLock.owner` after marker commit. Assert source and target both remain, same inode, and `unlink(source)` was never called.

- [ ] **Step 7: Run GREEN**

```bash
python -m pytest tests/test_gate2_hotfix1_worker_fencing.py -k 'after_link' -v
python -m pytest tests/test_gate5g_noreplace_compat.py -k 'live_' -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add app/tasks/handlers.py tests/test_gate5g_noreplace_compat.py tests/test_gate2_hotfix1_worker_fencing.py
git commit -m "fix(tasks): persist and fence hardlink noreplace transitions"
```

---

### Task 4: Add crash recovery for durably linked transitions without hashing under write lock

**Files:**
- Modify: `app/tasks/handlers.py`
- Test: `tests/test_gate5g_noreplace_compat.py`
- Extend: `tests/test_gate2_hotfix2_reconciliation_identity.py`
- Regression: `tests/test_gate2_hotfix4_reconciliation_evidence.py`
- Regression: `tests/test_gate2_hotfix5_freshness.py`

**Interfaces:**
- Recovery recognizes only `version=1`, `strategy=hardlink_unlink`, `phase=linked`.
- Any finishing `unlink(source)` occurs before the main reconciliation `BEGIN IMMEDIATE` transaction.
- Existing `_reconcile_executing_item()` remains responsible for DB-state/journal reconciliation after a safely completed filesystem transition.

- [ ] **Step 1: Write RED crash-window matrix**

Create explicit disk/DB states for:

```text
A. source+target same inode, no durable marker -> preserve both, conflict
B. source+target same inode, valid durable marker -> authoritative Worker may finish unlink then reconcile completed
C. source absent, target valid -> existing reconciliation completes
D. marker present, source/target different inode -> preserve both, conflict
E. both absent -> failed, no success journal
```

- [ ] **Step 2: Run RED crash tests**

```bash
python -m pytest tests/test_gate5g_noreplace_compat.py -k 'crash_window or linked_recovery' -v
```

Expected: valid durable-marker recovery fails initially because current code treats two-name state as conflict.

- [ ] **Step 3: Add outside-write-transaction recovery helper**

Add a helper with this interface:

```python
def _finish_durable_linked_transition_before_reconcile(
    *,
    context: JobContext,
    item: BatchPlanItem,
    settings: Settings,
) -> ReconcileEvidence | None:
    ...
```

Required behavior:

1. Return `None` unless the exact valid marker is present.
2. Marker source/target must match authoritative item paths for the operation.
3. If source absent and target present, return `gather_reconcile_evidence(target)` without mutation.
4. If both exist, both must be regular non-symlinks, same dev/inode, equal marker identity, and still satisfy frozen size/mtime/hash/integrity requirements.
5. Hash/evidence is gathered before any DB write lock.
6. Open short `BEGIN IMMEDIATE`, assert active Worker lease, renew lease timestamp, commit.
7. Re-stat source/target after the lease transaction; if identity changed, preserve both and return `None`.
8. Unlink source outside DB lock.
9. Return `gather_reconcile_evidence(target)` for normal existing reconciliation.

Any validation failure preserves data and returns `None`; existing both-names reconciliation marks conflict.

- [ ] **Step 4: Wire helper into `BatchPlanExecuteHandler.run()` reconciliation precompute**

For each executing item, run durable-linked recovery before the main reconciliation write transaction. If it returns target evidence, store it in existing `precomputed_evidence[item.id]`. Keep the existing source-absent quarantine/restore evidence path unchanged.

- [ ] **Step 5: Prove no hash under write lock**

Instrument `safe_quarantine_hash` using a concurrent `BEGIN IMMEDIATE` exactly as existing Gate2 tests do. Linked recovery must still pass.

- [ ] **Step 6: Prove idempotency**

Run recovery twice and assert exactly one `OperationJournal` for the item.

- [ ] **Step 7: Run recovery regressions**

```bash
python -m pytest tests/test_gate5g_noreplace_compat.py -k 'crash_window or linked_recovery' -v
python -m pytest tests/test_gate2_hotfix2_reconciliation_identity.py -v
python -m pytest tests/test_gate2_hotfix4_reconciliation_evidence.py -v
python -m pytest tests/test_gate2_hotfix5_freshness.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add app/tasks/handlers.py tests/test_gate5g_noreplace_compat.py tests/test_gate2_hotfix2_reconciliation_identity.py
git commit -m "fix(tasks): recover durable hardlink noreplace transitions"
```

---

### Task 5: Normalize unsupported directory behavior and preserve Gate5-E E4 architecture

**Files:**
- Modify: `app/batch_utilities/empty_dir_quarantine.py`
- Modify: `app/execution/executor.py`
- Extend: `tests/test_gate5e_e4_hotfix2.py`
- Test: `tests/test_gate5g_noreplace_compat.py`

**Interfaces:**
- Consumes `NoReplaceUnsupportedError`.
- Produces explicit failure reason containing `atomic no-replace unsupported`.
- Introduces no directory fallback.

- [ ] **Step 1: Write RED directory capability tests**

Monkeypatch `rename_noreplace_at` to raise `NoReplaceUnsupportedError(errno.EINVAL, "unsupported")` and assert empty-dir relocation leaves source intact, target absent, and result failed with explicit capability reason.

For `restore_empty_dir`, assert quarantine source remains and restore destination remains absent.

Also cover generic directory `rename`/`move`/`quarantine`/`restore` through `execute_item()`; none may return compatibility-required.

- [ ] **Step 2: Run RED directory tests**

```bash
python -m pytest tests/test_gate5e_e4_hotfix2.py -k 'unsupported' -v
python -m pytest tests/test_gate5g_noreplace_compat.py -k 'directory_' -v
```

Expected: FAIL until capability reason is normalized.

- [ ] **Step 3: Normalize unsupported directory errors without changing algorithm**

Catch `NoReplaceUnsupportedError` separately around empty-dir relocation and rollback. Initial relocation failure must return failed + explicit capability reason + zero mutation. If rollback itself is unsupported after an object was already moved, preserve it in quarantine exactly as current rollback-failure policy requires; never call plain `rename()`.

Ensure `restore_empty_dir` returns explicit failed state on unsupported capability and never falls back.

- [ ] **Step 4: Run directory GREEN + full E4 regression**

```bash
python -m pytest tests/test_gate5e_e4_hotfix2.py -v
python -m pytest tests/test_gate5e_e4_lifecycle.py -v
python -m pytest tests/test_gate5e_e4_recovery.py -v
python -m pytest tests/test_gate5e_e4_undo.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add app/batch_utilities/empty_dir_quarantine.py app/execution/executor.py tests/test_gate5e_e4_hotfix2.py tests/test_gate5g_noreplace_compat.py
git commit -m "fix(directory): fail closed when atomic noreplace is unsupported"
```

---

### Task 6: Complete operation coverage and adversarial race matrix

**Files:**
- Test: `tests/test_gate5g_noreplace_compat.py`
- Extend if needed: `tests/test_gate2_hotfix5_freshness.py`
- Production changes, only if a RED test exposes a real gap, must remain within the four-file whitelist.

- [ ] **Step 1: Parameterize normal compatibility coverage**

Use one test matrix over `rename`, `move`, `quarantine`, and `restore`. Each case must prove native was attempted first, fallback marker committed, source removed only after second lease fence, target bytes/hash preserved, exactly one success journal, and correct QuarantineEntry state where applicable.

- [ ] **Step 2: Parameterize collision coverage**

Pre-create target with sentinel bytes for all four operations. Assert source unchanged, target byte-for-byte unchanged, zero success journal, and no accidental overwrite.

- [ ] **Step 3: Add adversarial race coverage**

Separate tests for source inode change before link, source device mismatch, source size/mtime change after marker, expected-hash change in-place, target replacement, marker path mismatch, marker identity mismatch, and Worker lease loss after marker. No case may incorrectly unlink source.

- [ ] **Step 4: Prove native fast path never uses fallback**

Monkeypatch `link_noreplace_regular_file` to raise `AssertionError`, then run native-capable rename/quarantine/restore smoke cases. All must complete without fallback.

- [ ] **Step 5: Run focused compatibility suite**

```bash
python -m pytest tests/test_gate5g_noreplace_compat.py -v
```

Expected: PASS.

- [ ] **Step 6: Run Gate2/Gate3 safety regressions**

```bash
python -m pytest \
  tests/test_gate2_hotfix1_worker_fencing.py \
  tests/test_gate2_hotfix2_reconciliation_identity.py \
  tests/test_gate2_hotfix4_reconciliation_evidence.py \
  tests/test_gate2_hotfix5_freshness.py \
  tests/test_gate3_stale_plan.py -v
```

Expected: PASS.

- [ ] **Step 7: Refactor only hotfix duplication**

Permitted refactor targets are one marker parser/builder, one regular-file linked identity checker, and one lease-fence helper that exactly preserves existing semantics. Do not move unrelated code or split modules outside the whitelist.

- [ ] **Step 8: Re-run Step 5 and Step 6 after refactor**

Expected: PASS.

- [ ] **Step 9: Commit Task 6**

```bash
git add tests/test_gate5g_noreplace_compat.py tests/test_gate2_hotfix5_freshness.py app/fs_ops.py app/execution/executor.py app/tasks/handlers.py app/batch_utilities/empty_dir_quarantine.py
git commit -m "test(gate5g): cover noreplace compatibility races and operation matrix"
```

Only stage production files that actually changed in this task.

---

### Task 7: Run required focused, Gate5, full-backend, and frontend regression

**Files:** No production changes expected.

- [ ] **Step 1: Run focused NOREPLACE + execution suites**

```bash
python -m pytest \
  tests/test_gate5g_noreplace_compat.py \
  tests/test_execution.py \
  tests/test_quarantine_core.py \
  tests/test_quarantine_hardening.py \
  tests/test_gate2_hotfix1_worker_fencing.py \
  tests/test_gate2_hotfix2_reconciliation_identity.py \
  tests/test_gate2_hotfix4_reconciliation_evidence.py \
  tests/test_gate2_hotfix5_freshness.py \
  tests/test_gate3_stale_plan.py \
  tests/test_gate5e_e4_hotfix2.py \
  tests/test_gate5e_e4_lifecycle.py \
  tests/test_gate5e_e4_recovery.py \
  tests/test_gate5e_e4_undo.py -v
```

Expected: PASS.

- [ ] **Step 2: Run Gate5-D dedupe regression**

```bash
python -m pytest \
  tests/test_gate5d_dedupe_generate.py \
  tests/test_gate5d_dedupe_generate_api.py \
  tests/test_gate5d_dedupe_preview_api.py \
  tests/test_gate5d_d3_workflow_dedupe.py -v
```

Expected: PASS.

- [ ] **Step 3: Run Gate5 A-F focused regression**

```bash
python -m pytest tests/test_gate5*.py -v
```

Expected: PASS.

- [ ] **Step 4: Run full backend**

```bash
python -m pytest --disable-warnings -q
```

Expected: all tests pass; record the exact pass/warning counts verbatim in the walkthrough.

- [ ] **Step 5: Run frontend typecheck/tests/build**

```bash
cd frontend
npm run typecheck
npm test
npm run build
cd ..
```

Expected: all exit 0 and `frontend/dist/index.html` is non-empty.

- [ ] **Step 6: Confirm scope and worktree hygiene**

```bash
git diff --name-only 6ab7e76b133cc03b02df4b3cb9ce7423cbdcb380...HEAD
git diff --check
git status --short
```

Production files outside the four-file whitelist are forbidden. Worktree must be clean before packaging.

---

### Task 8: Produce new immutable candidate artifact and independent-review handoff

**Files:**
- Create: `docs/history/gate5g/Gate5-G-Noreplace-Compatibility-Hotfix-Walkthrough-2026-09-11.md`
- No additional production changes.

- [ ] **Step 1: Record immutable source identity**

```bash
REAL_HEAD="$(git rev-parse HEAD)"
SHORT_SHA="$(git rev-parse --short HEAD)"
git log -1 --oneline
git status --short
printf 'REAL_HEAD=%s\n' "$REAL_HEAD"
```

Expected: clean worktree and one exact SHA.

- [ ] **Step 2: Compare scope against failed candidate**

```bash
git diff --stat 6ab7e76b133cc03b02df4b3cb9ce7423cbdcb380..HEAD
git diff --name-only 6ab7e76b133cc03b02df4b3cb9ce7423cbdcb380..HEAD
```

Verify production changes are limited to the approved whitelist.

- [ ] **Step 3: Write walkthrough with verbatim evidence**

The walkthrough must record root cause, architecture compliance, modified production files, RED failure evidence, GREEN focused evidence, Gate2/Gate3/Gate5-E/Gate5-D results, full-backend result, frontend results, the known directory fail-closed limitation, `REAL_HEAD`, clean worktree state, and the rule that the new SHA restarts Gate5-G at G0.

- [ ] **Step 4: Create clean source ZIP**

```bash
CANDIDATE_ZIP="nas-file-center-v0.3.5-gate5g-noreplace-hotfix-${SHORT_SHA}.zip"
```

Build it from tracked files plus the approved walkthrough. Exclude `.git/`, `.pytest_cache/`, `__pycache__/`, `*.pyc`, `frontend/node_modules/`, `frontend/dist/`, coverage output, temporary DB/log/report files. Set ZIP comment to `REAL_HEAD`.

- [ ] **Step 5: Validate ZIP integrity and identity**

```bash
sha256sum "$CANDIDATE_ZIP"
CANDIDATE_ZIP="$CANDIDATE_ZIP" REAL_HEAD="$REAL_HEAD" python - <<'PY'
import os, zipfile
from pathlib import Path

p = Path(os.environ["CANDIDATE_ZIP"])
with zipfile.ZipFile(p) as z:
    assert z.testzip() is None
    assert z.comment.decode() == os.environ["REAL_HEAD"]
    print("ZIP_COMMENT =", z.comment.decode())
    print("ZIP_ENTRIES =", len(z.infolist()))
PY
```

Record the exact artifact path, SHA256, entry count, and ZIP comment in the walkthrough.

- [ ] **Step 6: Final implementation status**

The only allowed completion status before independent review is:

```text
NOREPLACE COMPATIBILITY HOTFIX IMPLEMENTATION COMPLETE
READY FOR INDEPENDENT REVIEW

Gate5-G = RESTART REQUIRED FROM G0 FOR NEW CANDIDATE
G8 = NOT AUTHORIZED
v0.3.5 = NOT CLOSED
```

Do not claim the hotfix candidate passes G0-G8 until the new immutable candidate is independently evaluated.

---

## Plan Self-Review Checklist

Before implementation starts, confirm every item below is satisfied by a task above:

- Unsupported errno classification is limited to `EINVAL`, `EOPNOTSUPP`/`ENOTSUP`, and `ENOSYS`.
- Native success/collision/EXDEV behavior stays unchanged.
- Hard-link fallback is regular-file-only.
- `link()` and `unlink()` are separated by a durable DB marker.
- Marker is committed before unlink.
- Frozen identity/hash is revalidated after link.
- Worker lease is revalidated after marker commit and before unlink.
- Crash after link but before marker preserves both names and fails closed.
- Durable linked crash state may be completed only by the authoritative Worker.
- Recovery evidence/hash remains outside SQLite write lock.
- Directory paths never fall back to plain rename/copy/delete.
- No schema/API/frontend/Docker/Worker-protocol/Dedupe-compiler changes.
- New candidate restarts Gate5-G at G0.
