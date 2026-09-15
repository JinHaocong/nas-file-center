# Gate6-A B10–B12 Plan-1 Remediation Evidence

Date: 2026-09-14
Baseline: `8e7e2a669268117c2b7f0c83e14e6e32199fc8ba` (`v0.3.5.1`)
Superseded candidate: `110d9002875470e473ea2de026e196d90fec7505`

This record documents the remediation after the final independent re-review found B10–B12. It does not claim Gate6-A closure; exact-candidate TDD/Closure, final independent review, and supported-scope real-NAS acceptance remain required.

## Approved scope decision

B10 exposed a structural conflict between pathname/NFC ownership authority and inode-global descriptor zeroization: `ftruncate(fd, 0)` is descriptor-bound against ABA but zeroes every hard link to the inode, including an unselected user/third-party hard link outside NFC-managed namespaces. Target zfuse cannot safely prove global hard-link exhaustion because `st_nlink` is not authoritative.

The approved resolution is safety scope withdrawal, not a weaker destructive primitive:

- Gate6-A v0.3.6 does **not** execute COMPAT/zfuse permanent purge.
- Bulk Restore remains supported.
- Purge Preview returns blocked with `PERMANENT_PURGE_DEFERRED_UNSAFE_HARDLINK_SCOPE`.
- Purge Plan generation creates zero destructive plan rows.
- UI permanent-purge action is disabled with explanatory copy.
- `execute_item(operation="quarantine_purge")` returns `EOPNOTSUPP` before purge filesystem mutation, including stale/handcrafted plans.
- Real-NAS acceptance for v0.3.6 must not execute COMPAT permanent purge.

The frozen decision is recorded in `docs/superpowers/specs/2026-09-14-gate6a-compat-purge-deferral-amendment.md`.

## B10 evidence

Test-only RED commit: `80add0e190536623ab61b4bcf06b1095f0a06620`.

The regression contract proves:
- purge Preview is blocked without mutation;
- purge Plan generation creates zero `BatchPlan`/`BatchPlanItem` rows;
- a handcrafted/stale `quarantine_purge` executor item fails with `EOPNOTSUPP` before filesystem mutation;
- an external unselected same-inode hard link preserves its original bytes.

Backend/API/executor production commit: `a6ddfa7719af604ea886712cd0addb205f097c22` (`fix(gate6a): defer unsafe bulk permanent purge`).

Observed helper validation run `34803765273`: PASS for B10 release boundary, preserved Gate5-G, and Bulk Restore coverage.

Frontend production commit: `3a2b12cef2d54a6a4cee12da7e1c1cfc3a2c578d` (`fix(gate6a): disable deferred bulk purge UI`).

Observed frontend helper run `34803944258`: RED→GREEN; permanent-purge UI disabled/explained while Bulk Restore remains available.

## B11 evidence

B11 reproduced the crash state where DB generation is durable and `attempt-N/` exists but `attempt-N/purge/` does not, plus repeated allocation-before-directory crash states.

Dedicated recovery tests are retained in `tests/test_gate6a_purge_recovery_generation_gap.py`.

Production commit: `0fbc77f1467d86d001f1e491c899c8d4867b83b9` (`fix(gate6a): recover interrupted purge generation preparation`).

Observed strict helper RED→GREEN run `34804580359`: PASS after remediation.

Recovery now treats current `active_attempt_generation` as durable monotonic state. It can resume a safe allocated attempt missing only its `purge/` child, and it does not require `current == frozen + 1`. If the current generation was durably allocated but its attempt directory never reached disk, recovery advances to the next write-once generation rather than reusing an uncertain generation pathname.

## B12 evidence

Test-only commit: `31e108b3e2482dc3dcb80171bf85647047c5cbbd`.

Dedicated RED run `34805079346` executed only the B12 audit-contract tests. Both tests reached the real purge reconciler and failed solely because the required AuditEvent did not exist:

1. `executing + purging/purging` post-intent resume required one idempotent `result="recovered"`, `recovery_phase="post_intent"` event;
2. unexpected transactional reconciliation state required one idempotent selected-purge `result="failed"`, `recovery_phase="reconciliation_failed"` event.

Both events bind `plan_id`, `item_id`, `quarantine_entry_id`, `preview_digest`, and reason.

GREEN remediation run `34805156237`: PASS. The runner required the B12 contract tests plus preserved Gate5-G regressions to pass before committing production code.

Production commit: `7d74cbda2ce330b5b50613b4302895effe05b87c` (`fix(gate6a): audit purge reconciliation outcomes`). Temporary RED/GREEN workflows and patch script were removed from the resulting tree.

## Test matrix migration

The earlier suite encoded permanent purge as a v0.3.6 released capability. After the approved B10 scope withdrawal, those expectations became obsolete rather than production regressions.

Migration run `34805364825` applied test-only scope changes, then required:

- preserved Gate5-G regressions: PASS;
- full Gate6-A focused backend: PASS.

Only after GREEN, commit `cc7798ead69816d993e0889ef2b4bf1e694eca7d` (`test(gate6a): align suite with deferred COMPAT purge scope`) was pushed.

Migration policy:
- old public/API/Worker tests that require successful v0.3.6 permanent purge are retained but explicitly marked scope-deferred;
- B10 release-boundary tests remain active;
- low-level transactional purge capture/qualification/ABA/lease/recovery tests remain active as dormant-core safety coverage;
- the B7 frozen-identity race remains active as a direct dormant-core test rather than routing through the now-disabled release executor;
- B11 repeated-crash test follows monotonic write-once generation semantics;
- B12 audit contract was renamed into the normal `test_gate6a_purge_recovery*.py` focused test glob.

## Remaining gates

This evidence commit intentionally triggers fresh normal Gate6-A TDD and Closure workflows on a new exact candidate. Gate6-A remains DO NOT MERGE until:

1. exact-candidate TDD passes (Gate5-G + Gate6-A backend + frontend);
2. exact-candidate full Closure/security/build + linux/amd64 Docker passes;
3. a fresh offline NAS image is built for that exact candidate;
4. final independent review explicitly evaluates B1–B12 and the B10 scope withdrawal;
5. supported-scope isolated real-NAS acceptance passes, including purge refusal/zero mutation and Bulk Restore behavior.
