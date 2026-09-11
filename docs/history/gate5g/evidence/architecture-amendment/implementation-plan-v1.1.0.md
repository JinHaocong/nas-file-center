# Gate5-G / G7 Transactional Mutation Implementation Plan (v1.1.0)
# Final Executable TDD Specification: Authoritative Anchor + Candidate Qualification + Write-Once Capture + Lease Discipline

**Document Version:** 1.1.0  
**Date:** 2026-09-11  
**Target Release:** NAS File Center v0.3.5  
**Branch:** `v0.3.5-gate5c-hotfix4`  
**Baseline Plan HEAD:** `98dfb6abad465363e976c61bbb038225f1aa60d4`  
**Frozen Architecture HEAD:** `0ddf932747021578f08843c5069ef88a461d493f`  
**Production Code Baseline HEAD:** `c32d0778c59add81e0c296d6f73aa66bc403c04f`  
**Status:** IMPLEMENTATION PLAN v1.1 COMPLETE — PENDING INDEPENDENT IMPLEMENTATION-PLAN REVIEW (PRODUCTION IMPLEMENTATION STRICTLY NOT YET AUTHORIZED)  

---

## 1. Executive Summary & Superpowers TDD Flow

This document provides the executable, task-by-task engineering plan for implementing **Gate5-G / G7 Transactional Mutation** under the approved, frozen **Revision 3.1 Architecture Amendment** (`0ddf932`).

### 1.1 Frozen Architecture Invariants (Zero Redesign)
The following foundational decisions are **CLOSED** and must be strictly implemented without divergence:
1. **Authoritative Persistent Private Anchor**: In `COMPAT_TRANSACTIONAL` mode, payload resides at `<quarantine_root>/.tx/entry-<id>/attempt-<gen>/anchor`. It remains authoritative for the entire active/restorable lifecycle.
2. **Presentation-Only Public Quarantine View**: The public quarantine path is strictly a convenience hard link; corruption/replacement never imperils the authoritative payload.
3. **Candidate Anchor Qualification (P0-1)**: Linking does not confer authority. Candidate anchor is validated against Gate3 frozen identity (descriptor-bound streaming SHA256, size, device, inode, mode, freshness) before publication or capture.
4. **Capture-by-Rename Source Retirement**: Public source pathname is retired via atomic ordinary `rename()` into an exclusive private slot. Post-capture classification determines outcome; foreign objects are preserved in place.
5. **Write-Once Capture Slot & Generation Allocation (P0-2)**: Monotonic generation allocation under SQLite `BEGIN IMMEDIATE`, committed before attempt directory creation; each generation owns exactly one write-once slot.
6. **Zero Payload-Bearing Unlink (P0-3)**: Unlinking anchors, captured sources, foreign objects, or unknown inodes is strictly forbidden in COMPAT mode.
7. **Per-Mutation Lease Discipline (P0-4)**: Lease renewed and asserted before every payload-affecting filesystem call, bounding stale workers to at most one non-destructive syscall.
8. **Preserve-in-Place for Foreign/Unknown Inodes (P0-5)**: Preserved in their original attempt slot without re-renaming or unsafe restore.
9. **Option DB-2 Schema & Legacy Compatibility (P1-1)**: Minimal explicit durable fields; legacy rows without anchors fail closed on COMPAT.
10. **COMPAT Purge Safety Gate (P1-2)**: Purge operations on `ACTIVE_COMPAT` entries fail closed.
11. **Single Reconciliation Hierarchy**: Low-level quarantine transaction truth resolves first; higher layers (`_reconcile_executing_item`, `WorkJob`, `OperationJournal`) consume resolved facts.

### 1.2 Strict TDD Lifecycle
Once production implementation is explicitly authorized by the project owner, execution will follow the mandatory Superpowers cycle:
```text
RED: Enumerate & write failing unit/integration tests for each task
  ↓
GREEN: Implement minimal production code to pass the tests
  ↓
REFACTOR: Clean up and harden while keeping all tests GREEN
  ↓
Focused Regression: Run task-relevant quarantine, dedupe, and recovery test suites
  ↓
Full Regression: Run complete test suite across entire project
  ↓
Frontend Validation: Typecheck, test, and build frontend (no source changes)
  ↓
Clean Candidate Build: Build Docker image nas-file-center:0.3.5-gate5g-<new-sha>
  ↓
Real NAS Validation: G0 full restart & zfuse execution under sudo
```

---

## 2. Codebase Reality Map & Existing Authorities

Inspection of production baseline `c32d0778c59add81e0c296d6f73aa66bc403c04f` establishes the concrete foundation:

| Component / File | Current Implementation Reality | Target Role in v1.1 Implementation |
| :--- | :--- | :--- |
| [`app/models.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/models.py#L142-L175) | `QuarantineEntry` contains `id`, `original_path`, `quarantine_path`, `state`, `size`, `content_hash`, `device`, `inode`, `last_error`. | Add DB-2 fields: `tx_token`, `tx_phase`, `authoritative_anchor_path`, `active_attempt_generation`. |
| [`app/db.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/db.py#L71-L165) | `init_db()` uses `_db_init_lock`, SQLite table inspection, automatic SQLite online backup, and `ALTER TABLE ... ADD COLUMN`. | Add idempotent migration for `quarantine_entries` columns and indexes with automatic backup. |
| [`app/fs_ops.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/fs_ops.py#L446-L550) | `rename_noreplace` & `rename_noreplace_at` execute single-call fallback with TOCTOU `os.link` + `os.unlink`. | Decommission unsafe check-then-unlink fallback; fail closed with `EOPNOTSUPP` on unsupported filesystems. |
| [`app/quarantine/paths.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/paths.py#L131-L141) | `safe_quarantine_hash` implements streaming SHA256 chunking (1MiB default). | Reused for hash streaming, wrapped by descriptor-bound qualification. |
| [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py#L510-L570) | `gather_reconcile_evidence` & `_validate_evidence` define Gate3 frozen physical identity & freshness check. | Reused as the authoritative qualification model. |
| [`app/batch_utilities/empty_dir_quarantine.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/empty_dir_quarantine.py#L90-L133) | `safe_open_parent_fd` implements robust component-by-component traversal using `O_RDONLY \| O_DIRECTORY \| O_NOFOLLOW`. | Reused directly for ancestor path traversal and descriptor-relative operations. |
| [`app/tasks/recovery.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/recovery.py#L29-L60) | `assert_active_worker_lease(session, worker_id)` checks `TaskLock` row 1 with 30s timeout. | Extended with `renew_and_assert_worker_lease()` for Per-Mutation Lease Fencing Discipline. |
| [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py#L580-L660) | `_reconcile_executing_item` reconciles crash items; `execute_item` runs un-fenced filesystem calls. | Refactor `_reconcile_executing_item` to consume resolved `QuarantineEntry` state; inject per-mutation lease fences into execution loop. |
| [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py#L3595-L3650) | `reconcile_startup_entries` runs independently on API startup. | Defer transactional entries (`tx_phase IS NOT NULL`) to Worker lease recovery. |
| [`app/service.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py#L4000-L4050) | `purge_quarantine_entry` deletes quarantine entries. | Add capability guard refusing purge on `ACTIVE_COMPAT` entries. |

---

## 3. Gate3 Frozen Physical Identity & SHA256 Authority Binding

### 3.1 Clarification of Complete Gate3 Authority
In the existing codebase ([`app/tasks/handlers.py::gather_reconcile_evidence`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py#L510-L535)), Gate3 frozen authority consists of:
1. Object mode verification: `stat.S_ISREG(st.st_mode)`.
2. Initial physical stat snapshot: `st_dev`, `st_ino`, `st_size`, `st_mtime_ns`, `st_ctime_ns`.
3. Streaming cryptographic hash: 1MiB chunked SHA256.
4. Post-hash stat snapshot: Re-verification that `st_dev`, `st_ino`, `st_size`, `st_mtime_ns`, and `st_ctime_ns` are strictly unchanged during hashing (detecting concurrent mutation).

### 3.2 Descriptor-Bound Candidate Qualification Algorithm
Candidate Anchor Qualification must execute strictly relative to an opened, descriptor-bound file handle without pathname re-open races:
```python
def qualify_candidate_anchor_fd(
    candidate_fd: int,
    expected_dev: int,
    expected_ino: int,
    expected_size: int,
    expected_hash: str,
    expected_mtime_ns: int | None = None,
) -> bool:
    # 1. Pre-hash stat check
    st_before = os.fstat(candidate_fd)
    if not stat.S_ISREG(st_before.st_mode):
        return False
    if st_before.st_dev != expected_dev or st_before.st_ino != expected_ino or st_before.st_size != expected_size:
        return False
    if expected_mtime_ns is not None and getattr(st_before, "st_mtime_ns", int(st_before.st_mtime * 1e9)) != expected_mtime_ns:
        return False

    # 2. Streaming SHA256 over descriptor
    h = hashlib.sha256()
    os.lseek(candidate_fd, 0, os.SEEK_SET)
    while chunk := os.read(candidate_fd, 1024 * 1024):
        h.update(chunk)
    actual_hash = h.hexdigest()
    if actual_hash != expected_hash:
        return False

    # 3. Post-hash stat verification (mutation detection)
    st_after = os.fstat(candidate_fd)
    if (
        st_after.st_dev != st_before.st_dev
        or st_after.st_ino != st_before.st_ino
        or st_after.st_size != st_before.st_size
        or getattr(st_after, "st_mtime_ns", int(st_after.st_mtime * 1e9)) != getattr(st_before, "st_mtime_ns", int(st_before.st_mtime * 1e9))
        or getattr(st_after, "st_ctime_ns", int(st_after.st_ctime * 1e9)) != getattr(st_before, "st_ctime_ns", int(st_before.st_ctime * 1e9))
    ):
        return False

    return True
```
- **Zero Re-Open Race**: All checks and hashing run on `candidate_fd`.
- **Zero Blake3**: Strictly SHA256.

---

## 4. Unambiguous Candidate -> Authoritative Path Promotion Model

To eliminate any ambiguity between `candidate_anchor` and `anchor`:

### 4.1 Single Immutable Path
The candidate anchor is created directly at its permanent, immutable authoritative location:
```text
<quarantine_root>/.tx/entry-<entry_id>/attempt-<gen_id>/anchor
```
- In Phase 1A, `os.link(source, anchor)` creates this file. At this stage, it is considered a **Candidate Anchor** in status `tx_phase = 'candidate_created'`.
- In Phase 1B, `qualify_candidate_anchor_fd()` inspects this file.
- Upon successful qualification, the SQLite transaction commits:
  ```python
  entry.authoritative_anchor_path = str(anchor_path)
  entry.tx_phase = 'authoritative_anchored'
  ```
- **Zero Payload Movement**: There is NO rename, NO move, and NO unlinking of the anchor.
- The path stored in `entry.authoritative_anchor_path` is immutable for the remaining life of the entry.

---

## 5. Generation Allocation & Write-Once Slot Invariants

Safety against ordinary `rename()` overwrite stems from **generational namespace ownership by construction**, NOT from check-then-rename:

1. **Transactional Generation Allocation**:
   - Monotonically increment `active_attempt_generation` under SQLite `BEGIN IMMEDIATE`:
     $$	ext{generation} \leftarrow 	ext{entry.active\_attempt\_generation} + 1$$
   - The generation number is **COMMITTED** to the database before the attempt directory is created on disk.
   - Generations never decrement, never roll back, and are never reused.
2. **Exclusive Directory Creation**:
   - Worker creates `<quarantine_root>/.tx/entry-<entry_id>/attempt-<generation>/` using `os.mkdir()`.
3. **Write-Once Capture Slot**:
   - Each attempt directory contains exactly one capture target: `attempt-<generation>/captured-source`.
   - A worker attempt is authorized to issue **at most ONE** `os.rename(source, captured-source)` call.
   - If `captured-source` already exists on disk (from crash or prior execution):
     - **NO RENAME IS ISSUED**.
     - The reconciler executes **CLASSIFICATION ONLY**.
     - If a subsequent retry requires capturing the source pathname again, it MUST allocate a **NEW generation** with its own distinct attempt directory.

---

## 6. `fs_ops` Compatibility Fallback Caller Matrix & Decommissioning

### 6.1 Caller Audit Matrix

| Caller Function / Location | Operation Type | Native RENAME_NOREPLACE Path | COMPAT Regular File Path | COMPAT Unsupported Inode (Symlink/Dir/Special) | Action on Native Failure |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `app/execution/executor.py::130` | Single file rename | Single-syscall atomic rename | Reject (`EOPNOTSUPP`) | Reject (`EOPNOTSUPP`) | Raise `EOPNOTSUPP` (no unsafe fallback) |
| `app/execution/executor.py::164` | Single file move | Single-syscall atomic rename | Reject (`EOPNOTSUPP`) | Reject (`EOPNOTSUPP`) | Raise `EOPNOTSUPP` (no unsafe fallback) |
| `app/execution/executor.py::203` | Single file undo | Single-syscall atomic rename | Reject (`EOPNOTSUPP`) | Reject (`EOPNOTSUPP`) | Raise `EOPNOTSUPP` (no unsafe fallback) |
| `app/execution/executor.py::429` | Restore empty dir | Single-syscall atomic rename | Reject (`EOPNOTSUPP`) | Reject (`EOPNOTSUPP`) | Raise `EOPNOTSUPP` (no unsafe fallback) |
| `app/batch_utilities/empty_dir_quarantine.py::147` | Empty dir quarantine | Single-syscall atomic rename | Reject (`EOPNOTSUPP`) | Reject (`EOPNOTSUPP`) | Raise `EOPNOTSUPP` (no unsafe fallback) |
| `app/batch_utilities/empty_dir_quarantine.py::263` | Empty dir restore | Single-syscall atomic rename | Reject (`EOPNOTSUPP`) | Reject (`EOPNOTSUPP`) | Raise `EOPNOTSUPP` (no unsafe fallback) |
| `app/service.py::3726` | Legacy quarantine restore | Single-syscall atomic rename | Reject (`EOPNOTSUPP`) | Reject (`EOPNOTSUPP`) | Raise `EOPNOTSUPP` (use transactional restore) |
| `app/tasks/handlers.py` (quarantine execution) | Dedupe file quarantine | Single-syscall atomic rename | **Transactional Mutation Engine** (`app/quarantine/transaction.py`) | Reject (`EOPNOTSUPP`) | Executes 4-phase transaction |

### 6.2 Decommissioning the Unsafe Fallback
- The old `_execute_safe_noreplace_fallback_at()` and `_execute_safe_noreplace_fallback()` functions in [`app/fs_ops.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/fs_ops.py) are **COMPLETELY REMOVED**.
- If `rename_noreplace()` or `rename_noreplace_at()` is called on a filesystem lacking native `RENAME_NOREPLACE`, it raises:
  ```python
  raise OSError(errno.EOPNOTSUPP, "Atomic no-replace rename not supported; legacy link+unlink fallback decommissioned for data safety. Use transactional mutation engine.")
  ```
- File quarantine on `COMPAT_TRANSACTIONAL` routes exclusively through the dedicated transactional engine.

---

## 7. API Startup Reconciler Deferral & Single Authority Convergence

### 7.1 Elimination of API-Worker Race
Currently, [`app/service.py::reconcile_startup_entries`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py#L3595) executes on FastAPI startup without a worker lease.

### 7.2 Strict Deferral Rule
In `_reconcile_single_transitional_entry(entry_id)`:
```python
if entry.tx_phase is not None:
    # Transactional entry: DO NOT MUTATE FROM API THREAD!
    # Defer exclusively to Worker lease reconciliation.
    return {
        "id": entry.id,
        "state": entry.state,
        "tx_phase": entry.tx_phase,
        "reconciled": False,
        "reason": "Transactional entry deferred to worker lease reconciliation",
    }
```
- Only legacy entries (`tx_phase IS NULL`) undergo legacy read-only inspection.
- The Worker lease reconciler (`reconcile_quarantine_transactions`) is the **sole mutation authority** for all transactional entries.

---

## 8. Exhaustive State vs `tx_phase` Persisted Matrix

| Lifecycle State | `QuarantineEntry.state` | `QuarantineEntry.tx_phase` | `authoritative_anchor_path` | `active_attempt_generation` | Physical Filesystem Reality |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Legacy Active Row** | `'active'` | `NULL` | `NULL` | `1` | Pre-amendment quarantine path exists. |
| **Legacy Restored Row** | `'restored'` | `NULL` | `NULL` | `1` | Pre-amendment restored path exists. |
| **Preparing** | `'preparing'` | `'preparing'` | `NULL` | $G$ | Intent recorded; attempt directory created. |
| **Candidate Created** | `'preparing'` | `'candidate_created'` | `NULL` | $G$ | Candidate anchor linked at `.tx/.../anchor`. |
| **Authoritative Anchored**| `'preparing'` | `'authoritative_anchored'`| `.tx/.../anchor` | $G$ | Anchor qualified against Gate3; authoritative. |
| **Public Published** | `'preparing'` | `'public_published'` | `.tx/.../anchor` | $G$ | Public view linked to anchor. |
| **Source Captured Expected**| `'preparing'` | `'source_captured_expected'`| `.tx/.../anchor`| $G$ | Source renamed to `captured-source`; inode matches anchor. |
| **Foreign Captured Conflict**| `'conflict'` | `'conflict'` | `.tx/.../anchor` | $G$ | Foreign file captured; preserved in place; conflict logged. |
| **Active (ACTIVE_COMPAT)** | `'active'` | `'active'` | `.tx/.../anchor` | $G$ | Steady state: anchor, public view, and capture link exist. |
| **Restoring** | `'restoring'` | `'restoring'` | `.tx/.../anchor` | $G_{	ext{res}}$ | Restore intent committed; restore attempt dir created. |
| **Restore Published** | `'restoring'` | `'restore_published'` | `.tx/.../anchor` | $G_{	ext{res}}$ | Original path linked to anchor. |
| **Restore View Captured** | `'restoring'` | `'restore_view_captured'`| `.tx/.../anchor`| $G_{	ext{res}}$ | Public quarantine view renamed into restore attempt slot. |
| **Restored** | `'restored'` | `'restored'` | `.tx/.../anchor` | $G_{	ext{res}}$ | Steady state: original path active; anchor intact. |
| **Conflict (Pre-Anchor)** | `'conflict'` | `'conflict'` | `NULL` | $G$ | Qualification mismatch; candidate preserved in place. |

---

## 9. Per-Mutation Lease Renewal & Fencing API

### 9.1 The `renew_and_assert_worker_lease()` API
In [`app/tasks/recovery.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/recovery.py):
```python
def renew_and_assert_worker_lease(
    session: Any,
    worker_id: str,
    now: datetime | None = None,
    timeout_seconds: float = WORKER_LEASE_TIMEOUT_SECONDS,
) -> TaskLock:
    if now is None:
        now = utcnow()
    lock = assert_active_worker_lease(session, worker_id, now=now, timeout_seconds=timeout_seconds)
    lock.acquired_at = now
    session.flush()
    return lock
```

### 9.2 Mutation Call Classification

| Filesystem Call | Classification | Payload-Affecting? | Guard Required |
| :--- | :--- | :--- | :--- |
| `os.link(src, candidate_anchor)` | Phase 1A Candidate Link | **YES** | `renew_and_assert_worker_lease` |
| `os.link(anchor, public_dst)` | Phase 2 Public Link | **YES** | `renew_and_assert_worker_lease` |
| `os.rename(src, captured-source)`| Phase 3 Source Capture | **YES** | `renew_and_assert_worker_lease` |
| `os.link(anchor, original_path)` | Phase R2 Restore Link | **YES** | `renew_and_assert_worker_lease` |
| `os.rename(pub_q, captured-view)` | Phase R3 View Capture | **YES** | `renew_and_assert_worker_lease` |
| `os.mkdir(attempt_dir)` | Namespace Preparation | **NO** | Standard session assert |
| `open(attempt-meta.json, "w")` | Metadata logging | **NO** | Standard session assert |
| `os.rmdir(empty_dir)` | Empty directory removal | **NO** | Standard session assert |
| `os.fstat(fd)` / `hashlib` | Read-only qualification | **NO** | None |

---

## 10. Symmetrical Restore Architecture & Invariants

Restore is a first-class transactional citizen:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              Symmetrical Restore Flow                                  │
└───────────────────────────────────┬────────────────────────────────────────────────────┘
                                    │
    Phase R1: Restore Intent        │ 1. SQLite BEGIN IMMEDIATE: assert lease
                                    │ 2. Allocate restore_generation = active_gen + 1
                                    │ 3. State = 'restoring', Phase = 'restoring'
                                    ▼
    Phase R2: Original Publication  │ 4. renew_and_assert_worker_lease()
                                    │ 5. os.link(authoritative_anchor, original_path) via dir_fd
                                    │    * If occupied: raises FileExistsError (EEXIST) -> abort
                                    │ 6. Commit Phase = 'restore_published'
                                    ▼
    Phase R3: Public View Capture   │ 7. renew_and_assert_worker_lease()
                                    │ 8. os.rename(quarantine_path, restore_attempt/captured-view)
                                    │ 9. Classify captured view (expected vs foreign)
                                    │    * If foreign: preserve in place, mark conflict
                                    │ 10. Commit Phase = 'restore_view_captured'
                                    ▼
    Phase R4: Finalize Restored     │ 11. SQLite commit: State = 'restored', Phase = 'restored'
                                    │ 12. Authoritative anchor remains 100% INTACT on disk.
```

---

## 11. Single Reconciliation Hierarchy & Phase-Action Table

When a worker acquires/takes over a lease, reconciliation resolves layers in strict order:
`Quarantine Transaction Truth` $ightarrow$ `_reconcile_executing_item` $ightarrow$ `recover_interrupted_jobs` $ightarrow$ `OperationJournal`.

| `tx_phase` at Crash | Observed Filesystem Truth | Reconciler Action | Next `tx_phase` | Next `state` | `BatchPlanItem` Result |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `preparing` | No anchor | Abandon attempt dir | `preparing` | `conflict` | `failed` |
| `candidate_created` | Candidate anchor on disk | Qualify candidate against Gate3 | If valid: `authoritative_anchored`; else: `conflict` | `preparing` or `conflict` | `failed` |
| `authoritative_anchored`| Anchor valid; no public view | Resume Phase 2 (allocate new generation) | `public_published` | `preparing` | In-progress |
| `public_published` | Public view linked; capture pending | Resume Phase 3 (allocate new generation) | `source_captured_expected` | `preparing` | In-progress |
| `source_captured_expected`| Source captured; active pending | Advance to active steady state | `active` | `active` | `completed` |
| `active` | Anchor & view intact | Steady state (no-op) | `active` | `active` | `completed` |
| `restoring` | Original path absent | Retry Phase R2 (allocate new gen) | `restore_published` | `restoring` | In-progress |
| `restore_published` | Original path linked; view capture pending | Resume Phase R3 (allocate new gen) | `restore_view_captured` | `restoring` | In-progress |
| `restore_view_captured`| View captured; restore finalize pending| Commit restored state | `restored` | `restored` | `completed` |
| `restored` | Original path intact; anchor intact | Steady state (no-op) | `restored` | `restored` | `completed` |
| `conflict` | Preserved attempt artifacts | Preserved in place (no-op) | `conflict` | `conflict` | `failed` |
| `legacy` | Unanchored row on COMPAT | Fail closed (`EOPNOTSUPP`) | `legacy` | `legacy` | `failed` |

---

## 12. Comprehensive Strict TDD Test Suite (45+ Test Cases)

The implementation plan establishes tests across 9 distinct test files:

### Test File Inventory:
1. `tests/test_compat_db2_migration.py` (Family G)
2. `tests/test_compat_qualification.py` (Family A)
3. `tests/test_compat_generation.py` (Family B)
4. `tests/test_compat_capture.py` (Family C)
5. `tests/test_compat_lease_fencing.py` (Family D)
6. `tests/test_compat_fs_ops_matrix.py` (Caller matrix)
7. `tests/test_compat_quarantine_orchestration.py` (Orchestrator)
8. `tests/test_compat_restore.py` (Family F)
9. `tests/test_compat_purge_gate.py` (Family H)
10. `tests/test_compat_reconciliation.py` (Single authority)
11. `tests/test_compat_crash_matrix.py` (Family E: C0–C11)

---

## 13. DB-2 Migration Implementation & Idempotency Specification

### 13.1 Changes in `app/db.py::init_db()`
```python
# In init_db():
expected_qe_cols = [
    ("tx_token", "VARCHAR(64)"),
    ("tx_phase", "VARCHAR(32)"),
    ("authoritative_anchor_path", "TEXT"),
    ("active_attempt_generation", "INTEGER DEFAULT 1 NOT NULL"),
]
# If missing, backup_database() runs, then:
for col, ctype in missing_qe_cols:
    conn.execute(text(f"ALTER TABLE quarantine_entries ADD COLUMN {col} {ctype}"))
conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quarantine_entries_tx_token ON quarantine_entries(tx_token)"))
conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quarantine_entries_tx_phase ON quarantine_entries(tx_phase)"))
```

---

## 14. Purge & Retention Safety Gate Caller Audit

All purge invocation points must be guarded:
1. **HTTP Endpoint** ([`app/service.py::purge_quarantine_entry`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py#L4000)):
   ```python
   if entry.authoritative_anchor_path:
       raise HTTPException(status_code=400, detail="ACTIVE_COMPAT entries are not purgeable under Gate5-G")
   ```
2. **Batch Purge Task** ([`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py)):
   Fails closed with `EOPNOTSUPP` if item references a COMPAT entry with an authoritative anchor.
3. **Startup Purging Reconciler** ([`app/service.py::_reconcile_single_transitional_entry`](file:///Users/Kerwin/MyProject/nas-file-center/app/service.py#L3638)):
   If `tx_phase IS NOT NULL`, defer to worker lease reconciliation.

---

## 15. Real NAS Acceptance Protocol on `zfuse`

Validation will occur on `极空间 NAS (Linux amd64, zfuse.zfsv3)` within:
```bash
TEST_ROOT="/mnt/zfpool/test_gate5g_compat_$(date +%s)"
```
### Pre-Flight Safety Checks:
1. Confirm `$TEST_ROOT` does not match `/mnt/zfpool/data*` or `/mnt/zfpool/config*`.
2. Confirm filesystem is `fuse.zfuse.zfsv3`: `stat -f -c %T "$TEST_ROOT"`.
3. Assert source and quarantine are on identical `st_dev`.
4. Establish sentinel file `/mnt/zfpool/sentinel.txt` with SHA256; verify untouched post-test.
5. All execution commands use `sudo`.

---

## 16. Frontend Validation Only

Frontend architecture remains CLOSED. Validation requires:
1. `npm run typecheck`
2. `npm run test`
3. `npm run build`

---

## 17. Superpowers Executable Task Breakdown

---

### Task 1: DB-2 Schema Migration & Legacy Row Compatibility

**Files:**
- Create: `tests/test_compat_db2_migration.py`
- Modify: `app/models.py`, `app/db.py`
- Test: `tests/test_compat_db2_migration.py`

**Interfaces:**
- Consumes: Existing SQLite database connection and `QuarantineEntry` model.
- Produces: `QuarantineEntry` model with `tx_token`, `tx_phase`, `authoritative_anchor_path`, `active_attempt_generation`.

- [ ] Write exact failing test in `tests/test_compat_db2_migration.py`:
  - `test_init_db_adds_db2_columns_and_creates_backup_on_upgrade`
  - `test_init_db_is_idempotent_on_second_run`
  - `test_legacy_rows_have_null_tx_fields_and_default_generation_one`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_db2_migration.py`
- [ ] State expected RED failure:
  `AssertionError: Column 'tx_token' not found in table 'quarantine_entries'`
- [ ] Write minimal implementation:
  - Add 4 columns to `app/models.py::QuarantineEntry`.
  - Add column inspection, backup trigger, and `ALTER TABLE` execution in `app/db.py::init_db()`.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_db2_migration.py`
- [ ] Refactor: Clean up column definitions and index names.
- [ ] Run focused regression:
  `pytest -v tests/test_quarantine_migration.py tests/test_compat_db2_migration.py`
- [ ] Commit exact files: `app/models.py`, `app/db.py`, `tests/test_compat_db2_migration.py`
- [ ] Commit message: `feat(db): add DB-2 transaction fields to QuarantineEntry with idempotent migration`

---

### Task 2: Candidate Anchor Qualification with Gate3 SHA256 & Physical Inode Binding

**Files:**
- Create: `app/quarantine/transaction.py`, `tests/test_compat_qualification.py`
- Modify: None
- Test: `tests/test_compat_qualification.py`

**Interfaces:**
- Consumes: Opened file descriptor, expected physical stat, expected SHA256 hash.
- Produces: `qualify_candidate_anchor_fd()` returning boolean.

- [ ] Write exact failing test in `tests/test_compat_qualification.py`:
  - `test_qualification_succeeds_when_stat_and_streaming_sha256_match`
  - `test_qualification_fails_when_device_mismatched`
  - `test_qualification_fails_when_inode_mismatched`
  - `test_qualification_fails_when_size_mismatched`
  - `test_qualification_fails_when_hash_mismatched`
  - `test_qualification_fails_when_file_mutated_during_hashing`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_qualification.py`
- [ ] State expected RED failure:
  `ModuleNotFoundError: No module named 'app.quarantine.transaction'`
- [ ] Write minimal implementation:
  - Implement `qualify_candidate_anchor_fd()` in `app/quarantine/transaction.py` implementing pre-stat, 1MiB SHA256 chunk streaming over descriptor, and post-stat verification.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_qualification.py`
- [ ] Refactor: Extract stat tuple comparisons to helper.
- [ ] Run focused regression:
  `pytest -v tests/test_compat_qualification.py`
- [ ] Commit exact files: `app/quarantine/transaction.py`, `tests/test_compat_qualification.py`
- [ ] Commit message: `feat(quarantine): implement descriptor-bound Candidate Anchor Qualification`

---

### Task 3: Generation Allocation & Exclusive Attempt Directory Creation

**Files:**
- Create: `tests/test_compat_generation.py`
- Modify: `app/quarantine/transaction.py`
- Test: `tests/test_compat_generation.py`

**Interfaces:**
- Consumes: SQLAlchemy session, `entry_id`, worker ID, quarantine root path.
- Produces: `allocate_next_generation()`, `create_attempt_directory()`.

- [ ] Write exact failing test in `tests/test_compat_generation.py`:
  - `test_generation_monotonically_increments_under_begin_immediate`
  - `test_generation_never_reused_on_retry`
  - `test_attempt_directory_created_with_0700_permissions`
  - `test_attempt_directory_creation_fails_if_already_exists`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_generation.py`
- [ ] State expected RED failure:
  `AttributeError: module 'app.quarantine.transaction' has no attribute 'allocate_next_generation'`
- [ ] Write minimal implementation:
  - Implement `allocate_next_generation(session, entry_id, worker_id)` using SQLite `BEGIN IMMEDIATE` and updating `entry.active_attempt_generation`.
  - Implement `create_attempt_directory(quarantine_root, entry_id, gen_id)`.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_generation.py`
- [ ] Refactor: Ensure session commits generation before filesystem directory creation.
- [ ] Run focused regression:
  `pytest -v tests/test_compat_generation.py`
- [ ] Commit exact files: `app/quarantine/transaction.py`, `tests/test_compat_generation.py`
- [ ] Commit message: `feat(quarantine): implement monotonic generation allocation and exclusive attempt directories`

---

### Task 4: Write-Once Capture-by-Rename & Post-Capture Classification

**Files:**
- Create: `tests/test_compat_capture.py`
- Modify: `app/quarantine/transaction.py`
- Test: `tests/test_compat_capture.py`

**Interfaces:**
- Consumes: Source parent dir_fd, leaf name, attempt dir_fd, anchor path.
- Produces: `execute_write_once_capture()`, `classify_captured_source()`.

- [ ] Write exact failing test in `tests/test_compat_capture.py`:
  - `test_capture_rename_succeeds_when_slot_vacant`
  - `test_capture_rename_rejected_when_slot_already_occupied`
  - `test_post_capture_classification_expected_when_inode_matches_anchor`
  - `test_post_capture_classification_foreign_when_inode_mismatches_anchor`
  - `test_foreign_captured_file_preserved_in_place_never_unlinked`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_capture.py`
- [ ] State expected RED failure:
  `AttributeError: module 'app.quarantine.transaction' has no attribute 'execute_write_once_capture'`
- [ ] Write minimal implementation:
  - Implement `execute_write_once_capture()` asserting slot vacancy and calling `os.rename()`.
  - Implement `classify_captured_source()`.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_capture.py`
- [ ] Refactor: Verify zero unlink calls exist in classification module.
- [ ] Run focused regression:
  `pytest -v tests/test_compat_capture.py`
- [ ] Commit exact files: `app/quarantine/transaction.py`, `tests/test_compat_capture.py`
- [ ] Commit message: `feat(quarantine): implement write-once capture rename and post-capture classification`

---

### Task 5: Per-Mutation Lease Renewal & Fencing Discipline

**Files:**
- Create: `tests/test_compat_lease_fencing.py`
- Modify: `app/tasks/recovery.py`, `app/quarantine/transaction.py`
- Test: `tests/test_compat_lease_fencing.py`

**Interfaces:**
- Consumes: SQLAlchemy session, `worker_id`.
- Produces: `renew_and_assert_worker_lease()` and lease fences across mutations.

- [ ] Write exact failing test in `tests/test_compat_lease_fencing.py`:
  - `test_renew_and_assert_updates_acquired_at_and_validates_lease`
  - `test_expired_lease_fails_assert_and_aborts_mutation`
  - `test_stale_worker_can_execute_at_most_one_authorized_mutation`
  - `test_second_mutation_fails_immediately_due_to_expired_fence`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_lease_fencing.py`
- [ ] State expected RED failure:
  `ImportError: cannot import name 'renew_and_assert_worker_lease' from 'app.tasks.recovery'`
- [ ] Write minimal implementation:
  - Add `renew_and_assert_worker_lease()` in `app/tasks/recovery.py`.
  - Wire fence checks into transaction execution stages.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_lease_fencing.py`
- [ ] Refactor: Optimize transaction context manager for lease fences.
- [ ] Run focused regression:
  `pytest -v tests/test_task_models_and_migration.py tests/test_compat_lease_fencing.py`
- [ ] Commit exact files: `app/tasks/recovery.py`, `app/quarantine/transaction.py`, `tests/test_compat_lease_fencing.py`
- [ ] Commit message: `feat(tasks): implement renew_and_assert_worker_lease and per-mutation lease fencing`

---

### Task 6: Decommission Unsafe `fs_ops` Fallback & Implement Caller Matrix

**Files:**
- Create: `tests/test_compat_fs_ops_matrix.py`
- Modify: `app/fs_ops.py`
- Test: `tests/test_compat_fs_ops_matrix.py`

**Interfaces:**
- Consumes: `rename_noreplace()`, `rename_noreplace_at()`.
- Produces: Fail-closed `EOPNOTSUPP` behavior on unsupported filesystems without unsafe fallback.

- [ ] Write exact failing test in `tests/test_compat_fs_ops_matrix.py`:
  - `test_rename_noreplace_fails_closed_with_eopnotsupp_when_unsupported`
  - `test_rename_noreplace_at_fails_closed_with_eopnotsupp_when_unsupported`
  - `test_unsafe_link_unlink_fallback_is_completely_unreachable`
  - `test_native_atomic_rename_behavior_preserved_on_supported_fs`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_fs_ops_matrix.py`
- [ ] State expected RED failure:
  `AssertionError: Expected OSError(EOPNOTSUPP), but legacy fallback was reached`
- [ ] Write minimal implementation:
  - Remove `_execute_safe_noreplace_fallback_at` and `_execute_safe_noreplace_fallback` from `app/fs_ops.py`.
  - Directly raise `OSError(errno.EOPNOTSUPP, "Atomic no-replace rename not supported; single-call fallback decommissioned")`.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_fs_ops_matrix.py`
- [ ] Refactor: Clean up unused imports and dead fallback branches.
- [ ] Run focused regression:
  `pytest -v tests/test_compat_fs_ops_matrix.py`
- [ ] Commit exact files: `app/fs_ops.py`, `tests/test_compat_fs_ops_matrix.py`
- [ ] Commit message: `refactor(fs_ops): decommission unsafe fallback and enforce fail-closed EOPNOTSUPP`

---

### Task 7: Transactional Quarantine Execution Orchestration

**Files:**
- Create: `tests/test_compat_quarantine_orchestration.py`
- Modify: `app/tasks/handlers.py`, `app/execution/executor.py`, `app/quarantine/transaction.py`
- Test: `tests/test_compat_quarantine_orchestration.py`

**Interfaces:**
- Consumes: BatchPlanItem quarantine task, worker lease context.
- Produces: Full 4-phase fenced quarantine transaction reaching `ACTIVE_COMPAT`.

- [ ] Write exact failing test in `tests/test_compat_quarantine_orchestration.py`:
  - `test_full_quarantine_transaction_reaches_active_compat_steady_state`
  - `test_candidate_link_failure_aborts_cleanly_without_payload_loss`
  - `test_qualification_mismatch_transitions_to_conflict_and_preserves_candidate`
  - `test_public_link_eexist_transitions_to_conflict_without_overwrite`
  - `test_source_capture_replaces_source_and_leaves_payload_in_anchor`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_quarantine_orchestration.py`
- [ ] State expected RED failure:
  `AssertionError: Expected QuarantineEntry.tx_phase == 'active', got None`
- [ ] Write minimal implementation:
  - Implement `execute_quarantine_transaction()` coordinating Phase 1A through Phase 4 with per-mutation fences.
  - Wire into `app/tasks/handlers.py::execute_item()` for quarantine operations.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_quarantine_orchestration.py`
- [ ] Refactor: Streamline error handling and audit logging.
- [ ] Run focused regression:
  `pytest -v tests/test_compat_quarantine_orchestration.py`
- [ ] Commit exact files: `app/tasks/handlers.py`, `app/execution/executor.py`, `app/quarantine/transaction.py`, `tests/test_compat_quarantine_orchestration.py`
- [ ] Commit message: `feat(execution): orchestrate 4-phase transactional quarantine with lease fences`

---

### Task 8: Symmetrical Restore Engine with Authoritative Anchor & Write-Once View Capture

**Files:**
- Create: `tests/test_compat_restore.py`
- Modify: `app/quarantine/restore.py`, `app/tasks/handlers.py`
- Test: `tests/test_compat_restore.py`

**Interfaces:**
- Consumes: Active `QuarantineEntry` with `authoritative_anchor_path`.
- Produces: Restored file at original path; public view captured; anchor intact.

- [ ] Write exact failing test in `tests/test_compat_restore.py`:
  - `test_restore_publishes_original_from_authoritative_anchor`
  - `test_restore_aborts_with_eexist_if_original_path_occupied`
  - `test_restore_captures_public_view_into_restore_attempt_slot`
  - `test_restore_preserves_foreign_public_view_in_place`
  - `test_restore_finalizes_restored_state_and_leaves_anchor_intact`
  - `test_restore_legacy_row_on_compat_fails_closed_with_eopnotsupp`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_restore.py`
- [ ] State expected RED failure:
  `AttributeError: module 'app.quarantine.restore' has no attribute 'execute_transactional_restore'`
- [ ] Write minimal implementation:
  - Implement `execute_transactional_restore()` in `app/quarantine/restore.py`.
  - Wire into `app/tasks/handlers.py` restore handler.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_restore.py`
- [ ] Refactor: Ensure anchor unlink is strictly omitted.
- [ ] Run focused regression:
  `pytest -v tests/test_compat_restore.py`
- [ ] Commit exact files: `app/quarantine/restore.py`, `app/tasks/handlers.py`, `tests/test_compat_restore.py`
- [ ] Commit message: `feat(restore): implement symmetrical transactional restore from authoritative anchor`

---

### Task 9: Purge & Retention Safety Gate (Zero Payload Unlink)

**Files:**
- Create: `tests/test_compat_purge_gate.py`
- Modify: `app/service.py`, `app/tasks/handlers.py`
- Test: `tests/test_compat_purge_gate.py`

**Interfaces:**
- Consumes: Purge requests on `QuarantineEntry`.
- Produces: Strict fail-closed `EOPNOTSUPP` refusal for `ACTIVE_COMPAT` entries.

- [ ] Write exact failing test in `tests/test_compat_purge_gate.py`:
  - `test_http_purge_endpoint_refuses_active_compat_entries`
  - `test_batch_purge_task_refuses_active_compat_entries`
  - `test_entry_never_marked_purged_while_anchor_exists`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_purge_gate.py`
- [ ] State expected RED failure:
  `AssertionError: Expected HTTP 400 with EOPNOTSUPP, got 200`
- [ ] Write minimal implementation:
  - Add capability check in `app/service.py::purge_quarantine_entry` and `app/tasks/handlers.py`.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_purge_gate.py`
- [ ] Refactor: Standardize error messages.
- [ ] Run focused regression:
  `pytest -v tests/test_compat_purge_gate.py`
- [ ] Commit exact files: `app/service.py`, `app/tasks/handlers.py`, `tests/test_compat_purge_gate.py`
- [ ] Commit message: `feat(purge): enforce safety gate refusing purge on ACTIVE_COMPAT entries`

---

### Task 10: Single Reconciliation Authority & API Startup Deferral

**Files:**
- Create: `tests/test_compat_reconciliation.py`
- Modify: `app/service.py`, `app/tasks/recovery.py`, `app/tasks/handlers.py`
- Test: `tests/test_compat_reconciliation.py`

**Interfaces:**
- Consumes: Transitional quarantine entries, worker recovery trigger.
- Produces: Single recovery authority with API startup deferral.

- [ ] Write exact failing test in `tests/test_compat_reconciliation.py`:
  - `test_api_startup_reconciler_defers_transactional_entries_without_mutation`
  - `test_worker_lease_recovery_reconciles_interrupted_transaction_first`
  - `test_batch_plan_item_reconciler_consumes_quarantine_entry_truth`
  - `test_work_job_and_operation_journal_synchronized_post_reconciliation`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_reconciliation.py`
- [ ] State expected RED failure:
  `AssertionError: Expected API startup reconciler to defer, but entry was mutated`
- [ ] Write minimal implementation:
  - Update `app/service.py::_reconcile_single_transitional_entry()` to check `tx_phase is not None` and defer.
  - Implement `reconcile_quarantine_transactions()` in `app/tasks/recovery.py`.
  - Update `_reconcile_executing_item()` in `app/tasks/handlers.py`.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_reconciliation.py`
- [ ] Refactor: Clean up reconciliation return dictionaries.
- [ ] Run focused regression:
  `pytest -v tests/test_compat_reconciliation.py`
- [ ] Commit exact files: `app/service.py`, `app/tasks/recovery.py`, `app/tasks/handlers.py`, `tests/test_compat_reconciliation.py`
- [ ] Commit message: `feat(recovery): establish single worker reconciliation authority and defer API startup`

---

### Task 11: Comprehensive Crash Recovery (C0–C11 Boundaries)

**Files:**
- Create: `tests/test_compat_crash_matrix.py`
- Modify: `app/quarantine/transaction.py`, `app/tasks/recovery.py`
- Test: `tests/test_compat_crash_matrix.py`

**Interfaces:**
- Consumes: Crashed transaction states (C0 through C11).
- Produces: Deterministic recovery without data loss.

- [ ] Write exact failing test in `tests/test_compat_crash_matrix.py`:
  - `test_crash_c0_pre_intent_recovery`
  - `test_crash_c1_intent_committed_recovery`
  - `test_crash_c1_1_source_replaced_pre_link_recovery`
  - `test_crash_c2_candidate_linked_db_lag_recovery`
  - `test_crash_c2_1_candidate_mismatch_recovery`
  - `test_crash_c2_2_gen_commit_pre_mkdir_recovery`
  - `test_crash_c3_authoritative_anchored_recovery`
  - `test_crash_c4_public_linked_db_lag_recovery`
  - `test_crash_c5_public_committed_recovery`
  - `test_crash_c6_capture_renamed_db_lag_recovery`
  - `test_crash_c6_1_capture_slot_exists_on_retry_recovery`
  - `test_crash_c7_active_committed_zero_unlink_recovery`
  - `test_crash_c8_restore_linked_db_lag_recovery`
  - `test_crash_c9_restore_view_captured_db_lag_recovery`
  - `test_crash_c10_legacy_row_fails_closed_recovery`
  - `test_crash_c11_purge_refused_on_compat_recovery`
- [ ] Run exact pytest command:
  `pytest -v tests/test_compat_crash_matrix.py`
- [ ] State expected RED failure:
  `AssertionError: Expected deterministic recovery for boundary C2, got unhandled exception`
- [ ] Write minimal implementation:
  - Add recovery dispatch handlers for each phase boundary in `app/quarantine/transaction.py`.
- [ ] Run exact focused test command:
  `pytest -v tests/test_compat_crash_matrix.py`
- [ ] Refactor: Deduplicate filesystem fact inspection.
- [ ] Run focused regression:
  `pytest -v tests/test_compat_crash_matrix.py`
- [ ] Commit exact files: `app/quarantine/transaction.py`, `app/tasks/recovery.py`, `tests/test_compat_crash_matrix.py`
- [ ] Commit message: `test(recovery): implement deterministic recovery handlers for C0-C11 crash boundaries`

---

### Task 12: Full Regression Suite & Verification Checkpoint

**Files:**
- Create: None
- Modify: None
- Test: Full project test suite (`tests/`)

**Interfaces:**
- Consumes: Complete project codebase.
- Produces: 100% green test pass across all existing and new test suites.

- [ ] Run full project automated test suite:
  `pytest -v tests/`
- [ ] Confirm output is pristine (0 errors, 0 failures).
- [ ] Run frontend validation:
  - `cd frontend && npm run typecheck`
  - `cd frontend && npm run test`
  - `cd frontend && npm run build`
- [ ] Verify working tree is clean:
  `git status --short`
- [ ] Create walkthrough artifact documenting test results and execution coverage.
- [ ] Commit message: `chore: complete full regression verification for Gate5-G transactional mutation`

---

## 18. Self-Review & Readiness Declaration

Before submitting for Independent Implementation-Plan Review:
- [x] All 16 review findings from v1.0.0 review are closed.
- [x] Every task has explicit Files (Create/Modify/Test), Interfaces, and Checkbox Steps.
- [x] Gate3 authority is grounded in streaming SHA256 and physical stat consistency (no Blake3).
- [x] Candidate anchor path promotion is unambiguous (single immutable path).
- [x] Write-once capture slot safety is proven by generational ownership, not stat checks.
- [x] `fs_ops` caller matrix audits all callers and decommissions the unsafe fallback.
- [x] API startup reconciler deferral prevents races against worker recovery.
- [x] State vs `tx_phase` matrix comprehensively maps all 14 phases.
- [x] Per-mutation lease discipline specifies exact mutation boundaries.
- [x] Restore is specified with dedicated, independent tasks.
- [x] Single reconciliation hierarchy is established.
- [x] Test matrix covers all C0–C11 boundaries and R1–R16 race conditions.
- [x] DB-2 migration is idempotent with automatic online backup.
- [x] Purge safety gate audits all purge sites.
- [x] Real NAS acceptance targets `/mnt/zfpool/test_gate5g_compat/` on `zfuse` under sudo.
- [x] Frontend remains closed with validation commands only.

```text
G7 TRANSACTIONAL MUTATION IMPLEMENTATION PLAN v1.1 COMPLETE
READY FOR FINAL INDEPENDENT IMPLEMENTATION-PLAN REVIEW
```
