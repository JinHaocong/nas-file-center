# Gate5-G Architecture Amendment v1.0.0 — Independent Review Findings & Revision-2 Blockers

**Document Reviewed:** `docs/superpowers/specs/2026-09-11-gate5g-zfuse-transactional-mutation-architecture-amendment.md` (v1.0.0)  
**Date:** 2026-09-11  
**Review Status:** **FAILED INDEPENDENT ARCHITECTURE REVIEW / REVISION-2 REQUIRED**  
**Authorization Status:** IMPLEMENTATION NOT AUTHORIZED  

---

## 1. Executive Summary & Directional Verdict

Independent Architecture Review has assessed the proposed **Persistent Two-Phase Mutation Transaction Architecture** (v1.0.0).

### What Was Approved
- The overall architectural direction (**Approach B**: Persistent Two-Phase Transaction + Private Recovery Anchor + Reconciliation Engine) is confirmed as the **correct and necessary foundational model**.
- The mathematical proof that userspace `fs_ops-only` compound operations cannot close the TOCTOU gap on `zfuse` without persistent recovery anchors is accepted as conclusive.
- Approach A (Capability Gate Fail-Closed) as mandatory fallback and Approach C (Vendor FUSE driver) as long-term native path are approved.

### Why Revision 2 Is Required (Failed Review)
Although the high-level concept is sound, the concrete technical specification in v1.0.0 contains **nine specific gaps, ambiguities, or secondary race windows** that must be rigorously resolved before the architecture can be frozen or implementation authorized.

---

## 2. Comprehensive Inventory of Revision-2 Blockers

### Blocker 1: Anchor-Release TOCTOU / Last Trusted Anchor Deletion
- **Vulnerability**: In v1.0.0 Phase 4, the engine verifies `lstat(destination)` matches anchor, commits `state = 'active'`, and unlinks `anchor_path`.
- **The Gap**: Between `lstat(destination)` (or DB active commit) and `unlink(anchor_path)`, an external actor can unlink `destination_path` and substitute foreign data. If `anchor_path` is unlinked at this point, the **last trusted reference** to the original inode is destroyed, resulting in original payload loss and a corrupted active quarantine entry.
- **Requirement for Rev 2**:
  - The anchor release must verify that `destination_path` is not only present and matching, but that its link count confirms the inode is anchored at the destination.
  - Formally specify the post-retirement anchor retention or atomic link-count verification invariants (`st_nlink >= 2` before anchor unlink).

### Blocker 2: Source-Path Replacement Causing Deletion of Third-Party Inode
- **Vulnerability**: In Phase 3, the engine executes `os.unlink(source)`.
- **The Gap**: Between Phase 1 (`link(source, anchor)`) and Phase 3 (`unlink(source)`), a concurrent third-party process on the NAS can replace `source` with a newly created, unrelated file. A blind `unlink(source)` will delete the third-party's new file.
- **Requirement for Rev 2**:
  - Phase 3 MUST verify that `source` still points to the exact same physical inode (`st_ino`, `st_dev`) as `anchor` before calling `unlink`.
  - If `source` was replaced by an external actor, `source` must NOT be unlinked! The engine must fail closed, preserve the replacement file, preserve the anchor, and transition to `conflict`.

### Blocker 3: Missing `DB = preparing` + Anchor-Present Crash Boundary
- **Vulnerability**: In v1.0.0 Crash Matrix, Q1 assumed anchor does not exist when `DB == 'preparing'`, and Q2 assumed DB already committed `anchor_established`.
- **The Gap**: A crash can occur immediately after `os.link(source, anchor)` succeeds on the filesystem, but **before** SQLite commits the transition from `preparing` to `anchor_established`.
- **Requirement for Rev 2**:
  - Add explicit crash boundary $Q_{1.5}$ (`DB == 'preparing'` AND `anchor` physically exists on disk).
  - Define deterministic reconciler behavior: verify whether `anchor` matches `source`, clean up orphan anchor safely, or advance according to observed filesystem facts.

### Blocker 4: `ACTIVE` + Anchor-Present Cleanup Safety
- **Vulnerability**: In v1.0.0, if a crash occurs in Q9/Q10 (after DB commits `active`, but before anchor is cleaned up), the reconciler cleans up the orphan anchor.
- **The Gap**: If `destination` was damaged, removed, or replaced while the system was down, blindly unlinking the orphan anchor during startup reconciliation destroys the only remaining copy of the user's data.
- **Requirement for Rev 2**:
  - Even when `state == 'active'`, the reconciler MUST verify that `destination_path` exists and its physical inode matches `anchor` before unlinking the anchor.
  - If `destination` is missing or mismatched, the anchor must be preserved into an incident holding directory (`quarantine/.conflicts/<tx_id>/`), and the entry marked `conflict`.

### Blocker 5: `tx_id` vs. `QuarantineEntry.id` Contradiction
- **Vulnerability**: Section G generated a random UUID `tx_id`, while Section P (Option DB-1) claimed the anchor path was deterministically bound to `quarantine_root + "/.tx/" + str(entry.id) + "/anchor"`.
- **The Gap**: `entry.id` is an auto-incrementing integer only available after database flush, and if a transaction is aborted and retried, using `entry.id` alone creates directory re-use races. Conversely, a random UUID requires a database column to persist in DB-1 unless an explicit deterministic compound token format is specified.
- **Requirement for Rev 2**:
  - Formally specify the exact transaction token and path convention (e.g. `quarantine/.tx/tx_<entry_id>_<generation_token>/anchor`), explaining how it is bound to both the database record and the filesystem without schema migrations under Option DB-1.

### Blocker 6: Reconciliation Authority Integration with Existing Recovery Subsystems
- **Vulnerability**: v1.0.0 defined a standalone `reconcile_interrupted_transactions()` without defining how it meshes with existing NAS File Center lifecycle authorities:
  - `_reconcile_executing_item` in `app/tasks/handlers.py`
  - `BatchPlanItem` states (`planned`, `executing`, `completed`, `failed`)
  - `WorkJob` restart recovery (`app/tasks/recovery.py`)
  - `OperationJournal` logging
- **Requirement for Rev 2**:
  - Define the strict hierarchical execution order between `WorkJob` recovery, `BatchPlanItem` recovery, and `QuarantineEntry` reconciliation.
  - Clarify whether item reconciliation delegates to quarantine transaction reconciliation, ensuring single-source-of-truth convergence.

### Blocker 7: Stale-Worker Filesystem Fencing after Lease Takeover
- **Vulnerability**: If Worker A suffers a prolonged thread/FUSE stall, its `TaskLock` lease expires after 30 seconds. Worker B acquires the lease and reconciles the transaction. If Worker A resumes execution, it could execute queued filesystem calls (e.g. `unlink(source)`).
- **The Gap**: SQLite `BEGIN IMMEDIATE` only fences database commits; it does not block stale user-space threads from issuing POSIX filesystem calls.
- **Requirement for Rev 2**:
  - Define a filesystem fencing protocol (e.g. pre-mutation lease assertion, descriptor-level fencing, or transaction directory renaming by the taking-over worker) so that any filesystem mutation attempted by a preempted worker fails closed with `ENOENT` or `EBUSY`.

### Blocker 8: Private `.tx` Trust / Threat Boundary
- **Vulnerability**: The location and security boundaries of `quarantine/.tx/` were underspecified.
- **Requirement for Rev 2**:
  - Formally specify:
    - Path reservation and exclusion from indexing (`IndexRoot`, `fclones`, scan jobs).
    - API router layer filtering (preventing path traversal into `.tx/`).
    - Permission model (`0700` restricted to container service user).
    - Threat model regarding SMB/NFS host mounts sharing the quarantine volume.

### Blocker 9: Parent/Path-Walk Race and `dir_fd` / `O_NOFOLLOW` Analysis
- **Vulnerability**: The fallback description referenced string-based path operations without addressing symlink substitution in ancestor directories during multi-phase execution.
- **Requirement for Rev 2**:
  - Incorporate the Gate5-E E4 `safe_open_parent_fd` descriptor-relative paradigm (`linkat`, `unlinkat`, `fstatat` with `dir_fd` and `AT_SYMLINK_NOFOLLOW`).
  - Prove that ancestor directory replacement cannot redirect publication or source retirement outside authorized roots.

---

## 3. Verdict & Actionable Directive

```text
VERDICT: FAILED INDEPENDENT ARCHITECTURE REVIEW
REVISION-2 REQUIRED BEFORE IMPLEMENTATION
```

**Directives for Revision 2**:
1. Incorporate resolutions for all 9 blockers directly into `docs/superpowers/specs/2026-09-11-gate5g-zfuse-transactional-mutation-architecture-amendment.md`.
2. Do NOT write or modify production code.
3. Do NOT implement database migrations.
4. Do NOT attempt runtime NAS validation.
5. Push the complete evidence bundle to GitHub for auditability.
