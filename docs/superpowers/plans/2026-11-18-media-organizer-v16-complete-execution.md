# V1.6 Complete Organizer Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans with test-driven-development. No production code without an observed failing test.

**Goal:** Finish real P/V grouped publication, safe original/wrapper cleanup and zero-change repeated scans without false security claims.

**Architecture:** Verified exclusive NAS namespace custody is a precondition for group publication and source-path deletion. Group directory publication removes name-based private pending-directory rename; all file publication remains source-FD pinned. A crash-safe journal drives finalization.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy WorkJobs, pytest, React/TypeScript, Linux renameat2/linkat, Docker.

**Spec:** `docs/superpowers/specs/2026-11-18-media-organizer-v16-complete-execution-design.md`

## Global Constraints

- Never modify production NAS media from CI, GitHub automation or without separate live authorization.
- Preserve defaults `MEDIA_ORGANIZER_EXECUTION_ENABLED=false`, `MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK=false`.
- Never treat a user ACK, a Worker lease or after-the-fact inode checks as exclusion of an uncooperative writer.
- No foreign file/dir deletion or relocation in fault-injection tests; no overwrite.
- Keep PR #397 Draft, no merge/release until complete behavior is verified.

## Review Focus

- Same-UID/root/SMB writers with parent directory mutation permission; fail closed without demonstrated isolation.
- Direct mkdir followed by swapped child before first open; cannot silently adopt foreign inode.
- Crash between source check and unlink; cannot unlink a foreign replacement.
- Existing numbered P/V groups and P1 wrappers in deep recursion; preserve every byte and collision suffix.
- Stale frozen manifests/mount identity and reordered directory entries; never double-execute.

## Tasks

### Task 1: Record real namespace trust model and capability gate

Files: `app/batch/media_organizer_capability_probe.py`, `app/batch/media_organizer_execution.py`, `tests/test_media_organizer_namespace_custody.py`, `docs/media-organizer-v16-execution-gate.md`.

- [ ] Write RED tests for shared-UID/group-writable/ACL/mount mismatches and rejection *before staging*.
- [ ] Verify RED in the dedicated V1.6 TDD workflow.
- [ ] Implement an enforceable custody validation interface; if mount proof cannot be obtained, return a hard stop. No bool-only bypass.
- [ ] Verify GREEN and record the limits of the proof.
- [ ] Commit.

### Task 2: Replace pending directory promotion

Files: `app/batch/media_organizer_publish.py`, `app/batch/media_organizer_deferred_cleanup.py`, `tests/test_media_organizer_pending_group_race.py`, `tests/test_media_organizer_publish.py`.

- [ ] RED: mixed P/V group under a mock/proven exclusive namespace publishes exact directory/file bindings; fault-injected source swap cannot relocate foreign directory.
- [ ] RED: crash before group receipt cannot adopt an unrecognized folder.
- [ ] Implement exclusive direct group creation under verified custody with durable receipt and FD-bound file links; remove V1.6 reachability of pending source rename.
- [ ] GREEN: all targeted group publication + recovery tests; commit.

### Task 3: Crash-safe audited cleanup and zero-change rescan

Files: `app/batch/media_organizer_cleanup_jobs.py`, `app/batch/media_organizer_deferred_cleanup.py`, `app/batch/media_organizer_execute_jobs.py`, `tests/test_media_organizer_finalization.py`.

- [ ] RED: frozen original paths, P1 wrappers and stage links remain after publication until separately confirmed cleanup.
- [ ] RED: under denied/revoked custody, no source unlink/rmdir occurs; foreign replacement survives.
- [ ] Implement private journal, per-unit confirmation and resumable cleanup with preflight proof; no broad directory delete.
- [ ] GREEN: finalization never precedes verified zero-change rescan and hash/count preservation; commit.

### Task 4: Wire complete UI / API semantics

Files: `app/batch/media_organizer_execute_jobs.py`, `app/media_organizer/router.py`, `frontend/src/pages/Batch/SemanticMediaOrganizerEditor.tsx`, `frontend/tests/media_organizer_preview.test.ts`.

- [ ] RED: grouped approval requires exact confirmed plan and effective custody proof; preview/complete/finalized states accurately shown.
- [ ] Replace temporary SEC-12 hold only after Tasks 1–3 make the Worker path safe.
- [ ] GREEN: frontend/backend focused tests; commit.

### Task 5: Isolated NAS and release

Files: `scripts/media_organizer_v16_real_nas_acceptance.py`, `docs/media-organizer-v16-execution-gate.md`, release notes.

- [ ] Check Linux filesystem semantics/permissions against the specific owner-created SATA acceptance root, with explicit execution authorization.
- [ ] Create disposable mixed-media, recursive, P1, conflict, interruption and homogeneous test sets. Check total counts and SHA-256 before/after.
- [ ] Run the full complete flow twice; second canonical scan reports `needed_moves=0` without unsafe stage hiding.
- [ ] Run all eight exact-HEAD GitHub CI checks to success, plus same-mount acceptance.
- [ ] Record residual risk and explicit owner approval; only then mark PR ready, merge and publish the stable Docker image.


## Progress log — 2026-11-18: Worker identity / namespace custody

### Evidence discovered
- The production `Dockerfile` has no `USER` instruction.
- `compose.yaml` and `compose.komodo.yaml` do not set a service `user:`.
- Therefore the current API and Worker containers run as UID 0 by default. The API and Worker also both receive writable `/data` mounts in the Komodo deployment.
- The direct grouped-publication primitive's POSIX owner/mode and ancestor checks are necessary but cannot establish a separate, least-privilege mutation principal while the Worker runs as root.

### TDD slice
- RED test added: `test_direct_group_refuses_root_worker_before_any_public_mutation`.
- First run exposed an ordering issue: stage-owner validation failed before the intended root-Worker assertion. The guard was moved to the beginning of the direct group creation function.
- GREEN: the focused backend + frontend V1.6 TDD workflow passed on commit `cbee88115408` (run `44265925311`). The new test now proves a root Worker is refused before public group creation and leaves original synthetic files byte-exact.

### Decision / remaining work
- This is a new necessary precondition, **not** a completed custody proof.
- Do not change production bind-mount ownership/ACLs automatically.
- Next: design and test a dedicated non-root Worker identity, separate API read-only access to `/data`, compatible shared database/report permissions, and explicit supported ACL/mount validation. If the actual NAS cannot prove that only this Worker principal can mutate the selected unit namespace during a job, keep grouped execution blocked.
- Task 1 remains OPEN until those deployment and mount-level checks exist. #402 remains OPEN; #400 cleanup and true second-scan-zero remain separate blockers.
