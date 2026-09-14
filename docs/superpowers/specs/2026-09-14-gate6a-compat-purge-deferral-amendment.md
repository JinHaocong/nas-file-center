# Gate6-A COMPAT Permanent Purge Deferral Amendment

**Date:** 2026-09-14  
**Status:** APPROVED SAFETY SCOPE AMENDMENT  
**Baseline:** `8e7e2a669268117c2b7f0c83e14e6e32199fc8ba` (`v0.3.5.1`)  
**Applies to:** Gate6-A v0.3.6 closure candidate only

## 1. Decision

Gate6-A v0.3.6 no longer authorizes execution of `COMPAT_TRANSACTIONAL` permanent payload purge on zfuse.

Bulk Restore remains in Gate6-A. Bulk purge selection/preview may remain visible for explanation, but it MUST fail closed and MUST NOT create an executable destructive plan. Worker/executor handling of any stale, handcrafted, or previously-created `quarantine_purge` item MUST return `EOPNOTSUPP` before any filesystem mutation.

The COMPAT purge engine and its tests may remain in the branch as dormant research/recovery code, but v0.3.6 release authority MUST NOT route production execution into its destructive phase.

## 2. B10 rationale: namespace authority vs inode-global mutation

The previous descriptor-zeroization protocol used `ftruncate(fd, 0)` to avoid pathname unlink ABA. That syscall is descriptor-bound but inode-global: every hard link to the selected inode observes the same zeroed payload.

Gate6-A ownership authority is narrower. It only proves NFC-owned aliases in the frozen selected topology and explicitly does not claim authority over arbitrary user/third-party hard links outside NFC-managed namespaces. Because `st_nlink` is unreliable on target zfuse and because the system cannot enumerate arbitrary hard links globally, Gate6-A cannot prove that an inode has no unselected external hard link before zeroization.

Therefore no available COMPAT primitive in the current architecture simultaneously proves both:

1. the destructive syscall is bound to the exact selected object without pathname ABA; and
2. the destructive effect is limited to selected/NFC-owned pathname authority.

Data safety takes precedence over feature completion. COMPAT permanent purge is deferred rather than weakening either invariant.

## 3. Frozen v0.3.6 behavior

For `action="purge"`:

- bulk Preview returns selected active entries as ineligible with stable reason `PERMANENT_PURGE_DEFERRED_UNSAFE_HARDLINK_SCOPE`;
- bulk Plan generation creates zero `BatchPlan` / `BatchPlanItem` destructive work and returns a blocked result;
- frontend permanent-purge action is disabled and explains the deferral;
- `execute_item(operation="quarantine_purge")` returns failed `EOPNOTSUPP` before reading/mutating purge payload state;
- no existing stale/handcrafted plan may bypass this executor gate;
- no Gate6-A real-NAS acceptance step shall execute permanent purge in v0.3.6.

Bulk Restore remains executable and must preserve its existing no-overwrite/frozen-target semantics.

## 4. Dormant purge-core hardening retained

Even though release execution is withdrawn, previously-reviewed purge-core recovery guarantees remain valuable and are kept as testable invariants. B11 and B12 from the final independent review MUST still be closed before Gate6-A closure:

- B11: crash recovery must recognize an allocated current attempt directory even when its `purge/` child was not created yet, and must tolerate repeated pre-directory crashes without artificially advancing into an unrecoverable generation state;
- B12: post-intent resume and reconciliation failure must emit idempotent `quarantine_purge` AuditEvents bound to `plan_id`, `item_id`, `quarantine_entry_id`, and `preview_digest`.

These fixes do not re-enable COMPAT purge execution.

## 5. Closure impact

The prior `110d900...` Closure/NAS image evidence is superseded by any code or documentation change after this amendment.

A new exact candidate requires:

1. strict RED→GREEN evidence for B11 and B12;
2. B10 fail-closed regression coverage at Preview, Plan, UI, and Worker/executor layers;
3. preserved Gate5-G tests;
4. full backend/frontend Closure and linux/amd64 Docker build;
5. independent re-review of baseline → new candidate;
6. real-NAS acceptance limited to the supported Gate6-A surface (Bulk Restore and non-destructive orchestration), with no COMPAT permanent purge execution.

PR #1 remains **DO NOT MERGE** until the new candidate independently passes review and supported-scope real-NAS acceptance.