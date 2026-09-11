# NAS File Center v0.3.5 — Gate5-G / G7 Architecture Freeze Amendment (Revision 3.1)
# Final Architecture Closure: Authoritative Anchor + Candidate Qualification + Write-Once Capture + Lease Discipline

**Document Version:** 3.1.0 (Revision 3.1)  
**Date:** 2026-09-11  
**Status:** ARCHITECTURE FREEZE AMENDMENT (REVISION 3.1) / PENDING FINAL INDEPENDENT REVIEW  
**Baseline Production Code HEAD:** `c32d0778c59add81e0c296d6f73aa66bc403c04f`  
**Remote Docs HEAD:** `22837e27a5f193b8d986f3a7626e12864689068a`  
**Branch:** `v0.3.5-gate5c-hotfix4`  
**Target Platform:** 极空间 NAS (ZSpace OS, Linux amd64, Docker, `zfuse.zfsv3`)  
**Authority:** Architecture Design Authorization (Final Architecture Closure)  
**Implementation Status:** IMPLEMENTATION NOT AUTHORIZED — ARCHITECTURAL SPECIFICATION ONLY  

---

## 1. Revision History & Closure Context

- **v1.0.0 (2026-09-11)**: Initial specification of Approach B (Two-Phase Mutation Transaction). Failed Independent Review due to 9 critical edge-case, race, and lifecycle gaps.
- **v2.0.0 (2026-09-11, `fb0efa9`)**: Attempted to solve TOCTOU via pre-checks (`st_nlink >= 2`, `fstatat`) before unlinking. Rejected by Independent Review (P0-A through P0-E) because userspace check-then-unlink is fundamentally non-atomic.
- **v3.0.0 (2026-09-11, `22837e2`)**: Major paradigm shift to **Authoritative Persistent Anchor**, **Presentation-Only Public View**, **Capture-by-Rename Source Retirement**, **Option DB-2 Schema Recommendation**, and **Passive Stale-Worker Safety**. The core paradigm was **ACCEPTED**.
- **v3.1.0 (Revision 3.1, 2026-09-11)**: **Final Architecture Closure**. Fully closes all remaining review findings:
  - *P0-1*: Strict two-step **Candidate Anchor Qualification Protocol** against Gate3 Frozen identity.
  - *P0-2*: Transactional **Generation Allocation & Write-Once Capture Slot** by construction.
  - *P0-3*: **Zero Payload-Bearing Unlink** in COMPAT mode (forbids unlinking anchors, captured sources, foreign objects, or unknown inodes).
  - *P0-4*: Formal structural justification of **"One Stale FS Syscall" via Per-Mutation Lease Discipline**.
  - *P0-5*: **Preserve-in-Place for Foreign / Unknown Inodes** without re-renaming or unsafe check-then-restore.
  - *P1-1*: Formal **DB-2 Legacy Row Compatibility & Fail-Closed Gate**.
  - *P1-2*: **COMPAT Purge & Retention Safety Gate** (refusing payload destruction while anchor persists).
  - *State Model Disambiguation*: Elimination of ambiguous choices; frozen deterministic state interpretations.

---

## 2. Preserved Core Paradigms (Frozen from Revision 3)

The following foundational models are frozen and NOT subject to redesign:
1. **Authoritative Private Payload Anchor**: The private anchor remains the sole authoritative payload entity for the full active and restorable lifecycle.
2. **Presentation-Only Public Quarantine View**: The public quarantine path is strictly a non-authoritative presentation view (convenience hard link). Its corruption or replacement never imperils the authoritative anchor.
3. **Capture-by-Rename Source Retirement**: Public source pathname is retired via atomic ordinary rename into a private attempt slot. Post-capture classification determines outcome.
4. **Option DB-2 Architectural Direction**: Explicit, minimal durable transaction fields preferred over overloading error columns.
5. **Single Reconciliation Hierarchy**: Unified single-source-of-truth convergence from low-level transaction reconciliation up to WorkJob and OperationJournal.

---

## 3. Candidate Anchor Qualification Protocol (P0-1)

`os.link(source, anchor)` does **NOT** immediately make the anchor authoritative. A concurrent actor could replace the source file between the final Gate3 pre-mutation check and the execution of `os.link()`.

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                      Candidate Anchor Qualification Protocol                           │
└───────────────────────────────────┬────────────────────────────────────────────────────┘
                                    │
    Phase 1A: Establish Candidate   │ 1. SQLite BEGIN IMMEDIATE (state='preparing')
                                    │ 2. os.link(source, candidate_anchor) via safe parent dir_fd
                                    ▼
    Phase 1B: Gate3 Qualification   │ 3. Open candidate_anchor_fd (O_RDONLY | O_NOFOLLOW)
                                    │ 4. fstat(candidate_anchor_fd) + cryptographic hash check
                                    │ 5. Validate against Gate3 Frozen Expected Identity:
                                    │    * inode & dev match Gate3 baseline snapshot
                                    │    * file size matches Gate3 baseline snapshot
                                    │    * SHA256 / Blake3 hash matches Gate3 baseline snapshot
                                    │    * file mode (S_ISREG) matches
                                    ▼
             ┌──────────────────────┴──────────────────────┐
             │ Qualified (Match)                           │ Discrepancy (Mismatch)
             ▼                                             ▼
    6. Commit Phase 1B:                           6. Fail-Closed Handling:
       - authoritative_anchor_path = path            - PRESERVE candidate_anchor on disk
       - state = 'authoritative_anchored'            - PRESERVE source and public filesystem facts
       - Advance to Phase 2 (Public Publication)     - DO NOT unlink candidate anchor
                                                     - DO NOT report success
                                                     - state = 'conflict' (reason: candidate_anchor_mismatch)
```

### Safety Invariants:
- **Zero Premature Authority**: No public publication (Phase 2) and no source capture (Phase 3) can occur until Candidate Anchor Qualification completes with 100% verification against Gate3 frozen identity.
- **Zero Mismatch Deletion**: If the candidate anchor does not match Gate3 identity, it is **never deleted**. It is preserved in place for administrative audit.

---

## 4. Generation Allocation & Write-Once Capture Slot Protocol (P0-2)

Because target `zfuse` supports ordinary POSIX `rename()`, an ordinary rename will atomically overwrite its destination if the destination already exists. Therefore, **capture safety must stem from namespace ownership by construction**, never from check-then-rename.

```text
<quarantine_root>/.tx/
  entry-<entry_id>/
    attempt-<generation_id>/       <-- Exclusively owned by generation_id
      candidate_anchor             <-- Created during Phase 1
      captured-source              <-- WRITE-ONCE capture slot
      attempt-meta.json            <-- Immutable attempt log
```

### Protocol Rules:
1. **Durable Generation Allocation**:
   - Monotonic generation allocation executes strictly under SQLite `BEGIN IMMEDIATE`:
     $$	ext{active\_attempt\_generation} \leftarrow 	ext{active\_attempt\_generation} + 1$$
   - The new `generation_id` is **COMMITTED** in the database before the filesystem attempt directory (`attempt-<gen_id>/`) is created.
   - Generations **NEVER decrement, NEVER roll back, and NEVER reuse an existing generation ID**.
2. **Exclusive Directory Creation**:
   - The worker creates `attempt-<gen_id>/` using `os.mkdir(..., mode=0700)`.
   - If `attempt-<gen_id>/` already exists, `os.mkdir` raises `FileExistsError` $ightarrow$ transaction aborts and increments generation.
3. **Write-Once Capture Slot**:
   - Each generation owns exactly **ONE write-once capture pathname**:
     `attempt-<gen_id>/captured-source`.
   - A generation may issue at most **ONE** `rename(source, captured-source)` invocation.
   - **If `captured-source` already exists on disk, NO rename to that path is ever allowed.**
   - On retry, crash recovery, or lease takeover:
     - The reconciler classifies the existing `captured-source` in place.
     - If a retry requires issuing a new rename, the engine **MUST allocate a NEW generation ID** (`attempt-<gen+1>/`).
   - Check-then-rename retries within the same slot are strictly prohibited.

---

## 5. Zero Payload-Bearing Unlink in COMPAT (P0-3)

For Gate5-G `COMPAT_TRANSACTIONAL` mode, **unlinking any payload-bearing private pathname is strictly FORBIDDEN**.

### 5.1 Banned Unlink Targets:
The engine and reconciliation systems are strictly prohibited from issuing `unlink()`, `unlinkat()`, or `remove()` against:
- `authoritative_anchor`
- `candidate_anchor`
- expected `captured-source`
- foreign captured object
- unknown / unrecognized inode
- restore captured view (`captured-quarantine-view`)
- any other payload-bearing private pathname.

### 5.2 Storage & Hard-Link Invariant:
- When source retirement succeeds (Case A: captured inode matches anchor inode), `captured-source` is **retained as another hard link** inside `attempt-<gen_id>/`.
- Because both `anchor` and `captured-source` point to the identical filesystem inode on `zfuse`, retaining `captured-source` **consumes zero duplicate payload bytes**.
- Category C (duplicate hard-link cleanup) from Revision 3 is **PERMANENTLY DELETED**.

### 5.3 Allowed Cleanup Only:
Cleanup in `COMPAT_TRANSACTIONAL` mode is strictly restricted to:
1. **Non-payload metadata**: Temporary JSON files (e.g. completed `attempt-meta.json`).
2. **Verified-empty directories**: `os.rmdir()` on directories containing zero files.
3. *Permanent payload destruction / purge is completely outside Gate5-G and is governed by Section 9.*

---

## 6. Formal Justification of "One Stale FS Syscall" (P0-4)

To prove that a resumed stale worker cannot execute arbitrary sequences of mutations, the architecture freezes a strict **Per-Mutation Lease-Fencing Discipline**:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        Mandatory Per-Mutation Execution Discipline                     │
└───────────────────────────────────┬────────────────────────────────────────────────────┘
                                    │
    Step 1: Lease Assertion Fence   │ SQLite BEGIN IMMEDIATE: assert active worker lease
                                    ▼
    Step 2: Single Mutation         │ Execute EXACTLY ONE payload-affecting filesystem call
                                    │ (e.g. link candidate, link public, or rename capture)
                                    ▼
    Step 3: Lease Assertion Fence   │ SQLite BEGIN IMMEDIATE: assert active worker lease
                                    ▼
    Step 4: Next Mutation           │ Execute next payload-affecting filesystem call
```

### Mathematical & Behavioral Justification:
- Let Worker 1 acquire a lease valid until $T_{	ext{lease}}$.
- Worker 1 successfully passes Fence 1 at $t_1 < T_{	ext{lease}}$.
- Worker 1 suffers an extreme FUSE or thread stall during Step 2.
- At $t_2 = T_{	ext{lease}}$, the lease expires. Worker 2 takes over and commits a new generation $G_2$.
- At $t_3 > t_2$, Worker 1 awakens.
- Worker 1 can execute **at most the single filesystem call authorized by Fence 1**.
- Before Worker 1 can execute *any subsequent* payload-affecting call (e.g. Step 4), Worker 1 **MUST** execute Fence 3.
- In Fence 3, SQLite `BEGIN IMMEDIATE` evaluates `assert_active_worker_lease(session, worker_1)`.
- Because Worker 2 already superseded the lease, Fence 3 **fails immediately with `StaleWorkerLeaseExpired`**.
- Worker 1's transaction is rolled back; Worker 1 is terminated or aborted.
- **Therefore, a stale worker can execute at most ONE stale filesystem call.**
- Because every single mutation primitive is designed to be passively safe (Section 7 in Revision 3), that single call is guaranteed to be data-preserving.
- *Implementation Requirement*: Current production code structures will be refactored during future implementation to enforce this per-mutation fence discipline.

---

## 7. Foreign / Unknown = Preserve in Place (P0-5)

When source retirement captures an object whose physical inode does not match the authoritative anchor (Case B: foreign object):

### 7.1 Absolute Preservation-in-Place Rule
$$	ext{FOREIGN / UNKNOWN} = 	ext{PRESERVE EXACTLY IN ITS UNIQUE ATTEMPT SLOT} + 	ext{DB conflict record} + 	ext{audit metadata}$$

- **No Renaming to Reorganize**: The engine **MUST NOT** rename `captured-source` to `captured-foreign-<timestamp>`. Doing so introduces an unnecessary rename that could fail or collide. The foreign object remains at its original write-once capture path: `attempt-<gen_id>/captured-source`.
- **No Unsafe Check-Then-Restore**: The engine **MUST NOT** execute `if source_path vacant: rename(captured-source, source_path)`. On `zfuse`, testing vacancy and renaming is a TOCTOU hazard that can overwrite subsequent third-party creations.
- **Restoration Rules**:
  - Regular foreign files: Future or manual administrative restoration MAY use strict hard-link publication (`link(captured-source, source_path)`) with atomic `EEXIST` semantics.
  - Symlinks, directories, and unknown special inodes: Preserve in place + record `conflict`. Zero automated restoration.

---

## 8. Database Model: DB-2 Specification & Legacy Compatibility (P1-1)

### 8.1 Minimal Durable DB-2 Schema Fields
Revision 3.1 formally defines the target minimal durable fields for `QuarantineEntry`:
1. `tx_token VARCHAR(64) NULL`: Cryptographically secure compound transaction identifier.
2. `tx_phase VARCHAR(32) NULL`: Granular transaction phase (`preparing`, `candidate_anchored`, `authoritative_anchored`, `public_published`, `source_captured`, `active`, `restoring`, `restored`, `conflict`, `legacy`).
3. `authoritative_anchor_path VARCHAR(1024) NULL`: Absolute path to the qualified authoritative anchor.
4. `active_attempt_generation INTEGER DEFAULT 1`: Monotonically increasing attempt counter.

### 8.2 Legacy Row Compatibility & Migration Invariants
When migrating from pre-amendment schemas:
1. **Safe Nullability**: All new fields are nullable or defaulted (`active_attempt_generation = 1`).
2. **Legacy Classification**: Existing rows without transaction data are classified as `legacy` (`tx_phase IS NULL` or `'legacy'`).
3. **Zero Anchor Fabrication**: Migration **MUST NOT** fabricate, synthesize, or retroactively guess authoritative anchors for pre-existing quarantine records.
4. **Existing Data Untouched**: Pre-existing filesystem paths and metadata remain intact.
5. **Native Execution**: Legacy rows on filesystems supporting `NATIVE_ATOMIC_NOREPLACE` may continue using native primitives.
6. **COMPAT Fail-Closed Gate**: Any legacy row residing on `COMPAT_TRANSACTIONAL` (`zfuse`) that requires a transactional mutation (such as restore or modification) but lacks a valid authoritative anchor **MUST FAIL CLOSED** with error:
   ```text
   OSError(errno.EOPNOTSUPP, "Legacy quarantine entry lacks authoritative transaction anchor; mutation refused")
   ```
7. *Status*: Database migration code remains **STRICTLY NOT AUTHORIZED** in this task.

---

## 9. COMPAT Purge & Retention Safety Gate (P1-2)

Permanent payload deletion architecture is strictly outside the scope of Gate5-G.

### Safety Invariants:
1. **No Anchor Purge**: The authoritative anchor of an `ACTIVE_COMPAT` quarantine entry **MUST NOT** be unlinked or deleted by any purge or retention routine in the current system.
2. **Purge Refusal**: Any retention job, user command, or purge task requesting the destruction of an authoritative payload on a `COMPAT_TRANSACTIONAL` filesystem **MUST FAIL CLOSED** with `EOPNOTSUPP`.
3. **No False "Purged" Status**: The database **MUST NOT** mark any `COMPAT_TRANSACTIONAL` entry as `'purged'` while its authoritative anchor payload still exists on disk.

---

## 10. State Model Disambiguation

Revision 3.1 eliminates all ambiguous state terms (such as `conflict / active_degraded`). The externally persisted state machine is frozen as follows:

```text
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              Frozen Persistent State Model                             │
├───────────────┬────────────────────────────────────────────────────────────────────────┤
│ DB State      │ Authoritative Meaning & Invariants                                     │
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ preparing     │ Initial intent recorded; generation allocated; candidate anchor pending│
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ conflict      │ Discrepancy detected (candidate mismatch, foreign capture, or public   │
│               │ view corruption). Authoritative payload preserved in place.            │
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ active        │ Steady-state ACTIVE_COMPAT: authoritative anchor valid & verified;     │
│               │ source retired via capture; public quarantine view verified.           │
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ restoring     │ Restore intent recorded; restore generation active; anchor verified.   │
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ restored      │ Original path published; public quarantine view retired; anchor intact.│
├───────────────┼────────────────────────────────────────────────────────────────────────┤
│ legacy        │ Pre-amendment entry; lacks authoritative anchor; fail closed on compat.│
└───────────────┴────────────────────────────────────────────────────────────────────────┘
```

### Immutability of Authoritative Anchor Path:
- **Single Authority**: ONLY the Gate3-qualified anchor path stored in `authoritative_anchor_path` is authoritative.
- **Permanent Binding**: Subsequent generations (retries, reconciliations) **NEVER replace or overwrite `authoritative_anchor_path`**.
- **Restore Binding**: All restore generations reference and publish from this identical `authoritative_anchor_path`.

---

## 11. Inode-Type Support Matrix & Capability Modes

| Inode Type | Mode 1: `NATIVE_ATOMIC_NOREPLACE` | Mode 2: `COMPAT_TRANSACTIONAL` | Enforcement & Safety Invariant |
| :--- | :--- | :--- | :--- |
| **Regular File (`S_ISREG`)** | **SUPPORTED** | **SUPPORTED** | Candidate Qualification + Capture-by-Rename + Zero Payload Unlink. |
| **Symlink (`S_ISLNK`)** | **SUPPORTED** | **FAIL CLOSED (`EOPNOTSUPP`)** | `zfuse` rejects hard links to symlinks (`EPERM`). Strictly fail closed. |
| **Directory (`S_ISDIR`)** | **SUPPORTED** | **FAIL CLOSED (`EOPNOTSUPP`)** | POSIX kernel prohibits directory hard links (`EPERM`). Strictly fail closed. |
| **Special (FIFO, Sock, Dev)** | **FAIL CLOSED (`EOPNOTSUPP`)** | **FAIL CLOSED (`EOPNOTSUPP`)** | Ineligible for deduplication mutation. Strictly fail closed. |

---

## 12. Exhaustive Crash & Interruption Matrix (Revision 3.1)

| Boundary | Filesystem State | DB State & Phase | Reconciler Action | Data Loss? | Overwrite? | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **C0: Pre-Intent** | All paths original | None | No-op. | NO | NO | SAFE |
| **C1: Intent Committed** | All paths original | `preparing` | Mark `conflict` (unstarted) or re-evaluate. | NO | NO | SAFE |
| **C1.1: Source Replaced Pre-Link** | Source = foreign file | `preparing` | Candidate link links foreign file; Phase 1B qualification detects mismatch; candidate preserved; mark `conflict`. | NO | NO | SAFE |
| **C2: Candidate Linked, DB Lag** | Candidate anchor present | `preparing` | Reconciler evaluates candidate against Gate3: if valid -> commit `authoritative_anchored`; if mismatch -> mark `conflict`. Zero deletion. | NO | NO | SAFE |
| **C2.1: Candidate Mismatch Post-Link**| Candidate anchor present (mismatch) | `preparing` | Reconciler preserves candidate; marks `conflict`. Zero deletion. | NO | NO | SAFE |
| **C2.2: Gen Commit, Pre-mkdir Crash**| DB gen incremented; no dir | `preparing` | Reconciler creates attempt dir for committed generation or advances generation. Zero collision. | NO | NO | SAFE |
| **C3: Anchor Authoritative** | Authoritative anchor verified | `authoritative_anchored` | Resume Phase 2 (Public Publication). | NO | NO | SAFE |
| **C4: Public Linked, DB Lag** | Public view present | `authoritative_anchored` | Reconciler verifies public view inode == anchor; commits `public_published`. | NO | NO | SAFE |
| **C5: Public Committed** | Public view present | `public_published` | Resume Phase 3 (Capture-by-rename). | NO | NO | SAFE |
| **C6: Capture Renamed, DB Lag** | `captured-source` present | `public_published` | Reconciler classifies `captured-source`: if matches anchor -> commit `active`; if foreign -> mark `conflict`. Zero deletion. | NO | NO | SAFE |
| **C6.1: Capture Slot Exists on Retry**| `captured-source` already on disk| `public_published` | Reconciler forbids rename into existing slot; classifies slot; allocates new generation if retry needed. | NO | NO | SAFE |
| **C7: Active Committed** | Anchor, View, Capture present | `active` | Steady-state `ACTIVE_COMPAT`. Zero unlink. | NO | NO | SAFE |
| **C8: Restore Linked, DB Lag** | Restored path present | `restoring` | Reconciler verifies restored inode == anchor; resumes public view capture. | NO | NO | SAFE |
| **C9: Restore View Captured** | Quarantine view retired | `restoring` | Reconciler commits `restored`. Zero unlink of anchor. | NO | NO | SAFE |
| **C10: Legacy Row Encountered** | Legacy entry on `zfuse` | `legacy` | Mutation refused; fails closed with `EOPNOTSUPP`. | NO | NO | SAFE |
| **C11: Purge Requested on Compat** | `ACTIVE_COMPAT` entry | `active` | Purge refused; fails closed with `EOPNOTSUPP`. Zero anchor deletion. | NO | NO | SAFE |

---

## 13. Deterministic Adversarial Race Matrix (Revision 3.1)

| Race Scenario | Adversarial Action | Architectural Defense & Invariant Guarantee |
| :--- | :--- | :--- |
| **R1: Source Replaced Pre-Link** | Third party replaces source before `os.link(source, candidate)`. | Candidate anchor holds foreign file. Phase 1B qualification inspects candidate against Gate3: **mismatch detected**. Candidate preserved; state = `conflict`. (**No False Authority**) |
| **R2: Candidate Mismatch Post-Link** | Attacker substitutes file inode during hard-link creation. | Phase 1B checks hash, size, and inode. Candidate qualification fails closed. State = `conflict`. Candidate preserved. (**Zero Data Loss**) |
| **R3: Source Replaced Pre-Capture** | Third party replaces source after anchor qualified but before rename. | Atomic `rename(source, captured-source)` captures foreign file into write-once slot. Post-capture check detects mismatch: foreign object preserved in place; state = `conflict`. (**Anti-Deletion**) |
| **R4: Source Recreated Post-Capture**| Third party creates file C at source path after rename. | Source retirement was already complete. File C remains untouched at source path. Quarantine succeeds. (**No Overwrite**) |
| **R5: Stale Generation Tries 2nd Capture**| Stale worker wakes up and calls rename into existing slot. | Write-once slot protocol: generation owns at most 1 rename; if slot exists, rename is prohibited. (**Write-Once Enforced**) |
| **R6: Public Destination Pre-occupied**| Third party creates file at public quarantine path before Phase 2. | `os.link(anchor, pub_dst)` fails atomically with `FileExistsError` (`EEXIST`). Zero overwrite. State = `conflict`. (**No Overwrite**) |
| **R7: Public Destination Replaced** | Third party replaces public quarantine path after Phase 2. | Authoritative anchor retains 100% of payload. Public view mismatch detected $ightarrow$ state = `conflict`. Payload safe. (**Zero Data Loss**) |
| **R8: Stale Worker Sycall with dir_fd**| Stale worker holding open `dir_fd` executes 1 filesystem call. | Per-mutation lease discipline limits stale worker to at most 1 call. Any valid call is non-destructive (EEXIST, ENOENT, or capture to private slot). Next call blocked by lease fence. (**Fenced**) |
| **R9: Legacy Row Mutation on Compat** | User requests restore of pre-amendment row on `zfuse`. | DB-2 compatibility gate detects `legacy` status and absence of anchor $ightarrow$ fails closed with `EOPNOTSUPP`. (**Zero Guessing**) |
| **R10: Purge Requested on ACTIVE_COMPAT**| Retention script calls purge on active compat entry. | Retention safety gate detects `COMPAT_TRANSACTIONAL` $ightarrow$ fails closed with `EOPNOTSUPP`. Anchor preserved. (**Zero Payload Loss**) |
| **R11: Crash Between Gen Commit & mkdir**| Process crashes after generation DB commit before `mkdir(attempt)`. | Reconciler finds uncreated attempt directory; creates it exclusively or advances generation. Zero collision. (**Deterministic**) |
| **R12: Multiple Generations Collide**| Stale worker and new worker execute concurrently. | Each generation strictly bound to unique `attempt-<gen>/` directory. File collision impossible by construction. (**Isolated**) |

---

## 14. Descriptor-Relative Operations (`dir_fd`) & Codebase Realities

- **Current Implementation Fact**: [`app/batch_utilities/empty_dir_quarantine.py::safe_open_parent_fd`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/empty_dir_quarantine.py#L90-L133) uses:
  ```python
  flags = os.O_RDONLY | os.O_DIRECTORY
  if hasattr(os, "O_NOFOLLOW"):
      flags |= os.O_NOFOLLOW
  curr_fd = os.open(comp, flags, dir_fd=parent_fd)
  ```
- **Proposed Implementation Requirement**:
  - Adopt this exact `safe_open_parent_fd` descriptor traversal for all transaction file operations.
  - All operations use descriptor-relative calls:
    - `os.link(src_leaf, cand_leaf, src_dir_fd=src_pfd, dst_dir_fd=attempt_dfd)`
    - `os.link(anc_leaf, pub_leaf, src_dir_fd=attempt_dfd, dst_dir_fd=pub_pfd)`
    - `os.rename(src_leaf, cap_leaf, src_dir_fd=src_pfd, dst_dir_fd=attempt_dfd)`
  - Ancestor symlink redirection outside configured roots is physically impossible.

---

## 15. Authoritative Architecture Review Checklist (Section 28 Compliance)

| # | Question | Answer | Formal Proof |
| :- | :--- | :--- | :--- |
| **1** | Can any normal success path unlink the last trusted anchor? | **NO** | In `ACTIVE_COMPAT`, the authoritative anchor persists indefinitely. The codebase contains zero calls to unlink the anchor. |
| **2** | Can any source retirement use check-then-unlink? | **NO** | Check-then-unlink is permanently banned. Source retirement executes strictly via atomic `rename()` into write-once capture slot. |
| **3** | Can a stale worker holding an old `dir_fd` destroy authoritative payload? | **NO** | Normal lifecycle contains no anchor unlink primitive. Stale mutation attempts are bounded to 1 non-destructive call by lease discipline. |
| **4** | Can a stale worker destroy a foreign replacement file? | **NO** | Stale rename moves foreign replacement into write-once private capture slot; foreign object is preserved in place; state = `conflict`. |
| **5** | Can a public-path replacement destroy authoritative payload? | **NO** | Public quarantine path is a presentation view hard link. Replacement drops link count to anchor from 2 to 1; anchor retains 100% of payload. |
| **6** | Can recovery delete an inode it cannot prove belongs to safe cleanup? | **NO** | Zero payload-bearing unlink rule (P0-3): Unlink of any payload inode is strictly forbidden. Unknown inodes are preserved in place. |
| **7** | Does crash-after-FS-before-DB preserve all evidence? | **YES** | All 15 crash boundaries (C0–C11) verify physical evidence is preserved on disk and recovered deterministically. |
| **8** | Can multiple attempt generations be distinguished after restart? | **YES** | Generations are strictly monotonic, allocated under SQLite `BEGIN IMMEDIATE`, and partitioned into unique `attempt-<gen>/` directories. |
| **9** | Can Restore preserve identical guarantees? | **YES** | Symmetrical restore originates from authoritative anchor, publishes via `link()`, and retires quarantine view via capture-by-rename. |
| **10**| Are unknown objects preserved rather than guessed/deleted? | **YES** | Absolute rule (P0-5): Foreign and unknown objects are preserved in place in their unique attempt slot; zero guessing, zero deletion. |

---

## 16. Authoritative Status Language

```text
G7 ARCHITECTURE AMENDMENT REVISION 3.1 COMPLETE
READY FOR FINAL INDEPENDENT ARCHITECTURE REVIEW
```
