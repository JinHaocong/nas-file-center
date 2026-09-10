# NAS File Center v0.3.5 — Gate5-F

## Architecture Freeze — Resource Control

**Date:** 2026-09-10
**Status:** ARCHITECTURE FREEZE CANDIDATE — OWNER DESIGN DIRECTION APPROVED / FINAL TEXT PENDING REVIEW
**Implementation status:** NOT AUTHORIZED
**Authorized baseline:** `3e4c8a00bcf54e0c0a13f1b9f21dd4fd05b2d1d9`
**Target branch:** `v0.3.5-gate5c-hotfix4`

---

# 1. Gate authority

The following prior stages are treated as immutable closed baselines:

```text
Gate5-A = PASS / CLOSED
Gate5-B = PASS / CLOSED
Gate5-C = PASS / CLOSED
Gate5-D = PASS / CLOSED
Gate5-E = PASS / CLOSED
```

Gate5-F is the only authorized next development stage.

```text
Gate5-G = FORBIDDEN
v0.3.5 = NOT CLOSED
```

Gate5-F MUST NOT redesign, reopen or weaken any CLOSED Gate.

Project priority remains:

```text
Data safety
> correctness
> recoverability
> performance
> UI
> feature count
```

---

# 2. Gate5-F objective

Gate5-F adds conservative application-level resource control for NAS workloads.

The feature exists to prevent:

```text
duplicate scanning
filesystem indexing
hash-heavy workloads
```

from unnecessarily saturating CPU / disk resources on the NAS.

Gate5-F is not a general operating-system resource manager.

The required V1 policy surface is:

```text
scan_threads
hash_threads
io_limit
job_priority
active_window
```

The design MUST continue using the existing Task Engine and existing single-worker ownership model.

---

# 3. Explicit non-goals

Gate5-F MUST NOT implement:

```text
a second Worker
parallel WorkJob execution architecture
a new task state machine
a Scheduler / Cron subsystem
automatic task creation by time
Docker/cgroup resource orchestration
hard disk MB/s guarantees
Linux ionice dependency
CPU affinity management
memory quotas
per-user resource quotas
per-plan resource policy
per-file resource scheduling
Gate5-G release closure work
unrelated refactoring
```

Scheduler remains separately DEFERRED.

`active_window` is resource admission policy only.

It MUST NOT mean:

```text
“At 02:00 automatically create/run Scan X.”
```

It only answers:

```text
“Given a task that already exists,
is this resource-intensive job currently eligible to start,
and under which resource profile?”
```

---

# 4. Existing architecture remains authoritative

Current architecture remains:

```text
API
 ↓
SQLite
 ↓
existing WorkJob queue
 ↓
single Worker ownership / lease
 ↓
existing TaskHandler
 ↓
fclones / filesystem / application work
```

Gate5-F MUST NOT replace this architecture.

Existing:

```text
TaskLock
WorkerState
worker lease fencing
JobContext checkpoints
queued/running/paused/cancelled/failed/completed
TaskEvent
```

remain authoritative.

No second worker execution path is authorized.

---

# 5. ResourcePolicy persistence

Gate5-F is authorized to add exactly one additive singleton persistence model:

```text
ResourcePolicy
```

Canonical table:

```text
resource_policy
```

Canonical singleton identity:

```text
id = 1
```

Fields:

```text
id

scan_threads
hash_threads

io_limit
job_priority

active_window_enabled
active_window_start
active_window_end
active_window_timezone
outside_window_mode

revision
updated_at
```

No existing table is removed or semantically repurposed.

One additive database migration is authorized.

Existing user databases MUST upgrade without deletion or rebuild.

Migration failure MUST follow the project's existing migration safety and backup rules.

---

# 6. ResourcePolicy canonical values

## 6.1 scan_threads

Type:

```text
integer
```

Allowed:

```text
1..32
```

Default:

```text
2
```

`scan_threads` is an upper bound, not a request to create extra concurrency.

If an existing scanner is serial:

```text
effective concurrency may remain 1
```

Gate5-F MUST NOT introduce unsafe parallel filesystem traversal merely to consume the configured thread count.

---

## 6.2 hash_threads

Type:

```text
integer
```

Allowed:

```text
1..32
```

Default:

```text
2
```

This is the upper bound for hash-heavy duplicate scanning work.

The current fclones integration exposes one `--threads` control.

Therefore V1 MUST compose:

```text
scan_threads
hash_threads
io_limit
active-window profile
legacy deployment ceiling when applicable
```

into one conservative effective fclones thread ceiling.

Gate5-F does not depend on undocumented per-stage fclones thread-pool syntax.

---

# 7. Conservative thread calculation

Define:

```text
configured_cap =
min(scan_threads, hash_threads)
```

Then apply `io_limit`.

Canonical V1 semantics:

```text
io_limit = low
→ io_cap = 1

io_limit = normal
→ io_cap = 2

io_limit = unlimited
→ io_cap = configured_cap
```

Therefore:

```text
normal_cap =
min(configured_cap, io_cap)
```

`unlimited` does NOT mean:

```text
CPU core count
automatic unbounded concurrency
```

It only means:

```text
do not apply the extra low/normal I/O-pressure clamp;
still obey explicit scan_threads/hash_threads.
```

The hard maximum remains:

```text
32
```

The default therefore remains conservative:

```text
scan_threads = 2
hash_threads = 2
io_limit = normal

→ effective cap <= 2
```

Gate5-F MUST NOT automatically derive concurrency from:

```text
os.cpu_count()
Docker reported cores
host NAS core count
```

---

# 8. Existing FCLONES_THREADS compatibility

The existing deployment setting:

```text
FCLONES_THREADS
```

MUST NOT simply disappear.

Gate5-F treats it as a legacy deployment ceiling.

When it contains a simple positive integer:

```text
effective_fclones_threads =
min(
    resource_policy_effective_cap,
    FCLONES_THREADS
)
```

This preserves the ability for a deployment administrator to enforce a stricter environment-level limit.

A database policy MUST NOT silently raise concurrency above an explicit deployment ceiling.

Existing per-job request state MUST likewise never bypass the global ResourcePolicy ceiling.

Effective runtime behavior is always:

```text
most restrictive valid ceiling wins
```

Gate5-F MUST add regression coverage for this precedence.

---

# 9. io_limit semantics

Despite the historical field name:

```text
io_limit
```

Gate5-F V1 does NOT promise an exact:

```text
MB/s
IOPS
disk bandwidth
```

limit.

Canonical values are:

```text
low
normal
unlimited
```

It is an application-level I/O pressure profile implemented by concurrency caps.

This MUST be clearly documented in API/UI copy.

Hard bandwidth enforcement through:

```text
cgroup v2 io.max
Docker blkio
host-specific NAS controls
```

is explicitly deferred and would require a separate Architecture Freeze.

---

# 10. job_priority semantics

Canonical V1 values:

```text
normal
background
```

This field MUST NOT alter correctness or mutation safety.

It controls queue admission preference only.

When:

```text
job_priority = normal
```

eligible queued tasks preserve existing FIFO behavior.

When:

```text
job_priority = background
```

resource-controlled scan/index jobs yield at claim time to other eligible queued work.

Within the same priority class:

```text
lowest WorkJob.id first
```

remains authoritative.

Gate5-F MUST NOT:

```text
modify a running mutation plan's priority
interrupt filesystem mutation
overwrite Task Engine state
```

No `high` / privileged real-time priority is introduced in V1.

No negative Unix nice value is required.

---

# 11. Resource-controlled job classes

Gate5-F V1 resource admission applies only to read-heavy scan/index workloads:

```text
index-root
fclones-scan
```

Mutation-oriented operations such as:

```text
batch-plan-execute
quarantine / restore execution
rename / move
rmdir_empty / restore_empty_dir
```

MUST NOT be automatically paused or blocked midway by ResourcePolicy.

Their existing:

```text
Freeze
Validate
Execute
lease fencing
checkpoint
reconciliation
```

contracts remain untouched.

Future job kinds require explicit opt-in before becoming resource controlled.

---

# 12. active_window model

V1 uses one configurable primary window.

Fields:

```text
active_window_enabled

active_window_start = HH:MM
active_window_end   = HH:MM

active_window_timezone = IANA timezone

outside_window_mode =
    limited
    or
    pause
```

Example:

```text
enabled = true
start = 00:00
end = 08:00
timezone = Asia/Shanghai
outside_window_mode = limited
```

Meaning:

```text
00:00–08:00
→ full resource profile

outside that window
→ limited profile
```

Cross-midnight windows are valid.

Example:

```text
23:00 → 07:00
```

`start == end` is invalid while active_window is enabled.

Timezone interpretation MUST be explicit and deterministic.

No hidden dependence on browser timezone is allowed.

If the configured timezone is invalid:

```text
PUT policy = reject

existing valid policy remains unchanged
```

---

# 13. active_window effective profiles

Inside the configured window:

```text
profile = full
```

Effective concurrency follows the normal policy calculation.

Outside the configured window:

If:

```text
outside_window_mode = limited
```

then:

```text
effective resource cap = min(normal_cap, 1)
```

Resource-controlled jobs may still start.

If:

```text
outside_window_mode = pause
```

then queued resource-controlled jobs:

```text
remain queued
are not claimed
are not cancelled
are not failed
```

The Worker remains available to claim other eligible job kinds.

This is admission control, not scheduling.

---

# 14. Running-job window transitions

Gate5-F MUST respect existing TaskHandler capabilities.

It MUST NOT invent fake resumability.

If an already-running resource-controlled job crosses from:

```text
full window
→ outside pause window
```

and the job does not already support safe pause/resume:

```text
do NOT SIGKILL
do NOT fabricate paused state
do NOT discard partial state
do NOT change supports_pause merely for Gate5-F
```

The running job may continue to its existing safe completion using the runtime resource parameters captured when its current non-resumable phase began.

New queued resource-controlled work remains blocked from starting.

If a future/existing handler genuinely supports cooperative pause/resume:

```text
it may yield only at an existing safe checkpoint boundary
```

No filesystem mutation may be interrupted between its safety fences.

---

# 15. Policy snapshot semantics

Resource correctness policy and filesystem identity are separate concerns.

ResourcePolicy MUST NOT become part of:

```text
Preview digest
Draft identity
Gate3 Freeze identity
Validate filesystem freshness
OperationJournal object identity
```

Changing ResourcePolicy MUST NOT make an existing Plan stale.

For queued jobs:

```text
latest committed ResourcePolicy is evaluated at claim/start time
```

For a running external subprocess:

```text
thread/resource parameters are captured at subprocess start
```

They are not mutated underneath an already-running fclones process.

Each task start SHOULD record a TaskEvent containing:

```text
resource_policy_revision
effective_profile
effective_thread_cap
io_limit
job_priority
active_window state
```

for diagnosis and auditability.

ResourcePolicy revision increments monotonically on successful update.

---

# 16. Claim-time architecture

Existing exclusive Worker lease remains mandatory.

Resource-aware claim MUST remain inside the existing short:

```text
BEGIN IMMEDIATE
→ assert_active_worker_lease()
→ choose eligible queued WorkJob
→ mark running
→ COMMIT
```

transaction.

No filesystem work, timezone database I/O, subprocess start or expensive computation is allowed while holding this SQLite write transaction.

Eligibility must be computed from:

```text
current valid ResourcePolicy
current time
job kind
job_priority
active_window mode
```

When outside a `pause` window:

```text
index-root / fclones-scan
```

are ineligible.

Other queued jobs remain eligible.

A resource-paused queue MUST NOT make the Worker appear offline or lease-lost.

---

# 17. fclones integration

Current fclones command generation remains authoritative for scan semantics.

Gate5-F may change only the effective resource argument passed to it.

The resulting command must use a bounded thread value such as:

```text
--threads 1
--threads 2
...
```

according to the effective policy.

Request payload supplied thread values MUST be treated as an additional requested ceiling, never an override above global policy.

Canonical composition:

```text
effective =
minimum of every applicable positive ceiling
```

Gate5-F MUST NOT change:

```text
scan roots
exclude semantics
isolate semantics
min_size semantics
name filters
report format
hash correctness
DuplicateGroup import semantics
```

---

# 18. Index-root behavior

`index-root` becomes subject to active-window admission.

Its existing indexing semantics remain unchanged.

`scan_threads` is a maximum permitted scan concurrency.

Gate5-F MUST NOT add parallel indexing if the current implementation cannot prove equivalent ordering, SQLite safety and checkpoint behavior.

Therefore V1 explicitly permits:

```text
configured scan_threads = 2
actual current index-root execution concurrency = 1
```

An upper bound does not require artificial parallelism.

Performance enhancement beyond existing safe concurrency is deferred.

---

# 19. Admin API

Gate5-F authorizes:

```text
GET /api/settings/resource-policy
PUT /api/settings/resource-policy
```

Both endpoints are administrator-only.

GET returns:

```text
persisted policy
revision
updated_at

effective_now:
    profile
    inside_active_window
    resource_jobs_admitted
    effective_thread_cap
```

PUT uses validated replacement semantics.

Invalid PUT:

```text
HTTP 422
0 database mutation
existing policy preserved
```

Concurrent updates MUST use the current persisted row as database truth.

No secrets or host-level privilege controls are exposed.

---

# 20. Frontend scope

Gate5-F authorizes one minimal Resource Control section in the existing Settings experience.

It may expose:

```text
Scan thread ceiling
Hash thread ceiling
I/O pressure profile
Job priority
Active window enable
Start / end
Timezone
Outside-window mode
Current effective profile
```

No dashboard redesign is authorized.

No charting is required.

No new design system is authorized.

Frontend must clearly state that:

```text
io_limit is a soft application-level pressure control,
not guaranteed MB/s throttling.
```

---

# 21. Failure behavior

ResourcePolicy failures MUST fail conservatively.

Examples:

```text
policy row unreadable
invalid persisted value
invalid timezone
invalid thread ceiling
```

must never result in:

```text
unbounded concurrency
CPU-count-derived fallback
mutation safety bypass
second worker startup
```

For resource-intensive scan work, inability to determine a valid effective cap MUST fail closed before subprocess execution.

Existing mutation jobs MUST NOT become permanently unavailable solely because resource-policy metadata is corrupted.

Resource policy failure must be observable through error/log evidence.

---

# 22. Security and authorization

Only administrators may read or modify ResourcePolicy through the settings API.

Resource controls MUST NOT be accepted from arbitrary task payloads as authority.

A caller cannot request:

```text
threads = 32
```

and override:

```text
global cap = 2
```

Global policy remains the ceiling.

Existing authentication/authorization architecture remains unchanged.

---

# 23. Database migration boundary

Exactly one additive Gate5-F policy migration is authorized.

Allowed:

```text
create resource_policy singleton table
seed valid default row
required index/constraint additions for this table only
```

Not authorized:

```text
rewrite WorkJob history
drop columns
rebuild unrelated tables
change Gate5-E journal schema
change Plan identity schema
change TaskLock model
create another worker ownership table
```

Default seeded policy:

```text
scan_threads = 2
hash_threads = 2
io_limit = normal
job_priority = normal

active_window_enabled = false
outside_window_mode = limited

revision = 1
```

When active window is disabled:

```text
start/end/timezone do not restrict execution
```

---

# 24. TDD acceptance requirements

Implementation MUST use:

```text
RED
→ GREEN
→ REFACTOR
→ focused regression
→ full regression
```

Mandatory regression coverage includes:

```text
singleton migration and upgrade

admin-only GET/PUT
invalid policy = 422 + no mutation
revision increment

default effective cap = 2
low I/O cap = 1
normal cap <= 2
unlimited still obeys explicit thread ceilings

legacy FCLONES_THREADS cannot be exceeded
task/request thread value cannot exceed global cap

active window inside/outside boundaries
cross-midnight window
invalid timezone
start == end rejection

outside limited => effective cap 1
outside pause => scan/index remains queued

outside pause does not block unrelated queued job
background priority yields to unrelated eligible work
normal priority preserves FIFO

single-worker lease fencing remains intact
queue-empty remains distinct from lease-lost
resource-paused queue does not fabricate lease loss

running non-resumable scan is not force-killed at time boundary

no automatic Scheduler task creation

fclones command receives effective bounded --threads

closed Gate regressions remain GREEN
```

---

# 25. Required regression gate

Before Gate5-F implementation may be submitted for Independent Review, run at minimum:

```text
Gate5-F focused tests

Task Engine tests
Worker lease/recovery tests
fclones scan tests
index-root tests

Gate3 / Planning / Execution safety tests
Gate5-D tests
Gate5-E tests

full backend tests

frontend typecheck
frontend production build

git diff --check
clean worktree
```

Exact fresh counts must be reported.

Do not copy historical pass counts as current evidence.

---

# 26. Production scope boundary

Expected implementation areas may include:

```text
app/models.py
app/db.py / migration mechanism
app/config.py
app/tasks/recovery.py
app/tasks/context.py
app/tasks/handlers.py
app/scanners/fclones.py
app/api/router.py
service/settings layer
frontend Settings resource-control components
focused tests
history/walkthrough docs
```

This is an expected boundary, not permission for unrelated refactoring.

If implementation discovers that a required change needs:

```text
second worker architecture
new Scheduler
hard cgroup I/O controls
Task Engine state-machine redesign
filesystem mutation semantic changes
```

implementation MUST STOP and request Architecture review.

---

# 27. Gate5-F invariants

A conforming implementation must preserve all of the following:

```text
ONE Worker ownership model

ResourcePolicy limits resources;
it never grants mutation authority.

ResourcePolicy never bypasses:
Preview
Generate Draft
Freeze
Validate
Execute

Default scan/hash pressure remains conservative.

No automatic CPU-count concurrency.

No arbitrary task payload can exceed the global ceiling.

Active window does not create tasks.

Outside-window pause means admission pause for queued
resource-intensive jobs.

Non-resumable running work is never fake-paused.

Mutation jobs are not interrupted by Resource Control.

io_limit is soft concurrency pressure,
not an MB/s guarantee.

Gate5-A through Gate5-E semantics remain unchanged.
```

---

# 28. Closure state after this Freeze

After this exact Freeze text is approved and its remote commit independently verified:

```text
Gate5-F Architecture Freeze
= APPROVED / CLOSED

Gate5-F Implementation
= AUTHORIZED NEXT

Gate5-G
= FORBIDDEN

v0.3.5
= NOT CLOSED
```

Implementation Agent may then receive a separate Implementation Plan.

This Architecture Freeze itself authorizes no production code changes.
