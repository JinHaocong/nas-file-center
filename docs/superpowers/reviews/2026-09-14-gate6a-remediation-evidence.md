# Gate6-A Destructive-Operation Remediation Evidence

Date: 2026-09-14
Baseline: `8e7e2a669268117c2b7f0c83e14e6e32199fc8ba` (`v0.3.5.1`)
Earlier code-remediation parent: `50cdfc02baf6104fd9d881219b7647efe905e472`
Latest Worker authority remediation: `e3de17210f9e383ef18f0c6ba94bf8a8fbc0c8ac`

This record summarizes the safety remediation performed after independent implementation/security review preparation for Gate6-A quarantine bulk restore and permanent purge. It is evidence only; Gate6-A remains open until exact-candidate automated closure, independent review, and real-NAS acceptance are complete.

## Remediated blockers

1. Destructive unlink ABA/path-replacement window: destructive purge no longer performs an unchecked path-based unlink after qualification; each destructive slot is re-opened and requalified under the parent descriptor immediately before mutation, with lease fencing and pathname/descriptor identity comparison.
2. Validate-to-Execute ownership race: purge execution revalidates authoritative ownership before initial capture and fails closed if a historical owner becomes active/restoring/restored/unknown or if topology authority changes.
3. Frozen QuarantineEntry identity drift: Worker compares persisted entry identity against frozen operation identity before entering transactional purge capture.
4. Destructive purge protocol migration: payload-bearing aliases are captured as same-inode witnesses and terminal destruction is represented by durable destroy intent plus zero-length same-inode tombstones instead of unsafe path disappearance assumptions.
5. Restart/recovery coverage: tests cover durable marker ordering, tombstone completion, partial capture recovery, foreign/private-slot preservation, selected-only mutation, partial batch outcomes, and per-selected-entry audit results.
6. Terminal-purge audit recovery: if the irreversible QuarantineEntry state reaches `purged` before Worker Phase 3 commits item/audit state, restart reconciliation reconstructs the selected purge audit and every frozen `historical_conflict_candidate` audit idempotently from `frozen_purge_topology_manifest`, keyed by plan/item/selected entry/preview digest plus linked path and owner.
7. Frozen topology authority at Execute/recovery: once a plan is frozen, Worker purge capture, normal historical-conflict audit finalization, and terminal crash-recovery audit reconstruction read `frozen_purge_topology_manifest` rather than the mutable draft `purge_topology_manifest`.
8. Per-item purge freshness semantics: `quarantine_purge` is excluded from generic whole-plan, item-boundary, and final-immediate stale fences. Purge-specific frozen identity + Capture → Qualification performs the final authority checks, so one selected entry can fail closed on path replacement without aborting later selected entries.

## B6 strict TDD evidence

RED candidate: `590c4420cbda7fd48b858d6008c04d5e9e8d2348`.

Observed RED:
- preserved quarantine/Gate5-G regression suite passed first;
- Gate6-A focused suite collected 83 tests;
- result: 82 passed, 1 failed;
- the sole failure was `test_restart_reconstructs_historical_conflict_audit_after_terminal_purge_crash` because restart produced zero historical-conflict audits where one frozen alias audit was required.

GREEN remediation runner: GitHub Actions run `34793375959`.

Observed GREEN before production commit:
- patch script compiled;
- `app/tasks/handlers.py` compiled;
- `git diff --check` passed;
- preserved quarantine/Gate5-G plus all Gate6-A bulk/purge/recovery focused tests passed;
- only after GREEN, the runner committed `50cdfc02baf6104fd9d881219b7647efe905e472` with message `fix(gate6a): reconcile historical purge audits after crash`;
- the temporary remediation workflow deleted itself in the same commit.

## Frozen-authority / per-item partial-failure strict TDD evidence

Test-only RED commit: `16d798f93bf2d690044309af6b2b5264070705b4`.

Three regression tests were added without production changes:
- `test_bulk_purge_source_replacement_is_item_local_failure_and_batch_continues`;
- `test_bulk_purge_execute_uses_frozen_manifest_not_mutable_draft_manifest`;
- `test_terminal_purge_recovery_audits_from_frozen_manifest_not_mutable_draft`.

Observed RED in Gate6-A TDD run `34795136601`:
- preserved quarantine/Gate5-G regression suite passed;
- Gate6-A focused suite collected 86 tests;
- result: **83 passed / 3 failed**;
- source replacement after Validate caused generic plan-level stale handling before any selected item could execute;
- Worker Execute consumed the tampered draft manifest instead of the frozen manifest;
- terminal crash recovery consumed the draft manifest and omitted a frozen historical-conflict audit.

First minimal remediation attempt was deliberately not committed. Runner `34795275094` changed the whole-plan and item-boundary freshness gates plus frozen-manifest reads, then ran the full preserved/focused set. Result: **85 passed / 1 failed**. The remaining failure showed a third generic `Final immediate source identity/stat check` still applied to `quarantine_purge`: the first selected entry completed, the middle replacement failed at that generic fence, and the loop `break` prevented the third selected entry from executing. The GREEN commit step was skipped.

Final remediation runner: `34795391819`.

Observed GREEN before production commit:
- exact RED head identity was verified;
- all replacement patterns matched exactly once;
- `app/tasks/handlers.py` and the regression test file compiled;
- `git diff --check` passed;
- preserved quarantine/Gate5-G regressions passed;
- all **86 / 86** Gate6-A focused backend tests passed;
- only after GREEN, the runner committed `e3de17210f9e383ef18f0c6ba94bf8a8fbc0c8ac` with message `fix(gate6a): enforce frozen purge authority and per-item stale handling`.

The production change is intentionally narrow:
- generic whole-plan preflight excludes `quarantine_purge`;
- generic item boundary freshness excludes `quarantine_purge`;
- generic final-immediate freshness excludes `quarantine_purge`;
- purge Phase 1 requires `frozen_purge_topology_manifest`;
- normal historical-conflict audit finalization uses the frozen manifest;
- terminal crash-recovery historical audit reconstruction uses the frozen manifest.

Purge-core capture, qualification, lease fencing, frozen QuarantineEntry identity binding, destroy-intent ordering, descriptor identity, and zero-length tombstone protocol were not weakened by this remediation.

## Remaining release blockers

- Exact final candidate normal Gate6-A TDD must pass.
- Exact final candidate full closure/security/build workflow must pass.
- Exact final candidate linux/amd64 Docker build must pass.
- npm audit remains intentionally non-clean and tracked separately; no `npm audit fix --force` is permitted in this destructive-operation gate.
- An actual independent review submission is still required; a reviewer request alone does not count.
- Real NAS/zfuse acceptance is still required and remains user-controlled.

Do not merge PR #1 or mark Gate6-A closed until all remaining blockers above are satisfied.
