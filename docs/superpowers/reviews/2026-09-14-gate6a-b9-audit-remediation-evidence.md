# Gate6-A B9 Bulk Restore Audit Remediation Evidence

Date: 2026-09-14

## Scope

This evidence addresses independent-review finding `G6A-R1`, which blocked the
previous exact candidate `ef73c5967d024fabce49076e221110cebe13c0e8` because
Gate6-A Bulk Restore did not fully satisfy the frozen per-entry audit contract.

The defect had two parts:

- several Execute-time terminal failure branches durably marked a
  `BatchPlanItem` failed and immediately continued without adding a matching
  `AuditEvent`;
- normal Bulk Restore audit details did not persist the frozen
  `conflict_policy`.

The release semantics are unchanged: Bulk Restore remains selected-only,
`skip|rename`, never-overwrite, with explicit partial failure. Plan 1 Permanent
Purge remains fail-closed.

## RED

Test-only commit:

`8c696b7575081729693a7c403b18bcd35f6d0540`

Formal Gate6-A TDD run:

`34811945000`

Observed RED evidence:

- preserved Gate5-G regression: `48/48 PASS`;
- Gate6-A focused suite: `3 failed, 63 passed, 30 skipped`;
- all three failures were confined to the new Bulk Restore audit contract
  assertions in `tests/test_gate6a_bulk_restore_worker_handler.py`.

The failures independently demonstrated:

1. successful restore audit lacked `conflict_policy`;
2. Validate-ready -> entry becomes non-active -> Execute failed safely but
   emitted zero restore failure audits;
3. a `[completed, failed, completed]` partial batch emitted only two restore
   audits instead of one audit for each terminal item.

No production code changed in the RED commit.

## Minimal production remediation

Production fix commit:

`6fd51a3fdaaf7f68bd7cfa42fd18ae8f5e0cbdef`

`BatchPlanExecuteHandler.run()` now adds Gate6-A Bulk Restore failure audit
records before terminal early-continue commits for the relevant restore paths,
including missing entry authority, Execute-time non-active state, missing frozen
target, and destination validation failure.

The emitted per-entry audit binds the durable/frozen facts required by the
architecture contract:

- `quarantine_entry_id`;
- frozen `target_path`;
- frozen `conflict_policy`;
- terminal result/reason;
- plan/item/task linkage.

Existing pre-mutation and final source-integrity failure audits are likewise
enriched with entry ID, frozen target, and conflict policy. The normal Phase-3
restore audit now records `conflict_policy` as well.

The patch does not change filesystem mutation authority, overwrite behavior,
selection semantics, Worker lease fencing, Plan 1 purge reachability, or any
Gate5-G transactional safety invariant.

## GREEN before push

Dedicated remediation workflow:

`34812367860`

The workflow checked out exact RED parent
`8c696b7575081729693a7c403b18bcd35f6d0540`, applied the production patch with
exact match-count guards, and required all checks to pass before pushing the
production commit.

Observed GREEN evidence:

- focused `tests/test_gate6a_bulk_restore_worker_handler.py`: `4/4 PASS`;
- preserved Gate5-G regression: `48/48 PASS`;
- `git diff --check`: PASS;
- production fix pushed only after those checks passed.

The first helper workflow attempt (`34812289994`) stopped before testing or
pushing because an exact patch anchor count did not match. It made no canonical
production change. The corrected helper run above is the authoritative GREEN
remediation run.

## Closure consequence

This evidence does **not** claim Gate6-A closure. The B9 remediation changed the
canonical candidate after the previous exact-candidate TDD, Closure, NAS image,
and independent review.

The commit containing this evidence becomes a new exact candidate and therefore
must receive fresh:

- formal Gate6-A TDD;
- Full Closure verification;
- exact-candidate linux/amd64 NAS-loadable image packaging and provenance;
- truly independent Implementation + Security re-review of baseline
  `8e7e2a669268117c2b7f0c83e14e6e32199fc8ba` to the new candidate;
- only after independent PASS, isolated real-NAS acceptance.

PR #1 must remain unmerged until those gates complete.
