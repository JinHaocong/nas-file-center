# Gate6-A G6A-NEW-01 frozen restore target recovery remediation

## Identity

- Production baseline: `8e7e2a669268117c2b7f0c83e14e6e32199fc8ba`
- Superseded reviewed candidate: `6176a36f6eba0e9e5e2f613f6abb6df1c4875bdc`
- Independent-review blocker: G6A-NEW-01 — Bulk Restore `rename` could lose the frozen `BatchPlanItem.target_path` across a crash while `QuarantineEntry` was still `restoring`, causing generic reconciliation to fall back to `entry.original_path`.

## Strict TDD RED

Test-only commit:

`bc8a786c7f5e9be1684520f2ef082b3b9aaaad00`

Parent:

`6176a36f6eba0e9e5e2f613f6abb6df1c4875bdc`

RED workflow:

`34818189755`

Observed evidence:

- preserved Gate5-G: `48/48 PASS`
- previous Gate6-A restore reconciliation-audit regressions remained PASS
- previous Bulk Restore worker-handler regressions remained PASS
- three new real crash-state regressions failed, and only those new regressions failed in the focused Gate6-A suite: `3 failed, 68 passed, 30 skipped`
- failure modes matched G6A-NEW-01 exactly:
  1. original owner disappeared after crash and recovery incorrectly restored to `original_path` instead of frozen rename target;
  2. original owner remained and recovery failed/conflicted instead of restoring to the safe frozen rename target;
  3. frozen rename target was already published before crash but recovery still reasoned around `original_path` and converged to conflict.

The third regression restarts/runs the Worker repeatedly to exercise idempotent convergence.

## GREEN production remediation

Verified GREEN helper workflow:

`34818504866`

The helper locked canonical at the exact RED parent, detached at that SHA, applied a guarded patch, and allowed the canonical fast-forward only after all verification steps succeeded.

Production fix commit:

`68984464fea886e4fd9d53f754c46a2463be3bc3`

Parent:

`bc8a786c7f5e9be1684520f2ef082b3b9aaaad00`

Production diff is restricted to:

`app/quarantine/reconcile.py`

GREEN evidence:

- NEW-01 crash regressions + prior G6A-R2 reconciliation-audit regressions + existing Bulk Restore worker-handler regressions: `9/9 PASS`
- preserved Gate5-G: `48/48 PASS`
- full Gate6-A focused backend suite: PASS

## Correctness invariant

For interrupted Gate6-A `quarantine-bulk-restore` execution, reconciliation now recovers the durable frozen restore authority from the unique executing `BatchPlanItem` bound to the quarantine entry.

- If a Gate6-A executing restore item exists, its frozen `target_path` is the recovery destination authority.
- `rename` recovery must never re-select `QuarantineEntry.original_path` merely because the original occupant disappeared or remained present after Freeze/Validate.
- If the frozen target is already published with the expected authoritative inode, recovery converges without another payload mutation.
- If the frozen target is occupied by a foreign inode, recovery fails closed; it does not overwrite.
- Ambiguous executing Gate6-A restore authority or a missing frozen target fails closed before restore publication.
- Legacy/non-Gate6-A transactional restore reconciliation retains its historical `original_path` behavior when no Gate6-A executing restore item applies.

## Preserved frozen semantics

This remediation does not authorize Permanent Purge and does not change Plan 1 release scope.

It does not weaken:

- selected-only and active-only Bulk Restore authority;
- no-overwrite restore behavior;
- Worker lease/fencing around filesystem mutation;
- authoritative anchor qualification;
- G6A-R1 per-entry audit contract;
- G6A-R2 terminal-qentry exactly-once audit convergence;
- B11 durable purge generation recovery invariant;
- Plan 1 `quarantine_purge` release-executor refusal.

## Closure requirement

The documentation commit containing this evidence becomes a new exact candidate and requires fresh exact-candidate Gate6-A TDD, Full Closure, exact-image packaging, artifact fingerprint verification, and a truly independent Implementation + Security re-review before any real NAS acceptance.
