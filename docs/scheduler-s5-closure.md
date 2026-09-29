# Scheduler S5 Closure Record

Status: **CURRENT — SOURCE / CI CLOSURE IN PROGRESS; REAL NAS ACCEPTANCE NOT EXECUTED**

## Authority and baseline

- S5 exact baseline: `main@9be4e1f7590b3d0d5f58c3bdf704391aba77d6be` (merge of Scheduler S4 PR #98).
- Canonical S5 branch: `feature/scheduler-s5-closure`.
- Canonical S5 PR: #99.
- Scheduler V1 authority remains frozen: time trigger / dispatch ledger only.
- This record does not authorize arbitrary WorkJob kinds, shell commands, arbitrary endpoints, automatic BatchPlan execution, quarantine purge/restore, permanent delete, Organizer Execute, or automatic Workflow Freeze / Validate / Execute.

## TDD evidence

The first S5 test-only head was:

`182ca3111978f3b51cfeecbd8619f8ef4814a748`

Release Validation run `36542110413` produced the intended RED evidence in full backend regression:

- `test_orphaned_pending_run_is_recovered_before_overlap` failed;
- observed result was `dispatched=0`, `skipped_overlap=1`;
- a durable `pending` ScheduleRun without an active WorkJob therefore blocked future slots indefinitely.

The minimal recovery fix is confined to `app/scheduler/dispatch.py`: an unbound/non-active durable pending row is failed closed with `SCHEDULER_DISPATCH_INTERRUPTED` inside the existing Scheduler write transaction. A genuinely active bound WorkJob still enforces `skip_if_active`.

## S5 closure coverage

The S5 focused suite covers:

- restart / downtime with `missed_run_policy=skip` and no catch-up storm;
- competing Scheduler owners / multi-Worker lease contention;
- unique `(schedule_id, scheduled_for_utc)` duplicate-dispatch fence after lease takeover;
- interrupted orphan-pending recovery before overlap evaluation;
- ScheduleRun ↔ WorkJob metadata/linkage consistency;
- stale pinned Workflow target failure and recovery only after explicit administrator rebind;
- preserved S1-S4 cron/DST, target allowlist, Resource Policy, RBAC/API and responsive UI contracts.

The dedicated `Scheduler S5 Closure` workflow additionally runs:

- focused Scheduler S1-S5 regression;
- full backend regression;
- frontend tests, TypeScript typecheck and production build;
- linux/amd64 Docker build;
- isolated synthetic-only scheduled index + scheduled scan in the built linux/amd64 image;
- candidate scope / authority-containment review;
- explicit zero-residue checks.

## Synthetic acceptance boundary

`scripts/scheduler_s5_acceptance.py` is intentionally guarded:

- requires an already-created, empty directory named exactly `nfc-scheduler-s5-acceptance`;
- requires `--confirm-synthetic-only YES`;
- creates only an owned `.nfc-scheduler-s5-*` child;
- uses only synthetic files and a synthetic SQLite database;
- runs with `ALLOW_MUTATION=false` and `ALLOW_DELETE=false`;
- cleans the owned run directory and requires the supplied acceptance root to be empty;
- emits `synthetic_only=true` and `real_nas_acceptance=false`.

CI/Docker synthetic evidence is **not** real-NAS evidence.

## Real NAS acceptance

**NOT EXECUTED / NOT CLAIMED.**

The S5 Architecture Freeze requires an isolated NAS run for scheduled index + scheduled scan and zero residue. That acceptance must use a fresh isolated synthetic fixture, never production DATA / CONFIG. Until such evidence is actually produced, overall Scheduler S5 remains **CURRENT**, even if source/CI closure is green and merged.

Organizer Advanced Rules C5 real-NAS acceptance is a separate matter. Scheduler evidence cannot be used to claim Organizer C5 real-NAS closure.

## Protected real-NAS entry

The shared manual acceptance entry is `.github/workflows/real-nas-acceptance.yml`.
It can run only on a self-hosted Linux x64 runner carrying the custom
`nas-file-center-acceptance` label. The procedure and safety boundary are
recorded in [`real-nas-acceptance.md`](real-nas-acceptance.md).

This entry does not itself close S5. S5 remains CURRENT until the workflow is
actually executed on the target NAS filesystem, passes with zero residue, and
the observed evidence is committed into this closure record.

## Final candidate

The exact final candidate SHA, final-head Actions run IDs, Docker identity and merge commit are recorded only after the final PR head is green. This avoids treating an intermediate document commit as final authority.
