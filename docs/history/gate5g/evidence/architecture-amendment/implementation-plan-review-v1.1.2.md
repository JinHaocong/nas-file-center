# Gate5-G / G7 Independent Implementation-Plan Review (v1.1.2)
# Final Implementation Plan Review Findings Archive

**Date:** 2026-09-11  
**Target Release:** NAS File Center v0.3.5  
**Branch:** `v0.3.5-gate5c-hotfix4`  
**Baseline Plan HEAD:** `f43f9276252cbd0c833ee7cffa36a47c1cdda49a`  
**Frozen Architecture HEAD:** `0ddf932747021578f08843c5069ef88a461d493f`  
**Production Code Baseline HEAD:** `c32d0778c59add81e0c296d6f73aa66bc403c04f`  
**Review Verdict:** **ERRATA IDENTIFIED / REVISION-1.1.3 FINAL CLOSURE REQUIRED**  

---

## 1. Executive Summary

The Independent Reviewer evaluated **Implementation Plan v1.1.2**. The architecture alignment, 13-variant reconciliation matrix, capability routing, and real-NAS path isolation were confirmed sound. 5 micro-level implementation errata were identified that must be closed in **Implementation Plan v1.1.3** to achieve implementation authorization readiness.

---

## 2. Authoritative Review Findings

### Finding 1: Correct `ctime` Semantics in Candidate Anchor Qualification
- **Defect**: v1.1.2 required candidate anchor `ctime` to match pre-link Gate3 source `expected_ctime_ns`.
- **Filesystem Reality**: Hard-link creation (`os.link`) creates a new directory entry pointing to the source inode, which increments `st_nlink` and legitimately updates the inode's `st_ctime`. Requiring candidate `ctime` to equal source pre-link `ctime` would cause false-positive qualification failures on POSIX filesystems. Furthermore, `BatchPlanItem` does not persist `expected_ctime_ns`.
- **Mandatory Closure**:
  - Pre-link Gate3 expected values: `dev`, `ino`, `size`, `mtime_ns`, `hash` (SHA256). Do not require pre-link `expected_ctime_ns`.
  - `ctime_ns` is used strictly as an **intra-qualification stability fence**: verify `st_dev`, `st_ino`, `st_size`, `mtime_ns`, and `ctime_ns` are completely unchanged between `fstat` before 1MiB SHA256 hashing and `fstat` after hashing on the candidate descriptor.
  - Replace `test_candidate_rejects_expected_ctime_mismatch` with `test_candidate_allows_legitimate_post_link_ctime_change_from_source_snapshot`.
  - Retain `test_candidate_rejects_ctime_change_during_hash`.
  - Do NOT modify Gate3 schema or `BatchPlanItem`.

### Finding 2: Fix `safe_open_parent_fd` Context Manager Usage & Signature
- **Defect**: v1.1.2 called `target_dfd = safe_open_parent_fd(...)` as a simple function.
- **Baseline Truth**: [`app/batch_utilities/empty_dir_quarantine.py::safe_open_parent_fd`](file:///Users/Kerwin/MyProject/nas-file-center/app/batch_utilities/empty_dir_quarantine.py#L90-L103) is a `@contextlib.contextmanager` yielding `(parent_fd, leaf_name)` and requiring `(source, allowed_roots)`.
- **Mandatory Closure**:
  - Update `resolve_mutation_capability` signature:
    ```python
    resolve_mutation_capability(
        source_path: Path | str,
        target_dir: Path | str,
        quarantine_root: Path | str,
        allowed_roots: Sequence[Path | str],
    ) -> MutationCapability
    ```
  - Use context manager:
    ```python
    probe_leaf = ".__probe_dummy"
    with safe_open_parent_fd(Path(target_dir) / probe_leaf, allowed_roots) as (target_dfd, _):
        probe_result = _probe_rename_noreplace_supported(dir_fd=target_dfd)
    ```
  - Verify probe executes on `target_dir` directly.

### Finding 3: Separate Filesystem Syscall Fence from DB Mutation Fence
- **Defect**: v1.1.2 did not explicitly distinguish the fence before a filesystem call from the fence guarding a DB state transition.
- **Mandatory Closure**:
  - **Pattern A (Payload Filesystem Syscall)**:
    `BEGIN IMMEDIATE` -> renew/assert worker lease -> `COMMIT`. No SQLite transaction held across FUSE call. Execute exactly ONE filesystem syscall.
  - **Pattern B (Worker-Authorized DB Transition)**:
    `BEGIN IMMEDIATE` -> `assert_active_worker_lease(session, worker_id)` -> perform DB mutation (`tx_phase`, `state`, `authoritative_anchor_path`, `active_attempt_generation`, `BatchPlanItem`, etc.) -> `COMMIT`. The lease assertion and DB mutation MUST reside in the SAME short write transaction.
  - Generation allocation MUST specifically be: `BEGIN IMMEDIATE` -> `assert_active_worker_lease` -> increment generation -> `COMMIT`.
  - Add RED tests proving a stale worker cannot commit a `tx_phase`/`state` or generation update post-takeover.

### Finding 4: Worker Lease Null Safety Order
- **Defect**: Checking `lock.acquired_at.tzinfo` before ensuring `lock.acquired_at is not None`.
- **Mandatory Closure**:
  - Preserve baseline order: check `if not lock.acquired_at: raise JobLeaseLost(...)` before accessing `lock.acquired_at.tzinfo`.

### Finding 5: Task 6 Path Typo Correction & Audit
- **Defect**: Task 6 commit step referenced `tests/test_gate5g_hotfix1_fs_ops.py`.
- **Mandatory Closure**:
  - Correct to `tests/test_gate5g_g7_hotfix1_fs_ops.py`. Audit all git add paths across all 12 tasks.
