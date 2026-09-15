# Gate6-A restore authority / containment remediation evidence

Date: 2026-09-14

## Scope

This evidence records remediation of the independent-review blockers against candidate `7eca4ffaea332b4861c2e06e60e7f59310a9716f`:

1. B3/B8/B9: `skip_preexisting_target` could be forged in mutable item metadata and normal lifecycle/Worker did not consistently prove `source_path == quarantine_entry.quarantine_path`.
2. NEW-03/B5: malformed metadata on a normal `planned` restore item could escape the per-item boundary and prevent a healthy sibling from continuing.

Permanent Purge Plan 1 release scope is unchanged and remains fail-closed.

## Strict RED

- original independently blocked candidate: `7eca4ffaea332b4861c2e06e60e7f59310a9716f`
- tests-only RED lineage:
  - `97e9599cfe478c271d3b1220570136e4efdec461`
  - `a5792aae6c0132289d8b06135feff6df3e061510` (renamed into the Gate6-A focused glob; no production-code change)
- authoritative RED run: `34833988364`
- RED job: `103943504682`
- exact RED checkout: `a5792aae6c0132289d8b06135feff6df3e061510`
- Gate5-G preserved: 48/48 PASS
- focused Gate6-A result: 3 failed / 79 passed / 30 scope-deferred skipped

The three intended failures were:

- forged post-Freeze `skip_preexisting_target=true` reclassified a new foreign occupant as pre-existing skip;
- a frozen restore item could cross-bind `source_path` to another active qentry while retaining the original qentry id;
- malformed metadata on a normal `planned` restore item escaped at the early Worker JSON parse and blocked a healthy sibling.

Regression file: `tests/test_gate6a_bulk_restore_review_blockers.py`.

## Production remediation

Production fix commit: `3a518add246d668aabdb0ac3a458f1c348287282`

Exact parent: `a5792aae6c0132289d8b06135feff6df3e061510`.

Production diff only:

- `app/api/quarantine_bulk_plan.py`
- `app/quarantine/bulk_lifecycle.py`
- `app/service.py`
- `app/tasks/handlers.py`

Diff size: 213 insertions / 16 deletions.

The remediation elevates the authoritative Preview/Draft pre-existing-skip decision into plan-level `restore_skip_authority`, binding qentry/source, target, conflict policy, and preview digest. Freeze, Validate, and the normal Worker path apply one shared binding contract. Item metadata alone can no longer create skip authority. The normal planned Worker intake now contains malformed/non-object restore metadata per item, records terminal failure safely, and continues unrelated siblings.

## GREEN

- GREEN workflow run: `34834796078`
- GREEN job: `103946059542`
- exact RED parent locked before patching
- targeted restore/reviewer regressions: 17/17 PASS
- preserved quarantine/Gate5-G set: 48/48 PASS
- production commit and push occurred only after both sets passed and only while canonical still equalled the exact RED parent.

No NAS acceptance was performed and no merge was performed.

## Next gate

This document commit is evidence-only. Its exact SHA must receive fresh exact-candidate Gate6-A TDD and Full Closure verification before packaging or independent re-review. Green remediation evidence is not itself release authorization.
