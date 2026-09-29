# Scheduler / Cron — S0 Architecture Freeze

Status: **S0 CLOSED — S1 CURRENT (PERSISTENCE + DISPATCH LEDGER)**
Source authority: `main` baseline `f604eb47dc17fdb935d396968aab3518629e3db2`
Product baseline: **v0.4.7**

## 1. Scope decision

The next product track is **Scheduler / Cron**.

This selection is based on current source ownership, not the order of historical
backlog items:

- the application already has a durable `WorkJob` queue and Worker state
  machine;
- saved Workflows already provide reusable, revisioned definitions;
- Resource Policy already provides timezone-aware active-window semantics;
- the Tasks UI already exposes queued/running/completed work;
- scheduling can therefore be added as a dispatch layer without adding a
  second filesystem executor.

The following candidates remain deferred:

- Similarity / pHash / video similarity: requires a new media-analysis domain,
  storage model and dependency/capability review;
- Notifications / webhook delivery: useful after scheduler/task event semantics
  are stable, but it is an outbound-delivery subsystem rather than a core
  execution primitive;
- Advanced Auth: remains a separate security-domain expansion;
- Hardlink / Reflink capability expansion: directly expands filesystem mutation
  authority and requires a dedicated filesystem capability freeze.

## 2. Non-negotiable authority boundary

Scheduler is a **time trigger and dispatch ledger only**.

It MUST NOT:

- execute filesystem mutations directly;
- call a second filesystem executor;
- bypass `WorkJob`, BatchPlan, PathGuard, no-clobber, stale validation,
  descriptor/inode identity checks, symlink protection, delete gates or
  last-file protection;
- turn a Preview into Execute automatically;
- auto-freeze, auto-validate or auto-execute a mutation plan;
- dispatch quarantine purge, permanent delete, audit clear, restore, rollback,
  Organizer structural mutation, generic batch-plan execution or any other
  destructive/mutating job merely because a cron slot became due;
- embed credentials, cookies, bearer tokens, passwords or other secrets in
  schedule payload JSON.

Existing `ALLOW_MUTATION` / `ALLOW_DELETE` semantics remain authoritative.
A schedule cannot grant or widen them.

## 3. V1 target allowlist

S1/S2 may dispatch only the following existing resource-oriented operations,
through their existing queue/service paths:

1. **Index root**
   - existing `index-root` WorkJob;
   - target must resolve to an existing allowed IndexRoot at dispatch time.

2. **Exact duplicate scan**
   - existing `fclones-scan` WorkJob;
   - schedule stores a validated scan request snapshot;
   - roots are revalidated against current allowed roots at dispatch time.

3. **Media analysis**
   - existing `media-analysis` WorkJob;
   - root keys are revalidated at dispatch time.

4. **Media integrity verification**
   - existing integrity verification queue path;
   - root keys are revalidated at dispatch time.

Not allowed in V1:

- `batch-plan-execute`;
- quarantine apply / purge / restore;
- audit deletion;
- corrupt-media permanent delete;
- Organizer Plan execution;
- arbitrary WorkJob kind strings;
- arbitrary HTTP endpoint invocation;
- shell commands;
- user-supplied executable code.

Every dispatch target is represented by a closed discriminator enum and a
strict Pydantic payload schema.

## 4. Workflow scheduling boundary

Saved Workflow integration is staged separately.

A future scheduled Workflow target MAY:

1. bind to one exact `workflow_id`;
2. bind to one exact `workflow_revision`;
3. bind to the exact `definition_sha256`;
4. perform the existing read-only compile/Preview path;
5. optionally materialize a **Draft Plan only** when the existing Generate
   contract can be satisfied without hidden or stale runtime inputs.

It MUST NOT automatically Freeze, Validate or Execute the generated plan.

Workflow updates never silently change an existing schedule. V1 schedule
binding is **pinned**, not "follow current revision". An administrator must
explicitly rebind a schedule to a newer Workflow revision.

Archived/missing Workflow revisions fail closed and do not dispatch.

## 5. Persistent model

S1 introduces two durable tables.

### `schedules`

Frozen fields:

- `id`;
- `name`;
- `description`;
- `enabled`;
- `target_type`;
- `target_json`;
- `cron_expression`;
- `timezone`;
- `overlap_policy`;
- `missed_run_policy`;
- `created_by_user_id`;
- `revision`;
- `created_at`;
- `updated_at`;
- `last_scheduled_for_utc`;
- `next_scheduled_for_utc`.

Constraints:

- admin-created/updated only;
- `revision >= 1`;
- target discriminator must be from the V1 allowlist;
- timezone must resolve through Python `zoneinfo`;
- cron expression must pass the frozen parser;
- optimistic locking uses `expected_revision`;
- disabling a schedule prevents future dispatch but preserves run history.

### `schedule_runs`

Frozen fields:

- `id`;
- `schedule_id`;
- `schedule_revision`;
- `scheduled_for_utc`;
- `dispatched_at`;
- `status`;
- `work_job_id`;
- `error_code`;
- `error_text`;
- `target_snapshot_json`;
- `created_at`.

Required unique constraint:

```text
UNIQUE(schedule_id, scheduled_for_utc)
```

This uniqueness is the primary duplicate-dispatch fence.

Deleting a schedule is not part of V1. Schedules are disabled, preserving
history and auditability.

## 6. Cron grammar and timezone semantics

V1 cron is deliberately narrow:

```text
minute hour day-of-month month day-of-week
```

Supported:

- five fields only;
- numeric values;
- `*`;
- comma-separated values;
- inclusive ranges;
- positive step values.

Not supported in V1:

- seconds;
- year field;
- nicknames such as `@daily`;
- `L`, `W`, `#`, `?`;
- textual month/day names;
- user-defined code or expressions.

Field ranges:

- minute: `0..59`;
- hour: `0..23`;
- day-of-month: `1..31`;
- month: `1..12`;
- day-of-week: `0..6`, Sunday = `0`.

Timezone is a required IANA zone name.

DST semantics are frozen:

- nonexistent local wall-clock times are skipped;
- ambiguous repeated local times fire once, using the first occurrence
  (`fold=0`);
- stored run identity is always the resolved UTC instant.

Cron matching is minute-granularity. Seconds are always zero.

S1 clarification for day matching follows standard cron semantics:

- if both day-of-month and day-of-week are wildcard, every otherwise matching
  calendar day is eligible;
- if one is wildcard, the restricted field controls the day;
- if both are restricted, **either** day-of-month or day-of-week may match.

This OR rule is part of the frozen recurrence contract and prevents later
implementations from silently switching to AND semantics.

## 7. Missed-run and overlap semantics

V1 supports one value for each policy:

```text
missed_run_policy = "skip"
overlap_policy    = "skip_if_active"
```

No unbounded catch-up is allowed.

After downtime or scheduler unavailability, past slots are recorded only if
they were already dispatched. Missed slots are not replayed.

Before dispatching a due slot, Scheduler checks whether a non-terminal
`schedule_run` / `WorkJob` from the same schedule is still active. If so:

- the due slot receives a terminal `skipped_overlap` run record;
- no new WorkJob is created.

Parallel execution from the same schedule is therefore not a V1 feature.

## 8. Dispatch transaction and idempotency

Scheduler evaluation has no filesystem authority.

For each due slot:

1. begin a SQLite `BEGIN IMMEDIATE` transaction;
2. reload the enabled schedule and its current revision;
3. insert the unique `schedule_runs` identity for
   `(schedule_id, scheduled_for_utc)`;
4. revalidate target configuration and current resource references;
5. apply overlap policy;
6. create the existing allowed WorkJob through a target-specific dispatcher;
7. bind `schedule_run.work_job_id`;
8. update `last_scheduled_for_utc` / `next_scheduled_for_utc`;
9. commit.

If the unique run identity already exists, the slot is already accounted for
and MUST NOT dispatch again.

WorkJob creation and schedule-run binding occur in the same write transaction
where practical. If an existing service path currently commits internally, S1
must refactor that path into a transaction-aware helper rather than accept a
duplicate-dispatch window.

## 9. Scheduler ownership and lease

The existing Worker process owns scheduler ticking.

No API-process background timer is introduced.

A scheduler tick:

- runs at most once per minute;
- evaluates due schedules in UTC;
- does not hold a database transaction while running a filesystem job;
- only persists dispatch records and WorkJobs.

S1 introduces a lightweight DB-backed scheduler lease/state so that a future
multi-worker deployment cannot dispatch the same slot concurrently. The unique
run constraint remains the final idempotency fence even if lease ownership is
lost.

The scheduler lease is not the WorkJob execution lease and must not weaken
existing worker fencing.

## 10. Resource Policy interaction

Scheduler recurrence and Resource Policy active windows are different concepts.

- Scheduler decides **when a task is due**.
- Resource Policy decides whether a resource-controlled WorkJob may currently
  be claimed / at what resource profile.

A due scheduled scan or index job may therefore be queued while Resource Policy
holds resource jobs outside its active window.

Scheduler MUST NOT rewrite, bypass or temporarily override Resource Policy.

## 11. RBAC and API boundary

Read access:

- authenticated users may view schedules and schedule-run history.

Write access:

- administrator only for create, edit, enable/disable, manual "run now" and
  Workflow revision rebind.

"Run now" uses the same target validation and dispatch path as a cron slot and
creates a durable run record. It is not a direct endpoint shortcut.

Mutation endpoints retain CSRF/origin protection.

V1 does not introduce API tokens, webhook secrets or machine credentials.

## 12. Audit / observability

Each lifecycle transition is observable:

- schedule created;
- schedule updated;
- schedule enabled/disabled;
- due slot dispatched;
- due slot skipped for overlap;
- due slot rejected for invalid/stale target;
- WorkJob bound;
- manual run requested.

Schedule run detail links to its WorkJob and Task events where applicable.

Failures are fail-closed. A target-validation error produces a failed
`schedule_run`; Scheduler does not "best effort" mutate the target payload.

## 13. Frontend contract

S3/S4 expose a dedicated Scheduler surface.

Desktop:

- schedule ledger;
- enabled status;
- target summary;
- cron expression;
- timezone;
- next run;
- previous run/result;
- linked task;
- edit / enable-disable / run-now actions.

Mobile:

- dense schedule cards;
- next run and target are first-screen facts;
- no desktop table horizontal dependency.

Editor:

- target type is a closed selector;
- target-specific fields reuse existing root/workflow selectors;
- cron editor provides validation and a read-only next-occurrence preview;
- timezone selector reuses the existing IANA timezone UX;
- destructive target types are not displayed because they do not exist in the
  server allowlist.

## 14. Migration / compatibility

Migration is additive.

Required compatibility guarantees:

- existing databases migrate with zero schedules;
- existing WorkJobs/Task history remain unchanged;
- existing Resource Policy row remains unchanged;
- existing Workflow revisions remain unchanged;
- downgrade is not promised, but pre-migration backup behavior remains
  authoritative;
- schedule migration failure blocks startup rather than partially enabling the
  scheduler.

## 15. TDD matrix

S1 — persistence / recurrence core:

- additive migration and legacy database preservation;
- model constraints;
- strict cron parser;
- IANA timezone validation;
- DST nonexistent-time skip;
- DST repeated-time first-occurrence-only;
- next-occurrence calculation;
- optimistic schedule revision locking;
- disabled schedule behavior;
- unique run slot identity;
- scheduler lease contention.

S2 — dispatch:

- index target revalidation;
- scan payload validation;
- media target validation;
- same-slot duplicate tick creates exactly one WorkJob;
- overlap skip;
- missed slots not replayed;
- resource-policy pause queues but does not bypass;
- stale/missing target fails closed;
- arbitrary WorkJob kind rejected;
- destructive WorkJob kinds impossible through schema;
- no credential fields accepted.

S3 — Workflow draft-only integration:

- exact workflow revision and SHA pin;
- workflow update does not alter schedule binding;
- archived revision fails closed;
- Preview stays read-only;
- Draft generation uses existing digest/stale rules;
- zero automatic Freeze/Validate/Execute.

S4 — frontend:

- PC schedule ledger;
- mobile cards;
- editor validation;
- next-run preview;
- timezone/DST warning copy;
- run-now confirmation;
- status/history linkage.

S5 — closure:

- full backend regression;
- frontend tests/typecheck/build;
- linux/amd64 Docker;
- restart/downtime test proving no catch-up storm;
- duplicate-tick concurrency test;
- isolated NAS run for scheduled index + scheduled scan;
- zero test residue;
- closure record bound to exact candidate SHA.

## 16. Implementation sequence

```text
S0  Scope + Architecture Freeze                         CLOSED
S1  Schema + cron parser + recurrence + lease/run log  CURRENT
S2  Safe target dispatch (index/scan/media)            NEXT
S3  Workflow pinned Preview/Draft-only scheduling      LATER
S4  Scheduler frontend / mobile                        LATER
S5  Closure / Docker / isolated NAS acceptance         LATER
```

No S1+ change may expand the frozen target allowlist without a new architecture
amendment.

## 17. Organizer C5 independence

Organizer Advanced Rules C5 real-NAS evidence is a separate closure record.

Starting Scheduler S0 does not fabricate or imply Organizer C5 closure. Scheduler
must not reuse the absence of Organizer evidence as permission to weaken any
Organizer or filesystem safety gate.
