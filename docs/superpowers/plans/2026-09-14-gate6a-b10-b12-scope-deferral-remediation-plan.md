# Gate6-A B10–B12 Scope-Deferral Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close independent-review blockers B10–B12 without weakening Gate5-G or re-enabling unsafe COMPAT permanent purge in v0.3.6.

**Architecture:** Treat B10 as a release-scope withdrawal, not an inode-global zeroization patch: API, UI, and Worker/executor all fail closed before purge filesystem mutation. Keep the existing purge core dormant but repair its recovery state machine (B11) and audit truth (B12) with strict TDD so no known crash/audit defect remains hidden in retained code.

**Tech Stack:** Python 3.12, SQLAlchemy/SQLite, pytest, FastAPI, React/TypeScript, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-14-gate6a-compat-purge-deferral-amendment.md`

## Global Constraints

- `main` / v0.3.5.1 remains untouched.
- B10 release behavior: `quarantine_purge` is never executable in v0.3.6; Worker must fail before filesystem mutation.
- Bulk Restore remains supported.
- Do not remove Gate5-G safeguards or introduce payload-bearing unlink/rmtree.
- Dormant purge-core B11/B12 fixes MUST NOT re-enable the executor path.
- Strict TDD: observe each new regression RED before production code change.
- Any final code change requires fresh exact-candidate TDD, Closure, linux/amd64 image, independent review, and supported-scope NAS acceptance.

---

### Task 1: Verify/lock B10 fail-closed release boundary

**Files:**
- Test: `tests/test_gate6a_bulk_plan1_scope_reduction.py`
- Verify: `app/api/quarantine_bulk.py`
- Verify: `app/execution/executor.py`
- Verify: `frontend/src/pages/Quarantine/index.tsx`

- [ ] Confirm Preview blocks purge with `PERMANENT_PURGE_DEFERRED_UNSAFE_HARDLINK_SCOPE`.
- [ ] Confirm Plan generation creates zero destructive plan rows.
- [ ] Confirm handcrafted/stale `quarantine_purge` execution returns `EOPNOTSUPP` before mutation and an external same-inode hard link keeps original bytes.
- [ ] Confirm Bulk Purge UI is disabled with explanatory copy while Bulk Restore remains executable.
- [ ] Preserve existing observed GREEN evidence; do not rewrite already-correct production code unless a regression appears.

---

### Task 2: B11 — Recover allocated attempt directory before `purge/` creation

**Files:**
- Create: `tests/test_gate6a_purge_recovery_generation_gap.py`
- Modify: `app/quarantine/purge.py`

- [ ] **RED 1:** simulate crash after `attempt-N` mkdir succeeds but before `attempt-N/purge` mkdir. On retry assert the same current generation is resumed, `purge/` is created safely, captures proceed, and no new generation is allocated.
- [ ] **RED 2:** simulate a previously advanced current generation greater than `frozen+1` with its current attempt directory absent/empty. Assert recovery uses the already-durable current generation instead of requiring `frozen+1` or incrementing again.
- [ ] Verify current implementation fails with `PURGE_RECOVERY_REQUIRED`.
- [ ] Implement one recovery helper that treats DB `active_attempt_generation` as the durable allocated generation: if `current==frozen`, allocate once; if `current>frozen`, recover/create exactly `attempt-current`, require it to be a real directory, reject unknown contents, create/resume exact `purge/` under lease fencing, and never increment merely because a prior filesystem mkdir crashed.
- [ ] Run B11 tests + existing purge recovery/capture tests + preserved Gate5-G regressions and require GREEN.

---

### Task 3: B12 — Recovery/resume and reconciliation-failure audit truth

**Files:**
- Create or modify: `tests/test_gate6a_purge_recovery_audit_contract.py`
- Modify: `app/tasks/handlers.py`

- [ ] **RED 1:** reconcile `BatchPlanItem=executing` with selected `QuarantineEntry=purging/purging`. Assert item returns to `planned` and exactly one idempotent `AuditEvent(operation="quarantine_purge", result="recovered")` exists with `plan_id`, `item_id`, `quarantine_entry_id`, `preview_digest`, and `recovery_phase="post_intent"`.
- [ ] **RED 2:** reconcile a valid selected purge item whose qentry is in an unexpected transactional state. Assert item becomes `failed` and exactly one selected purge failure AuditEvent records qid + preview digest + reconciliation reason.
- [ ] Verify both tests fail against current handler.
- [ ] Add a small idempotent purge-recovery-audit helper used by pre-intent, post-intent, and reconciliation-failure branches. Deduplicate by plan/item/qid/preview_digest/result/recovery_phase.
- [ ] Keep terminal `purged/purged` completion and historical-conflict audit reconstruction unchanged.
- [ ] Run B12 tests + existing restart/preintent/terminal/historical audit tests + preserved Gate5-G regressions and require GREEN.

---

### Task 4: Migrate obsolete executable-purge tests to deferred-scope contract

**Files:**
- Modify only tests that still create purge plans through the public API or assert Worker success through `execute_item`.

- [ ] Do not delete purge-core unit/recovery coverage; call dormant core helpers directly where the test is specifically validating retained recovery logic.
- [ ] Update public API/Worker tests to expect release deferral, not successful purge.
- [ ] Require focused Gate6-A suite to be internally consistent with the approved v0.3.6 scope.

---

### Task 5: Final candidate closure

- [ ] Record B10–B12 RED/GREEN evidence in remediation docs.
- [ ] Run normal Gate6-A TDD on the exact final SHA: preserved Gate5-G + all focused backend + frontend PASS.
- [ ] Run full Closure Verification: backend full regression, frontend test/typecheck/build, security/diff checks, API/Worker image consistency, linux/amd64 Docker PASS.
- [ ] Build a fresh offline NAS image only for the new exact SHA.
- [ ] Update PR #1 to state that v0.3.6 NAS acceptance excludes COMPAT permanent purge and is limited to supported Bulk Restore/non-destructive Gate6-A behavior.
- [ ] Obtain final independent Implementation + Security PASS before any real-NAS operation.