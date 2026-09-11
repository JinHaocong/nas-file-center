# NAS File Center v0.3.5 — Gate5-G / G7 Architecture Freeze Amendment (Revision 3)
# Authoritative Anchor + Capture-Based Retirement + Stale-Worker-Safe Semantics

**Document Version:** 3.0.0 (Revision 3)  
**Date:** 2026-09-11  
**Status:** ARCHITECTURE FREEZE AMENDMENT PROPOSAL (REVISION 3) / PENDING INDEPENDENT REVIEW  
**Baseline Production Code HEAD:** `c32d0778c59add81e0c296d6f73aa66bc403c04f`  
**Remote Docs HEAD:** `fb0efa96d2982174bb1bc56f6b065342ff7f7ae9`  
**Branch:** `v0.3.5-gate5c-hotfix4`  
**Target Platform:** 极空间 NAS (ZSpace OS, Linux amd64, Docker, `zfuse.zfsv3`)  
**Authority:** Architecture Design Authorization (Authoritative Anchor + Capture-Based Retirement + Stale-Worker-Safe Semantics)  
**Implementation Status:** IMPLEMENTATION NOT AUTHORIZED — ARCHITECTURAL SPECIFICATION ONLY  

---

## 1. Revision History & Paradigm Shift

- **v1.0.0 (2026-09-11)**: Proposed basic two-phase transaction with recovery anchor. Failed Independent Architecture Review due to 9 critical edge-case, race, and lifecycle blockers.
- **v2.0.0 (2026-09-11, `fb0efa9`)**: Attempted to solve TOCTOU races by introducing `st_nlink >= 2` pre-checks and pre-unlink `fstatat` inode verification. Failed Independent Architecture Review due to fundamental flaws (P0-A through P0-E):
  - *P0-A*: Anchor release remained TOCTOU (`st_nlink >= 2` check and `unlink(anchor)` are not atomic; destination replacement causes payload loss).
  - *P0-B*: Source retirement remained TOCTOU (`fstatat` verify followed by `unlink(source)` deletes third-party replacement files).
  - *P0-C*: Q1.5 crash recovery repeated check-then-delete.
  - *P0-D*: Transaction directory rename is NOT fencing against stale workers holding open directory descriptors (`dir_fd`).
  - *P0-E*: Symmetrical restore inherited identical check-then-unlink vulnerabilities.
- **v3.0.0 (Revision 3, 2026-09-11)**: **Fundamental Architectural Shift**:
  - Abandon userspace attempts to emulate atomic move via check-then-unlink.
  - Establish **Authoritative Private Payload Anchor** persisting for the entire active/restorable lifecycle.
  - Public quarantine pathname treated strictly as a **non-authoritative presentation view**.
  - Replace source unlinking with **capture-by-rename** into unique per-attempt private slots.
  - Enforce **passive stale-worker safety** where resumed stale syscalls are intrinsically non-destructive.
  - Define steady state as **`ACTIVE_COMPAT`**.

---

## 2. Foundational Architectural Principles

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Revision 3 Core Paradigm: Invariant Semantics                   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. Semantics over Checks: Safety stems from the filesystem call itself, never from     │
│    "check immediately before delete". Userspace check-then-unlink is banned.           │
│                                                                                        │
│ 2. Authoritative Anchor: The private anchor (.tx/entry-<id>/attempt-<gen>/anchor)      │
│    is the authoritative payload for the full QuarantineEntry lifecycle.                │
│                                                                                        │
│ 3. Presentation-Only Public View: Public quarantine path is merely a convenience link. │
│    Its corruption or replacement never imperils the authoritative payload.             │
│                                                                                        │
│ 4. Capture-Based Retirement: Source pathname is retired via atomic ordinary rename     │
│    into a private slot. Captured objects are classified AFTER rename. Foreign files    │
│    are preserved in conflict holding; they are NEVER destroyed.                        │
│                                                                                        │
│ 5. No Anchor Deletion: Steady-state ACTIVE_COMPAT retains the authoritative anchor.    │
│    No normal-lifecycle completion ever deletes the last trusted anchor.                │
│                                                                                        │
│ 6. Passive Stale-Worker Safety: A resumed worker issuing an extra syscall with an open │
│    dir_fd cannot destroy payload, overwrite destinations, or delete foreign files.     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Authoritative Private Payload Anchor & `ACTIVE_COMPAT` Model

### 3.1 Authoritative Anchor Definition
In `COMPAT_TRANSACTIONAL` mode, the payload's authoritative location is:
```text
<quarantine_root>/.tx/entry-<entry_id>/attempt-<gen_id>/anchor
```
- The private anchor is created in Phase 1 via `os.link(source, anchor)`.
- Because `source` and `anchor` are on the same filesystem (`zfuse`), hard-linking preserves the physical inode without duplicating payload bytes.
- **The anchor remains physically present and authoritative throughout the entire active and restorable lifecycle of the `QuarantineEntry`.**
- Normal quarantine finalization **DOES NOT UNLINK THE ANCHOR**.

### 3.2 Public Quarantine View as Presentation-Only
The public quarantine path (e.g. `<quarantine_root>/sub/file.dup1`) is published in Phase 2 via:
```text
os.link(anchor, public_destination)
```
- If `public_destination` already exists, `os.link` atomically raises `FileExistsError` (`EEXIST`). Zero overwrite.
- The public destination is strictly a **non-authoritative view**:
  - If an external user, SMB client, or script modifies, unlinks, or replaces `public_destination`, the authoritative payload in `anchor` remains 100% unaffected.
  - The reconciler monitors the public view. If the public view is missing or replaced, the `QuarantineEntry` transitions to `conflict` / `active_degraded`, alerting administrators while payload remains safe.

### 3.3 Steady-State Specification: `ACTIVE_COMPAT`
A successful quarantine operation reaches steady-state `ACTIVE_COMPAT`, defined by the following concurrent invariant facts:
1. **Database**: `QuarantineEntry.state == 'active'`.
2. **Authoritative Payload**: `<quarantine_root>/.tx/entry-<entry_id>/attempt-<gen_id>/anchor` exists, is readable, and matches Gate3 baseline hash/identity.
3. **Public Source**: Retired from original path (captured into private attempt directory).
4. **Public View**: `<quarantine_root>/<relative_path>` exists and shares inode with `anchor`.
5. **Conflict Directory**: Empty (no foreign replacement captured).

---

## 4. Capture-Based Source Retirement via Atomic Ordinary Rename

### 4.1 Prohibition of Check-Then-Unlink
All variations of the following pattern are **permanently prohibited**:
```python
# FORBIDDEN PATTERN (Vulnerable to TOCTOU)
st = stat(source_path)
if st.st_ino == expected_ino:
    os.unlink(source_path)  # External actor can substitute file between stat and unlink!
```

### 4.2 Atomic Capture-by-Rename
Target `zfuse.zfsv3` supports standard POSIX `rename()` on the same filesystem. Revision 3 utilizes ordinary rename to atomically retire the source pathname into a private per-attempt capture slot:
```python
# Atomic capture into private attempt slot
os.rename(source_leaf, captured_leaf, src_dir_fd=src_parent_fd, dst_dir_fd=attempt_dfd)
```

### 4.3 Post-Capture Semantic Classification
Because the rename is atomic, whatever object occupied `source_path` at that instant is now safely isolated inside `attempt-<gen_id>/captured-source`. The engine inspects the captured object **AFTER** the rename:
```python
st_cap = os.fstat(captured_fd)
```

#### Case A: Captured Inode == Authoritative Anchor Inode
- **Meaning**: The intended source file was atomically removed from the public namespace.
- **Action**:
  - Source retirement is complete and verified.
  - Payload is already durably anchored in `.tx/.../anchor` and published at `public_destination`.
  - `captured-source` can be safely unlinked inside the private attempt slot (leaving `st_nlink >= 2` across anchor and public destination), or retained as attempt evidence.
  - Quarantine operation proceeds to `ACTIVE_COMPAT`.

#### Case B: Captured Inode != Authoritative Anchor Inode
- **Meaning**: A concurrent external actor replaced `source_path` with a new, unrelated file prior to the rename.
- **Mandatory Safety Actions**:
  1. **NEVER DELETE THE CAPTURED OBJECT**: The foreign file is irreplaceable user/third-party data.
  2. **NEVER CLAIM QUARANTINE SUCCESS**: The intended source file was already unlinked or replaced externally.
  3. **PRESERVE ORIGINAL PAYLOAD**: The intended payload remains safe and intact in `authoritative_anchor`.
  4. **ISOLATE TO CONFLICT HOLDING**:
     ```text
     Rename captured-source -> .tx/entry-<entry_id>/attempt-<gen_id>/captured-foreign-<timestamp>
     ```
  5. **TRANSITION DATABASE**: `QuarantineEntry.state = 'conflict'`, `last_error = "Source replaced by external actor; foreign object captured and preserved"`.
  6. **RESTORE SOURCE (OPTIONAL / NO-OVERWRITE)**: Attempt safe publication of foreign object back to `source_path` using `link()` or non-destructive rename if `source_path` is vacant; otherwise retain in conflict holding for administrative resolution.

---

## 5. Per-Attempt Private Capture Namespace & Generation Model

### 5.1 Namespace Hierarchy
To prevent any possibility of concurrent or stale workers destructively colliding, all private operations occur within strictly partitioned, generation-indexed directories:
```text
<quarantine_root>/.tx/
  entry-<entry_id>/
    attempt-<generation_id>/
      anchor                     # Authoritative payload hard link
      captured-source            # Staged capture slot during Phase 3
      captured-foreign-<uuid>    # Preserved third-party object if Case B encountered
      attempt-meta.json          # Durable attempt metadata (worker_id, timestamps)
```

### 5.2 Attempt Generation Monotonicity
- Every mutation attempt is assigned a monotonically increasing `generation_id` (e.g. `1`, `2`, `3`).
- A stale worker and a new/reconciling worker **NEVER** share an `attempt-<generation_id>` directory.
- `attempt-meta.json` durably records:
  ```json
  {
    "entry_id": 42,
    "generation_id": 1,
    "worker_id": "worker-node-1:thread-4",
    "phase": "source_captured",
    "created_at": "2026-09-11T13:10:00Z"
  }
  ```

---

## 6. Database Model: DB-1 vs DB-2 Evaluation & Recommendation

### 6.1 Evaluation Comparison

| Dimension | Option DB-1 (Zero Schema Migration) | Option DB-2 (Minimal Durable Generation Fields) |
| :--- | :--- | :--- |
| **Schema Changes** | None (uses `last_error` and directory conventions). | Adds 4 explicit columns to `QuarantineEntry`. |
| **Field Specification** | Crammed: `last_error = "TX:<token>:<gen>:<phase>"`. | Explicit: `tx_token`, `tx_phase`, `authoritative_anchor_path`, `active_generation`. |
| **Crash Recovery** | Reconciler must parse formatted error strings and scan disk for attempt directories. | Reconciler directly queries SQLite authoritative state under `BEGIN IMMEDIATE`. |
| **Stale Worker Defense** | Relies on directory prefix matching and convention. | Fully enforces database-level generation fence (`active_generation == attempt_generation`). |
| **Architectural Rigor** | Low (fragile overloading of error fields). | **High (strict, robust, deterministic).** |

### 6.2 Authoritative Recommendation
**Revision 3 formally recommends Option DB-2.**
- *Rationale*: Project priority is `Data safety > Correctness > Recoverability > Performance > UI > Features`. Avoiding a database migration at the cost of cramming transaction semantics into error strings violates the core safety priority.
- *Minimal DB-2 Fields*:
  1. `tx_token VARCHAR(64)`: Unique transaction token.
  2. `tx_phase VARCHAR(32)`: Detailed transaction phase (`preparing`, `anchored`, `published`, `captured`, `active`, `restoring`, `restored`, `conflict`).
  3. `authoritative_anchor_path VARCHAR(1024)`: Exact filesystem path of the authoritative anchor.
  4. `active_generation INTEGER DEFAULT 1`: Current active generation counter.
- *Status Note*: Database migration is **NOT AUTHORIZED** in this task. This specification establishes the required schema target for future implementation planning.

---

## 7. Stale-Worker Safety Model (Passive Invariant Protection)

### 7.1 Rejection of Path-Rename Fencing
Revision 2 incorrectly claimed that renaming `.tx/<token>` fences stale workers.
**Fact**: An open directory file descriptor (`dir_fd`) remains bound to the directory inode across pathname renaming. A resumed stale worker holding an open `dir_fd` can continue issuing descriptor-relative system calls (`unlinkat`, `renameat`, `linkat`).

### 7.2 Passive Invariant Protection Model
Revision 3 assumes that a stalled worker **CAN** awaken and execute **ONE MORE SYSTEM CALL** using its existing open file descriptors. All mutation primitives are designed such that this execution is **intrinsically data-preserving**:

```text
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                          Stale Worker Sycall Execution Matrix                            │
├──────────────────────┬─────────────────────────┬─────────────────────────────────────────┤
│ Sycall Attempted     │ Concurrency State       │ Resulting Invariant / Impact            │
├──────────────────────┼─────────────────────────┼─────────────────────────────────────────┤
│ link(anchor, pub_dst)│ Destination published   │ Returns EEXIST. Zero overwrite.         │
│                      │ Destination vacant      │ Creates harmless duplicate hard link.   │
├──────────────────────┼─────────────────────────┼─────────────────────────────────────────┤
│ rename(source,       │ Source already captured │ Returns ENOENT. Zero effect.            │
│  attempt1/captured)  │ Source replaced         │ Atomically captures foreign file into   │
│                      │                         │ W1's private attempt slot. Preserved.   │
├──────────────────────┼─────────────────────────┼─────────────────────────────────────────┤
│ DB Status Commit     │ Lease expired           │ SQLite BEGIN IMMEDIATE lease assertion  │
│                      │                         │ fails. Commit rejected / rolled back.   │
├──────────────────────┼─────────────────────────┼─────────────────────────────────────────┤
│ unlink(anchor)       │ Any                     │ FORBIDDEN PRIMITIVE: Codebase contains  │
│                      │                         │ zero calls to unlink authoritative      │
│                      │                         │ anchor in normal lifecycle.             │
└──────────────────────┴─────────────────────────┴─────────────────────────────────────────┘
```

---

## 8. Symmetrical Restore Redesign

Restore operations must adhere to identical authoritative-anchor principles:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              Symmetrical Restore Flow                                  │
└───────────────────────────────────┬────────────────────────────────────────────────────┘
                                    │
    Phase R1: Intent & Target Lock  │ 1. SQLite BEGIN IMMEDIATE (state='restoring')
                                    │ 2. Verify authoritative anchor exists and valid
                                    ▼
    Phase R2: Original Publication  │ 3. os.link(anchor, original_path) [Atomic EEXIST]
                                    │ 4. If occupied: fail closed, abort restore
                                    ▼
    Phase R3: Public View Retire    │ 5. os.rename(public_quarantine, restore_captured)
                                    │ 6. Post-rename check: if foreign -> preserve in conf
                                    ▼
    Phase R4: Finalize Restored     │ 7. SQLite COMMIT (state='restored')
                                    │ 8. Authoritative anchor remains preserved
```

### 8.1 Public Quarantine View Retirement During Restore
- When restoring to `original_path`, the public quarantine view pathname must be retired.
- **Check-then-unlink is forbidden**.
- The engine uses **capture-by-rename** into `<quarantine_root>/.tx/entry-<id>/restore-attempt-<gen>/captured-quarantine-view`.
- If an external actor replaced `public_quarantine` with a foreign file, the foreign file is captured and preserved into conflict holding.
- The authoritative anchor persists through `restored` state.

---

## 9. Inode-Type Support Matrix & Capability Modes

| Inode Type | Mode 1: `NATIVE_ATOMIC_NOREPLACE` | Mode 2: `COMPAT_TRANSACTIONAL` | Enforcement & Safety Invariant |
| :--- | :--- | :--- | :--- |
| **Regular File (`S_ISREG`)** | **SUPPORTED** | **SUPPORTED** | Authoritative Anchor + Capture-by-Rename (`linkat` + `renameat`). Zero data loss. |
| **Symlink (`S_ISLNK`)** | **SUPPORTED** | **FAIL CLOSED (`EOPNOTSUPP`)** | `zfuse` rejects hard links to symlinks (`EPERM`). Capture cannot bind anchor. Strictly fail closed. |
| **Directory (`S_ISDIR`)** | **SUPPORTED** | **FAIL CLOSED (`EOPNOTSUPP`)** | POSIX kernel prohibits directory hard links (`EPERM`). Strictly fail closed. |
| **Special (FIFO, Sock, Dev)** | **FAIL CLOSED (`EOPNOTSUPP`)** | **FAIL CLOSED (`EOPNOTSUPP`)** | Special files ineligible for quarantine mutation. Strictly fail closed. |

---

## 10. Reconciliation Hierarchy & Multiple-Attempt Classification

```text
Worker Lease Acquisition (assert_active_worker_lease)
  ↓
[Layer 1: Base Truth] Quarantine Transaction Reconciler
  - Reconciles QuarantineEntry against filesystem facts in .tx/entry-<id>/attempt-*/
  - Classifies all discovered objects across all attempts:
      * Authoritative Anchor: matches baseline hash/inode -> preserved.
      * Expected Captured Source: matches anchor inode -> safe retirement acknowledged.
      * Foreign Captured Source: inode mismatch -> moved to quarantine/.conflicts/, state=conflict.
      * Public Quarantine View: verify link to anchor; if missing -> mark active_degraded.
      * Unknown Inode: PRESERVE + CONFLICT. Never delete unknown inodes.
  ↓
[Layer 2: Execution Items] BatchPlanItem Reconciler (_reconcile_executing_item)
  - Synchronizes BatchPlanItem state based on QuarantineEntry truth:
      * QuarantineEntry == 'active' -> BatchPlanItem = 'completed'.
      * QuarantineEntry in ('conflict', 'abandoned') -> BatchPlanItem = 'failed'.
  ↓
[Layer 3: Work Jobs] WorkJob Recovery (recover_interrupted_jobs)
  - Evaluates job progress; completes or marks WORKER_INTERRUPTED.
  ↓
[Layer 4: Audit Trail] OperationJournal
  - Logs structured reconciliation events.
```

---

## 11. Comprehensive Crash & Interruption Matrix (C0 – C12)

| Boundary | Inode at Source | Inode at Anchor | Inode at Public View | Inode in Capture Slot | SQLite State | Reconciliation Action | Data Loss? | Overwrite? | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **C0: Pre-Intent** | Original | Absent | Absent | Absent | None | No-op. | NO | NO | SAFE |
| **C1: Intent Recorded** | Original | Absent | Absent | Absent | `preparing` | Mark `abandoned`. Source untouched. | NO | NO | SAFE |
| **C2: Anchor Created, DB Lag** | Original | Original | Absent | Absent | `preparing` | Reconciler preserves anchor, verifies source; marks `abandoned`. | NO | NO | SAFE |
| **C3: Anchor Committed** | Original | Original | Absent | Absent | `anchored` | Reconciler resumes Phase 2 or cleans to `abandoned`. | NO | NO | SAFE |
| **C4: Public View Linked, DB Lag**| Original | Original | Original | Absent | `anchored` | Reconciler detects valid public view, commits `published`. | NO | NO | SAFE |
| **C5: Public View Committed** | Original | Original | Original | Absent | `published` | Reconciler resumes Phase 3 (capture-rename). | NO | NO | SAFE |
| **C6: Source Renamed, DB Lag** | Absent | Original | Original | Original | `published` | Reconciler classifies capture slot: matches anchor -> commits `active`. | NO | NO | SAFE |
| **C7: Foreign File Renamed** | Absent | Original | Original | Foreign | `published` | Reconciler classifies capture slot: mismatch -> moves foreign to conflicts, marks `conflict`. | NO | NO | SAFE |
| **C8: Active Committed** | Absent | Original | Original | Verified | `active` | Steady-state `ACTIVE_COMPAT`. Anchor preserved. | NO | NO | SAFE |
| **C9: Stale Attempt Remaining** | Absent | Original | Original | Artifacts | `active` | Reconciler archives stale attempt metadata. Inodes preserved. | NO | NO | SAFE |
| **C10: Restore Linked, DB Lag** | Restored | Original | Original | Absent | `restoring` | Reconciler detects restored link, resumes restore capture. | NO | NO | SAFE |
| **C11: Restore View Renamed** | Restored | Original | Absent | Captured | `restoring` | Reconciler verifies capture, commits `restored`. | NO | NO | SAFE |
| **C12: Restored Committed** | Restored | Original | Absent | Processed | `restored` | Steady-state RESTORED. Anchor preserved. | NO | NO | SAFE |

---

## 12. Deterministic Adversarial Race Matrix (R1 – R16)

| Race Scenario | Adversarial Event Sequence | Architectural Defense & Invariant Guarantee |
| :--- | :--- | :--- |
| **R1: Source Replaced Before Capture** | Third party unlinks source and creates file B before `rename()`. | Atomic `rename()` moves B into `captured-source`. Post-rename inspection detects `st_ino != anchor_ino`. File B preserved in conflict holding. Quarantine aborted. (**No Deletion**) |
| **R2: Source Replaced After Verification**| Third party replaces source after an inspection but before rename. | Inspection occurs strictly **AFTER** rename. Pre-checks are eliminated. File B is captured and preserved. (**TOCTOU Closed**) |
| **R3: Source Recreated After Capture** | Third party creates file C at `source_path` immediately after rename. | Source was already retired. File C exists at public path untouched. Active quarantine completes. (**No Overwrite**) |
| **R4: Stale Worker Capture Attempt** | Stale Worker 1 wakes up and calls `rename()` on `source_path`. | If source already retired: returns `ENOENT`. If third-party file present: renames to W1's private attempt slot; preserved. (**Safe**) |
| **R5: Two Generations Capture Different Occupants** | Gen 1 captures original file; Gen 2 captures subsequent recreation. | Each generation writes to its own isolated `attempt-<gen>/` directory. Both files preserved and classified. (**No Collision**) |
| **R6: Public Destination Pre-occupied** | Third party creates file at `public_destination` before Phase 2. | `os.link(anchor, dst)` atomically fails with `FileExistsError`. Zero overwrite. Transaction aborts. (**No Overwrite**) |
| **R7: Public Destination Replaced** | Third party unlinks and replaces `public_destination` after Phase 2. | Authoritative anchor retains original payload. Public view mismatch detected $
ightarrow$ `conflict` / `active_degraded`. (**Zero Data Loss**) |
| **R8: Stale Worker Holds Old TX dir_fd**| Stale worker issues `unlink("anchor", dir_fd=tx_dfd)`. | Normal lifecycle contains **NO anchor unlink primitive**. Operation does not exist. (**Payload Safe**) |
| **R9: Stale Worker Holds src_parent_fd**| Stale worker issues `unlink(leaf, dir_fd=src_pfd)`. | Unlink primitive removed from codebase. Stale worker can only issue `rename()` to its private attempt slot. (**Safe**) |
| **R10: Current Reconciles while Old Runs**| Worker 2 reconciles transaction while Worker 1 executes syscall. | Sycall either fails (`ENOENT`/`EEXIST`) or captures object into W1 attempt slot. Reconciler processes all slots. (**Safe**) |
| **R11: Crash Post-Anchor Pre-DB** | Crash after `link(source, anchor)` before SQLite commit. | Boundary C2: Reconciler finds anchor, verifies source reachable, safely preserves or rolls back. (**Safe**) |
| **R12: Crash Post-Capture Pre-DB** | Crash after `rename(source, captured)` before SQLite commit. | Boundary C6/C7: Reconciler inspects `captured-source`. If expected -> advances to `active`; if foreign -> `conflict`. (**Safe**) |
| **R13: Restore Destination Appears** | Third party creates file at `original_path` before restore link. | `os.link(anchor, original_path)` fails with `FileExistsError`. Restore aborts safely without overwriting. (**No Overwrite**) |
| **R14: Restore Public View Replaced** | Third party replaces public quarantine view before restore retirement. | Restore capture renames foreign object to restore attempt slot; preserved in conflict. Anchor safe. (**No Deletion**) |
| **R15: Private Attempt Contains Unknown Inode**| Unrecognized file found in attempt directory during startup. | Reconciler rule: **UNKNOWN == PRESERVE + CONFLICT**. File moved to `conflicts/`; administrator notified. (**Zero Data Loss**) |
| **R16: Multiple Attempt Dirs on Restart**| Crash leaves `attempt-1/` and `attempt-2/` on disk. | Reconciler parses all attempt directories; merges evidence; preserves all payload-bearing inodes. (**Deterministic**) |

---

## 13. Cleanup Policy & Deletion Invariants

To eliminate accidental data loss, Revision 3 categorizes filesystem cleanup:

1. **Category A: Metadata Cleanup (Permitted)**
   - Deletion of temporary JSON status files inside completed attempt directories (e.g. `attempt-meta.json`).
2. **Category B: Empty Directory Cleanup (Permitted)**
   - Invocation of `rmdir()` on verified empty generation directories after all artifacts are archived.
3. **Category C: Duplicate Hard-Link Cleanup (Strictly Constrained)**
   - Unlinking duplicate capture links (e.g. `captured-source`) ONLY when the authoritative anchor and public view are verified and hold `st_nlink >= 2`.
4. **Category D: Payload-Bearing Pathname Deletion (STRICTLY PROHIBITED)**
   - Deletion of `authoritative_anchor` during normal quarantine or restore lifecycle is **FORBIDDEN**.
   - Permanent deletion/purge belongs to a separate, future lifecycle stage and is out of scope for Gate5-G.

---

## 14. Threat Model & Private Namespace Access Specification

### 14.1 Threat Boundary
- **In-Scope Actors**:
  - Concurrent local users and unprivileged host processes.
  - SMB / NFS network clients accessing shared volumes.
  - Competing, crashed, or resumed stale NAS File Center workers.
  - External scripts writing to public source or quarantine directory trees.
- **Out-of-Scope Actors**:
  - Malicious host `root` user with direct kernel/Docker privileges.
  - Compromised container daemon or compromised Linux kernel.
  - Hostile filesystem drivers deliberately returning fraudulent syscall results.

### 14.2 Namespace Access Specification
1. **Directory Location**: `<quarantine_root>/.tx/`, created with mode `0700`, owned by container runtime user.
2. **Host Share Deployment Prerequisites**:
   - For SMB exports of `<quarantine_root>`, host configuration MUST specify:
     ```text
     veto files = /.tx/.conflicts/
     ```
   - Deployment documentation will explicitly mandate this configuration.
3. **Internal Application Guards**:
   - `app/tasks/indexing.py` and `fclones` runners automatically exclude `**/.tx/**` and `**/.conflicts/**`.
   - API endpoints reject any path request containing `/.tx` or `/.conflicts`.
   - `IndexRoot` registration rejects roots intersecting transaction directories.

---

## 15. Descriptor-Relative Operations (`dir_fd`) & Codebase Realities

### 15.1 Current Code Fact
Inspection of [`app/batch_utilities/empty_dir_quarantine.py::safe_open_parent_fd`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/empty_dir_quarantine.py#L90-L133) establishes the **actual current implementation**:
- Path traversal opens parent directories using:
  ```python
  flags = os.O_RDONLY | os.O_DIRECTORY
  if hasattr(os, "O_NOFOLLOW"):
      flags |= os.O_NOFOLLOW
  curr_fd = os.open(comp, flags, dir_fd=parent_fd)
  ```
- It does **NOT** use `O_PATH` (which is Linux-specific and requires different handling across POSIX platforms).

### 15.2 Proposed Implementation Requirement
- Future implementation will adopt this exact proven `safe_open_parent_fd` descriptor traversal.
- All mutation operations across source, anchor, and public destination will execute relative to opened directory descriptors:
  - `os.link(src_leaf, anc_leaf, src_dir_fd=src_pfd, dst_dir_fd=attempt_dfd)`
  - `os.link(anc_leaf, pub_leaf, src_dir_fd=attempt_dfd, dst_dir_fd=pub_pfd)`
  - `os.rename(src_leaf, cap_leaf, src_dir_fd=src_pfd, dst_dir_fd=attempt_dfd)`
- Path-walk races against ancestor directories are eliminated.

---

## 16. Authoritative Architecture Review Checklist (Section 28 Compliance)

| # | Question | Answer | Formal Proof |
| :- | :--- | :--- | :--- |
| **1** | Can any normal success path unlink the last trusted anchor? | **NO** | In `ACTIVE_COMPAT`, the authoritative anchor persists indefinitely. Normal lifecycle contains no code unlinking the anchor. |
| **2** | Can any source retirement use check-then-unlink? | **NO** | Check-then-unlink is banned. Source retirement executes strictly via atomic `rename()` into private capture slot. |
| **3** | Can a stale worker holding an old `dir_fd` destroy authoritative payload? | **NO** | Descriptors held by stale workers cannot unlink anchors (no such syscall exists). Stale writes fail (`EEXIST`) or capture into private slots. |
| **4** | Can a stale worker destroy a foreign replacement file? | **NO** | Stale rename moves foreign replacement into worker's private attempt slot; reconciler classifies and preserves it in `conflicts/`. |
| **5** | Can a public-path replacement destroy authoritative payload? | **NO** | Public path is a presentation view hard link. Replacement drops link count to anchor from 2 to 1; anchor retains 100% of payload bytes. |
| **6** | Can recovery delete an inode it cannot prove belongs to safe cleanup? | **NO** | Reconciler enforces **UNKNOWN == PRESERVE + CONFLICT**. Unproven inodes are moved to `conflicts/`, never unlinked. |
| **7** | Does crash-after-FS-before-DB preserve all evidence? | **YES** | All 13 crash boundaries (C0–C12) verify that physical artifacts on disk are preserved and recovered deterministically. |
| **8** | Can multiple attempt generations be distinguished after restart? | **YES** | Each attempt resides in an isolated `attempt-<gen_id>/` directory with explicit `attempt-meta.json` logging. |
| **9** | Can Restore preserve identical guarantees? | **YES** | Symmetrical restore originates from authoritative anchor, publishes via `link()`, and retires quarantine view via capture-by-rename. |
| **10**| Are unknown objects preserved rather than guessed/deleted? | **YES** | Absolute architectural invariant: Unknown inodes are moved to incident conflict storage; zero guessing, zero deletion. |

---

## 17. Authoritative Status Language

```text
G7 ARCHITECTURE AMENDMENT REVISION 3 COMPLETE
READY FOR INDEPENDENT ARCHITECTURE REVIEW
```
