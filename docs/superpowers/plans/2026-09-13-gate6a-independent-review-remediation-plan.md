# Gate6-A Independent Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remediate all six blocking findings from the independent review of baseline `8e7e2a669268117c2b7f0c83e14e6e32199fc8ba` to candidate `9fb3f92fad653f73944832f8d13a8bdf801e9701` without weakening Gate5-G safety or touching `main`.

**Architecture:** Keep Gate6-A serial per-entry orchestration and frozen Preview/Draft/Freeze/Validate semantics. Amend the purge execution protocol so public/historical aliases are captured into high-entropy, role-addressable, write-once private leaves with no pre-check-to-rename window; destructive payload removal becomes descriptor-bound zeroization of the single qualified inode, leaving zero-length private tombstones as durable recovery evidence instead of pathname unlink. Move DB-only ownership authority revalidation into the same `BEGIN IMMEDIATE` transaction as `active -> purging`, add purge-aware crash reconciliation, and route purge stale/failure handling through the per-item purge engine so later selected entries continue and audits remain entry-bound.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/SQLite, POSIX/Linux filesystem syscalls, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-13-gate6a-quarantine-bulk-operations-architecture-freeze.md`

## Global Constraints

- Stable v0.3.5.1 / Gate5-A..G behavior is read-only and must not be weakened.
- Data safety > correctness > recoverability > performance > UI aesthetics > feature count.
- No payload-bearing broad recursive delete; no `rmtree`; no unsafe fallback unlink.
- `ctime` remains diagnostic-only for SHA256-authoritative zfuse payloads; `st_nlink` is forbidden as authority.
- No SQLite write transaction may span a potentially blocking zfuse syscall.
- Each payload-affecting syscall must be preceded by Worker lease renewal/assertion.
- Real NAS acceptance remains a hard merge blocker after automated closure.

---

### Task 1: Amend Gate6-A purge protocol for race-free payload destruction

**Files:**
- Modify: `docs/superpowers/specs/2026-09-13-gate6a-quarantine-bulk-operations-architecture-freeze.md`
- Test: `tests/test_gate6a_transactional_purge_capture_target_race.py`
- Test: `tests/test_gate6a_transactional_purge_destroy.py`
- Test: `tests/test_gate6a_purge_recovery.py`

**Interfaces:**
- Logical slot roles remain `authoritative_anchor`, `captured_source`, `public_view`, and `historical_conflict_candidate`.
- Physical capture leaves become `<logical-slot>--<128-bit-random-token>` and are never reused.
- Recovery discovers physical leaves by strict logical-role prefix within the current monotonic purge generation.
- Destruction authority is descriptor-bound zeroization (`ftruncate(fd, 0)`) of the fully qualified payload inode, not pathname unlink.
- Zero-length private leaves are durable tombstone evidence and may remain after terminal `purged`; they are non-payload metadata/evidence, not authoritative live payload aliases.

- [ ] **Step 1: Write failing tests for B1 and B2**
  - Capture test injects a would-be fixed-slot occupant between old pre-check and rename and proves the new protocol never targets a predictable reusable leaf and never overwrites the foreign object.
  - Destroy test replaces a captured pathname after descriptor qualification and proves the exact opened qualified inode is zeroized while the replacement object is preserved and causes fail-closed closure rather than being unlinked.

- [ ] **Step 2: Run focused tests and verify RED for the intended reasons.**

- [ ] **Step 3: Implement high-entropy role-addressable physical capture leaves and remove deterministic payload destination reuse.**
  - Use a cryptographically strong token generated immediately before the single rename syscall.
  - Do not expose the physical leaf name through a filesystem pre-check.
  - Recovery must discover role leaves by strict parser, reject unknown names, reject multiple payload leaves for one logical alias, and fail closed when both source and role leaf are missing.

- [ ] **Step 4: Replace payload unlink with descriptor-bound zeroization.**
  - Qualify every captured alias first.
  - Re-open one canonical qualified leaf with `O_NOFOLLOW`, re-check dev/inode/size/mtime/SHA256, renew/assert lease, then `os.ftruncate(fd, 0)`.
  - Never unlink payload-bearing capture leaves in Gate6-A COMPAT purge.
  - After zeroization, verify all discovered logical-role leaves are regular files with the frozen dev/inode and size `0`; any foreign/unknown object is preserved and blocks terminal closure.

- [ ] **Step 5: Update crash recovery semantics.**
  - If source and role leaf are both missing, always `PURGE_RECOVERY_REQUIRED`; absence alone is never destruction proof.
  - A zero-length same-inode tombstone in the current purge generation is durable destruction evidence.
  - Original-size qualified leaves mean zeroization still needs to run.
  - Mixed/foreign evidence fails closed.

- [ ] **Step 6: Run focused purge capture/destroy/recovery tests and verify GREEN.**

- [ ] **Step 7: Commit the protocol amendment and implementation.**

---

### Task 2: Make ownership authority revalidation atomic with `active -> purging` (B3)

**Files:**
- Modify: `app/quarantine/purge.py`
- Test: `tests/test_gate6a_bulk_preview_purge_owner_race.py`
- Test: `tests/test_gate6a_transactional_purge.py`

**Interfaces:**
- Keep filesystem topology observation outside SQLite write transactions.
- Add a DB-only ownership revalidation helper that queries current same-payload `QuarantineEntry` rows and validates frozen historical owner identities/states without filesystem I/O.
- `_begin_transactional_purge_intent(...)` must run this DB-only helper under the same `BEGIN IMMEDIATE` transaction that commits `state='purging'`.

- [ ] **Step 1: Write a failing race test that changes a historical owner after filesystem topology observation but before the intent transaction and expects zero filesystem mutation plus BLOCK.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement DB-only ownership revalidation inside `_begin_transactional_purge_intent`.**
- [ ] **Step 4: Verify GREEN and preserved no-zfuse-under-SQLite-write-lock discipline.**
- [ ] **Step 5: Commit.**

---

### Task 3: Reconcile terminal purge success after Worker crash (B4)

**Files:**
- Modify: `app/tasks/handlers.py`
- Test: `tests/test_gate6a_purge_recovery_restart.py`
- Test: `tests/test_gate6a_bulk_purge_audit.py`
- Test: `tests/test_gate6a_bulk_purge_history_audit.py`

**Interfaces:**
- `_reconcile_executing_item(...)` gets an explicit `quarantine_purge` branch.
- If selected `QuarantineEntry` is already `purged/purged`, the item is reconciled to `completed` and the same selected-entry + historical-alias audit evidence that Phase 3 would have written is recreated in the reconciliation transaction.
- If entry remains in a resumable purge phase, the item returns to `planned` so the purge engine resumes; it must not be converted to a generic failed freshness result.

- [ ] **Step 1: Write a failing test for crash after terminal `QuarantineEntry=purged` commit but before `BatchPlanItem`/Audit finalize.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Implement purge-aware reconciliation and idempotent audit/journal recreation.**
- [ ] **Step 4: Verify GREEN.**
- [ ] **Step 5: Commit.**

---

### Task 4: Make bulk purge partial failure truly per-entry and auditable (B6)

**Files:**
- Modify: `app/tasks/handlers.py`
- Test: `tests/test_gate6a_bulk_purge_partial.py`
- Test: `tests/test_gate6a_bulk_purge_audit.py`
- Test: `tests/test_gate6a_bulk_purge_worker_handler.py`

**Interfaces:**
- Generic whole-plan freshness preflight must not abort `quarantine_purge` items; purge-specific frozen identity/topology checks remain authoritative.
- Generic boundary/final freshness abort paths must not `break` the Gate6-A purge loop.
- Every purge failure must produce an AuditEvent containing `quarantine_entry_id` and `preview_digest`.
- Later selected entries continue unless Worker/job authority is lost.

- [ ] **Step 1: Write a failing three-entry test where the middle purge entry becomes frozen-identity stale and assert `[completed, failed, completed]` plus one failure audit bound to entry + preview digest.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Exclude `quarantine_purge` from generic whole-plan/boundary freshness aborts and rely on purge-specific execution validation.**
- [ ] **Step 4: Ensure purge-specific failed results reach normal Phase 3 audit/finalization and loop continuation.**
- [ ] **Step 5: Verify GREEN.**
- [ ] **Step 6: Commit.**

---

### Task 5: Frozen manifest authority cleanup

**Files:**
- Modify: `app/tasks/handlers.py`
- Test: `tests/test_gate6a_bulk_purge_worker_handler.py`

**Interfaces:**
- Execute must consume `frozen_purge_topology_manifest` when present; legacy draft-only paths may use `purge_topology_manifest` only before Freeze, never as destructive authority after a frozen plan exists.

- [ ] **Step 1: Write a failing test where mutable draft manifest diverges from frozen manifest and Execute must use the frozen one.**
- [ ] **Step 2: Verify RED.**
- [ ] **Step 3: Route purge execution to the frozen manifest.**
- [ ] **Step 4: Verify GREEN.**
- [ ] **Step 5: Commit.**

---

### Task 6: Full closure and independent re-review

**Files:**
- Modify as evidence only: PR #1 body/comments and closure artifacts.

- [ ] Run preserved Gate5-G regression suite.
- [ ] Run all Gate6-A focused backend tests.
- [ ] Run frontend Gate6-A tests.
- [ ] Run full backend regression.
- [ ] Run frontend tests, typecheck, and production build.
- [ ] Run baseline-to-HEAD diff/security checks.
- [ ] Build/load linux/amd64 Docker image and record immutable identity/artifact digest.
- [ ] Update PR #1 with exact new candidate SHA and evidence.
- [ ] Send exact new candidate to an independent reviewer; do not self-approve.
- [ ] Only after independent PASS, proceed to isolated real 极空间 zfuse NAS acceptance.
