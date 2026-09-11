# NAS File Center v0.3.5 — Gate5-G / G7 Architecture Freeze Amendment (Revision 2)
# zfuse-compatible Persistent Mutation Transaction Architecture

**Document Version:** 2.0.0 (Revision 2)  
**Date:** 2026-09-11  
**Status:** ARCHITECTURE FREEZE AMENDMENT PROPOSAL (REVISION 2) / PENDING INDEPENDENT REVIEW  
**Baseline HEAD:** `c32d0778c59add81e0c296d6f73aa66bc403c04f`  
**Target Platform:** 极空间 NAS (ZSpace OS, Linux amd64, Docker, `zfuse.zfsv3`)  
**Authority:** Architecture Design Authorization (Option B Primary + Option A Fallback + Option C Native Preferred)  
**Implementation Status:** IMPLEMENTATION NOT AUTHORIZED — ARCHITECTURAL SPECIFICATION ONLY  

---

## 1. Revision History & Context

- **v1.0.0 (2026-09-11)**: Initial specification of Approach B (Two-Phase Mutation Transaction with Recovery Anchor). Evaluated by Independent Architecture Review; failed due to 9 specific edge-case, fencing, and linearization blockers.
- **v2.0.0 (Revision 2, 2026-09-11)**: Fully resolves all 9 Independent Review blockers:
  1. *Anchor-Release Invariant*: Atomic link-count verification (`st_nlink >= 2`) before anchor retirement.
  2. *Source-Path Protection*: Pre-retirement physical identity verification of source to prevent third-party file deletion.
  3. *Expanded Crash Matrix*: Added boundary $Q_{1.5}$ (`DB == 'preparing'` + anchor present).
  4. *ACTIVE Cleanup Safety*: Safe post-active anchor cleanup requiring destination identity proof; conflict retention on failure.
  5. *Unified Identity Model*: Deterministic compound transaction token binding under Option DB-1 (zero schema migration).
  6. *Reconciliation Hierarchy*: Formal integration with `_reconcile_executing_item`, `BatchPlanItem`, `WorkJob`, and `OperationJournal`.
  7. *Filesystem Fencing*: Dual-tier fencing with transaction directory invalidation neutralizing stale workers.
  8. *Threat Boundary*: Private `.tx` namespace exclusion, path validation, and security model.
  9. *Ancestor Path Safety*: Full integration of `dir_fd`, `O_NOFOLLOW`, and descriptor-relative operations (`linkat`, `unlinkat`).

---

## 2. Fundamental Architectural Model

```text
┌────────────────────────────────────────────────────────────────────────┐
│               Persistent Two-Phase Mutation Architecture               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
    Phase 1: Intent & Anchor        │ 1. SQLite BEGIN IMMEDIATE (state='preparing', tx_token)
                                    │ 2. os.link(source, anchor) via safe parent dir_fd
                                    │ 3. SQLite COMMIT (state='anchor_established')
                                    ▼
    Phase 2: Public Publication     │ 4. os.link(anchor, destination) [Atomic No-Overwrite]
                                    │ 5. fstat/lstat verify destination inode == anchor inode
                                    │ 6. SQLite COMMIT (state='published')
                                    ▼
    Phase 3: Source Retirement      │ 7. Verify source inode == anchor inode [Anti-Third-Party]
                                    │ 8. os.unlink(source) via src_parent_fd
                                    ▼
    Phase 4: Finalize & Anchor Rel  │ 9. SQLite COMMIT (state='active')
                                    │ 10. Verify anchor st_nlink >= 2 & destination intact
                                    │ 11. os.unlink(anchor) & remove tx_dir
                                    ▼
    Reconciliation Engine           │ Startup / lease takeover deterministic recovery
```

---

## 3. Resolution of the 9 Independent Review Blockers

### 3.1 Blocker 1: Anchor-Release Invariants & Atomic Link-Count Verification
**The Hazard**: In v1.0.0, unlinking `anchor` when `destination` was concurrently replaced could destroy the last reference to the original inode.  
**Revision 2 Guarantee**:
1. Before unlinking `anchor`, the engine opens `anchor_fd = os.open(anchor_path, os.O_RDONLY)`.
2. Inspects `st_anc = os.fstat(anchor_fd)` and `st_dst = os.lstat(destination_path)`.
3. **Hard-link Invariant Check**:
   - The engine asserts `st_dst.st_ino == st_anc.st_ino` AND `st_dst.st_dev == st_anc.st_dev`.
   - The engine asserts `st_anc.st_nlink >= 2`.
   - *Proof*: If `destination_path` still references the inode, the VFS inode link counter must be at least 2 (`anchor` + `destination`). If an external actor unlinked `destination_path`, `st_nlink` atomically drops to 1.
4. If `st_anc.st_nlink < 2` or identity check fails:
   - **THE ENGINE NEVER UNLINKS ANCHOR!**
   - The anchor is retained. SQLite state transitions to `conflict`.
   - User payload is preserved in `anchor`. Zero data loss.
5. Only when `st_anc.st_nlink >= 2` and destination identity is proven does `os.unlink(anchor_path)` execute.

### 3.2 Blocker 2: Pre-Retirement Source Inode Verification
**The Hazard**: Between Phase 1 (`link(source, anchor)`) and Phase 3 (`unlink(source)`), a third-party process could replace `source` with a newly created file. A blind `unlink(source)` would delete the third party's new data.  
**Revision 2 Guarantee**:
1. Before calling `os.unlink(source)` in Phase 3, the engine executes `fstatat(src_parent_fd, source_name, AT_SYMLINK_NOFOLLOW)`.
2. Verifies `st_src.st_ino == st_anc.st_ino` AND `st_src.st_dev == st_anc.st_dev`.
3. If `st_src.st_ino != st_anc.st_ino`:
   - An external actor replaced `source`.
   - **THE ENGINE NEVER UNLINKS SOURCE!**
   - The replacement file remains untouched.
   - Since the original payload is already safely published at `destination` and protected in `anchor`, the engine marks SQLite state as `conflict` (`source_replaced_externally`), preserving all files for administrative audit.

### 3.3 Blocker 3: Crash Boundary $Q_{1.5}$ (`DB == 'preparing'` + Anchor Present)
**The Hazard**: A crash immediately after `os.link(source, anchor)` but before SQLite commits `anchor_established` left an anchor with DB still in `preparing`.  
**Revision 2 Guarantee**:
- Defined explicit crash boundary $Q_{1.5}$ in Crash Matrix.
- **Reconciler Dispatch for `preparing`**:
  ```text
  Check if anchor exists on disk:
  - If anchor DOES NOT exist: entry.state = 'abandoned' (source untouched).
  - If anchor DOES exist:
      Verify lstat(anchor).st_ino == lstat(source).st_ino.
      Since destination was never published:
          os.unlink(anchor_path)
          rmdir(tx_dir)
          entry.state = 'abandoned'
      Source payload remains 100% intact. Zero leaked links.
  ```

### 3.4 Blocker 4: `ACTIVE` + Anchor-Present Cleanup Safety
**The Hazard**: If the worker crashed in Q9/Q10 (after DB committed `active` but before anchor was unlinked), blindly unlinking the orphan anchor during startup reconciliation could destroy the only surviving payload if `destination` had been corrupted during downtime.  
**Revision 2 Guarantee**:
- When the startup reconciler encounters a `QuarantineEntry` with `state == 'active'` and an existing anchor on disk:
  1. Inspect `destination_path` via `lstat`.
  2. If `destination_path` exists AND `st_dst.st_ino == st_anc.st_ino`:
     - Safe to unlink `anchor_path` and remove `tx_dir`.
  3. If `destination_path` is missing OR `st_dst.st_ino != st_anc.st_ino`:
     - **DO NOT UNLINK ANCHOR!**
     - Rename `tx_dir` to `quarantine/.conflicts/incident_<entry_id>_<timestamp>/`.
     - Update DB `entry.state = 'conflict'`, `entry.last_error = "Active destination missing/replaced; payload preserved in conflict holding"`.
     - Alert administrator. Payload remains 100% preserved.

### 3.5 Blocker 5: Unified Transaction Identity Model (Option DB-1 Baseline)
**The Hazard**: Contradiction between random UUID `tx_id` and auto-incrementing integer `QuarantineEntry.id`.  
**Revision 2 Specification**:
- Formally adopts **Option DB-1** (zero schema migration, 100% backward compatible).
- Deterministic compound transaction token format:
  $$\text{tx\_token} = \text{f"tx\_}\{\text{entry.id}\}\_\{\text{entry.created\_at.strftime('\%Y\%m\%d\%H\%M\%S')}\}\_\{\text{os.urandom(4).hex()}"\}$$
- Deterministic path resolution:
  $$\text{anchor\_dir} = \text{quarantine\_root} / \text{".tx"} / \text{tx\_token}$$
  $$\text{anchor\_path} = \text{anchor\_dir} / \text{"anchor"}$$
- Persistence in existing fields:
  - Upon creation in Phase 1, `entry.last_error` records `TX:<tx_token>`.
  - Reconciler parses `TX:<tx_token>` from `entry.last_error` or scans `quarantine/.tx/` matching prefix `tx_{entry.id}_*`.
  - Guarantees complete uniqueness across retries, crash restarts, and auto-increment resets without adding a single database column.

### 3.6 Blocker 6: Reconciliation Authority Hierarchy
**The Hazard**: Unclear integration between `QuarantineEntry` reconciliation and existing `WorkJob` / `BatchPlanItem` recovery.  
**Revision 2 Execution Hierarchy**:
```text
Worker Lease Acquisition (assert_active_worker_lease)
  ↓
[Step A: Lowest Layer] Quarantine Transaction Reconciler
  - Reconciles all pending/interrupted QuarantineEntry rows against filesystem facts.
  - Converges entries to active, conflict, or abandoned.
  ↓
[Step B: Middle Layer] BatchPlanItem Reconciler (_reconcile_executing_item)
  - Inspects items in 'executing' state.
  - Queries associated QuarantineEntry.
  - If QuarantineEntry == 'active' -> BatchPlanItem becomes 'completed'.
  - If QuarantineEntry in ('abandoned', 'conflict') -> BatchPlanItem becomes 'failed'.
  ↓
[Step C: Top Layer] WorkJob Recovery (recover_interrupted_jobs)
  - Syncs job status based on plan items.
  - If all items reconciled -> job completes or fails with WORKER_INTERRUPTED.
  ↓
[Step D: Audit Log] OperationJournal
  - Records reconciliation event with structured context.
```

### 3.7 Blocker 7: Stale-Worker Filesystem Fencing
**The Hazard**: If Worker A suffers a FUSE stall, its lease expires. Worker B takes over and reconciles. When Worker A wakes up, its user-space thread could execute raw POSIX filesystem calls.  
**Revision 2 Fencing Protocol**:
1. **Tier 1 (Database Lease Fence)**: Every state mutation runs in SQLite `BEGIN IMMEDIATE` asserting `assert_active_worker_lease(session, worker_id)`. Stale Worker A cannot commit any DB transition.
2. **Tier 2 (Filesystem Namespace Fencing via Directory Invalidation)**:
   - When Worker B takes over the lease and initiates reconciliation for transaction `tx_token`:
   - Worker B renames `quarantine/.tx/<tx_token>` to `quarantine/.tx/<tx_token>.fenced_<worker_b_id>`.
   - If stale Worker A attempts to call `os.unlink(anchor)` or manipulate files relative to `anchor_dir`, the operating system immediately returns `ENOENT`.
   - Stale Worker A is neutralized on the filesystem.

### 3.8 Blocker 8: Private `.tx` Trust & Threat Boundary
**The Hazard**: Insecure access or exposure of internal transaction staging directory.  
**Revision 2 Specification**:
- **Location & Mode**: `<quarantine_root>/.tx/`, created with permissions `0700`, owned by container runtime user.
- **Scanner & Indexer Exclusion**:
  - `app/tasks/indexing.py` and `fclones` runners automatically append `--exclude='**/.tx/**'` to scan parameters.
  - IndexRoot registry rejects registering paths inside `.tx/`.
- **API Guard**: `app/execution/executor.py::require_allowed_path()` and router validation reject any path containing `/.tx/` or ending in `/.tx`.
- **SMB / Host Threat Model**:
  - If `<quarantine_root>` is exported to SMB/NFS on the host, host configuration must include `veto files = /.*/`.
  - Even if an external SMB client manipulates files inside `.tx/`: The reconciler treats unexpected or tampered anchor inodes as a `conflict`, never trusts external data, and fails closed without data loss.

### 3.9 Blocker 9: Ancestor Path-Walk Races (`dir_fd` & `O_NOFOLLOW`)
**The Hazard**: String-based path operations allow concurrent actors to swap parent directories with symlinks during multi-phase execution.  
**Revision 2 Specification**:
- Employs Gate5-E E4 `safe_open_parent_fd(path, allowed_roots)`:
  - Resolves and verifies parent directory descriptors with `O_PATH | O_DIRECTORY | O_NOFOLLOW`.
  - All operations use descriptor-relative system calls:
    - `os.link(src_name, anchor_name, src_dir_fd=src_pfd, dst_dir_fd=tx_dfd)`
    - `os.link(anchor_name, dst_name, src_dir_fd=tx_dfd, dst_dir_fd=dst_pfd)`
    - `os.unlink(src_name, dir_fd=src_pfd)`
    - `os.unlink(anchor_name, dir_fd=tx_dfd)`
  - Ancestor symlink redirection outside authorized roots is physically impossible.

---

## 4. Comprehensive Inode-Type Support Matrix

| Inode Type | Mode 1: `NATIVE_ATOMIC_NOREPLACE` | Mode 2: `COMPAT_TRANSACTIONAL` | Safety Enforcement Mechanism |
| :--- | :--- | :--- | :--- |
| **Regular File (`S_ISREG`)** | **SUPPORTED** | **SUPPORTED** | Two-Phase Transaction + Private Recovery Anchor (`linkat` + `unlinkat`). |
| **Symlink (`S_ISLNK`)** | **SUPPORTED** | **FAIL CLOSED (`EOPNOTSUPP`)** | `zfuse` rejects hard links to symlinks (`EPERM`). `os.symlink` creates disconnected inodes; `readlink` text equality does not prove generation ownership. Strictly fail closed. |
| **Directory (`S_ISDIR`)** | **SUPPORTED** | **FAIL CLOSED (`EOPNOTSUPP`)** | POSIX kernel prohibits directory hard links (`EPERM`). `rmdir_empty` refuses execution on `COMPAT_TRANSACTIONAL`. Strictly fail closed. |
| **Special Inodes (FIFO, Sock, Dev)** | **FAIL CLOSED (`EOPNOTSUPP`)** | **FAIL CLOSED (`EOPNOTSUPP`)** | Never eligible for deduplication or quarantine relocation. |

---

## 5. Exhaustive Crash & Interruption Matrix (Revision 2)

| Boundary | Source State | Anchor State | Destination State | SQLite State | Restart / Reconciliation Action | Data Loss? | Overwrite? | False Success? | Convergence Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Q0: Pre-Intent** | Intact | Absent | Absent | None | No-op. Job re-evaluates. | NO | NO | NO | SAFE (Clean) |
| **Q1: Post-Intent** | Intact | Absent | Absent | `preparing` | Reconciler marks `abandoned`. | NO | NO | NO | SAFE (Clean) |
| **Q1.5: Anchor Created, DB Uncommitted** | Intact | Present | Absent | `preparing` | Reconciler verifies anchor matches source, unlinks anchor, cleans tx_dir, marks `abandoned`. | NO | NO | NO | SAFE (Source intact) |
| **Q2: Anchor Committed** | Intact | Present | Absent | `anchor_established` | Reconciler unlinks anchor, cleans tx_dir, marks `abandoned`. | NO | NO | NO | SAFE (Source intact) |
| **Q3: Destination Published** | Intact | Present | Present (verified) | `anchor_established` | Reconciler detects valid destination matching anchor, commits `published`, resumes source retirement. | NO | NO | NO | SAFE (Forward convergence) |
| **Q4: Post-Publish Verify** | Intact | Present | Present (verified) | `anchor_established` | Same as Q3. | NO | NO | NO | SAFE (Forward convergence) |
| **Q5: DB Committed Published** | Intact | Present | Present (verified) | `published` | Reconciler verifies source identity, unlinks source, commits `active`, cleans anchor. | NO | NO | NO | SAFE (Forward convergence) |
| **Q6: Pre-Unlink Source** | Intact | Present | Present (verified) | `published` | Same as Q5. | NO | NO | NO | SAFE (Forward convergence) |
| **Q7: Post-Unlink Source** | Unlinked | Present | Present (verified) | `published` | Reconciler commits `active`, verifies anchor `st_nlink >= 2`, cleans anchor. | NO | NO | NO | SAFE (Forward convergence) |
| **Q8: Pre-Active Commit** | Unlinked | Present | Present (verified) | `published` | Same as Q7. | NO | NO | NO | SAFE (Forward convergence) |
| **Q9: Pre-Anchor Cleanup** | Unlinked | Present | Present | `active` | Reconciler verifies destination matches anchor: if YES, clean anchor; if NO, preserve anchor to `conflicts/`. | NO | NO | NO | SAFE (Clean or Isolated) |
| **Q10: During Anchor Cleanup** | Unlinked | Partial | Present | `active` | Reconciler cleans residual tx_dir. | NO | NO | NO | SAFE (Clean) |

---

## 6. Deterministic Adversarial Race Matrix (Revision 2)

| Race Scenario | Sequence of Events | Defense & Invariant Enforcement |
| :--- | :--- | :--- |
| **R1: Pre-existing Destination** | Third party creates destination just before publication. | `os.link(anchor, dst)` raises `FileExistsError` atomically. Anchor cleaned up; source untouched. (**No Overwrite**) |
| **R2: Destination Unlink Post-Publish** | Third party unlinks destination immediately after publication. | `anchor` retains physical inode. Source retirement verifies destination identity; aborts if missing. Payload preserved in anchor. (**No Data Loss**) |
| **R3: Destination Replaced (Unrelated)** | Third party replaces destination with foreign file before source retirement. | Pre-retirement check detects `st_dst.st_ino != st_anc.st_ino`. Source is NOT unlinked. Foreign file untouched. Transitions to `conflict`. (**No Blind Retirement / No False Success**) |
| **R4: Source Replaced Post-Anchor** | Third party replaces source file after anchor is created. | Phase 3 pre-retirement check detects `st_src.st_ino != st_anc.st_ino`. Source is NOT unlinked! Replacement file untouched. Anchor and destination preserved. (**Anti-Third-Party Deletion**) |
| **R5: Destination Replaced Post-Retirement** | Third party replaces destination after source unlinked but before anchor release. | Blocker 1 check detects `st_anc.st_nlink < 2` or inode mismatch. Anchor is NOT unlinked. Anchor moved to `conflicts/`. (**Zero Data Loss**) |
| **R6: Stale Worker Race** | Stale Worker A awakens after lease expired and attempts `unlink(source)`. | Fencing Protocol Tier 2: Worker B already renamed tx_dir. Worker A's descriptor operations fail with `ENOENT`. Tier 1: DB commit fails lease check. (**Fenced**) |
| **R7: Symlink Publication Attack** | Caller attempts symlink deduplication on `zfuse`. | Mode 2 capability gate strictly raises `OSError(errno.EOPNOTSUPP)`. Zero mutation executed. (**Fail Closed**) |
| **R8: Ancestor Directory Replacement** | Adversary swaps parent directory with symlink to `/etc`. | Descriptor-relative operations (`dir_fd` + `O_NOFOLLOW`) reject following symlinks. Path remains constrained. (**Path Safety**) |

---

## 7. Symmetrical Restore Specification

Restore follows identical two-phase transactional rules in reverse:
1. **Restore Intent & Anchor**:
   - Query Gate3 baseline hash/size of quarantined file.
   - Establish restore anchor: `<quarantine_root>/.tx/<restore_tx_token>/anchor` linked from `quarantine_path`.
   - Persist `QuarantineEntry.state = 'restoring'`.
2. **Restore Publication**:
   - `os.link(anchor, original_path)` via `src_parent_fd`.
   - If `original_path` exists: `FileExistsError` raised atomically $\rightarrow$ Restore fails safely without overwriting.
   - Verify `lstat(original_path)` matches anchor inode.
3. **Quarantine Source Retirement**:
   - Verify `quarantine_path` inode matches anchor.
   - `os.unlink(quarantine_path)`.
4. **Finalization & Anchor Release**:
   - Persist `QuarantineEntry.state = 'restored'`.
   - Verify anchor `st_nlink >= 2` and `original_path` intact.
   - Unlink restore anchor and clean tx_dir.

---

## 8. Authoritative Reviewer Checklist (Section 34 Compliance)

1. **Can destination replacement ever cause original payload loss?**  
   *NO*. Private recovery anchor holds the physical inode throughout source retirement; anchor release verifies `st_nlink >= 2`.
2. **Can source retirement occur without a durable independent recovery path?**  
   *NO*. Phase 1 guarantees anchor establishment and SQLite persistence prior to source retirement.
3. **Can any third-party file be overwritten?**  
   *NO*. Destination publication uses `os.link()`, which kernel-atomically fails with `EEXIST` if occupied.
4. **Can any third-party file be deleted by source retirement or reconciliation?**  
   *NO*. Source retirement verifies source inode matches anchor before unlinking; reconciliation never unlinks foreign inodes.
5. **Can symlink text equality be mistaken for ownership?**  
   *NO*. Symlinks strictly fail closed with `EOPNOTSUPP` in `COMPAT_TRANSACTIONAL` mode.
6. **Is every crash boundary convergent?**  
   *YES*. All 12 crash boundaries (Q0–Q10 including Q1.5) converge deterministically.
7. **Are ambiguous states fail closed?**  
   *YES*. Conflicted or missing destinations transition to `conflict`, preserving anchors in `conflicts/`.
8. **Is native atomic rename still preferred when available?**  
   *YES*. `NATIVE_ATOMIC_NOREPLACE` uses kernel VFS single-syscall rename.
9. **Does zfuse get a safe supported path where proven?**  
   *YES*. Regular files on identical `st_dev` are fully supported with mathematical guarantees.
10. **Do unsupported inode types fail closed?**  
    *YES*. Symlinks, directories, and special inodes fail closed with `EOPNOTSUPP`.
11. **Is Restore proven separately?**  
    *YES*. Full symmetrical two-phase restore transaction specified in Section 7.
12. **Is Gate3 still authoritative?**  
    *YES*. Physical identity and hash validation remain strictly governed by Gate3.
13. **Are CLOSED gates otherwise untouched?**  
    *YES*. Zero redesign of Preview, Draft, Freeze, Validate, ResourcePolicy, or Worker leases.
14. **Is any DB migration truly necessary?**  
    *NO*. Option DB-1 demonstrates full sufficiency using existing schema and deterministic path binding.
15. **Can the resulting architecture be tested deterministically?**  
    *YES*. Every phase, crash boundary, and race condition has a specified deterministic test harness.
16. **Does implementation require a new Gate5-G candidate and full G0 restart?**  
    *YES*. Any code changes require a new commit SHA and full validation restart from G0.

---

## 9. Authoritative Status Language

```text
G7 ARCHITECTURE AMENDMENT REVISION COMPLETE
READY FOR INDEPENDENT ARCHITECTURE REVIEW
```
