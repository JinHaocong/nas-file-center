# V1.6 Worker permission acceptance implementation plan

> Use subagent-driven implementation and a separate scoped reviewer.

**Goal:** provide a concrete, opt-in real-NAS test of the verified Worker,
API and foreign identities using only a newly provisioned disposable scope.

**Spec:** ../specs/2026-11-19-v16-worker-permission-acceptance-design.md

**Stack:** Python standard library and the NAS's installed Docker CLI/image;
pytest-compatible focused tests. No new runtime dependency.

## Task 1: Implement the bounded controller and probes

Files: `scripts/v16_nas_worker_permission_acceptance.py` and
`tests/test_media_organizer_worker_permission_acceptance.py`.

- [x] Write focused regressions and record expected failures first.
- [x] Implement validation of live configuration and identities before fixture changes.
- [x] Limit provisioning to new, descriptor-checked sibling/unit inodes.
- [x] Implement restricted temporary-container attestation and the probe matrix.
- [x] Stop on unexpected mutations and verify retained synthetic evidence.
- [x] Emit a bounded local-permission result with custody/release always false.
- [x] Run focused tests and independently review the changes.

The test filename is included by the existing V1.6 workflow's
`tests/test_media_organizer_*.py` selection; no CI selector expansion is needed.

## Task 2: Document and publish the next NAS step

Files: `docs/real-nas-acceptance.md`, this plan and its design specification.

- [x] Record the owner's subsequent identity/mount evidence without private paths.
- [x] Specify disposable writes separately from the earlier read-only collector.
- [x] Document the final CLI, result schema and remaining acceptance boundary.

Publication procedure: atomically commit code, tests and documentation on
the existing Draft PR with an expected-head lease. Compare the published
file blob identities, then provide a commit-pinned download/checksum command.
Report local verification, CI and actual NAS status separately.

## Verification record

- Initial feature RED: all six initial focused tests failed because the
  new helper did not yet exist.
- Behavioral RED: 10 passed and two failed for missing directory fsync and
  separate unrelated-UID traversal denial. Corresponding GREEN: 12 passed.
- Cleanup/opt-in RED: 11 passed and three failed. Corresponding GREEN:
  all 14 focused helper tests passed.
- The separate reviewer and integration controller each independently ran
  all 14 helper tests and all 15 existing preflight tests successfully.
- The tests exercise identity/maps/groups/capabilities and mount mismatch,
  read prerequisites, unexpected-success stopping, denial errno handling,
  real disposable-file snapshot reads/replacement detection, directory
  fsync failures, explicit opt-in, Docker construction and cleanup outcomes.
- Isolated CLI checks passed for missing explicit opt-in, invalid data-root
  encoding, non-root refusal and help. Both new Python files compiled.
- Material review fixes: typed Docker `.ID` fields; separate existing-entry
  stat/search denial; frozen metadata checks before bounded reads; full
  explicit opt-in spelling; cleanup exclusively by a successful create's
  returned full ID. Ambiguous creation is a failure with retained evidence,
  not a reason to remove a container discovered by name or label.
- Optional hardlink/publication probes were deliberately left outside this
  local-permission step. Existing issuer, app/deployment flags and old NAS
  fixtures remain outside the change.
- The local workspace is a targeted source snapshot with no pytest package
  or Docker daemon. Tests used a standard-library direct function runner;
  no full local suite, live Docker/Go-template execution or ZOS/FUSE run is
  claimed. The Docker template correction was checked against upstream
  source. Actual NAS behavior remains an owner-executed acceptance step.
- This scoped independent code review is not production security sign-off
  for #398. CI for the new commit is reported separately from these results.
