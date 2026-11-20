# V1.6 security review preparation implementation plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`; preserve the observed RED → GREEN evidence for each repair.

**Goal:** Repair verified remaining safety defects and prepare PR #397 for a genuine non-author review without granting release authority.

**Architecture:** Keep the existing frozen-manifest, separate Worker, immutable cleanup-plan and explicit recovery design. Correct missing authorization boundaries locally. Distinguish deterministic identity checks and cooperative maintenance coordination from externally enforced namespace custody.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/SQLite, pytest, Linux directory/file descriptors, GitHub Actions.

**Spec:** Owner's 2026-11-20 migration instructions; GitHub issues #398–#403. Baseline source is `4b554477a9b4b5b90fb4a6c01b8814b7c50d4811`.

## Global constraints

- Preserve recursive P/V, conflict suffixes, homogeneous-directory rules and idempotence.
- Do not overwrite foreign files, introduce ordinary-rename fallbacks, or weaken tests or safety checks.
- Unproven namespace custody must fail closed; maintenance acknowledgement is not a kernel exclusion proof.
- Preserve failed-operation evidence, existing original paths and independently confirmed recovery boundaries.
- Do not change production NAS or homelab-komodo, merge/mark Ready, publish images/tags, or close unapproved security issues.
- Old physical NAS PASS belongs only to `f93f9d74d4992c291b685a177acc72941f6e8325`; do not rerun or transfer that claim.
- Same baseline HEAD has nine successful required workflows; Release Validation skipped while Draft; submitted PR reviews: zero.

## Review focus

- Worker lease expires after the last checkpoint but before a nested filesystem operation: no further authorized media mutation or stale database validation commit.
- A filesystem name changes type while opening a planned regular file: reject promptly without blocking the sole Worker.
- A source/directory name changes after identity checks: preserve foreign objects and reject when exclusive authority is unavailable.
- Recovery starts with partial or mismatched private evidence: no expanded scope, implicit destructive replay, or invented finalization.
- A historical acceptance report or self-review is mistaken for current-source or independent release approval: retain exact provenance and open gates.

## Task 1: Fence Worker-owned storage probes and validation (#403)

**Files:** `app/storage_optimization/jobs.py`, `app/storage_optimization/capability.py`, relevant validation methods in `app/service.py`; focused regression tests.

**Interfaces:** Thread an optional callable mutation fence through capability probe entry points, including hardlink/reflink nested operations. Worker handlers supply an active-lease/lock/reservation assertion. Validation supplies a worker identity for a final in-transaction active-lease check.

- [x] Preserve the three observed real-lease-expiry failures as repository regression tests.
- [x] Add a separate stale-validation-commit assertion: item/plan state must remain unchanged when lease is lost immediately before persistence.
- [x] Invoke the fence before each scratch mutation and preserve recovery evidence if authority is lost; do not convert lease loss into a supported capability result.
- [x] Revalidate the lease inside the final validation transaction before committing item/plan state.
- [x] Run the new tests and existing storage/API/quarantine/maintenance boundary regressions.

## Task 2: Recheck staging and publication (#401)

**Files:** `app/batch/media_organizer_stage.py`, `app/batch/media_organizer_publish.py`, FD-link helpers and focused source-race tests.

**Interfaces:** Preserve verified open-file-FD linking and the absence of name-based link/rename fallbacks.

- [x] Trace active Worker and recovery call paths; distinguish legacy synthetic paths.
- [x] Demonstrate any regular-file open/type-change defect in temporary fixtures before modifying production.
- [x] Apply the smallest bounded/nonblocking open correction supported by the reproduction.
- [x] Verify identity drift refuses publication and original files remain intact.

## Task 3: Enforce and document unproven namespace hold (#399/#402)

**Files:** Shared operation-authority/execute/cleanup guards, corresponding boundary tests, security review notes.

**Interfaces:** Strict custody remains independently issued and production-deny. Any maintenance safety restriction must apply at API submission and Worker execution/recovery, with immutable evidence retained.

- [x] Trace active original/stage unlink, wrapper/stage rmdir and public-group creation boundaries.
- [x] Record the demonstrated limitations of last-check identity validation and the existing maintenance contract.
- [x] Add fail-closed tests for unavailable exclusive authority at each reachable production mutation path; do not claim that a replacement followed by an exception prevented the mutation.
- [x] Implement the minimal hold required by the current owner safety requirement and explicitly document any loss of maintenance-mode execution availability.
- [x] Keep strict/synthetic lifecycle tests and report genuine functional/release blockers rather than weakening an acceptance gate.

## Task 4: Cleanup protocol, integrated verification and handoff (#400/#398)

**Files:** Cleanup plan/job/finalization/handoff modules as evidence requires; review notes and issue comments.

- [x] Verify plan digest, manifest/job/unit binding, separate confirmation, recovery ancestry, BEGIN/DONE journal replay and zero-scan finalization ordering.
- [x] Record whether evidence proves payload hashes or only file metadata; never broaden the claim.
- [x] Review the complete diff separately from implementation, repair confirmed findings with focused tests.
- [ ] Verify local targeted/full backend tests as warranted, push only after checking the live branch HEAD, and inspect current-source CI job logs on failures.
- [ ] Update corresponding issue evidence; keep #398 and issues requiring non-author approval open, preserve Draft and release restrictions.

## Execution record

- 2026-11-20: Live PR/issue/review/CI state fetched. Baseline confirmed unchanged; isolated local checkout created. Engineering review tasks split by scope. No existing production files or NAS services changed.
- 2026-11-20: #403 three real Worker-lease-expiry regressions observed RED against baseline. Both scratch mutations and stale validation persistence occurred after expiry; later terminal checkpoint rejection was too late.

- 2026-11-20: Three baseline namespace-boundary experiments reproduced foreign-entry deletion/adoption. Production API, queued Worker and recovery paths now require external custody for both modes, including flat stage creation; the live issuer remains unavailable.
- 2026-11-20: Three FIFO-open failures observed RED then GREEN. Existing descriptor-based source linking preserved; no ordinary rename fallback added.
- 2026-11-20: A separate patch review found eight additional issues. Probe collision/read and custody tests: 8 RED → 8 GREEN. Worker flush/contention/startup/caller tests: 4 RED → 4 GREEN. Iterable scope consumption also RED → GREEN; read-only-mount coverage wording corrected.
- 2026-11-20: Existing storage/API/validation/fencing modules: 58 passed. Additional Worker/heartbeat/recovery/media-sort regression: 76 passed. These are scoped overlapping runs, not an aggregate full-suite result.
- Post-commit gates: record exact new SHA and current-source Actions results in PR #397 and issue evidence. None of the baseline CI, synthetic fixture tests or engineering agent reviews grants independent security approval or release authority.
- 2026-11-20: Legacy storage recovery bypass reproduced at prepared/new, captured/old and published states. Held custody now covers mutating execution/recovery and journal extension; completed reconciliation stays read-only. Five failures plus one existing pass became six passing new tests; the relevant combined execution/fencing suite passed 36 cases.
