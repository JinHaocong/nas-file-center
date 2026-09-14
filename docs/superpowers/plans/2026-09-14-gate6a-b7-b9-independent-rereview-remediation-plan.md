# Gate6-A B7–B9 Independent Re-Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close independent re-review blockers B7–B9 without weakening Gate5-G COMPAT invariants or changing the real-NAS acceptance boundary.

**Architecture:** Keep `BatchPlanItem.expected_*` as the immutable payload authority for bulk purge. Carry that frozen identity through Worker Execute into the purge engine; bind it atomically with lease + ownership revalidation inside the same `BEGIN IMMEDIATE` that commits `active→purging`; never re-derive destructive identity from mutable `QuarantineEntry` after that point. Treat pre-intent Worker crashes as resumable, auditable work, and require a successful descriptor `fsync()` durability proof before any recovery path may commit terminal `purged`.

**Tech Stack:** Python 3.12, SQLAlchemy/SQLite, pytest, FastAPI worker state machine, POSIX descriptor-relative filesystem operations, GitHub Actions Gate6-A TDD/Closure.

**Spec:** `docs/superpowers/specs/2026-09-14-gate6a-independent-review-safety-amendment.md`

## Global Constraints

- Preserve Gate5-G COMPAT invariants and the v0.3.5.1 baseline semantics.
- No payload-bearing pathname unlink/rmtree in COMPAT purge.
- `st_nlink` is never safety/completeness authority.
- ctime remains diagnostic-only for SHA256-authoritative regular files.
- No SQLite write transaction is held across FUSE syscalls.
- Worker lease fencing remains mandatory before destructive mutation and terminal DB truth.
- Foreign/unknown evidence is preserved and fails closed.
- Any code change invalidates the prior exact-candidate closure/package and requires fresh TDD, full closure, linux/amd64 package, independent re-review, then real-NAS acceptance.

---

### Task 1: B7 — Atomically bind frozen payload identity to irreversible purge intent

**Files:**
- Modify: `tests/test_gate6a_transactional_purge_executor.py`
- Modify: `app/execution/executor.py`
- Modify: `app/quarantine/purge.py`

**Interfaces:**
- Consumes: `OperationItem.expected_device`, `expected_inode`, `expected_size`, `expected_mtime_ns`, `expected_hash`; frozen purge topology manifest.
- Produces: purge engine calls that require explicit frozen payload identity and `_begin_transactional_purge_intent(...)` that verifies that identity inside its `BEGIN IMMEDIATE` before `active→purging`.

- [ ] **Step 1: Write the failing race test**

Add a test that freezes payload X, lets `execute_item()` pass its initial frozen identity read, then monkeypatches `_begin_transactional_purge_intent` to atomically change the selected `QuarantineEntry` identity to Y and replace the frozen source aliases with hardlinks to Y immediately before the real intent transaction. Assert Execute fails with `PURGE_FROZEN_IDENTITY_CHANGED`, both X control evidence and Y payload remain non-zero, no attempt-2 purge namespace is created, and the selected row never enters `purging`.

- [ ] **Step 2: Run the test and verify RED**

Run the existing Gate6-A TDD focused suite. Expected: the new test fails because current `_begin_transactional_purge_intent` does not receive/verify `expected_*` and current qualification/destruction re-derive identity from `QuarantineEntry`.

- [ ] **Step 3: Implement minimal frozen-identity authority plumbing**

Pass the five frozen identity fields from `OperationItem` into `execute_transactional_purge_capture()` and `destroy_transactional_purge_capture()`. Extend `_begin_transactional_purge_intent()` to compare the selected row identity to those exact frozen values inside the same `BEGIN IMMEDIATE` as lease/ownership revalidation and `active→purging`. Qualification, marker material, descriptor destruction, recovery closure, and terminal commit must consume the passed frozen identity rather than mutable post-Freeze `QuarantineEntry` identity. Missing frozen identity must fail closed.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the new B7 race test plus transactional purge executor/intent/capture/qualification/destroy suites and preserved Gate5-G tests. Expected: PASS; X/Y are never destructively confused.

- [ ] **Step 5: Commit B7 remediation**

Commit only after observed GREEN.

---

### Task 2: B8 — Reconcile pre-intent Worker crash as resumable and auditable

**Files:**
- Modify: `tests/test_gate6a_purge_recovery_restart.py`
- Modify: `app/tasks/handlers.py`

**Interfaces:**
- Consumes: `BatchPlanItem.state=executing`, `metadata.execution.phase=intent`, frozen purge metadata, selected `QuarantineEntry` state.
- Produces: `executing + active/active` purge reconciliation to `planned`, plus an idempotent recovery AuditEvent bound to `plan_id`, `item_id`, `quarantine_entry_id`, and `preview_digest`.

- [ ] **Step 1: Write the failing pre-intent crash test**

Create a ready/frozen bulk purge plan, persist only Worker Phase-1 (`BatchPlanItem=executing`, execution phase `intent`) while keeping `QuarantineEntry=active/active` and payload untouched, simulate takeover/requeue, then run the new Worker. Assert reconciliation re-plans/retries the item, emits exactly one recovery audit with qid + preview digest, and the normal execution can complete; it must not mark the untouched item failed merely because the process crashed before purge intent.

- [ ] **Step 2: Run the test and verify RED**

Expected: current `_reconcile_executing_item()` maps `active/active` to failed and produces no purge recovery audit.

- [ ] **Step 3: Implement minimal reconciliation**

In the `quarantine_purge` reconciliation branch, treat selected `active/active` plus durable Worker execution intent as a pre-purge-intent crash: set item back to `planned`, clear the transient failure reason, and create an idempotent recovery audit (`result="recovered"`) containing plan/item/task/qid/preview_digest and a reason indicating no purge intent or filesystem mutation had occurred. Do not use this branch for any other selected lifecycle state.

- [ ] **Step 4: Run recovery + audit tests and verify GREEN**

Run B8 test, existing purge restart/terminal-commit/historical-audit suites, full Gate6-A focused tests, and preserved Gate5-G tests.

- [ ] **Step 5: Commit B8 remediation**

Commit only after observed GREEN.

---

### Task 3: B9 — Require successful payload fsync proof on zeroized recovery

**Files:**
- Modify: `tests/test_gate6a_transactional_purge_destroy.py` or `tests/test_gate6a_purge_recovery.py`
- Modify: `app/quarantine/purge.py`

**Interfaces:**
- Consumes: valid durable `destroy-intent.json`, complete same-inode size-zero tombstone closure, active Worker lease.
- Produces: a descriptor-bound recovery durability fence that re-opens one known private tombstone, verifies exact frozen dev/inode + size zero, renews/asserts lease, and successfully `fsync(fd)` before terminal `purged` may be committed.

- [ ] **Step 1: Write the failing fsync-error recovery test**

Fault-inject the first payload `os.fsync(fd)` after a successful `ftruncate(fd, 0)` to raise `EIO`, leaving the durable marker and observable zero tombstones. Simulate process restart/takeover, and instrument payload fsync on retry. Assert retry must perform a successful second descriptor fsync before terminal `purged`; if the retry fsync also fails, entry remains `purging` and terminal DB truth is not written.

- [ ] **Step 2: Run the test and verify RED**

Expected: current recovery sees marker + size-zero closure, sets `qualified=[]`, performs no second payload fsync, and can commit `purged`.

- [ ] **Step 3: Implement minimal durability recovery fence**

Add a helper that, after zeroized closure is established, opens a deterministic known private tombstone with `O_RDWR|O_NOFOLLOW`, verifies regular-file dev/inode/size against frozen identity, renews/asserts Worker lease, calls `os.fsync(fd)`, and re-verifies descriptor identity/size. Call it both after fresh zeroization and on marker+zero-tombstone recovery before terminal commit. Any open/stat/fsync error fails closed and leaves DB state non-terminal.

- [ ] **Step 4: Run destroy/recovery suites and verify GREEN**

Run the new B9 test, all purge recovery/destroy/capture tests, full Gate6-A focused tests, and preserved Gate5-G tests.

- [ ] **Step 5: Commit B9 remediation**

Commit only after observed GREEN.

---

### Task 4: Final exact-candidate closure and handoff

**Files:**
- Modify: `docs/superpowers/reviews/2026-09-14-gate6a-remediation-evidence.md`
- PR #1 body/comments only after exact SHA is known.

**Interfaces:**
- Consumes: GREEN commits for B7/B8/B9.
- Produces: a new exact candidate SHA and evidence set; no Gate6-A CLOSED claim.

- [ ] **Step 1: Record B7–B9 RED/GREEN evidence and resulting invariants.**
- [ ] **Step 2: Trigger normal Gate6-A TDD on the exact candidate and require preserved Gate5-G + all focused/backend/frontend tests PASS.**
- [ ] **Step 3: Run full Closure Verification and require backend regression, frontend tests/typecheck/build, diff/security checks, API/Worker image consistency, and linux/amd64 Docker build PASS.**
- [ ] **Step 4: Export/load/verify an offline linux/amd64 NAS image tar for the same exact SHA and record tar/image/manifest/artifact digests.**
- [ ] **Step 5: Update PR #1 to supersede `05e6dea...`, request independent re-review of the new exact candidate, and do not start NAS acceptance until that review returns PASS.**
