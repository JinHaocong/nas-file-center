# Docker restart during quarantine purge: safe diagnosis

## Incident / user symptom (2026-10-27)

A Docker restart interrupted quarantine cleanup; records **#1106** and **#884**
remain shown as **清除中** (`state=purging`) and the list intentionally
disables repeat purge and terminal-record deletion. The screenshot alone
**does not establish** whether their work jobs finished, whether the
quarantine payload still exists, or whether their `tx_phase` is populated.
Do not claim these entries have already been restored/purged.

### Why forcing a status change is unsafe

- Legacy single-entry purge commits `purging` before unlink and commits
  `purged` afterward. Docker can be stopped between these commits.
- The API service's startup reconciliation only handles entries without
  transactional metadata; entries with `tx_phase` or an authoritative
  anchor are deliberately deferred to a lease-fenced Worker. A
  transactional purge may have a durable frozen manifest, capture
  witnesses and a destroy-intent marker in `.tx`; missing a public
  path **does not prove** the transaction is complete.
- Worker recovery can mark nonresumable interrupted jobs as failed;
  resumable jobs require a checkpoint and valid authority. Neither case
  authorizes a second irreversible deletion outside the frozen plan.
- Never run `UPDATE quarantine_entries SET state='purged'`,
  `DELETE FROM quarantine_entries`, remove `.tx`, or manually
  `rm -rf` quarantine payloads as a workaround.

## Read-only diagnosis available with this change

As an **admin** open **文件隔离区**, find an item still **清除中**,
and click **恢复诊断**. This invokes:

`GET /api/quarantine/{id}/recovery-diagnostic`

It reads metadata only and reports: state, transaction mode / phase,
attempt generation, linked WorkJob ID/status/error code, linked
BatchPlan ID/status, PlanItem state, last error, a descriptive reason and
a cautious next-step message. **No file probes, deletions, writes,
requeues, lease changes or state transitions are made.** Ordinary
users are forbidden (`403`); unauthenticated requests return `401`.

For #1106 / #884, review **both separate diagnostic responses**.
Note: a QuarantineEntry's persisted `task_id` and `plan_item_id` are
**provenance references**, which may identify the original quarantine job,
not the subsequently interrupted purge executor. Resolve the actual purge
plan from plan item metadata / task logs before attempting any retry.
Collect the result plus Worker log excerpts around the restart and
the state of any linked job/plan. A valid current Worker lease and
retained frozen transaction authority must be assessed before
attempting replay/recovery using the established worker flow.
If diagnostic shows a legacy row still in purging after an API restart,
check that the API container actually restarted with the current DB and
inspect startup reconciliation error logs; do not fake a terminal state.

Read-only first responders may also use the existing
`GET /api/quarantine/1106`, `GET /api/quarantine/884` and the Tasks
page; these return less transaction/plan context than the new endpoint.
Avoid pasting original paths or passwords into public issue discussions;
redact user-specific filesystem details before sharing logs.

## CI browser overlay transition hardening (PR #356)

During post-#355 exact-HEAD UI Validation on `91b2d95fe5ac36269c692931690e1df1bc1897ac`,
the `browser-overlay-smoke` job failed only on the
`Purge dark-light-1920` sequence: after closing Restore and immediately
opening Purge, `inspect()` observed `Scrim intercepts pointer hits`.
All earlier 31 modal sequences and the Portal theme/paint checks had passed.
This is **an observed transition race, not proof that live quarantine
destruction was triggered or that masking is safe**.

The real Chromium test now waits **at most 3.5 seconds** for Radix's
new Purge dialog to be `data-state=open` and for its actual center
to receive `document.elementFromPoint` hits after the prior Restore
scrim retires. The original, strict `inspect()` z-index/viewport/
background/pointer assertion is **still run after the wait**.
A persistent overlay obstruction must still fail the test.
A source regression test pins the bounded wait and retained safety check.
Only the synthetic read-only browser harness was changed; no
production dialog, API, Docker or filesystem delete behavior changed.
New exact-HEAD CI must pass before merge.

## Deployment and signoff separation

This PR only adds a **read-only diagnostic path**, not an automatic
recover/delete endpoint. It cannot itself remove the two stuck entries.
The owner must separately authorize any operation against live NAS data,
and production deploy is not implied by GitHub merge.
GitHub unit tests use a disposable temporary SQLite DB and synthetic
files only. Project formal stages #70–#74 remain **OPEN** at 69/74
until actual human/NAS/owner signoff.
