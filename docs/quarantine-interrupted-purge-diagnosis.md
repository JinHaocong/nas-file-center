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

## Deployment and signoff separation

This PR only adds a **read-only diagnostic path**, not an automatic
recover/delete endpoint. It cannot itself remove the two stuck entries.
The owner must separately authorize any operation against live NAS data,
and production deploy is not implied by GitHub merge.
GitHub unit tests use a disposable temporary SQLite DB and synthetic
files only. Project formal stages #70–#74 remain **OPEN** at 69/74
until actual human/NAS/owner signoff.
