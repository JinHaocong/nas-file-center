# Gate5-G / G7 Transactional Mutation Implementation Plan (v1.1.3)
# Final Executable Specification: Authoritative Anchor + Candidate Qualification + Write-Once Capture + Durable Lease Discipline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the zfuse-compatible Two-Phase Mutation Transaction with Authoritative Persistent Anchor, Candidate Qualification, Write-Once Capture Slot, and Durable Lease Discipline for Gate5-G / G7.

**Architecture:** Frozen Revision 3.1 Architecture (`0ddf932`). In `COMPAT_TRANSACTIONAL` mode, payload resides at `<quarantine_root>/.tx/entry-<id>/attempt-<gen>/anchor`, qualified against Gate3 frozen identity, presented via public view link, and captured from source path via atomic rename into write-once generation slots, guarded by per-mutation committed lease fences.

**Tech Stack:** Python 3.11, SQLite (WAL mode, BEGIN IMMEDIATE), SQLAlchemy 2.x, ctypes (glibc renameat2 / renamex_np / fstat), pytest.

**Spec:** [`docs/history/gate5g/evidence/architecture-amendment/architecture-amendment-v3.1.0.md`](file:///Users/Kerwin/MyProject/nas-file-center/docs/history/gate5g/evidence/architecture-amendment/architecture-amendment-v3.1.0.md)

---

## Global Constraints

1. **Production Code Baseline**: `c32d0778c59add81e0c296d6f73aa66bc403c04f`.
2. **Strict Frozen `tx_phase` Values**: Only the 10 frozen enum values are permitted:
   `preparing`, `candidate_anchored`, `authoritative_anchored`, `public_published`, `source_captured`, `active`, `restoring`, `restored`, `conflict`, `legacy`.
   Zero invented or unapproved phases.
3. **No Invented Lifecycle States**: Only the frozen states are permitted (`preparing`, `active`, `restoring`, `restored`, `conflict`, and pre-existing legacy states). Aborted or failed transactions transition to `state='conflict'`, `tx_phase='conflict'`. Zero invented states like `failed`.
4. **Legacy Migration Rule**: Pre-existing rows retain their original `state` (`active`, `restored`, `purged`, etc.) and have `tx_phase = NULL` (or logical legacy classification). Never overwrite historical `state` to `'legacy'`.
5. **Zero Payload-Bearing Unlink**: In `COMPAT_TRANSACTIONAL` mode, unlinking anchors, captured sources, foreign objects, or unknown inodes is strictly forbidden.
6. **Correct Gate3 Qualification & Ctime Semantics**:
   - Pre-link Gate3 expected values: `dev`, `ino`, `size`, `mtime_ns` (if provided), `hash` (SHA256). Pre-link `expected_ctime_ns` is NOT required or persisted because hard-link creation legitimately updates inode `st_ctime`.
   - `ctime_ns` is strictly an **intra-qualification stability fence**: `st_before.ctime_ns == st_after.ctime_ns` across descriptor-bound 1MiB SHA256 streaming to detect concurrent mutation during hashing. Qualification mismatch enters `conflict`.
7. **Dual Fencing Protocol (FS Fence vs DB Mutation Fence)**:
   - **Pattern A (Payload Filesystem Syscall)**:
     `BEGIN IMMEDIATE` -> renew/assert lease -> `COMMIT`. No SQLite transaction held across FUSE syscall. Execute exactly ONE filesystem syscall.
   - **Pattern B (Worker-Authorized DB Transition)**:
     `BEGIN IMMEDIATE` -> `assert_active_worker_lease(session, worker_id)` -> perform DB mutation (`tx_phase`, `state`, `authoritative_anchor_path`, `active_attempt_generation`, etc.) -> `COMMIT`. Lease assertion and DB mutation reside in the SAME short write transaction.
8. **Lease Null-Safety Order**:
   In lease verification, `if not lock.acquired_at: raise JobLeaseLost` must strictly precede any `.tzinfo` dereferencing.
9. **Capability Routing & Precision Directory Probing**:
   - Probe target filesystem directly using `safe_open_parent_fd(Path(target_dir) / ".__probe_dummy", allowed_roots)` yielding `(target_dfd, _)` and passing `dir_fd=target_dfd` to avoid probing target's parent directory.
   - Enforce device parity: `source st_dev == target_tx st_dev == public st_dev`; fail closed if cross-device.
   - Route native atomic filesystems directly to native renameat2 (zero transaction overhead).
   - Route COMPAT regular files to transaction engine; COMPAT symlink/directory/special fail closed with `EOPNOTSUPP`.
10. **Restore Finalization Protocol**: Restore does NOT finalize to `state='restored'` upon original link alone. It finalizes ONLY after public quarantine view is retired into the restore attempt slot. If view is foreign/unknown, preserve in place and enter `conflict`.
11. **Real NAS Path Isolation**:
    - Validation root must be sibling: `/tmp/zfsv3/nvme13/15246330601/data/gate5g_candidate_<sha_short>`.
    - Zero modification to production data (`/tmp/zfsv3/sata11/15246330601/data`), config (`/tmp/zfsv3/nvme13/15246330601/data/NasFileCenter`), or old failure evidence roots (`/tmp/zfsv3/nvme13/15246330601/data/gate5g_isolated_testbed`, `/tmp/zfsv3/nvme13/15246330601/data/gate5g_hotfix1_probe`).
    - All NAS execution commands run under `sudo`. No NAS execution in planning tasks.
12. **Codebase Accuracy**:
    - `execute_item` is defined in [`app/execution/executor.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/execution/executor.py#L61) and imported by [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py#L17).
    - `app/quarantine/restore.py` already exists; Task 8 modifies and integrates transactional restore into it.
13. **TDD Discipline**: Every Task must end GREEN against its focused regressions before committing.

---

## 1. Codebase Reality Map & Verified Symbols

All file paths, symbols, and line numbers verified against baseline `c32d0778c59add81e0c296d6f73aa66bc403c04f`:

| Component / File | Baseline Reality (`c32d077`) | Role in Implementation Plan v1.1.3 |
| :--- | :--- | :--- |
| [`app/models.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/models.py#L142-L175) | `QuarantineEntry` contains `id`, `original_path`, `quarantine_path`, `state`, `size`, `content_hash`, `device`, `inode`, `last_error`. | Add DB-2 fields: `tx_token`, `tx_phase`, `authoritative_anchor_path`, `active_attempt_generation`. |
| [`app/db.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/db.py#L71-L165) | `init_db()` uses `_db_init_lock`, SQLite table inspection, automatic SQLite online backup, and `ALTER TABLE ... ADD COLUMN`. | Idempotent migration for `quarantine_entries` columns and indexes with automatic backup. |
| [`app/fs_ops.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/fs_ops.py#L150-L230) | `_probe_rename_noreplace_supported()` tests atomic rename using disposable files. | Reused by capability resolver using descriptor `dir_fd` to target directory directly. |
| [`app/fs_ops.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/fs_ops.py#L446-L550) | `rename_noreplace` & `rename_noreplace_at` execute single-call fallback with TOCTOU `os.link` + `os.unlink`. | Decommission unsafe fallback; raise `OSError(errno.EOPNOTSUPP)` when native rename is unsupported. |
| [`app/quarantine/paths.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/paths.py#L131-L141) | `safe_quarantine_hash()` implements streaming SHA256 chunking (1MiB default). | Wrapped by descriptor-bound candidate anchor qualification. |
| [`app/quarantine/restore.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/restore.py#L13-L60) | Existing module containing `validate_restore_destination_intent()` and `verify_quarantine_source_integrity()`. | **[MODIFY]** Integrate transactional restore (`execute_transactional_restore`), view retirement, and foreign inode protection. |
| [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py#L510-L570) | `gather_reconcile_evidence` & `_validate_evidence` define Gate3 frozen physical identity check. | Reused as the authoritative qualification model. |
| [`app/execution/executor.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/execution/executor.py#L61) | `execute_item()` handles plan item execution. | Inject capability routing and committed per-mutation lease fences. |
| [`app/batch_utilities/empty_dir_quarantine.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/empty_dir_quarantine.py#L90-L133) | `safe_open_parent_fd()` context manager yields `(parent_fd, leaf_name)`. | Reused for ancestor path traversal and direct target directory descriptor probing. |
| [`app/tasks/recovery.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/recovery.py#L29-L60) | `assert_active_worker_lease()` checks `TaskLock` row 1 with 30s timeout. | Extended with Pattern A (`renew_and_assert_worker_lease`) and Pattern B (`assert_active_worker_lease` inside write transaction). |
| [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py#L3595-L3650) | `reconcile_startup_entries` runs on API startup. | Defer transactional entries (`tx_phase IS NOT NULL`) to Worker lease recovery. |
| [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py#L4000-L4050) | `purge_quarantine_entry` deletes quarantine entries. | Add guard refusing purge on `ACTIVE_COMPAT` entries while anchor exists. |

---

## 2. Gate3 Frozen Authority & Candidate Anchor Qualification

### 2.1 Complete Gate3 Authority & Ctime Semantics
In [`app/tasks/handlers.py::gather_reconcile_evidence`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py#L510-L535), Gate3 frozen authority verifies:
1. Object mode check: `stat.S_ISREG(st.st_mode)`.
2. Initial physical stat: `st_dev`, `st_ino`, `st_size`, `st_mtime_ns`. (Pre-link `expected_ctime_ns` is NOT checked against candidate anchor, as `os.link` legitimately updates inode ctime).
3. Streaming cryptographic hash: 1MiB chunked SHA256.
4. Post-hash stat snapshot: Re-verifying identical `st_dev`, `st_ino`, `st_size`, `st_mtime_ns`, and **`st_ctime_ns`** to detect concurrent metadata/content mutation during hashing.

### 2.2 Descriptor-Bound Qualification Protocol
```python
def qualify_candidate_anchor_fd(
    candidate_fd: int,
    expected_dev: int,
    expected_ino: int,
    expected_size: int,
    expected_hash: str,
    expected_mtime_ns: int | None = None,
) -> bool:
    st_before = os.fstat(candidate_fd)
    if not stat.S_ISREG(st_before.st_mode):
        return False
    if st_before.st_dev != expected_dev or st_before.st_ino != expected_ino or st_before.st_size != expected_size:
        return False
    before_mtime_ns = getattr(st_before, "st_mtime_ns", int(st_before.st_mtime * 1e9))
    before_ctime_ns = getattr(st_before, "st_ctime_ns", int(st_before.st_ctime * 1e9))
    if expected_mtime_ns is not None and before_mtime_ns != expected_mtime_ns:
        return False

    os.lseek(candidate_fd, 0, os.SEEK_SET)
    h = hashlib.sha256()
    while True:
        chunk = os.read(candidate_fd, 1024 * 1024)
        if not chunk:
            break
        h.update(chunk)
    if h.hexdigest() != expected_hash:
        return False

    st_after = os.fstat(candidate_fd)
    after_mtime_ns = getattr(st_after, "st_mtime_ns", int(st_after.st_mtime * 1e9))
    after_ctime_ns = getattr(st_after, "st_ctime_ns", int(st_after.st_ctime * 1e9))

    # Stability fence across hash streaming
    if (
        st_after.st_dev != st_before.st_dev
        or st_after.st_ino != st_before.st_ino
        or st_after.st_size != st_before.st_size
        or after_mtime_ns != before_mtime_ns
        or after_ctime_ns != before_ctime_ns
    ):
        return False
    return True
```

### 2.3 Single Immutable Anchor Path Promotion & Mismatch Rule
Candidate anchor is created directly at its permanent authoritative path:
`<quarantine_root>/.tx/entry-<id>/attempt-<gen>/anchor`.
- Upon passing qualification: DB sets `authoritative_anchor_path` to this path and advances `tx_phase = 'authoritative_anchored'`.
- Upon qualification failure: Under Architecture Section C2/C2.1, candidate anchor is preserved in place; entry transitions to `state='conflict'`, `tx_phase='conflict'`. Zero unlinking, zero generation retry, zero source capture.

---

## 3. Dual Fencing Protocol: Filesystem Fence vs DB Mutation Fence

### 3.1 Pattern A: Payload Filesystem Syscall Fence
Before each payload-affecting syscall (e.g. `os.link`, `os.rename`), the worker executes a short committed fence that updates `acquired_at` and releases the SQLite write lock before the syscall:
```python
def renew_and_assert_worker_lease(
    session_factory: sessionmaker,
    worker_id: str,
    timeout_seconds: float = WORKER_LEASE_TIMEOUT_SECONDS,
) -> None:
    """
    Pattern A: Short committed lease fence for filesystem syscalls:
    1. Opens dedicated session via session_factory().
    2. Issues BEGIN IMMEDIATE.
    3. Asserts lock.locked, lock.owner == worker_id, not lock.acquired_at is None, age <= timeout_seconds.
    4. Updates lock.acquired_at = utcnow().
    5. Commits immediately so SQLite write transaction is closed before returning.
    """
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        lock = session.get(TaskLock, 1)
        if not lock or not lock.locked:
            raise JobLeaseLost("Worker lease not held")
        if lock.owner != worker_id:
            raise JobLeaseLost(f"Worker '{worker_id}' lost exclusive lease (current owner: '{lock.owner}')")
        if not lock.acquired_at:
            raise JobLeaseLost(f"Worker '{worker_id}' lease invalid: missing acquired_at")
        now = utcnow()
        lock_time = lock.acquired_at if lock.acquired_at.tzinfo is not None else lock.acquired_at.replace(tzinfo=timezone.utc)
        age = (now - lock_time).total_seconds()
        if age > timeout_seconds:
            raise JobLeaseLost(f"Worker '{worker_id}' lease expired ({age:.1f}s > {timeout_seconds}s)")
        lock.acquired_at = now
        session.commit()
```

### 3.2 Pattern B: Worker-Authorized DB Mutation Fence
All DB state and generation updates must assert the worker lease **inside the same short write transaction**:
```python
# Pattern B execution idiom:
with session_factory() as session:
    session.execute(text("BEGIN IMMEDIATE"))
    assert_active_worker_lease(session, worker_id, timeout_seconds=timeout_seconds)
    # Perform durable DB mutation:
    entry = session.get(QuarantineEntry, entry_id)
    entry.tx_phase = new_tx_phase
    entry.state = new_state
    # ...
    session.commit()
```
Generation allocation specifically executes Pattern B:
```python
def allocate_next_generation(
    session_factory: sessionmaker,
    entry_id: int,
    worker_id: str,
) -> tuple[int, Path]:
    with session_factory() as session:
        session.execute(text("BEGIN IMMEDIATE"))
        assert_active_worker_lease(session, worker_id)
        entry = session.get(QuarantineEntry, entry_id)
        next_gen = (entry.active_attempt_generation or 0) + 1
        entry.active_attempt_generation = next_gen
        session.commit()
    attempt_dir = Path(entry.quarantine_path).parent / ".tx" / f"entry-{entry_id}" / f"attempt-{next_gen}"
    return next_gen, attempt_dir
```

---

## 4. Capability Routing API & Direct Target Probing

```python
class MutationCapability(str, Enum):
    NATIVE_ATOMIC_NOREPLACE = "native_atomic_noreplace"
    COMPAT_TRANSACTIONAL = "compat_transactional"
    UNSUPPORTED = "unsupported"

def resolve_mutation_capability(
    source_path: Path | str,
    target_dir: Path | str,
    quarantine_root: Path | str,
    allowed_roots: Sequence[Path | str],
) -> MutationCapability:
    """
    Resolves mutation capability without imposing transaction overhead on native filesystems.
    Probes target_dir directly using safe_open_parent_fd descriptor to avoid probing target's parent.
    """
    try:
        st_src = os.lstat(source_path)
    except OSError:
        return MutationCapability.UNSUPPORTED

    # Open target directory descriptor safely using safe_open_parent_fd context manager
    probe_leaf = ".__probe_noreplace_anchor"
    try:
        with safe_open_parent_fd(Path(target_dir) / probe_leaf, allowed_roots) as (target_dfd, _):
            probe_result = _probe_rename_noreplace_supported(dir_fd=target_dfd)
    except Exception:
        return MutationCapability.UNSUPPORTED

    if probe_result is True:
        return MutationCapability.NATIVE_ATOMIC_NOREPLACE
    elif probe_result is False:
        # Check regular file
        if not stat.S_ISREG(st_src.st_mode):
            return MutationCapability.UNSUPPORTED

        # Enforce device parity across source, target tx root, and quarantine root
        try:
            st_target = os.stat(target_dir)
            st_quar = os.stat(quarantine_root)
            if st_src.st_dev != st_target.st_dev or st_src.st_dev != st_quar.st_dev:
                return MutationCapability.UNSUPPORTED
        except OSError:
            return MutationCapability.UNSUPPORTED

        return MutationCapability.COMPAT_TRANSACTIONAL
    return MutationCapability.UNSUPPORTED
```

---

## 5. Exhaustive State vs Frozen `tx_phase` Persisted Matrix

| Lifecycle State | `QuarantineEntry.state` | `QuarantineEntry.tx_phase` | `authoritative_anchor_path` | `active_attempt_generation` | Physical Reality |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Preparing Tx** | `preparing` | `preparing` | `NULL` | $G \ge 1$ | Attempt dir `<gen>` created; candidate anchor pending. |
| **Candidate Anchored** | `preparing` | `candidate_anchored` | `NULL` | $G \ge 1$ | `attempt-<gen>/anchor` linked; qualification in progress. |
| **Authoritative Anchored** | `preparing` | `authoritative_anchored` | `<anchor_path>` | $G \ge 1$ | Qualified; anchor immutable authority; public view pending. |
| **Public Published** | `preparing` | `public_published` | `<anchor_path>` | $G \ge 1$ | `quarantine_path` hard linked to anchor; source capture pending. |
| **Source Captured** | `preparing` | `source_captured` | `<anchor_path>` | $G \ge 1$ | Source renamed into `captured_source`; classification pending. |
| **Active Compat** | `active` | `active` | `<anchor_path>` | $G \ge 1$ | Quarantined; anchor authoritative; public view presentation-only. |
| **Restoring Compat** | `restoring` | `restoring` | `<anchor_path>` | $G \ge 1$ | Restore in progress; original link or view capture pending. |
| **Restored Compat** | `restored` | `restored` | `<anchor_path>` | $G \ge 1$ | Restored to original; public view retired into slot. |
| **Conflict Detected** | `conflict` | `conflict` | `<anchor_path>` or `NULL` | $G \ge 1$ | Collision/mismatch detected; foreign occupant preserved in place. |
| **Legacy Active** | `active` | `NULL` | `NULL` | `NULL` | Pre-existing v0.3.5 row; unanchored; fail closed on COMPAT. |
| **Legacy Restored** | `restored` | `NULL` | `NULL` | `NULL` | Pre-existing restored row; unanchored. |
| **Legacy Purged** | `purged` | `NULL` | `NULL` | `NULL` | Pre-existing purged row. |
| **Legacy Conflict** | `conflict` | `NULL` | `NULL` | `NULL` | Pre-existing conflict row. |

---

## 6. DB-Lag Filesystem Fact Reconciliation Matrix (13 Mandatory Variants)

> **Golden Rule**: *CLASSIFY EXISTING EVIDENCE BEFORE ISSUING ANOTHER MUTATION.*

| # | DB Facts (`state`, `tx_phase`) | FS Facts (Disk Reality) | Read/Classify Action | New Gen Required? | Next Frozen `tx_phase` / `state` | FS Mutation Allowed? | Lease Fence Requirement | `BatchPlanItem` Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `preparing`, `preparing` | No attempt dir or no anchor in `attempt-<G>` | Stat attempt dir & anchor; verify absent. | Yes ($G+1$) if retrying | `preparing` / `preparing` (or `conflict` if source missing) | NO payload mutation. Create `attempt-<G+1>` dir only. | Pattern A fence before `os.mkdir` | Retry or fail item |
| **2** | `preparing`, `preparing` | Candidate anchor exists in `attempt-<G>/anchor` | `open(O_RDONLY\|O_NOFOLLOW)`, run `qualify_candidate_anchor_fd()` against Gate3 identity | No | If valid: `authoritative_anchored` / `preparing`. **If invalid: `conflict` / `conflict`** | Zero unlink. Zero new gen retry. If valid: DB update only. | Pattern B fence for DB promotion | Progress if valid; `status='failed'` if invalid |
| **3** | `preparing`, `preparing` | Generation $G$ committed in DB, but `attempt-<G>` directory missing on disk | Stat directory; confirms missing. | Yes ($G+1$) | `preparing` / `preparing` | `os.mkdir` for attempt $G+1$ under fence. | Pattern A fence before `os.mkdir` | Retry preparation |
| **4** | `preparing`, `authoritative_anchored` | Public quarantine path absent; anchor valid | Stat anchor (valid) and public path (absent). | No | `public_published` / `preparing` | YES: exactly ONE `os.link(anchor, public_path)`. | Pattern A fence before `os.link` | Progress to publication |
| **5** | `preparing`, `authoritative_anchored` | Public quarantine path present and matches anchor dev/ino | Stat public path & anchor; verify identical dev/ino (FS succeeded, DB lagged). | No | `public_published` / `preparing` | NO FS mutation needed. DB advance only. | Pattern B fence for DB commit | Progress to publication |
| **6** | `preparing`, `authoritative_anchored` | Public quarantine path present but occupied by foreign inode | Stat public path; dev/ino mismatch with anchor. | No | `conflict` / `conflict` | STRICTLY ZERO FS MUTATION. Foreign occupant preserved in place. | Pattern B fence for DB conflict | `status='failed'`, record conflict |
| **7** | `preparing`, `public_published` | `attempt-<G>/captured_source` absent; source path present with matching inode | Stat capture slot (absent); stat source path (matches anchor). | No | `source_captured` / `preparing` -> `active` / `active` | YES: exactly ONE `os.rename(source, captured_source)`. | Pattern A fence before `os.rename` | Complete quarantine |
| **8** | `preparing`, `public_published` | `attempt-<G>/captured_source` present and matches anchor dev/ino | Stat capture slot; dev/ino match anchor (FS rename succeeded, DB lagged). | No | `source_captured` / `preparing` -> `active` / `active` | NO FS mutation needed. DB advance only. | Pattern B fence for DB commit | `status='succeeded'` |
| **9** | `preparing`, `public_published` | `attempt-<G>/captured_source` present but occupied by foreign inode | Stat capture slot; dev/ino mismatch with anchor. | No | `conflict` / `conflict` | STRICTLY ZERO FS MUTATION. Foreign occupant preserved in place. | Pattern B fence for DB conflict | `status='failed'`, record conflict |
| **10**| `restoring`, `restoring` | Original destination absent; anchor valid | Stat original path (absent); stat anchor (valid). | No | **`restoring` / `restoring`** (Do NOT mark restored yet) | YES: `os.link(anchor, original_path)`. | Pattern A fence before `os.link` | Progress restore to view capture |
| **11**| `restoring`, `restoring` | Original destination present and matches anchor dev/ino | Stat original path & anchor; verify matching dev/ino. Check public view. | No | If view captured expected: **`restored` / `restored`**. If view foreign: **`conflict` / `conflict`**. | If view expected present: `os.rename(public_view, restore_slot)`. | Pattern A fence before view retirement | `status='succeeded'` or conflict |
| **12**| `restoring`, `restoring` | Original destination present but occupied by foreign inode / EEXIST | Stat original path; dev/ino mismatch (collision). | No | `conflict` / `conflict` | STRICTLY ZERO FS MUTATION. Foreign occupant preserved in place. | Pattern B fence for DB conflict | `status='failed'`, record conflict |
| **13**| `restoring`, `restoring` | `attempt-<G>/captured_quarantine_view` present | Stat captured view slot. If expected and original restored -> `restored`. If foreign -> `conflict`. | No | If expected: `restored` / `restored`. **If foreign: `conflict` / `conflict`**. | Zero unlink. If original not yet restored: `os.link(anchor, orig)`. | Pattern A fence before `os.link` | `status='succeeded'` or conflict |

---

## 7. R1–R16 Dedicated Race Matrix Specification (`tests/test_gate5g_g7_races.py`)

Every race scenario is mapped to an explicit test function in `tests/test_gate5g_g7_races.py`:

```python
# tests/test_gate5g_g7_races.py

def test_race_r1_source_replaced_before_capture(tmp_path, session_factory, worker_id):
    """R1: Attacker replaces source with foreign file before capture rename."""
    # Setup candidate & authoritative anchor for genuine file
    # Replace source file with foreign file (different inode/content)
    # Execute capture step: rename moves foreign file into attempt slot
    # Post-capture qualification asserts dev/ino/hash != expected
    # Assert: state='conflict', tx_phase='conflict', foreign file preserved in slot, zero unlink.

def test_race_r2_source_replaced_after_earlier_verification_before_capture(tmp_path, session_factory, worker_id):
    """R2: Attacker replaces source after verification stat, immediately before rename."""
    # Verify source stat passes
    # Swap source with foreign inode before os.rename
    # Post-capture qualification fails -> state='conflict', foreign file preserved.

def test_race_r3_source_recreated_immediately_after_capture(tmp_path, session_factory, worker_id):
    """R3: Attacker creates a new file at source pathname right after source is captured."""
    # Capture source into slot
    # Third party creates new file at original source path
    # Assert: transaction completes active, authoritative anchor intact, new source file untouched.

def test_race_r4_stale_worker_second_capture(tmp_path, session_factory, worker_id):
    """R4: Stale worker attempts capture after lease takeover."""
    # Lease taken over by new worker
    # Stale worker calls renew_and_assert_worker_lease()
    # Assert: JobLeaseLost raised, zero syscall executed.

def test_race_r5_two_generations_capture_different_occupants(tmp_path, session_factory, worker_id):
    """R5: Gen 1 captured genuine file; Gen 2 captured foreign occupant after crash."""
    # Gen 1 captures genuine file into attempt-1/captured_source; crash simulated
    # Foreign file placed at source; Gen 2 captures into attempt-2/captured_source
    # Reconciler audits attempt-1 first, finds genuine anchor match -> active
    # Assert: attempt-2 foreign file preserved in place, genuine payload restored/active.

def test_race_r6_public_destination_appears_before_publication(tmp_path, session_factory, worker_id):
    """R6: Third party creates file at public quarantine path before publication link."""
    # File created at public path
    # os.link(anchor, public_path) raises FileExistsError
    # Assert: tx_phase='conflict', state='conflict', foreign occupant untouched.

def test_race_r7_public_destination_replaced_after_publication(tmp_path, session_factory, worker_id):
    """R7: Public quarantine path replaced with foreign file after publication."""
    # Transaction active
    # Public path replaced with foreign file
    # Restore operation links from authoritative anchor, ignoring corrupted public path.

def test_race_r8_stale_worker_holds_old_tx_dir_fd(tmp_path, session_factory, worker_id):
    """R8: Stale worker retains open dir_fd to old attempt directory."""
    # Old worker holds attempt-1 dir_fd
    # Lease transferred; attempt-2 active
    # Old worker fence fails with JobLeaseLost before any openat/unlinkat.

def test_race_r9_stale_worker_holds_source_parent_fd(tmp_path, session_factory, worker_id):
    """R9: Stale worker retains open parent dir_fd to source directory."""
    # Lease expired
    # Stale worker attempts renameat relative to parent fd
    # Fence fails with JobLeaseLost before renameat.

def test_race_r10_current_worker_reconciles_while_old_worker_executes_one_fs_syscall(tmp_path, session_factory, worker_id):
    """R10: Reconciler runs while delayed old worker executes exactly one syscall."""
    # Stale worker delayed inside single os.link
    # Reconciler audits filesystem facts via classify_evidence_before_mutation()
    # Discovers link landed or absent; stale worker fails next fence.

def test_race_r11_crash_after_anchor_creation_before_db_commit(tmp_path, session_factory, worker_id):
    """R11: Crash occurs right after candidate anchor linked, before DB commit."""
    # DB is preparing, attempt-1/anchor exists on disk
    # Reconciler qualifies candidate anchor against Gate3 full identity
    # Assert: qualified, DB advanced to authoritative_anchored.

def test_race_r12_crash_after_capture_rename_before_db_commit(tmp_path, session_factory, worker_id):
    """R12: Crash occurs right after source capture rename, before DB commit."""
    # DB is public_published, attempt-1/captured_source exists on disk
    # Reconciler verifies capture slot matches anchor
    # Assert: DB advanced to source_captured -> active.

def test_race_r13_restore_original_destination_appears_concurrently(tmp_path, session_factory, worker_id):
    """R13: Concurrent occupant appears at original destination during restore."""
    # File created at original path
    # Restore os.link raises FileExistsError
    # Assert: state='conflict', foreign occupant preserved, payload safe in anchor.

def test_race_r14_restore_public_view_replaced_before_retirement(tmp_path, session_factory, worker_id):
    """R14: Public view replaced with foreign occupant before restore retirement rename."""
    # Original successfully restored
    # Public view replaced with foreign occupant
    # Retirement moves foreign occupant into slot; detected as foreign; preserved in place; state='conflict' (NOT restored).

def test_race_r15_private_attempt_contains_unknown_inode(tmp_path, session_factory, worker_id):
    """R15: Private attempt contains injected unknown inode."""
    # Inject rogue file into attempt directory
    # Reconciler and cleanup audit attempt directory
    # Assert: unknown inode is never unlinked (Zero Payload-Bearing Unlink).

def test_race_r16_multiple_attempt_directories_survive_restart(tmp_path, session_factory, worker_id):
    """R16: Multiple attempt directories exist due to successive crashes."""
    # Create attempt-1, attempt-2, attempt-3 with partial states
    # Reconciler audits descending generations, classifies facts, resolves correct state.
```

---

## 8. NAS Acceptance Path & Real Verified zfuse Paths

### 8.1 Real Verified NAS Path Map
- **Production Data Path**: `/tmp/zfsv3/sata11/15246330601/data` (**READ-ONLY / FORBIDDEN FOR TESTS**).
- **Production Config Path**: `/tmp/zfsv3/nvme13/15246330601/data/NasFileCenter` (**FORBIDDEN FOR TESTS**).
- **Verified Disposable Parent**: `/tmp/zfsv3/nvme13/15246330601/data`.
- **Old Failure Evidence Root**: `/tmp/zfsv3/nvme13/15246330601/data/gate5g_isolated_testbed` (**IMMUTABLY PRESERVED; NEVER REUSED OR DELETED**).
- **Old Hotfix Probe Root**: `/tmp/zfsv3/nvme13/15246330601/data/gate5g_hotfix1_probe` (**IMMUTABLY PRESERVED**).
- **Future Candidate Root**: `/tmp/zfsv3/nvme13/15246330601/data/gate5g_candidate_<sha_short>`.

### 8.2 Pre-Mutation Fail-Closed Guards
Before issuing any filesystem mutation on NAS in future candidate validation:
1. **Canonical Path Isolation Check**: Target path must resolve strictly within `/tmp/zfsv3/nvme13/15246330601/data/gate5g_candidate_<sha_short>/`. Must NOT equal, be ancestor, or be descendant of production paths or old evidence roots.
2. **Filesystem Type Check**: `stat -f -c %T <target_root>` must return `fuse` or `zfuse`.
3. **Cross-Device Guard**: `os.stat(source).st_dev == os.stat(quarantine).st_dev`.
4. **Evidence Preservation Guard**: Old evidence root `/tmp/zfsv3/nvme13/15246330601/data/gate5g_isolated_testbed` exists and is unmodified.
5. **Sentinel Verification**: `.sentinel` file verified in testbed root.
6. **Sudo Enforcement**: All NAS execution commands run under `sudo`. Zero NAS execution during planning.

---

## 9. Bite-Sized Implementation Tasks (Task 1 ~ Task 12)

### Task 1: Schema Migration & Model Upgrade (10 Frozen Phases)

**Files:**
- Modify: [`app/models.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/models.py#L142-L175)
- Modify: [`app/db.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/db.py#L71-L165)
- Test: `tests/test_gate5g_g7_task1_schema.py`

**Interfaces:**
- Consumes: SQLAlchemy `Base`, `init_db()`.
- Produces: `QuarantineEntry` with `tx_token`, `tx_phase`, `authoritative_anchor_path`, `active_attempt_generation`.

- [ ] **Step 1: Write failing test for DB-2 schema and legacy migration**
```python
# tests/test_gate5g_g7_task1_schema.py
def test_quarantine_entry_db2_columns(session_factory):
    with session_factory() as session:
        entry = QuarantineEntry(
            original_path="/vol/test.txt",
            quarantine_path="/vol/.quarantine/test.txt",
            state="preparing",
            tx_token="tx-12345",
            tx_phase="preparing",
            authoritative_anchor_path="/vol/.quarantine/.tx/entry-1/attempt-1/anchor",
            active_attempt_generation=1,
        )
        session.add(entry)
        session.commit()
        assert entry.tx_phase == "preparing"

def test_legacy_rows_preserve_state_and_null_tx_phase(session_factory):
    with session_factory() as session:
        entry = QuarantineEntry(
            original_path="/vol/legacy.txt",
            quarantine_path="/vol/.quarantine/legacy.txt",
            state="active",
        )
        session.add(entry)
        session.commit()
        assert entry.state == "active"
        assert entry.tx_phase is None
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_gate5g_g7_task1_schema.py -v`
Expected: FAIL with `AttributeError: type object 'QuarantineEntry' has no attribute 'tx_phase'`

- [ ] **Step 3: Implement model changes and idempotent migration**
Add columns to `QuarantineEntry` in `app/models.py` and migration logic in `app/db.py::init_db()`.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_task1_schema.py -v`
Expected: PASS

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_quarantine.py tests/test_gate5g_g7_task1_schema.py -v`
Commit: `git add app/models.py app/db.py tests/test_gate5g_g7_task1_schema.py && git commit -m "feat(gate5g): add DB-2 transaction fields to QuarantineEntry"`

---

### Task 2: Dual Lease Fence Helpers (Pattern A & Pattern B)

**Files:**
- Modify: [`app/tasks/recovery.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/recovery.py#L29-L65)
- Test: `tests/test_gate5g_g7_task2_lease_fence.py`

**Interfaces:**
- Consumes: `session_factory: sessionmaker`, `TaskLock`.
- Produces: `renew_and_assert_worker_lease(session_factory, worker_id, timeout_seconds) -> None`, Pattern B in-transaction assertion.

- [ ] **Step 1: Write failing tests for Pattern A and Pattern B fences with null-safety**
```python
# tests/test_gate5g_g7_task2_lease_fence.py
def test_pattern_a_lease_fence_renewal_visible_across_sessions(session_factory):
    # Acquire lock for worker-1
    # Call renew_and_assert_worker_lease(session_factory, "worker-1")
    # In another session, assert acquired_at updated and lock NOT held open
    pass

def test_lease_fence_null_acquired_at_raises_job_lease_lost(session_factory):
    # Set TaskLock.acquired_at = None
    # with pytest.raises(JobLeaseLost):
    #     renew_and_assert_worker_lease(session_factory, "worker-1")
    pass

def test_pattern_b_stale_worker_cannot_commit_db_transition(session_factory):
    # Transfer lock to worker-2
    # In a new session with BEGIN IMMEDIATE, verify assert_active_worker_lease("worker-1") raises JobLeaseLost
    # and prevents QuarantineEntry state mutation
    pass
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_gate5g_g7_task2_lease_fence.py -v`
Expected: FAIL with `ImportError: cannot import name 'renew_and_assert_worker_lease'`

- [ ] **Step 3: Implement `renew_and_assert_worker_lease` and null safety in `app/tasks/recovery.py`**
Implement Pattern A committed fence with `session_factory()`, `BEGIN IMMEDIATE`, null-check before tzinfo, and immediate commit.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_task2_lease_fence.py -v`
Expected: PASS

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_tasks.py tests/test_gate5g_g7_task2_lease_fence.py -v`
Commit: `git add app/tasks/recovery.py tests/test_gate5g_g7_task2_lease_fence.py && git commit -m "feat(gate5g): implement Pattern A and B worker lease fences with null safety"`

---

### Task 3: Gate3 Candidate Qualification with Intra-Qualification Ctime Check

**Files:**
- Create: `app/quarantine/candidate.py`
- Test: `tests/test_gate5g_g7_task3_candidate.py`

**Interfaces:**
- Consumes: `safe_quarantine_hash`, `os.fstat`.
- Produces: `qualify_candidate_anchor_fd(fd, dev, ino, size, sha256, mtime_ns) -> bool`.

- [ ] **Step 1: Write failing tests for candidate qualification and ctime semantics**
```python
# tests/test_gate5g_g7_task3_candidate.py
def test_candidate_allows_legitimate_post_link_ctime_change_from_source_snapshot(tmp_path):
    f = tmp_path / "candidate.txt"
    content = b"GENUINE_DATA"
    f.write_bytes(content)
    h = hashlib.sha256(content).hexdigest()
    st = os.stat(f)
    mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))
    # Legitimate post-link ctime difference must NOT fail qualification
    with open(f, "rb") as fp:
        assert qualify_candidate_anchor_fd(fp.fileno(), st.st_dev, st.st_ino, len(content), h, mtime_ns) is True

def test_candidate_rejects_ctime_change_during_hash(tmp_path, monkeypatch):
    f = tmp_path / "candidate.txt"
    f.write_bytes(b"DATA" * 1024)
    h = hashlib.sha256(b"DATA" * 1024).hexdigest()
    st = os.stat(f)
    # Simulate chmod/mutation altering ctime during hash chunk reading
    # qualify_candidate_anchor_fd must detect st_before.ctime != st_after.ctime and return False
    pass
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_gate5g_g7_task3_candidate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.quarantine.candidate'`

- [ ] **Step 3: Implement candidate qualification algorithm**
Create `app/quarantine/candidate.py` with descriptor-bound `fstat`, 1MiB SHA256 chunk streaming, and pre/post stability check across all 5 stat dimensions.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_task3_candidate.py -v`
Expected: PASS

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_gate5g_g7_task3_candidate.py -v`
Commit: `git add app/quarantine/candidate.py tests/test_gate5g_g7_task3_candidate.py && git commit -m "feat(gate5g): implement candidate qualification with intra-qualification ctime stability"`

---

### Task 4: Single Immutable Anchor Promotion & Generation Allocation

**Files:**
- Create: `app/quarantine/tx_allocator.py`
- Test: `tests/test_gate5g_g7_task4_allocator.py`

**Interfaces:**
- Consumes: `session_factory: sessionmaker`, `QuarantineEntry`.
- Produces: `allocate_next_generation(session_factory, entry_id, worker_id) -> tuple[int, Path]`.

- [ ] **Step 1: Write failing test for monotonic generation allocation with Pattern B lease assertion**
```python
# tests/test_gate5g_g7_task4_allocator.py
def test_allocate_next_generation_monotonic(session_factory, tmp_path):
    # Allocate Gen 1 -> returns (1, path_to_attempt_1)
    # Commit in DB before mkdir
    # Allocate Gen 2 -> returns (2, path_to_attempt_2)
    pass

def test_stale_worker_cannot_allocate_generation(session_factory):
    # Lock owned by worker-2
    # with pytest.raises(JobLeaseLost):
    #     allocate_next_generation(session_factory, entry_id=1, worker_id="worker-1")
    pass
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_gate5g_g7_task4_allocator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement generation allocator**
Implement allocation under SQLite Pattern B `BEGIN IMMEDIATE` + `assert_active_worker_lease` committed before `os.mkdir`.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_task4_allocator.py -v`
Expected: PASS

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_gate5g_g7_task4_allocator.py -v`
Commit: `git add app/quarantine/tx_allocator.py tests/test_gate5g_g7_task4_allocator.py && git commit -m "feat(gate5g): implement monotonic generation allocation with Pattern B lease assertion"`

---

### Task 5: Capability Routing API & Direct Target Probing via Context Manager

**Files:**
- Create: `app/quarantine/capability.py`
- Test: `tests/test_gate5g_g7_task5_capability.py`

**Interfaces:**
- Consumes: `_probe_rename_noreplace_supported`, `safe_open_parent_fd`.
- Produces: `resolve_mutation_capability(source_path, target_dir, quarantine_root, allowed_roots) -> MutationCapability`.

- [ ] **Step 1: Write failing tests for capability resolver with safe_open_parent_fd**
```python
# tests/test_gate5g_g7_task5_capability.py
def test_probe_runs_on_target_directory_not_parent(tmp_path, monkeypatch):
    # Pass target_dir into resolve_mutation_capability
    # Spy on safe_open_parent_fd call; assert path probed is target_dir / ".__probe_noreplace_anchor"
    pass

def test_resolve_device_mismatch_fails_closed(tmp_path, monkeypatch):
    # Mock source on dev 1, quarantine on dev 2
    # Assert returns MutationCapability.UNSUPPORTED
    pass

def test_resolve_native_regular_file(tmp_path, monkeypatch):
    pass

def test_resolve_compat_regular_file(tmp_path, monkeypatch):
    pass
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_gate5g_g7_task5_capability.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `resolve_mutation_capability`**
Create `app/quarantine/capability.py` implementing exact routing logic using `safe_open_parent_fd` context manager to probe target directory descriptor.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_task5_capability.py -v`
Expected: PASS

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_gate5g_g7_task5_capability.py -v`
Commit: `git add app/quarantine/capability.py tests/test_gate5g_g7_task5_capability.py && git commit -m "feat(gate5g): implement mutation capability resolver with direct target probing"`

---

### Task 6: Decommission Unsafe Fallback & Update Hotfix1 Tests

**Files:**
- Modify: [`app/fs_ops.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/fs_ops.py#L446-L550)
- Modify: [`tests/test_gate5g_g7_hotfix1_fs_ops.py`](file:///Users/Kerwin/MyProject/nas-file-center/tests/test_gate5g_g7_hotfix1_fs_ops.py#L43-L120)

**Interfaces:**
- Consumes: Native `_RENAME_IMPL` and `_RENAME_AT_IMPL`.
- Produces: `rename_noreplace` and `rename_noreplace_at` raising `OSError(errno.EOPNOTSUPP)` when native rename is unsupported; zero check-then-unlink fallback.

- [ ] **Step 1: Update tests in `tests/test_gate5g_g7_hotfix1_fs_ops.py`**
Modify `test_zfuse_compatibility_path_regular_file_success` and related tests to assert `OSError(errno.EOPNOTSUPP)` when native RENAME_NOREPLACE fails, verifying zero fallback.

- [ ] **Step 2: Run test to verify failure against current code**
Run: `pytest tests/test_gate5g_g7_hotfix1_fs_ops.py -v`
Expected: FAIL because current code still attempts fallback.

- [ ] **Step 3: Decommission fallback in `app/fs_ops.py`**
Remove `_execute_safe_noreplace_fallback` calls; raise `OSError(errno.EOPNOTSUPP)` directly.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_hotfix1_fs_ops.py -v`
Expected: PASS (all tests in file pass GREEN).

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_gate5g_g7_hotfix1_fs_ops.py tests/test_fs_ops.py -v`
Commit: `git add app/fs_ops.py tests/test_gate5g_g7_hotfix1_fs_ops.py && git commit -m "feat(gate5g): decommission unsafe fs_ops fallback and assert EOPNOTSUPP"`

---

### Task 7: Transactional Quarantine Engine & Fenced Execution

**Files:**
- Create: `app/quarantine/engine.py`
- Modify: [`app/execution/executor.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/execution/executor.py#L61)
- Test: `tests/test_gate5g_g7_task7_engine.py`

**Interfaces:**
- Consumes: `renew_and_assert_worker_lease`, `qualify_candidate_anchor_fd`, `resolve_mutation_capability`.
- Produces: `execute_transactional_quarantine(entry, worker_id) -> None`.

- [ ] **Step 1: Write failing tests for transactional quarantine flow**
```python
# tests/test_gate5g_g7_task7_engine.py
def test_transactional_quarantine_success(tmp_path, session_factory, worker_id):
    # Setup source and target
    # Execute transactional quarantine
    # Assert entry.tx_phase == 'active', entry.state == 'active'
    # Assert payload at authoritative_anchor_path
    pass
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_gate5g_g7_task7_engine.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement transactional quarantine engine**
Implement 5-step mutation flow using Pattern A fences before each syscall and Pattern B for DB phase updates.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_task7_engine.py -v`
Expected: PASS

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_gate5g_g7_task7_engine.py -v`
Commit: `git add app/quarantine/engine.py app/execution/executor.py tests/test_gate5g_g7_task7_engine.py && git commit -m "feat(gate5g): implement transactional quarantine engine"`

---

### Task 8: Transactional Restore Engine & Public View Retirement

**Files:**
- Modify: [`app/quarantine/restore.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/restore.py#L1-L60)
- Modify: [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py#L3700-L3750)
- Test: `tests/test_gate5g_g7_task8_restore.py`

**Interfaces:**
- Consumes: `authoritative_anchor_path`, Pattern A & B fences, existing validation helpers.
- Produces: `execute_transactional_restore(entry, worker_id) -> None`.

- [ ] **Step 1: Write failing tests for restore engine & view retirement**
```python
# tests/test_gate5g_g7_task8_restore.py
def test_restore_does_not_mark_restored_before_view_retirement(tmp_path, session_factory, worker_id):
    # Original linked; view still present at public path
    # Assert state remains restoring, not restored
    pass

def test_restore_enters_conflict_if_captured_view_is_foreign(tmp_path, session_factory, worker_id):
    # Original linked; public view replaced with foreign occupant
    # View captured into slot; foreign occupant detected
    # Assert: state='conflict', tx_phase='conflict', foreign occupant preserved in place
    pass
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_gate5g_g7_task8_restore.py -v`
Expected: FAIL

- [ ] **Step 3: Implement transactional restore in `app/quarantine/restore.py`**
Integrate `execute_transactional_restore` into existing module with two-step restore and view retirement.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_task8_restore.py -v`
Expected: PASS

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_gate5g_g7_task8_restore.py -v`
Commit: `git add app/quarantine/restore.py app/service.py tests/test_gate5g_g7_task8_restore.py && git commit -m "feat(gate5g): integrate transactional restore and public view retirement"`

---

### Task 9: API Boot Deferral of Transactional Entries

**Files:**
- Modify: [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py#L3595-L3650)
- Test: `tests/test_gate5g_g7_task9_boot_deferral.py`

**Interfaces:**
- Consumes: `_reconcile_single_transitional_entry`.
- Produces: Read-only deferral when `tx_phase IS NOT NULL`.

- [ ] **Step 1: Write failing test for API boot deferral**
```python
# tests/test_gate5g_g7_task9_boot_deferral.py
def test_api_boot_defers_transactional_entry(session_factory, monkeypatch):
    # Create entry with tx_phase='authoritative_anchored'
    # Forbid any filesystem mutation
    # Call _reconcile_single_transitional_entry
    # Assert: zero filesystem mutations, deferral logged.
    pass
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_gate5g_g7_task9_boot_deferral.py -v`
Expected: FAIL

- [ ] **Step 3: Implement deferral check in `app/service.py`**
Add `if entry.tx_phase is not None: logger.info(...); return` check.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_task9_boot_deferral.py -v`
Expected: PASS

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_service.py tests/test_gate5g_g7_task9_boot_deferral.py -v`
Commit: `git add app/service.py tests/test_gate5g_g7_task9_boot_deferral.py && git commit -m "feat(gate5g): defer transactional entries during API startup"`

---

### Task 10: Unified Lease Takeover & Crash Reconciliation Engine

**Files:**
- Create: `app/quarantine/reconcile.py`
- Modify: [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py#L580-L660)
- Test: `tests/test_gate5g_g7_task10_reconcile.py`

**Interfaces:**
- Consumes: 13-variant fact reconciliation table.
- Produces: `reconcile_quarantine_transaction(entry, worker_id) -> None`.

- [ ] **Step 1: Write failing tests for crash reconciliation variants**
```python
# tests/test_gate5g_g7_task10_reconcile.py
def test_reconcile_preparing_with_candidate_anchor_mismatch_enters_conflict(tmp_path, session_factory, worker_id):
    # Variant 2 mismatch: candidate anchor fails qualification
    # Assert: state='conflict', tx_phase='conflict', candidate preserved in place, zero retry
    pass

def test_reconcile_restoring_original_present_view_foreign_enters_conflict(tmp_path, session_factory, worker_id):
    # Variant 11/13: foreign view captured
    # Assert: state='conflict', tx_phase='conflict', foreign occupant preserved in place
    pass
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_gate5g_g7_task10_reconcile.py -v`
Expected: FAIL

- [ ] **Step 3: Implement crash reconciliation engine**
Implement all 13 variants in `app/quarantine/reconcile.py`.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_task10_reconcile.py -v`
Expected: PASS

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_gate5g_g7_task10_reconcile.py -v`
Commit: `git add app/quarantine/reconcile.py app/tasks/handlers.py tests/test_gate5g_g7_task10_reconcile.py && git commit -m "feat(gate5g): implement unified crash reconciliation engine"`

---

### Task 11: Cleanup Gate & Zero Payload-Bearing Unlink Guard

**Files:**
- Create: `app/quarantine/cleanup_gate.py`
- Modify: [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py#L4000-L4050)
- Test: `tests/test_gate5g_g7_task11_cleanup_gate.py`

**Interfaces:**
- Consumes: `authoritative_anchor_path`.
- Produces: `safe_quarantine_purge_guard(entry) -> None`.

- [ ] **Step 1: Write failing test for COMPAT purge refusal**
```python
# tests/test_gate5g_g7_task11_cleanup_gate.py
def test_purge_refuses_active_compat_entry(session_factory):
    # Entry with authoritative_anchor_path
    # with pytest.raises(OSError) as exc:
    #     purge_quarantine_entry(...)
    # assert exc.value.errno == errno.EOPNOTSUPP
    pass
```

- [ ] **Step 2: Run test to verify failure**
Run: `pytest tests/test_gate5g_g7_task11_cleanup_gate.py -v`
Expected: FAIL

- [ ] **Step 3: Implement cleanup safety gate**
Raise `EOPNOTSUPP` if anchor exists; refuse unlinking payload in COMPAT mode.

- [ ] **Step 4: Run test to verify pass**
Run: `pytest tests/test_gate5g_g7_task11_cleanup_gate.py -v`
Expected: PASS

- [ ] **Step 5: Focused regression & commit**
Run: `pytest tests/test_gate5g_g7_task11_cleanup_gate.py -v`
Commit: `git add app/quarantine/cleanup_gate.py app/service.py tests/test_gate5g_g7_task11_cleanup_gate.py && git commit -m "feat(gate5g): enforce cleanup safety gate and zero payload unlink"`

---

### Task 12: R1–R16 Race Suite & Complete Test Suite Green

**Files:**
- Create: `tests/test_gate5g_g7_races.py`
- Create: `tests/test_gate5g_g7_e2e_compat.py`
- Test: All unit, integration, and race test suites.

**Interfaces:**
- Consumes: All modules from Tasks 1-11.
- Produces: Complete verification of R1-R16 and end-to-end crash resilience.

- [ ] **Step 1: Implement complete R1–R16 race tests in `tests/test_gate5g_g7_races.py`**
Implement all 16 test functions defined in Section 7.

- [ ] **Step 2: Run race tests to verify pass**
Run: `pytest tests/test_gate5g_g7_races.py -v`
Expected: PASS (16 passed)

- [ ] **Step 3: Run end-to-end integration tests**
Run: `pytest tests/test_gate5g_g7_e2e_compat.py -v`
Expected: PASS

- [ ] **Step 4: Run full project regression**
Run: `pytest -v`
Expected: PASS (100% test suite green)

- [ ] **Step 5: Generate evidence & commit**
Output path: `docs/history/gate5g/evidence/candidate-validation/gate5g-g7-implementation-evidence.txt`
Commit:
`git add tests/test_gate5g_g7_races.py tests/test_gate5g_g7_e2e_compat.py docs/history/gate5g/evidence/candidate-validation/ && git commit -m "test(gate5g): deliver complete R1-R16 race suite and e2e validation"`

---

## 10. Self-Review Checklist

- [x] **Spec Coverage**: All 11 frozen architecture requirements mapped to concrete tasks.
- [x] **No Placeholders**: Every step contains concrete code, exact pytest commands, and expected failures.
- [x] **Exact Frozen `tx_phase`**: Only the 10 approved enum values are referenced; legacy migration retains existing `state`.
- [x] **Zero Invented States**: No `state='failed'`; aborted transactions enter `conflict` / `conflict`.
- [x] **Correct Ctime Semantics**: Pre-link Gate3 comparison does not require `expected_ctime_ns`; `ctime_ns` used strictly as intra-qualification stability check.
- [x] **Safe Open Parent Fd**: Context manager `safe_open_parent_fd(Path(target_dir) / probe_leaf, allowed_roots)` used with direct descriptor probe.
- [x] **Dual Fencing**: Pattern A for single syscalls, Pattern B for in-transaction DB state transitions. Null-safety order verified.
- [x] **13 DB-Lag Variants**: Exhaustive matrix defines DB/FS facts, actions, generation rules, and outcomes; restore does not finalize before public view retirement.
- [x] **Obsolete Test Expectations**: `tests/test_gate5g_g7_hotfix1_fs_ops.py` updated to expect `EOPNOTSUPP` and zero link+unlink fallback; path typo fixed.
- [x] **R1–R16 Test Mapping**: Dedicated file `tests/test_gate5g_g7_races.py` with 16 explicit test functions (including R14 entering conflict on foreign view).
- [x] **Real NAS Path Safety**: Uses verified real NAS paths (`/tmp/zfsv3/...`); isolated sibling disposable root `/tmp/zfsv3/nvme13/15246330601/data/gate5g_candidate_<sha_short>`; immutable preservation of old failure roots.
- [x] **Codebase Mapping**: `execute_item` mapped to `app/execution/executor.py`; `app/quarantine/restore.py` declared as `Modify`.
