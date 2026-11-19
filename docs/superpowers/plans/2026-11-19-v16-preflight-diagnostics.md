# V1.6 Preflight Diagnostic Correction Implementation Plan

> For agentic workers: use subagent-driven-development for the scoped implementation and independent review.

**Goal:** make read-only metadata reports accurately distinguish possible Worker access from exclusive namespace ownership, and preserve useful failure details.

**Architecture:** extend only the standalone diagnostic and its focused tests; record the owner's sanitized NAS evidence in the acceptance runbook. The production issuer and organizing implementation remain unchanged.

**Tech Stack:** Python standard library; pytest.

**Spec:** ../specs/2026-11-19-v16-preflight-diagnostics-design.md

## Global Constraints

- No production NAS changes or permission repair; no new dependency.
- Keep no-follow directory inspection, read-only behavior and private path redaction.
- Keep release_ready=false and namespace_exclusive_custody_proven=false.
- The modeled group is --shared-gid; supplementary groups, actual mapping and runtime filesystem enforcement are not verified.

## Review Focus

- Shared-group access must not remove exclusive-writer blockers.
- Owner/named-user denial cannot fall through to broader group/other grants.
- Matching ACL groups and their mask must grant both write and search in one entry.
- Missing ACL evidence must remain unknown, with a review condition.
- Error details must locate the directory depth without leaking a path or leaving open descriptors.

## Task 1: Correct the report

Files: scripts/v16_nas_namespace_custody_preflight.py and tests/test_media_organizer_namespace_custody_preflight.py.

- [x] Add regressions for the observed API-owned 2770/shared-GID case, POSIX/ACL precedence and masks, unknown ACL metadata, and a denied ancestor's structured error details.
- [x] Run the regressions against the pinned baseline and retain the expected failures.
- [x] Implement the minimal metadata-model and error-detail correction described in the spec.
- [x] Run focused regressions and verify the read-only/custody boundaries remain intact.
- [x] Obtain independent code review; resolve material findings.
- [x] Commit the complete code/test/documentation change atomically to the existing feature branch with a head lease.

## Task 2: Record the next NAS evidence boundary

Files: docs/real-nas-acceptance.md and this plan.

- [x] Record the sanitized host observation and distinguish the legacy API harness from a new Worker fixture.
- [x] Specify that actual API/Worker IDs, groups, maps and capabilities precede provisioning; local multi-UID mutation probes must use a newly approved disposable scope.
- [x] Report local verification separately from pending CI and actual NAS acceptance.

## Verification and review record

- Initial focused RED: 7 existing test functions passed; 7 new regression
  functions failed against the pinned baseline for the expected reasons.
- Initial focused GREEN: all 14 test functions passed.
- Independent review reproduced a pre-existing ACL errno classification bug:
  Linux errno 93 (`EPROTONOSUPPORT`) was treated as `ENOATTR` when that name
  was unavailable. Only actually defined absence errno values are now used.
- Review-fix RED: 14 passed, 1 failed; review-fix GREEN: 15 passed, 0 failed.
- Independent scoped re-review passed all 15 focused tests and confirmed
  the ACL classification and delivery-command findings were addressed.
  This is code review of the diagnostic correction, not the independent
  production security sign-off required by #398.
- Tests ran through a standard-library direct function runner in a non-root
  Python 3.12 environment. The snapshot has no pytest installation; no full
  repository suite or new-head CI result is claimed here.
- Unmocked local CLI checks covered the group-writable case, retained
  ownership/group blockers, redacted missing-component diagnostics, and
  unchanged fixture metadata/content. Local temporary storage returning
  `ENOTSUP` correctly produced unknown ACL evidence.
- Deferred minor: the existing effective-UID-based fixture pattern assumes
  a non-root test runner; root test-runner portability was not expanded in
  this diagnostic change. Running the collector itself as root with an
  explicit non-root Worker UID remains supported.
- Actual NAS runtime identities, multi-UID enforcement, external writer
  exclusion and full lifecycle acceptance remain outstanding. No NAS
  permissions, old test artifacts or production execution flags changed.
