# Gate5-G / G7 Transactional Mutation Implementation Plan
# Final Architecture v3.1.0: Authoritative Anchor + Candidate Qualification + Write-Once Capture + Lease Discipline

**Plan Version:** 1.0.0  
**Date:** 2026-09-11  
**Target Release:** NAS File Center v0.3.5  
**Branch:** `v0.3.5-gate5c-hotfix4`  
**Production Baseline HEAD:** `c32d0778c59add81e0c296d6f73aa66bc403c04f`  
**Frozen Architecture Spec:** `docs/superpowers/specs/2026-09-11-gate5g-zfuse-transactional-mutation-architecture-amendment.md` (v3.1.0)  
**Status:** IMPLEMENTATION PLAN AUTHORIZED — STRICT TDD EXECUTION READY (PRODUCTION CODE MODIFICATION NOT YET AUTHORIZED)  

---

## 1. Executive Summary & Frozen Architecture Alignment

This plan defines the engineering execution for **Gate5-G / G7 Transactional Mutation** under the approved, frozen **Revision 3.1 Architecture Amendment** (`0ddf932`).

### 1.1 Frozen Architecture Invariants (Zero Redesign)
The following decisions are **CLOSED** and must be strictly implemented without divergence:
1. **Authoritative Private Anchor**: In `COMPAT_TRANSACTIONAL` mode, payload resides at `<quarantine_root>/.tx/entry-<id>/attempt-<gen>/anchor`. It remains authoritative for the entire active/restorable lifecycle.
2. **Presentation-Only Public Quarantine View**: The public quarantine path is strictly a convenience hard link; corruption/replacement never imperils the authoritative payload.
3. **Candidate Anchor Qualification (P0-1)**: Linking does not confer authority. Candidate anchor is validated against Gate3 frozen identity (SHA256, size, device, inode, mode) before publication or capture.
4. **Capture-by-Rename Source Retirement**: Public source pathname is retired via atomic ordinary `rename()` into an exclusive private slot. Post-capture classification determines outcome; foreign objects are preserved in place.
5. **Write-Once Capture Slot & Generation Allocation (P0-2)**: Monotonic generation allocation under SQLite `BEGIN IMMEDIATE`, committed before attempt directory creation; each generation owns exactly one write-once slot.
6. **Zero Payload-Bearing Unlink (P0-3)**: Unlinking anchors, captured sources, foreign objects, or unknown inodes is strictly forbidden in COMPAT mode.
7. **Per-Mutation Lease Discipline (P0-4)**: Lease asserted before every payload-affecting filesystem call, bounding stale workers to at most one non-destructive syscall.
8. **Preserve-in-Place for Foreign/Unknown Inodes (P0-5)**: Preserved in their original attempt slot without re-renaming or unsafe restore.
9. **Option DB-2 Schema & Legacy Compatibility (P1-1)**: Minimal explicit durable fields; legacy rows without anchors fail closed on COMPAT.
10. **COMPAT Purge Safety Gate (P1-2)**: Purge operations on `ACTIVE_COMPAT` entries fail closed.
11. **Single Reconciliation Hierarchy**: Low-level quarantine transaction truth resolves first; higher layers (`_reconcile_executing_item`, `WorkJob`, `OperationJournal`) consume resolved facts.

### 1.2 Strict TDD Execution Flow
Once implementation is authorized by the project owner, execution will follow the mandatory cycle:
```text
RED: Enumerate & write failing unit/integration tests for each component
  ↓
GREEN: Implement minimal production code to pass the tests
  ↓
REFACTOR: Clean up and harden while keeping all tests GREEN
  ↓
Focused Regression: Run all quarantine, dedupe, and recovery test suites
  ↓
Full Regression: Run complete test suite across entire project
  ↓
Frontend Validation: Verify UI status and quarantine views
  ↓
Clean Candidate Build: Build Docker image nas-file-center:0.3.5-gate5g-<new-sha>
  ↓
Real NAS Validation: G0 full restart & zfuse execution under sudo
```

---

## 2. Codebase Reality Map & Existing Infrastructure

Inspection of production baseline `c32d0778c59add81e0c296d6f73aa66bc403c04f` establishes the concrete foundation:

| Component / File | Current Implementation Reality | Target Role in v3.1 Implementation |
| :--- | :--- | :--- |
| [`app/models.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/models.py#L142-L175) | `QuarantineEntry` contains `id`, `original_path`, `quarantine_path`, `state`, `size`, `content_hash`, `device`, `inode`, `last_error`. | Add DB-2 fields: `tx_token`, `tx_phase`, `authoritative_anchor_path`, `active_attempt_generation`. |
| [`app/db.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/db.py#L71-L165) | `init_db()` uses `_db_init_lock`, SQLite table inspection, automatic SQLite online backup, and `ALTER TABLE ... ADD COLUMN`. | Add idempotent migration for `quarantine_entries` columns and indexes with automatic backup. |
| [`app/fs_ops.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/fs_ops.py#L446-L550) | `rename_noreplace` & `rename_noreplace_at` execute single-call fallback with TOCTOU `os.link` + `os.unlink`. | Refactor to isolate `NATIVE_ATOMIC_NOREPLACE` from `COMPAT_TRANSACTIONAL`; delegate transactional operations to dedicated transaction engine. |
| [`app/quarantine/paths.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/paths.py#L131-L141) | `safe_quarantine_hash` implements streaming SHA256 chunking (1MiB default). | **Authoritative Gate3 Hash Authority**: Reused directly for Candidate Anchor Qualification. |
| [`app/batch_utilities/empty_dir_quarantine.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/empty_dir_quarantine.py#L90-L133) | `safe_open_parent_fd` implements robust component-by-component traversal using `O_RDONLY \| O_DIRECTORY \| O_NOFOLLOW`. | Reused directly for ancestor path traversal and descriptor-relative operations. |
| [`app/tasks/recovery.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/recovery.py#L29-L60) | `assert_active_worker_lease(session, worker_id)` checks `TaskLock` row 1 with 30s timeout. | Reused for Per-Mutation Lease Fencing Discipline. |
| [`app/tasks/handlers.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/tasks/handlers.py#L580-L660) | `_reconcile_executing_item` reconciles crash items; `execute_item` runs un-fenced filesystem calls. | Refactor `_reconcile_executing_item` to consume resolved `QuarantineEntry` state; inject per-mutation lease fences into execution loop. |
| [`app/execution/executor.py`](file:///Users/Kerwin/MyProject/nas-file-center/app/execution/executor.py#L370-L445) | Contains direct `rename_noreplace_at` calls and raw `os.unlink` calls. | Add capability gates preventing COMPAT payload-bearing unlinks. |

---

## 3. Gate3 Frozen Hash Authority Reuse (No Blake3)

### 3.1 Strict SHA256 Authority Binding
- **Code Reality**: In [`app/quarantine/paths.py::safe_quarantine_hash`](file:///Users/Kerwin/MyProject/nas-file-center/app/quarantine/paths.py#L131-L141), Gate3 stores streaming SHA256 hashes:
  ```python
  def safe_quarantine_hash(file_path: Path | str, chunk_size: int = 1024 * 1024) -> str:
      h = hashlib.sha256()
      with open(file_path, "rb") as f:
          while chunk := f.read(chunk_size):
              h.update(chunk)
      return h.hexdigest()
  ```
- **Freeze Rule**: Generic architecture wording ("SHA256 / Blake3") is **grounded strictly in SHA256**. Blake3 will NOT be introduced. Gate3 remains strictly CLOSED.

### 3.2 Candidate Anchor Qualification Logic
In Phase 1B, the engine qualifies the candidate anchor:
```python
def qualify_candidate_anchor(
    candidate_path: Path,
    expected_hash: str,
    expected_size: int,
    expected_dev: int,
    expected_ino: int,
) -> bool:
    st = os.lstat(candidate_path)
    if not stat.S_ISREG(st.st_mode):
        return False
    if st.st_size != expected_size or st.st_dev != expected_dev or st.st_ino != expected_ino:
        return False
    actual_hash = safe_quarantine_hash(candidate_path)
    return actual_hash == expected_hash
```

---

## 4. DB-2 Minimal Migration Plan

### 4.1 Target SQLAlchemy Model Changes
In [`app/models.py::QuarantineEntry`](file:///Users/Kerwin/MyProject/nas-file-center/app/models.py#L142):
```python
class QuarantineEntry(Base):
    __tablename__ = "quarantine_entries"
    # ... existing fields ...
    
    # DB-2 Transaction & Generation Fields
    tx_token: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    tx_phase: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    authoritative_anchor_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    active_attempt_generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
```

### 4.2 Idempotent SQLite Migration in `app/db.py`
Integrated into `init_db()`:
1. Inspect columns of `quarantine_entries`.
2. Detect missing columns:
   ```python
   expected_qe_cols = [
       ("tx_token", "VARCHAR(64)"),
       ("tx_phase", "VARCHAR(32)"),
       ("authoritative_anchor_path", "TEXT"),
       ("active_attempt_generation", "INTEGER DEFAULT 1 NOT NULL"),
   ]
   ```
3. If missing columns exist and tables are populated, trigger `backup_database(db_path, backups_dir)`.
4. Execute `ALTER TABLE quarantine_entries ADD COLUMN ...` for each missing column.
5. Create indexes:
   ```sql
   CREATE INDEX IF NOT EXISTS ix_quarantine_entries_tx_token ON quarantine_entries(tx_token);
   CREATE INDEX IF NOT EXISTS ix_quarantine_entries_tx_phase ON quarantine_entries(tx_phase);
   ```

### 4.3 Legacy Row Classification & Compatibility Gate
- Pre-existing rows have `tx_phase IS NULL` and `authoritative_anchor_path IS NULL`.
- `tx_phase` is classified as `'legacy'` in business logic.
- **Fail-Closed Gate**: If any operation on `COMPAT_TRANSACTIONAL` attempts to restore or mutate a legacy row without an `authoritative_anchor_path`, it raises:
  ```python
  raise OSError(errno.EOPNOTSUPP, "Legacy quarantine entry lacks authoritative transaction anchor; mutation refused")
  ```

---

## 5. Per-Mutation Lease Fencing Discipline

Every payload-affecting filesystem call is bounded by its own lease assertion under SQLite `BEGIN IMMEDIATE`:

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│              Per-Mutation Lease Fencing Protocol (Strict Progression)            │
├─────────┬─────────────────────────┬──────────────────────────────────────────────┤
│ Step    │ Action Type             │ Detailed Execution                           │
├─────────┼─────────────────────────┼──────────────────────────────────────────────┤
│ Fence 1 │ SQLite BEGIN IMMEDIATE  │ assert_active_worker_lease(session, worker_id)
│         │                         │ Allocate tx_token, generation=1, phase=prep  │
├─────────┼─────────────────────────┼──────────────────────────────────────────────┤
│ Mut 1   │ FS Payload Call (1/3)   │ os.link(source, candidate_anchor) via dir_fd │
├─────────┼─────────────────────────┼──────────────────────────────────────────────┤
│ Check   │ Non-mutating Read       │ qualify_candidate_anchor() [SHA256, stat]    │
├─────────┼─────────────────────────┼──────────────────────────────────────────────┤
│ Fence 2 │ SQLite BEGIN IMMEDIATE  │ assert_active_worker_lease(session, worker_id)
│         │                         │ Commit phase='authoritative_anchored'        │
├─────────┼─────────────────────────┼──────────────────────────────────────────────┤
│ Mut 2   │ FS Payload Call (2/3)   │ os.link(anchor, public_destination) via dir_fd
├─────────┼─────────────────────────┼──────────────────────────────────────────────┤
│ Fence 3 │ SQLite BEGIN IMMEDIATE  │ assert_active_worker_lease(session, worker_id)
│         │                         │ Commit phase='public_published'              │
├─────────┼─────────────────────────┼──────────────────────────────────────────────┤
│ Mut 3   │ FS Payload Call (3/3)   │ os.rename(source, write_once_capture_slot)   │
├─────────┼─────────────────────────┼──────────────────────────────────────────────┤
│ Check   │ Non-mutating Read       │ Classify captured inode (Expected vs Foreign)│
├─────────┼─────────────────────────┼──────────────────────────────────────────────┤
│ Fence 4 │ SQLite BEGIN IMMEDIATE  │ assert_active_worker_lease(session, worker_id)
│         │                         │ Commit state='active' or 'conflict'          │
└─────────┴─────────────────────────┴──────────────────────────────────────────────┘
```

---

## 6. Write-Once Capture Slot & Generation Allocation Protocol

### 6.1 Directory & Slot Layout
```text
<quarantine_root>/.tx/
  entry-<entry_id>/
    attempt-<generation_id>/
      candidate_anchor             # Established in Phase 1
      anchor                       # Authoritative anchor (qualified)
      captured-source              # WRITE-ONCE capture slot
      attempt-meta.json            # Durable attempt record
```

### 6.2 Write-Once Enforcement API
A dedicated module `app/quarantine/transaction.py` will enforce:
```python
def execute_write_once_capture(
    src_parent_fd: int,
    source_leaf: str,
    attempt_dir_fd: int,
    captured_leaf: str = "captured-source",
) -> None:
    # 1. Enforce write-once: if destination slot already exists, reject rename!
    try:
        os.stat(captured_leaf, dir_fd=attempt_dir_fd, follow_symlinks=False)
        raise FileExistsError(errno.EEXIST, "Write-once capture slot already occupied")
    except FileNotFoundError:
        pass
        
    # 2. Atomic rename from public source into exclusive attempt slot
    os.rename(source_leaf, captured_leaf, src_dir_fd=src_parent_fd, dst_dir_fd=attempt_dir_fd)
```

---

## 7. Zero Payload-Bearing Unlink Implementation & Audit

### 7.1 Existing Deletion Call Audit
The following existing destructive call sites must be guarded:
1. `app/fs_ops.py::rename_noreplace`: Remove fallback `os.unlink(source_name)` when in COMPAT mode.
2. `app/execution/executor.py::execute_item`: Guard `item.operation == "unlink"` to refuse execution if path is inside `quarantine/.tx/`.
3. `app/service.py::purge_quarantine_entry`: Insert capability guard:
   ```python
   if entry.authoritative_anchor_path and is_compat_mode(entry):
       raise HTTPException(status_code=400, detail="ACTIVE_COMPAT entries are not purgeable under Gate5-G")
   ```

### 7.2 Permitted Cleanup Only
- Deletion of non-payload JSON: `attempt-meta.json`.
- `os.rmdir()` on verified empty directories.

---

## 8. Symmetrical Restore Implementation Plan

Restore operations mirror the authoritative transaction in reverse:
1. **Restore Candidate & Intent**:
   - Query `authoritative_anchor_path` from `QuarantineEntry`.
   - SQLite `BEGIN IMMEDIATE`: allocate restore generation, `state = 'restoring'`.
2. **Original Path Publication**:
   - `os.link(authoritative_anchor, original_path)` relative to `target_parent_fd`.
   - If `original_path` occupied $ightarrow$ `FileExistsError` (`EEXIST`), restore aborts cleanly.
3. **Public Quarantine View Retirement**:
   - Atomically rename `quarantine_path` into `<quarantine_root>/.tx/entry-<id>/restore-attempt-<gen>/captured-quarantine-view`.
   - If foreign file was captured $ightarrow$ preserve in place, mark `conflict`.
4. **Finalize Restored**:
   - SQLite commit `state = 'restored'`.
   - Authoritative anchor remains untouched and preserved on disk.

---

## 9. Single Reconciliation Hierarchy

Unified recovery hierarchy ensuring deterministic convergence:
```text
Worker Lease Acquisition (assert_active_worker_lease)
  ↓
[Level 1] Quarantine Transaction Reconciler
  - Evaluates entry.tx_phase and attempt directories on disk:
      * 'preparing': if candidate exists -> qualify or preserve as conflict; else abandon.
      * 'authoritative_anchored': candidate qualified -> resume public publication.
      * 'public_published': public link exists -> resume capture-by-rename (allocate new gen).
      * 'source_captured': classify captured-source -> advance to 'active' or 'conflict'.
      * 'active': steady state -> zero mutation.
  ↓
[Level 2] BatchPlanItem Reconciler (_reconcile_executing_item)
  - Inspects items in 'executing' state.
  - Queries associated QuarantineEntry:
      * QuarantineEntry == 'active' -> item.state = 'completed'.
      * QuarantineEntry in ('conflict', 'legacy') -> item.state = 'failed'.
  ↓
[Level 3] WorkJob Recovery (recover_interrupted_jobs)
  - Updates WorkJob status to 'completed' or marks WORKER_INTERRUPTED.
  ↓
[Level 4] OperationJournal Logging
  - Commits audit record for the reconciled mutation.
```

---

## 10. Comprehensive Strict TDD Test Suite Plan

### Mandatory Test Families (to be created in `tests/test_compat_transactional.py`):

#### Family A: Candidate Anchor Qualification Tests
- `test_candidate_anchor_qualified_when_hash_and_inode_match`
- `test_candidate_anchor_fails_when_hash_mismatched`
- `test_candidate_anchor_fails_when_size_mismatched`
- `test_candidate_anchor_fails_when_source_replaced_pre_link`
- `test_zero_publication_or_capture_if_candidate_qualification_fails`

#### Family B: Generation Allocation & Write-Once Slot Tests
- `test_generation_monotonically_increments_under_begin_immediate`
- `test_generation_never_reused_after_crash`
- `test_attempt_directory_created_exclusively`
- `test_write_once_capture_slot_rejects_second_rename_if_occupied`
- `test_retry_allocates_new_generation_and_leaves_old_slot_intact`

#### Family C: Capture-by-Rename Semantics Tests
- `test_source_capture_succeeds_when_captured_inode_matches_anchor`
- `test_source_capture_preserves_foreign_file_in_place_when_inode_mismatches`
- `test_source_recreation_after_capture_leaves_new_file_untouched`
- `test_multiple_generations_capture_different_occupants_without_collision`
- `test_foreign_captured_file_is_never_deleted`

#### Family D: Per-Mutation Lease Fencing Tests
- `test_stale_worker_can_execute_at_most_one_authorized_call`
- `test_second_mutation_call_fails_immediately_on_expired_lease`
- `test_stale_db_commit_rejected_by_lease_assertion`

#### Family E: Crash Recovery & Interruption Tests
- `test_crash_c0_pre_intent_recovery`
- `test_crash_c1_intent_committed_recovery`
- `test_crash_c2_candidate_linked_db_lag_recovery`
- `test_crash_c3_anchor_authoritative_recovery`
- `test_crash_c4_public_linked_db_lag_recovery`
- `test_crash_c6_capture_renamed_db_lag_recovery`
- `test_crash_c7_active_committed_zero_unlink_recovery`

#### Family F: Symmetrical Restore Tests
- `test_restore_publishes_from_authoritative_anchor_with_eexist_guard`
- `test_restore_captures_public_quarantine_view_via_rename`
- `test_restore_preserves_foreign_quarantine_view_in_place_on_mismatch`
- `test_restore_leaves_authoritative_anchor_intact`

#### Family G: DB-2 Migration & Legacy Row Compatibility Tests
- `test_db2_migration_adds_columns_and_creates_backup`
- `test_legacy_row_has_null_tx_fields_and_generation_one`
- `test_legacy_row_fails_closed_on_compat_zfuse_mutation`

#### Family H: Purge / Retention Fail-Closed Tests
- `test_purge_refused_on_active_compat_quarantine_entry`
- `test_active_compat_never_marked_purged_while_anchor_exists`

#### Family I: Full Regression Suite Tests
- Run complete test suite: native rename, 6 dedupe policies, Gate3 Freeze/Validate, Gate5-E E4.

---

## 11. Real NAS Acceptance Plan (Future Execution under sudo)

Future real-NAS validation will execute on `极空间 NAS (Linux amd64, zfuse.zfsv3)` within an isolated disposable root:
```bash
TEST_ROOT="/tmp/test_gate5g_compat_$(date +%s)"
sudo mkdir -p "$TEST_ROOT"
```
**Test Phases**:
1. Capability probe confirms `COMPAT_TRANSACTIONAL` admission.
2. Regular file mutation executes Phase 1A through Phase 4.
3. Inode inspection confirms `anchor` and `public_quarantine` share physical inode (`st_ino`).
4. Inspection confirms `captured-source` exists as matching hard link; zero payload loss.
5. Symmetrical restore executes; original path verified; anchor remains intact.
6. Sentinel file verification confirms zero external filesystem mutation.

---

## 12. Candidate Rebuild & Full G0 Restart Rule

- When implementation is completed and independently approved:
- A NEW candidate commit SHA will be generated.
- Candidate Docker image will be built: `nas-file-center:0.3.5-gate5g-<new-sha>`.
- **Gate5-G validation MUST restart from G0.**
- Historical G1–G6 evidence will be retained for audit but cannot be credited to the new candidate.

---

## 13. Deliverable & Review Readiness

```text
G7 TRANSACTIONAL MUTATION IMPLEMENTATION PLAN COMPLETE
READY FOR INDEPENDENT IMPLEMENTATION-PLAN REVIEW
```
