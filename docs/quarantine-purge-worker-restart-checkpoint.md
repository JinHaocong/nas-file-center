# Worker restart: durable checkpoint before batch-plan recovery (2026-10-27)

## Demonstrated source gap

`BatchPlanExecuteHandler` in `app/tasks/handlers_base.py` declares
`supports_resume=True` and already reconciles interrupted plan items using
frozen manifests, transactional witnesses and Worker lease fencing. However,
its initial and per-item `JobContext.checkpoint` calls previously omitted
`checkpoint_data`. Consequently `WorkJob.checkpoint_json` may remain NULL
when Docker is interrupted, and
`recover_interrupted_jobs()` requires a JSON `schema_version` before it
will requeue a running resumable job. It otherwise marks the job
`failed/WORKER_INTERRUPTED` and may leave the linked quarantine entry in
`purging` pending manual, evidence-based recovery.

That is a confirmed **code-level checkpoint mismatch**, not proof that
live QuarantineEntry #1106 / #884 took this particular failure path.
They still require their own diagnostic results and actual job/plan binding.

## Narrow future-restart protection

The batch handler now calls the **existing, lease-fenced**
`JobContext.checkpoint` with an explicit versioned,
plan-bound checkpoint **before** it scans or reconciles executing items,
and again at each normal item-boundary checkpoint:

```json
{"schema_version": 1, "plan_id": 123, "resume_mode": "reconcile_executing_items"}
```

No new file deletion, direct retry API, forced state reset, new Worker
privilege, special plan bypass or automatic `purged` transition is added.
On a later Worker restart, an interrupted job with that committed
checkpoint is eligible to be requeued under the existing owner lease.
The ordinary batch executor then starts from its **existing complete
reconciliation** and frozen plan-item verification, including the
transactional purge post-intent witnesses, before any attempt at changes.
If the manifest, lease, identity or transaction evidence is wrong, existing
fail-closed checks still reject recovery.

A crash **before the first checkpoint can commit** remains
`WORKER_INTERRUPTED`, not silently forced to retry. Historical jobs
already marked failed and/or stuck `purging` records do not gain new
checkpoint bytes retroactively; they require actual read-only diagnosis
and separately approved recovery. This change is preventative for
future interrupted executions, **not** a resolution of #1106/#884.

## Regression

`tests/test_worker_recovery_and_claim.py` simulates a process termination
immediately after the first checkpoint has durably committed in a
disposable SQLite database with an isolated synthetic `purging` payload.
The original `batch-plan-execute` job is then requeued by the existing
lease-fenced `recover_interrupted_jobs` (rather than failed), while
the plan item/entry state and payload bytes remain unchanged. A source
contract test pins the checkpoint before initial reconciliation and
before item Phase 1 DB intent. Existing no-checkpoint restart tests
continue to assert fail-closed behavior.

## Full-regression pause-fixture correction

The first candidate HEAD `690f5b67a4704de92f8fd61e3a8f45695a4e7534`
failed both Release Validation and Organizer C5 full regression at
`tests/test_gate2_worker_execution.py::test_worker_safe_pause_and_resume`.
Its test mocked `JobContext.checkpoint` and injected a pause at the
**third checkpoint invocation**, historically the boundary before item #2.
The newly committed startup checkpoint is now the first call, so ordinal
#3 occurs **before item #1**; the fixture incorrectly expected item #1
to have been moved. This is a deterministically observed test assumption,
not a production filesystem mutation.

The corrected regression injects the simulated pause only when the
actual `progress_message` begins `Executing item #2:`. This keeps
the exact intended item boundary and tests existing pause/resume behavior
independently of legitimate startup or progress checkpoints. It does not
disable assertions, change production pause/restore behavior, or authorize
a replay without a valid lease/frozen authority. Latest-head complete
regressions are required before merge; the original failures remain
historical evidence, not proof of new-head CI success.

## Release / owner constraints

Merge only after exact latest-HEAD CI, regression, snapshot and reviewer
checks pass, then confirm independent merged-main CI and branch cleanup.
The test uses only disposable synthetic filesystem state.

The real NAS incident remains [Issue #357](https://github.com/JinHaocong/nas-file-center/issues/357)
OPEN until proven resolution. **No production deployment, NAS cleanup,
database edits or human signoff are authorized by this PR.**
Formal owner acceptance [Issue #347](https://github.com/JinHaocong/nas-file-center/issues/347)
remains **69/74 (93.2%)** with #70–#74 OPEN.
