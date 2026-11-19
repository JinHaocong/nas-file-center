# V1.6 maintenance-window implementation plan

> Execute the accepted owner decision of 2026-11-19 ("同意"). No further design approval is needed.
> Upstream baseline: 98f32610ecce411068fdf2bb2c80e858b09bbb8d, Draft PR #397.
> Local isolated snapshot baseline: f2cd4f409446f14e19dbefa8392a52666b84af0f.

## Goal

Deliver the existing complete in-place organizer through an explicit maintenance-window mode. Preserve strict custody refusal, integrity controls, independent cleanup confirmation and recoverability. Do not enable execution defaults or release the candidate.

## Architecture

Configuration selects strict (default) or maintenance_window. Every maintenance execution, cleanup and recovery requires a fresh boolean confirmation and exact existing operation token, and binds its mode in job state and immutable frozen evidence. API eligibility does not acquire a Worker session or inspect private stage directories. Worker operations use a context-managed authority with explicit scope and resource release. A maintenance session is not a ScopedNamespaceCustody and cannot assert_exclusive.

An FD-held, non-expiring cooperative flock serializes application job/recovery filesystem work across Workers. A durable unfinished maintenance execution additionally reserves application mutation processing between execution and separate cleanup/recovery; queued unrelated jobs wait without blocking eligible maintenance follow-ups. Only a successfully finalized family releases that reservation automatically; failures after frozen evidence preserve the reservation and require recovery. This is an application cooperation mechanism within one shared CONFIG_DIR, not storage custody or exclusion of outside writers.

## Global Constraints

- Strict verified_namespace_custody and assert_exclusive_custody retain deny-by-default semantics. The legacy namespace ACK never grants maintenance authority.
- The new setting is MEDIA_ORGANIZER_EXECUTION_MODE with allowed values strict and maintenance_window, default strict. Existing allow flags remain required and default false.
- Every maintenance execution, cleanup and recovery request uses maintenance_window_confirmed: true (a strict boolean). Confirmation is fresh for each action and bound to its exact unit/job/immutable evidence. Legacy absent mode means strict, never maintenance.
- Successful maintenance results report assurance_level=maintenance_window and namespace_exclusive_custody_proven=false. Do not claim release readiness.
- Keep no-overwrite publication, pinned source FDs, no-follow path validation, source identity checks, unknown-entry rejection, durable journals, separate cleanup and final canonical second scan 0/0.
- The operator must pause writes through other aliases, shares, handles and services throughout the window. A violating concurrent replacement can be wrongly deleted and cannot be promised recoverable.
- Do not change real NAS mounts, existing media ownership/ACLs, feature defaults, or the existing legacy fixture. Do not merge or release.
- Do not add the private source label to tracked files or commit messages.
- Implement and test real production entry paths without permissive injected custody issuers. Nonroot simulation in ordinary tests is allowed only for the process identity prerequisite; separate actual nonroot acceptance must be explicit.
- Work only in /workspace/scratch/d331d8c59276/maintenance-work. Use /workspace/scratch/d331d8c59276/maintenance-venv/bin/python for pytest.
- All changed/new code is repository-backed. The controller publishes one atomic upstream commit with an expected-head lease. Implementers do not commit or push shared changes.
- Write failing behavioral tests first, record the observed red and green commands, and report concrete remaining limitations. No subagent delegation from implementers.

## Review Focus

Verify mode/evidence substitution resistance; private API versus Worker separation; lock lifetime on exceptions and lease takeover; durable reservation with cleanup/recovery progress; scope validation for future and retired parents; existing strict tests; full real implementation lifecycle and negative cases.

### Task 1: Explicit operation authority and lower-level guards

Own app/batch/media_organizer_authority.py (new), app/batch/media_organizer_publish.py, app/batch/media_organizer_deferred_cleanup.py, app/batch/media_organizer_finalize.py and tests/test_media_organizer_maintenance_authority.py (new). Do not edit job modules, config, Worker or frontend.

Read the accepted spec and current lower-level checks. Add explicit operation authorization dispatch, keeping app/batch/media_organizer_custody.py unchanged. The shared interface is:
- execution_mode(settings) -> str, validates strict or maintenance_window.
- check_api_eligibility(settings, unit, parents=()) -> None: strict invokes existing issuer/check; maintenance validates the canonical selected unit sufficiently for enqueue without private stage access and acquires no Worker lock/FD lifetime.
- acquire_operation_authority(settings, unit, parents, *, manifest=None) -> context manager yielding a strict proof or MaintenanceWindowSession. Mode and per-operation confirmations are validated by job entry points before acquisition. Strict existing proof behavior stays compatible; release resources if supported.
- assert_operation_authorized(authority, parents) -> None: exact maintenance session uses its explicit assert_mutation_allowed method, otherwise existing assert_exclusive_custody.
- fence_operation_authority(authority, callback) -> an explicit operation wrapper that invokes the lease callback on every assertion without masquerading as strict custody. The dispatcher recognizes that wrapper.

Maintenance acquisition requires app.tasks.media_mutation_lock.media_mutation_lock(settings) and releases it and pinned FDs in finally. It validates nonroot Worker access, canonical no-follow selected path, writable mount, and explicit scope. Bind existing parents; distinguish planned future stage/P/V parents and journal-authorized retired parents. Do not accept arbitrary missing parents. Existing mutation receipts/journals remain authoritative for per-entry lifecycle. If the shared interface needs refinement, tell the controller immediately rather than editing another owner's files.

Replace lower-level guards with the explicit operation guard and retain all adjacent validation. Do not add a permissive strict issuer or implement assert_exclusive on a maintenance session.

TDD: strict false/ACK refusal preserved; maintenance cannot satisfy strict guard; default flags/mode not authorization; writable nonroot scoped session works; outside scope/symlink/identity/read-only/closed session fail; FDs/locks release after exceptions; future and cleanup-retired paths are validated correctly; low-level no-overwrite and unknown-entry checks remain effective.

### Task 2: Cooperative Worker lock and durable reservation

Own app/tasks/media_mutation_lock.py (new), app/worker.py, app/tasks/recovery.py, tests/test_media_mutation_lock.py (new) and tests/test_media_organizer_maintenance_reservation.py (new). Do not edit job modules, config, authority or frontend.

Implement media_mutation_lock(settings) as a context manager. It is reentrant within the owning thread/process, exclusive across threads/processes and shared by all cooperating Workers using the same canonical CONFIG_DIR. Use a regular no-follow FD-held flock, validate directory/file identity and permissions, never unlink/recreate the lock to release it, and fail closed on unavailable/changed lock. Paused holders retain exclusion after DB lease expiry. Explicitly account for fork/child descriptor lifetime and document the supported same-config deployment boundary.

Cover every process_work_job invocation and worker startup/takeover filesystem recovery and residue/archive cleanup before a handler could write. Audit API mutation routes for operations outside WorkJobs; report concrete bypasses and coordinate minimal coverage. Locks must not be held over API HTTP response lifetimes. Keep process_work_job signature compatible.

Add durable maintenance reservation gating derived from WorkJob.state_json execution_mode=maintenance_window and frozen checkpoint evidence. State bindings provided by Task 3: maintenance_window_confirmed=true, execution_mode in all related states; execute recovery has canonical recovery_of_job_id matching retry_of; cleanup state has execution_job_id and frozen_job_id. A family with frozen evidence and phase other than completed blocks unrelated application mutation jobs until successful finalization; failed/restarted family stays reserved. Queued unrelated jobs must not starve its cleanup/recovery. Conservatively wait jobs with unknown mutation scope. Read-only preview may run. Do not let a mode change release a reservation. Legacy strict jobs retain existing behavior. Coordinate family traversal with Task 3, including recoveries whose original failed execution remains in the DB.

TDD: subprocess holder blocks contender despite elapsed fake DB lease; exception releases; symlink/lock replacement fails; direct dispatcher and startup recovery guarded; foreign queued mutation waits; maintenance cleanup/recovery bypasses that queue safely; failed frozen family remains reserved; finalized family releases; mode change does not bypass.

### Task 3: Configuration, API and production job integration

Own app/config.py, app/media_organizer/router.py, app/batch/media_organizer_jobs.py, app/batch/media_organizer_execute_jobs.py, app/batch/media_organizer_cleanup_jobs.py and new tests/test_media_organizer_maintenance_jobs.py (plus narrowly necessary existing tests). Do not edit authority, lower-level mutators, Worker/recovery modules or frontend.

Add the configuration and strict-boolean request confirmation described in Global Constraints. New optional function keyword maintenance_window_confirmed=False on enqueue execution, cleanup and both recovery operations. Strict clients remain compatible. Bind execution_mode and maintenance_window_confirmed in every related job state; immutable manifest/checkpoints bind execution_mode and reject inconsistent recovery/cleanup. Absent mode is strict. Require a new confirmation for each enqueue, even recovered jobs. Include mode/assurance/false custody/requires_maintenance_window in preview/execution/cleanup responses.

Use Task 1 interfaces for API eligibility and Worker context lifetime. APIs must not traverse private stage paths in maintenance mode; continue validating shared immutable handoff and original job evidence. Worker acquisition and explicit release cover successful run, exceptions, cancellation and lease loss. Cleanup lease fencing uses fence_operation_authority rather than a maintenance object masquerading behind assert_exclusive. Keep existing strict behavior/tests and all independent cleanup/recovery checks.

Coordinate durable reservation family with Task 2; expose exact state/checkpoint bindings. A completed recovery followed by cleanup must finalize the entire original family for reservation purposes without rewriting immutable approval evidence. Do not let early failure with no media writes permanently block the queue.

TDD first: missing/false/string maintenance ACK fails; correct separate ACK + token queues; defaults and strict ACK-only remain closed; mode tampering/switch/replay fails; actual normal preview -> enqueue -> Worker -> cleanup -> final 0/0 uses the real new authority, no injected proof; full payload counts/hashes preserved; failure/recovery exercised; API private-stage isolation. Root will add frontend tests and run integration suite.

### Task 4: UI, documentation and candidate validation (controller)

Update frontend request/response types, execution editor and task cleanup/recovery actions. Each maintenance action requires an explicit unticked checkbox and explains the maintenance window and residual replacement/deletion risk in plain Chinese. Reset confirmation across operation/unit changes. Strict UI remains compatible; optional false arguments need not alter old request bodies.

Mark the spec owner-approved, document configuration, shared-config serialization/reservation and recovery behavior. Run relevant backend tests, the project's full pytest suite and frontend tests/build, reporting environmental blockers specifically. Obtain independent scoped review of tasks and integrated delta; fix material findings. Publish only reviewed code/tests/docs on the existing Draft PR with an expected-head lease. Inspect actual candidate CI. Prepare a pinned, reviewable disposable real SATA full lifecycle acceptance step after the candidate is ready; do not silently enable existing installed services.

## Verification and publication

Baseline tests run from the isolated snapshot with all source blob hashes verified. No local git history is claimed to be upstream history. The local snapshot baseline only supports review diffs; publishing uses the real upstream tree and parent. Candidate completion is distinct from real NAS acceptance and release.
