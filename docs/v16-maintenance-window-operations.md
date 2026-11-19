# V1.6 maintenance-window operations

Status: implemented candidate; candidate CI, real SATA full-lifecycle acceptance and release review remain required.
Owner operating-contract approval: 2026-11-19.
Design: [accepted maintenance-window contract](superpowers/specs/2026-11-19-v16-maintenance-window-proposal.md).
Implementation plan: [maintenance-window plan](superpowers/plans/2026-11-19-v16-maintenance-window.md).

## Two separate execution modes

The default is `MEDIA_ORGANIZER_EXECUTION_MODE=strict`. Its production custody issuer still refuses execution on an unproven backend. A boolean acknowledgement, a writable directory, the API/Worker UID split, or the application lock is not strict namespace custody.

The separately selected `maintenance_window` mode supports the existing in-place organizer with an operator-maintained pause on other writes. The owner must keep that pause in effect throughout execution, the wait for independent cleanup confirmation, cleanup and any recovery. It covers the selected unit and writes to the same underlying files through other shares, names, hardlinks, writable handles or backing paths. If a writer violates the pause, a substituted file can be deleted between the last check and a name-based cleanup syscall; detection and recovery cannot promise to restore it.

The application retains its no-overwrite, pinned-source, no-follow, frozen identity, unknown-entry refusal, journal and final zero-change scan checks. Successful maintenance execution always reports `assurance_level=maintenance_window` and `namespace_exclusive_custody_proven=false`. It does not establish release readiness.

## Candidate configuration

The organizer remains disabled and strict in the committed deployment templates. General mutation/delete settings retain their existing deployment overrides: for example, `compose.komodo.yaml` sets both to true. The table lists application defaults unless a deployment value is explicitly noted. A reviewed disposable acceptance deployment must deliberately select the same mode in API and Worker:

| Setting | Required for a maintenance candidate | Application default / noted deployment value |
| --- | --- | --- |
| MEDIA_ORGANIZER_EXECUTION_MODE | maintenance_window | strict |
| MEDIA_ORGANIZER_EXECUTION_ENABLED | true | false |
| ALLOW_MUTATION | true | false |
| ALLOW_DELETE | true | false |
| MEDIA_ORGANIZER_NAMESPACE_QUIESCENCE_ACK | Leave false; never used as maintenance proof | false |
| NFC_SHARED_CONFIG_GID | Shared config group for distinct API/Worker UIDs | Deployment group, normally 10000 |

Configuration is only an eligibility gate. Each execution, cleanup, execution recovery and cleanup recovery request must also include its exact existing operation confirmation token and the strict JSON boolean `maintenance_window_confirmed: true`. The UI supplies four separate, initially unchecked acknowledgements bound to the current unit/job or reviewed plan. String values such as `"true"` are invalid.

Do not switch a frozen job between modes. An absent mode in legacy evidence means strict. The mode is bound to the preview, approval, WorkJob, frozen manifest and recovery evidence; mismatches fail closed. Finish or recover a maintenance family with its original mode and evidence.

The actual Worker must be nonroot and have write/search access to the approved disposable media scope. The API retains a read-only media bind and uses immutable shared config evidence for cleanup review and recovery; it does not open Worker-private stages. The accepted local permission fixture does not authorize changing ownership or ACLs on existing media.

## Application coordination

All cooperating instances must use one trusted, stable CONFIG_DIR inode namespace with functional Linux flock. Separate config copies, independently mounted replicas or an administratively replaced config tree cannot coordinate through this protocol. The shared directory must have the project's shared-GID policy; a single-UID configuration must be private to that UID and not group/world writable.

The Worker holds an FD-based lock while dispatching a job and while performing startup/takeover recovery cleanup. It never deletes the lock file to unlock it. A paused Worker retains the lock after its database lease expires; another cooperative Worker cannot enter a media mutation until that file lock is released. The database lease remains an independent check.

A frozen unfinished maintenance family reserves application mutation processing across process restarts and the wait for cleanup approval. Unrelated writes remain queued; the family's cleanup and recovery can run ahead of them. Read-only previews remain eligible. Successful journal finalization and the real 0/0 scan release the reservation. A post-freeze failure preserves the window. Clearing visible task history does not discard the underlying organizer evidence.

Storage capability probes and plan validation can create temporary entries, so they also acquire the cooperative lock and check the reservation. They return a conflict while another operation or maintenance window owns it. API cancellation of a queued archive task performs no media directory removal; a later Worker owns eligible cleanup.

These controls coordinate this application's cooperative writers. They do not exclude other NAS applications, SMB/NFS services, privileged processes, same-UID programs or external aliases.

## Workflow and recovery

1. Select the approved disposable unit and complete its read-only preview.
2. Verify the unit, planned mappings and conflicts. Pause other writers, acknowledge the maintenance window, and submit the exact per-unit execution token.
3. The Worker freezes the mode-bound evidence, stages verified source links and publishes without overwriting. The resulting state may still need independent cleanup or deferred publication.
4. Read the cleanup inventory, including retained entries and deferred targets. Confirm the maintenance window again and submit the cleanup token.
5. The Worker completes the durable journal, finishes publication and cleanup, and performs the canonical scan. Completion requires both needed moves and renamed count to equal zero.
6. After an interruption, retain the stage, config reports, database and original job evidence. Use the exact offered recovery action and a fresh maintenance confirmation. A failed recovery that cannot validate evidence stops; manually deleting a stage, clearing a checkpoint, changing modes or unlinking the application lock is not a recovery procedure.

The reservation is intentionally conservative after frozen work fails. There is no force-release endpoint that declares damaged or incomplete evidence safe. If recovery is impossible, retain the evidence for a reviewed manual repair of the disposable candidate; do not copy such changes onto production media.

## Acceptance and completion

Local tests exercise the actual nonroot maintenance authority through API enqueue, Worker dispatch, independent cleanup, publication/cleanup interruption, recovery and the final 0/0 scan. They compare file payload hashes and counts; a planner metadata fingerprint alone is not treated as payload verification. Separate lock tests use real subprocesses and retain exclusion after an expired database lease.

The physical SATA acceptance must still run the ordinary production mode with distinct real API and Worker identities, the API's read-only media mount, no permissive synthetic custody issuer and a new isolated config/data fixture. It must cover mixed P/V, the 200-file bucket boundary, historical/overlapping names, refusals, independent cleanup and interruptions, and compare payload hashes/counts before and after. Record the exact candidate commit and image digest.

The standalone `scripts/v16_nas_maintenance_acceptance.py` helper performs this acceptance in a newly created `nfc-v16-maintenance-<random>` subtree. It requires a locally available immutable image ID or repository digest and an exact matching candidate revision label. The Docker publication workflow first runs the same helper against its exact locally built candidate on a synthetic Linux fixture. This Docker result is distinct from physical SATA evidence.

The host helper creates only its new private fixture, with separate API-owned shared config and Worker-owned media. It starts two isolated containers with no network connectivity, no extra capabilities and read-only roots. Only the new config/data paths are bound, with the API data bind read-only. HTTP requests run over loopback inside the API container; the real leased Worker dispatcher executes jobs. The helper verifies real runtime IDs, capabilities, mount modes and shared-config lock contention, rejects unconfirmed API actions and keeps the strict issuer closed. Its mixed, 201-photo-plus-video and historical-overlap fixtures each require matching payload hashes/counts and a 0/0 second scan; explicit test-only interruption wrappers exercise publication and cleanup recovery without replacing the production authority.

Keep the fixture and `acceptance-report.json` as evidence. The helper removes only its own verified temporary containers. Acceptance requires both `PASS_MAINTENANCE_LIFECYCLE` and a zero controller exit, with false namespace custody and false release readiness. A report publication or sync failure is a failed run even if readable bytes remain; the controller reports any uncertainty about retained evidence or container cleanup. This helper does not grant write access to existing media or change installed services.

Only the resulting evidence plus candidate CI and independent release review can support a release decision. The original running services, old acceptance fixture and existing media must remain untouched during candidate testing.
