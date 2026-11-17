# Media Organizer V1.6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. This plan is compatible with Matt Pocock's to-tickets → implement → tdd → code-review flow.

**Goal:** Deliver approved V1.6 deterministic renaming and 200-item layout for both MediaPackage and semantic, with semantic recursive unit discovery and safe preview/execute.

**Architecture:** Leave MediaPackage's fixed-layout path contract intact, reuse its pure naming / size rules, and add a separate read-only semantic unit planner and boundary-aware discovery. Integrate through authenticated Worker jobs and the existing verified, no-replace execution lifecycle; never substitute a generic os.rename shortcut.

**Tech Stack:** Python 3.12+, pytest, FastAPI, SQLite/SQLAlchemy, WorkJob/Worker, React 18, TypeScript, Vite.

**Spec:** docs/superpowers/specs/2026-11-17-media-organizer-v1.6-design.md (privately approved source is the V1.6 资料空间 document).

## Global constraints

- Exactly 200 pure images/videos → unit root 001–200, no bucket. 201+ pure → buckets of maximum 200.
- Mixed image and video, any count → P/V buckets. Every media filename is reallocated deterministically from 001, preserving the last original extension's spelling.
- P, P_1, V, V_1 buckets show actual count and byte-derived human size; use MediaPackage formatter. Other follows the current legacy logic.
- Canonical units have zero moves and zero renames; correct numbering in a wrong directory is NOT canonical.
- Protect author/work/collection/version/batch boundaries; only verified media-classification wrappers may be collapsed.
- No actual NAS mutation in automated tests; tests use tmp_path and synthetic harmless names. No private user's path inventories committed.
- Preserve allow-root, symlink, no-clobber, frozen manifest, Worker lease, report integrity and crash recovery protections.
- Do not modify the current generic media_sort behavior as a side effect; semantic is a separate mode.

## Review focus (mandatory overlooked inputs)

1. Source directory contains a symlink or foreign mounted child → blocked without traversal (tests in tasks 2 and 4).
2. P directory contains independent works, despite its name → must NOT flatten across work boundaries (task 4 test).
3. Mixed upper/lower extension and a real same-name collision in separate wrappers → all files kept; deterministic consecutive ordinals (task 3 test).
4. Existing canonical P [n size] buckets scanned in a different scandir order → already_organized with zero moves (task 3 test).
5. Interrupted rename publication and a foreign destination created mid-flight → no clobber; reproducible recovery state (task 6 tests).

---

### Task 1 — Capture MediaPackage's existing V1.6 contract (TDD regression slice)

**Files**
- Test: tests/test_media_package_naming.py
- Test: tests/test_media_package_organizer.py
- Touch production only if an approved test reveals an actual regression: app/batch/media_package_naming.py or app/batch/media_package_organizer.py

**Interfaces**
- Existing: numbered_name, allocate_names, preview_media_package_package.
- Produces: reviewed executable acceptance fixtures for 1/200/201, mixed extensions, and already-organized zero-work.

- [ ] Step 1: Add behavior tests for 200 pure files remaining flat, 201 split 200+1, numbering independent per group, stale bucket labels and canonical no-op.
- [ ] Step 2: Run tests/test_media_package_naming.py and tests/test_media_package_organizer.py; record the baseline result. Any new failing behavior test is RED only when it fails for the intended requirement.
- [ ] Step 3: Implement the smallest fix only if needed; do not change the fixed MediaPackage path validator.
- [ ] Step 4: Re-run the two modules and confirm GREEN.
- [ ] Step 5: Commit tests (and minimal fix if needed); fresh Standards and Spec review.

### Task 2 — First usable semantic read-only unit preview: pure ≤200 with old P1 wrapper

**Files**
- Create: app/batch/media_organizer_planner.py
- Create: tests/test_media_organizer_planner.py
- Reuse: app/batch/media_package_naming.py, app/batch/media_package_organizer.py helpers where safely callable

**Interfaces**
- Produces: preview_non_MediaPackage_unit(unit: Path, *, allowed_roots: list[Path], quarantine_root: Path | None = None) -> dict
- Contract: status, operation, totals, groups, planned source→target rows, input identity/fingerprint; no writes.

- [ ] Step 1 (RED): Construct a synthetic work with 28 JPGs in root + 7 JPGs in P1; assert 35 root targets named 001.jpg–035.jpg and no P folder, source files unchanged.
- [ ] Step 2: Run pytest tests/test_media_organizer_planner.py -q and confirm the expected new-function failure.
- [ ] Step 3 (GREEN): Implement minimal bounded read-only planner for one explicit unit using the existing size and naming rules; block symlinks and foreign paths.
- [ ] Step 4: Verify GREEN, no filesystem writes, and re-preview after simulating the canonical target yields zero changes.
- [ ] Step 5: Commit and perform fresh Standards + Spec review. No API or NAS mutation yet.

### Task 3 — Mixed media, grouping, historical aliases and idempotency

**Files**
- Modify: app/batch/media_organizer_planner.py
- Test: tests/test_media_organizer_planner.py
- Test: tests/test_media_package_organizer.py (regression coverage only)

**Interfaces**
- Extends preview_non_MediaPackage_unit contract without breaking Task 2.

- [ ] Step 1 (RED): Add parameterized cases 1P, 1V, 200P, 201P, 401P, 1P+1V, root+V, photos/videos, P/P, wrongly swapped P and V, Other, duplicate original basename and mixed extension case.
- [ ] Step 2: Assert exact group capacities, actual byte labels, stable ordinal assignment, and that every input identity survives exactly once. Verify RED on new cases.
- [ ] Step 3 (GREEN): Add independent P/V/Other bucket allocation, old-wrapper validation and last-extension classification using existing helpers.
- [ ] Step 4: Add random-order scan invariance and already_canonical_bucket_noop test; run both new and MediaPackage regression modules.
- [ ] Step 5: Commit; independent review emphasizing idempotency and no-clobber target allocation.

### Task 4 — Recursive semantic boundary discovery with blocked reasons

**Files**
- Create: app/batch/media_organizer_units.py
- Create: tests/test_media_organizer_units.py
- Modify: app/batch/media_organizer_planner.py only for compatible unit metadata

**Interfaces**
- Produces: discover_non_MediaPackage_units(selection: Path, *, allowed_roots: list[Path], quarantine_root: Path | None = None) -> Iterator[dict]
- Item fields: unit path, boundary kind, status/reason, no mutations.

- [ ] Step 1 (RED): Synthetic author/collection/A100-01/A100-02 yields two independent units; 4K/PT yields two; nested plain P/P wrapper yields one owning unit.
- [ ] Step 2: Add tests for P containing distinct works, ambiguous 1/2 dirs, non-month topic root, symlink and out-of-allowed-root; confirm RED.
- [ ] Step 3 (GREEN): Implement bounded DFS classification with non-crossing semantic boundaries, per-unit ambiguity reason, cancellation hooks.
- [ ] Step 4: Verify fixtures plus max-depth/entry limits and deterministic unit ordering.
- [ ] Step 5: Commit, review, and update glossary/ADR only for a genuinely new decision.

### Task 5 — Background preview + authenticated paginated API

**Files**
- Create: app/batch/media_organizer_jobs.py
- Prefer a separate router: app/media_organizer/router.py (new package), register in app/main.py
- Integrate task handler using app/tasks handler registration pattern (verify the real registry path before coding)
- Create: tests/test_media_organizer_jobs.py
- Create: tests/test_media_organizer_api.py

**Interfaces**
- POST /api/media-organizer/previews with selected scope → queued WorkJob ID.
- GET /api/media-organizer/previews/{job_id}?page=1&page_size=25&status=all → bounded page, summary, status.

- [ ] Step 1 (RED): Test unauthenticated request rejection, scoped-preview isolation, paginated ready/skipped/blocked rows, cancellation, and zero NAS mutations.
- [ ] Step 2: Confirm RED before implementation.
- [ ] Step 3 (GREEN): Reuse WorkJob queue/report patterns, bounded report output and status mapping; attach current identity fingerprint to every unit result.
- [ ] Step 4: Run API + worker + previous suites, then commit and review.

### Task 6 — Safe execution on a frozen manifest, with recovery

**Files**
- Create: app/batch/media_organizer_execution.py (adapter around existing no-replace/staged operations)
- Create: app/batch/media_organizer_execute_jobs.py
- Modify: app/media_organizer/router.py for confirmed execute endpoints
- Create: tests/test_media_organizer_execution.py
- Create: tests/test_media_organizer_execute_jobs.py

**Interfaces**
- POST /api/media-organizer/previews/{job_id}/execute with exact preview token and explicit mutation permissions.
- GET /api/media-organizer/executions/{job_id} for progress/recovery evidence.

- [ ] Step 1 (RED): Frozen original identity mismatches, symlink/mount swap, existing foreign target, race between validation/publish, crash after stage and after first publish, resuming with mismatched job ID.
- [ ] Step 2: Confirm expected failures; disable production mutations by default.
- [ ] Step 3 (GREEN): Persist manifest before syscalls; reuse audited directory FD/no-follow and no-replace primitives, lease/permission gates, recovery journal. Never silently downgrade safety on FUSE.
- [ ] Step 4: Verify simulated restart and exact file-byte/inode preservation where applicable; run MediaPackage execute/recovery regressions.
- [ ] Step 5: Commit and request a security-focused second review. Stop if safe publication semantics cannot be demonstrated.

### Task 7 — Batch UI + front/back integrated QA

**Files**
- Create: frontend/src/pages/Batch/SemanticOrganizerEditor.tsx
- Create: frontend/src/api/media_organizer.ts
- Modify: frontend/src/pages/Batch/index.tsx
- Create: frontend/tests/media_organizer_preview.test.tsx (adjust extension to repository test convention)

**Interfaces**
- Separate Batch operation; selection, start/cancel preview, statuses, group count/bytes, paginated moves, explicit safe execute confirmation and audit.

- [ ] Step 1 (RED): UI tests for scope selection, read-only progress, already_organized no-op, blocked reason, target size/count visibility and disabled execute until explicit confirmation.
- [ ] Step 2: Confirm RED; use synthetic API fixtures.
- [ ] Step 3 (GREEN): Implement smallest independent editor following current Batch UI components and media_package API conventions.
- [ ] Step 4: Run frontend test, typecheck/build and backend integration; commit and fresh two-axis review.

### Task 8 — Release gates and NAS pilot (human approved only)

**Files**
- Add relevant focused .github/workflows regression gate if needed.
- Document acceptance evidence under docs/, not private filename dumps.

- [ ] Step 1: Run full affected pytest suites and frontend test/typecheck/build in CI.
- [ ] Step 2: Independent Standards + Spec code review, plus explicit safety/no-delete review.
- [ ] Step 3: Test read-only preview on small real scopes; redact private data and inspect every source→target group.
- [ ] Step 4: Only after human confirms, pilot actual moves on a backed-up non-sensitive sandbox / disposable copy, not on the original NAS tree.
- [ ] Step 5: Verify second scan shows 0 changes; record audit/recovery result and request explicit approval before any larger rollout.

## Dependency graph

Task 1 → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 8.
Task 5 → Task 7 → Task 8. Tasks 6 and 7 can run in isolated worktrees in parallel after Task 5's API contract is stable.

## Execution notes

- Matt Pocock skills: setup-matt-pocock-skills, to-spec, to-tickets, implement (invokes tdd and code-review), pr.
- Each coding ticket is a fresh context/worktree. TDD means **observed RED → smallest GREEN → REFACTOR → affected regression checks → review → commit**. Do not label unexecuted tests as passing.
- This plan documents proposed interfaces; code owners must reconcile actual registry/router module names against the checked-out branch before writing production code.
- Development begins with document and issue review; tests and production code are intentionally not changed in this foundation-only PR.
