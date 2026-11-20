# V1.6 maintenance-window operating contract

**Decision date:** 2026-11-21  
**Owner decision:** During a batch organize operation, no other file-modifying operation will be performed. This pause remains in effect through the separately confirmed cleanup or any interruption recovery.

## Supported assurance level for this NAS

The selected runtime mode is `MEDIA_ORGANIZER_EXECUTION_MODE=maintenance_window`. This is an explicit operational assumption, not kernel-enforced namespace custody. It is intentionally reported as:

- `assurance_level=maintenance_window`
- `namespace_exclusive_custody_proven=false`
- `release_ready` is determined by the remaining independent review and release gates, not by this acknowledgement alone.

Strict mode remains fail-closed because the production `verified_namespace_custody()` issuer has no independently verified host/NAS proof.

## What the operator confirms

Before each execution, recovery, cleanup and cleanup-recovery WorkJob, the administrator must explicitly confirm that all other writers are paused for the complete lifecycle. This includes:

- SMB/shared-folder clients writing to the selected unit
- OpenList uploads, moves, copies and background jobs
- PikPak/Rclone sync, upload, download and move jobs
- photo-library import/index/repair jobs that modify files
- other NAS applications, scripts, shell sessions and scheduled jobs that can modify the selected unit
- other NFC media mutation jobs (also serialized by the NFC mutation lock and maintenance reservation).

The UI confirmation is fresh per WorkJob. Execution confirmation does not silently authorize separate cleanup or recovery; each has its own confirmation. The pause must continue until the cleanup Worker completes its second zero-change scan or the recovery operation reaches a safe terminal state.

## What the Worker enforces

- dedicated non-root Worker identity
- exact job-bound literal `maintenance_window_confirmed=true`
- NFC cooperative media-mutation lock and maintenance reservation
- active Worker lease and per-mutation lease fences
- one frozen manifest, plan, job identity and ancestry
- canonical selected-unit scope and pinned directory FDs/inode checks
- no-follow opens, no overwrite, retained evidence, journaled cleanup and explicit recovery
- a second scan before finalization.

These controls serialize NFC work and detect many identity/evidence changes. They do not stop a privileged process outside NFC from writing concurrently.

## Observed NAS facts (2026-11-20/21)

- SATA mount: `zfuse.zfsv3`, mount ID `620`, `default_permissions,allow_other` visible.
- Worker scratch: `10002:10000`, mode `0700`; local UID matrix confirmed Worker access and EACCES for tested different unprivileged UIDs.
- `pikpak-rclone` and `openlist` are host-mapped UID 0 with `CAP_DAC_OVERRIDE`, each has the entire SATA data root mounted RW, and each can access the Worker-owned 0700 scratch.
- Current `nas-file-center-api` and `nas-file-center-worker` containers are production `1.4.6` root/RW deployments. They are not the V1.6 candidate Compose boundary and must not be changed as part of this work.
- No direct Samba share of the SATA data root, active TCP/445 session or relevant NFS export was found in the read-only snapshots. This does not eliminate alternate paths or future sessions.

Therefore the maintenance-window contract is valid only while those external services and all other writers remain idle. Do not claim that 0700, the cooperative lock, FUSE flags or this acknowledgement technically blocks them.

## Failure and recovery rules

If the operator cannot guarantee the pause, do not start the batch. If an unexpected external write is noticed, stop further execution and preserve the stage, originals, journals and reports for review; do not manually delete or retry. A failed job requires its separate explicit recovery flow and a renewed maintenance-window confirmation.

Do not change, stop, restart or remount OpenList, Rclone, Komodo, the existing 1.4.6 containers, or the production SATA data root as part of this contract.

## Review and release

An independent non-author reviewer must review this weaker threat model and the remaining #399/#402 race boundaries. This contract does not replace the formal GitHub Review, current-candidate NAS acceptance, Release Validation, or owner deployment approval. If a future requirement is to withstand an uncooperative concurrent root/SMB writer, maintenance-window mode is insufficient and strict host-enforced custody must be designed separately.