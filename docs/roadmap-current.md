# NAS File Center — Current Roadmap

Status: CANONICAL CURRENT ROADMAP  
Release authority: **v0.4.7**  
Source authority: **default branch `main`**  
Last reconciled: 2026-09-29

## 1. Authority order

When documents disagree, use this order:

1. merged source and tests on `main`;
2. current package / image metadata (`pyproject.toml`, `compose*.yaml`);
3. current gate closure documents under `docs/`;
4. this roadmap;
5. older roadmap / planning snapshots as historical evidence only.

Design-history headings in `DESIGN.md` are not product release numbers unless
release/package/image metadata explicitly promotes them.

## 2. Current release baseline

The current product, Python package and Docker image version is **0.4.7**.

Current runtime architecture remains:

```text
React + TypeScript + Ant Design
        ↓
      FastAPI
        ↓
      SQLite
        ↓
      Worker
        ↓
fclones / filesystem
```

The safety lifecycle remains authoritative:

```text
Preview
→ Draft Plan
→ Freeze
→ Validate
→ Execute
→ Audit / Quarantine / Undo where applicable
```

No roadmap item may bypass PathGuard, no-clobber, stale validation, descriptor
identity, symlink protection, mutation/delete gates, or last-file protection.

## 3. Closed / source-complete work

### Gate6-C — Cross-Storage Quarantine Transaction

**CLOSED / MERGED**

Primary implementation: PR #52.

Subsequent production/NAS compatibility fixes remain part of the accepted
authority, including EXDEV fallback, NOREPLACE fallback, recursive inode
rebinding/source retirement, legacy orphan purge handling and terminal cleanup
handling.

### Gate6-D — Media Metadata + Integrity

**SOURCE-COMPLETE / MERGED**

- PR #59 — media metadata, integrity analysis and approved corrupt-media
  permanent-delete path.
- PR #72 — SHA256 integrity baseline / verification.

The 036 feature track is source-complete at this boundary.

### UI / right-workspace refinement

**CLOSED FOR CURRENT PRODUCT PHASE**

PRs #73–#83 completed the current responsive workspace, page-composition,
spacing and title-system pass. Further UI work should be defect-driven rather
than treated as the next product phase.

## 4. Historical 036 backlog that is NOT the current queue

The following items are deliberately **not implicit next gates**:

- Similarity / pHash / video similarity — **OUT OF SCOPE** for the closed 036
  track.
- Notifications / webhook delivery — **OUT OF SCOPE** for the closed 036 track.
- Advanced Auth (API token / TOTP / recovery codes) — **DEFERRED**.
- Hardlink / Reflink capability expansion — **DEFERRED**.
- Scheduler / Cron — **DEFERRED**.

Any of these may return later only through a new Scope + Architecture Freeze.
They must not be reopened merely because an older roadmap listed them in
sequence.

## 5. CURRENT — Organizer Advanced Rules

**Status: C0 CLOSED / C1 CLOSED / C2 CLOSED / C3 CLOSED / C4 CLOSED / C5 CURRENT — CLOSURE**

This is the next product-development phase.

The intended product direction is to extend the existing Organizer Profile /
Preview / Plan pipeline without introducing a second mutation authority.

### C0 closure

Architecture freeze: [`organizer-advanced-rules-architecture-freeze.md`](organizer-advanced-rules-architecture-freeze.md)

C0 source-audited and froze the following rules:

1. **Depth-aware directory rules**
   - root depth = 0;
   - depth 1 directory names remain unchanged;
   - renaming may begin at depth >= 2.

2. **Recursive file numbering**
   - process files recursively below the preserved first-level directories;
   - numbering is independent per parent directory;
   - preserve extensions and define extension-case behavior;
   - detect collisions and NAME_MAX overflow before Plan generation.

3. **Latest-child prefix**
   - support marking the newest eligible child directory with a configurable
     `New ` prefix;
   - freeze the timestamp/tie-breaking authority before implementation.

4. **Existing Organizer statistics/templates remain compatible**
   - preserve the existing image/video/file/folder/size/statistics template
     semantics unless an explicit schema migration is approved.

5. **Collapse Single-Child Wrapper**
   - detect an eligible wrapper containing exactly one child directory;
   - preview the promotion before mutation;
   - never overwrite destination entries;
   - remove the wrapper only after the move is complete and the wrapper is
     revalidated as truly empty;
   - preserve rollback/audit/Plan safety boundaries.

### Frozen C0 outputs

C0 established:

- current Organizer source ownership map;
- Profile schema compatibility decision;
- deterministic sort / numbering rules;
- timestamp and tie-breaking rules for `New `;
- wrapper-collapse eligibility and failure matrix;
- Preview proposal representation;
- mapping from proposals into the existing BatchPlan lifecycle;
- stale / conflict / rollback semantics;
- TDD matrix, Docker validation plan and real-NAS acceptance plan.

### Implementation progress

- **C0 CLOSED** — Architecture Freeze / scope and safety authority frozen.
- **C1 CLOSED** — advanced-rules schema, additive migration, V1/V2 profile
  compatibility and shared read-only Organizer compiler.
- **C2 CLOSED** — digest-bound standalone/Workflow Organizer rename-stage Plan
  generation with Generate → Freeze source binding.
- **C3 CLOSED** — Single-Child Wrapper Collapse structural Stage A reuses
  the existing Gate6-B descriptor-bound discovery/capability probe and exact
  `MOVE → rmdir_empty` primitive, extends cleanup authority only to the explicit
  Organizer structural Plan context, and keeps global delete disabled.
- **C4 CLOSED** — shared Advanced Rules editor, digest-bound standalone/Workflow staged Preview, blocking-conflict UI, explicit Stage A/Stage B row separation, and fresh Preview gating after Stage A.
- **C5 CURRENT** — full closure / Docker / isolated real-NAS acceptance. Repository closure harness and dedicated C5 workflow are implemented; final closure remains blocked on passing the same harness on the actual NAS filesystem with zero residue. Closure record: [`organizer-advanced-rules-c5-closure.md`](organizer-advanced-rules-c5-closure.md).

C3 does not authorize generic delete, recursive rmdir, shell move, or a second
filesystem executor.

## 6. NEXT CURRENT — Scheduler / Cron

**Status: S0 CLOSED / S1 CURRENT — PERSISTENCE + DISPATCH LEDGER**

Fresh scope decision: **Scheduler / Cron**.

Architecture freeze:
[`scheduler-s0-architecture-freeze.md`](scheduler-s0-architecture-freeze.md)

The next track was selected from the deferred candidate set after a source-level
ownership audit. Scheduler has the best fit with the current architecture
because it can reuse the existing WorkJob queue, Worker state machine, Workflow
revision model and timezone-aware Resource Policy without introducing a second
filesystem executor.

Frozen V1 authority:

- Scheduler is a time-trigger / dispatch ledger, not a mutation executor.
- S1/S2 dispatch only allowlisted resource-oriented jobs: index, exact duplicate
  scan, media analysis and media integrity verification.
- arbitrary WorkJob kinds, shell commands and arbitrary endpoint invocation are
  forbidden.
- mutation-plan execution, quarantine purge/restore, permanent delete, audit
  deletion and Organizer execution are not schedulable V1 targets.
- future Workflow scheduling is pinned to an exact revision + definition SHA and
  may only reach Preview / Draft; it cannot automatically Freeze, Validate or
  Execute.
- `missed_run_policy = skip` and
  `overlap_policy = skip_if_active` are frozen for V1.
- one durable unique `(schedule_id, scheduled_for_utc)` run identity is the
  final duplicate-dispatch fence.

Implementation sequence:

- **S0 CLOSED** — scope decision, authority boundary, cron/timezone semantics,
  idempotency, lease, RBAC, TDD and closure plan frozen.
- **S1 CURRENT** — additive schedule/run schema, strict cron parser, recurrence
  engine and scheduler lease/idempotency core.
- **S2 NEXT** — safe allowlisted dispatch for index/scan/media jobs.
- **S3 LATER** — exact-revision Workflow Preview/Draft-only scheduling.
- **S4 LATER** — Scheduler desktop/mobile frontend.
- **S5 LATER** — closure, Docker, restart/concurrency and isolated NAS acceptance.

Scheduler S0/S1 authorization does not fabricate or imply Organizer Advanced
Rules C5 closure. The Organizer real-NAS closure evidence remains an independent
record until supplied and committed.

## 7. Other deferred candidate tracks

The following remain deferred behind the Scheduler scope decision:

- Similarity / pHash / video similarity;
- Notifications / webhook delivery;
- Advanced Auth (API token / TOTP / recovery codes);
- Hardlink / Reflink capability expansion.

Any later activation still requires its own fresh Scope + Architecture Freeze.
