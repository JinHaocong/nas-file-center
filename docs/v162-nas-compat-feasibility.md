# V1.6.2: NAS compatibility — minimal-permission feasibility

Status: **diagnostic spike only**; not a release, media mutation or production rollout.
Tracking: [#405](https://github.com/JinHaocong/nas-file-center/issues/405).

## Why this is needed

On ZOS/zfuse, selected media folders can be owned by different NAS UIDs,
including root:root 0755. V1.6.1 allows mixed owners under a confirmed
maintenance-window session but cannot override Linux DAC for non-root
Worker UID 10002. Making the operator migrate all of `/data` ACLs is
not acceptable as part of normal media organization.

Expected UX: browser selection -> read-only preview -> explicit job-bound
confirmation -> safe publish and verified finalization, without SSH.

## Minimal first choice

Retain exactly the existing API (UID 10001, `/data:ro`) and Worker
(UID 10002) deployment. **Explore** granting only `CAP_DAC_OVERRIDE`
to the isolated Worker while retaining `cap_drop: [ALL]` and
`no-new-privileges:true`. This may bypass DAC on folders owned by
other UIDs without changing SQLite/report ownership or root guards.

This is a hypothesis, **not a compatibility claim**. Linux/Docker can
discard effective capabilities when exec'ing as UID 10002; adding a
capability to the bounding set does not mean Python has it effectively.
Actual ZOS/zfuse behavior must be independently tested. DAC override
also expands the Worker's access over every mounted path, including
`/config` and the currently mounted quarantine; security review must
consider every existing Worker job before the mode can be enabled.

Run the standalone **CI-only synthetic probe** via
`scripts/probe_nas_compat_capability.sh` on GitHub Actions to compare:

- existing non-root/no-capability Worker: cannot read a root-owned
  0600 file or create files in root-owned 0755 directory;
- same Worker with only `--cap-add DAC_OVERRIDE`:
  reports CapEff and actual access under a new disposable bind.

The probe creates and cleans only its own synthetic `mktemp` folder.
It does not touch existing mounts, app database, real media, ACLs or
other services. A pass proves **only** this CI Docker host behavior.

## If the experiment fails

Do **not** just run the ordinary Worker as root. Current code explicitly
refuses UID 0 in the execution, maintenance authority, publication and
finalization paths; shared SQLite, group permissions and locks also
deliberately distrust root-owned state. A root Worker also acquires
far broader authority over *unrelated* WorkJob types.

If capability retention fails, design a bounded privileged file-operation
helper rather than weakening UID checks or giving API write privileges.
The helper can be a separate process/container, but any extra runtime
must be justified by this concrete feasibility result.

## Security requirements for either choice

1. The default ordinary deployment remains UID 10002 with zero
   effective capabilities; any new NAS mode is separately opt-in.
2. API stays non-root and read-only on media. Strict custody is never
   inferred from an administrative checkbox, DAC override or root UID.
3. Keep one selected canonical `/data` unit, reviewed frozen
   evidence, no-follow, no-overwrite, Worker lease and mutation lock,
   journaled recovery and separately confirmed final cleanup.
4. The maintenance-window mode relies on pausing external media writers
   during execution **and through cleanup/recovery**. It is not kernel
   exclusion and cannot defeat hostile same-UID/root writers.
5. Re-review #399/#401/#402 source-basename races under any elevated
   permission. Validate #400 finalization before returning
   `finalized=true`; never silently delete foreign entries.
6. The non-root API may be unable to *browse* a private root-owned
   0700 directory even if the Worker gains DAC override. Preview and
   selection UX must be included in the implementation, not just writes.
7. Use only synthetic/CI fixtures during development. A disposable
   same-mount ZOS/zfuse check requires explicit owner authorization;
   this document is **not** such authorization.

## Exit criteria

Document the actual baseline/candidate CI matrix, choose the smallest
viable execution boundary, then implement the guarded NAS mode with
security regressions. Keep V1.6.1 available for rollback. Do not
modify production `/data` ACLs, media, backup, progress database or
recovery evidence.

## Second synthetic experiment: temporary root startup, non-root runtime

Plain `--cap-add DAC_OVERRIDE` on UID 10002 is not necessarily effective.
The CI probe now additionally checks an explicit **test-only launcher**:
a root-started container with only DAC_OVERRIDE/SETUID/SETGID, using
`PR_SET_KEEPCAPS` + `capset` + `PR_CAP_AMBIENT_RAISE` and finally
`execve` into a process with real/effective UID 10002, GID 10000 and
**only effective DAC_OVERRIDE**. The probe verifies `CapEff=0x2`,
`NoNewPrivs=1` and root-owned fixture read/write after the exec.

This tests whether retaining non-root database/report ownership is
mechanically possible **without a persistent root Worker**. It is still
only a synthetic CI feasibility check. The test-only launcher is not a
production command or authorization. Even if it passes, the elevated
capability applies to **every Worker task and all mounted paths**.
Implementing such a mode requires a separate runtime confinement and
threat-model review; it cannot be merged into the default profile.

## Prototype status: dormant optional startup entrypoint

`app/nas_compat_launcher.py` now contains the **actual production-shaped**
root-startup -> non-root transition, guarded by
`NFC_NAS_COMPAT_WORKER_ENABLED=true`, exact numeric UID/GID and
`MEDIA_ORGANIZER_EXECUTION_MODE=maintenance_window`.
It checks `NoNewPrivs`, exact startup permitted/effective/bounding
capabilities (DAC_OVERRIDE, SETUID, SETGID), drops to UID 10002/GID 10000
with no supplementary groups, removes SETUID/SETGID and all other
permitted/effective capabilities, raises only DAC_OVERRIDE ambient and
executes only the fixed `python -m app.worker` command.

`app.worker.worker_loop` checks the final non-root capability profile
**before any SQLite, scheduler, recovery, or WorkJob operation** when
opt-in is set. The default Worker is unchanged. The disposable Docker
probe invokes this same code for its synthetic final exec.

**NOT YET DEPLOYABLE:** No Komodo or default Compose profile calls this
entrypoint. We intentionally have NOT enabled the mode on any host,
granted any capability to the default Worker, performed a ZOS/FUSE
probe or approved its wider effects on other Worker tasks. A separate
review must confine the elevated capability to a justifiable set of
approved operations or explicitly accept/document the residual risk.

## New: protected-folder selection and scratch-only deployment model

The UI now offers a direct absolute-path field alongside the directory picker.
The API can defer *read-only preview queueing* for a permission-denied child
only when `NFC_NAS_COMPAT_API_DEFERRED_SELECTION_ENABLED=true`, the API
runs as non-root, and `maintenance_window` is configured. Before deferral,
accessible ancestors must be real directories (not symlinks). Missing paths,
reserved quarantine paths, other namespaces, strict mode, and an enabled
Worker capability profile cannot use this exception. A completed Worker
preview and job-bound confirmation remain prerequisites for execution.

Added `compose.v162-nas-compat-scratch.yaml` to demonstrate the eventual
two-container layout on a **brand-new disposable config and data root**.
It has no host ports, an internal Docker network, non-root read-only API,
and a tightly defined root-startup -> non-root Worker launcher. Unlike the
normal Compose, its test-only Worker startup has DAC_OVERRIDE/SETUID/SETGID
only during its controlled handoff; the effective Worker must end as UID
10002/GID 10000 with only DAC_OVERRIDE.

**IMPORTANT:** This scratch topology explicitly keeps `ALLOW_MUTATION=false`,
`ALLOW_DELETE=false` and `MEDIA_ORGANIZER_EXECUTION_ENABLED=false`
in BOTH services. It is **not** a runnable production media organizer, a
security approval, a ZOS/zfuse compatibility proof, or authorization to
enable writes. It cannot reuse existing NAS or NFC config and data paths.
Do not deploy it into Komodo or bind it to the real /data root.

`scripts/test_v162_scratch_compose.sh` checks its rendered Compose config
in CI using only a newly created temporary test root; it does NOT start
containers, modify files, or invoke any Docker privilege on a real NAS.

Remaining: inspect how ambient DAC_OVERRIDE affects **all** Worker job types,
complete the cleanup and hostile-writer security review (#399–#403),
get independent reviewer approval, and perform a separately owner-approved
same-mount ZOS disposable validation before adding any production overlay.


## Task-scoped DAC capability (experimental safety boundary)

The earlier prototype kept DAC_OVERRIDE effective/ambient in the entire Worker
process. That was unacceptable even for a candidate because unrelated
scheduled jobs, archive operations and child processes would inherit or use
it. The revised **default-off** prototype now performs a two-step handoff:

1. A fixed, root-started launcher drops to UID 10002/GID 10000 with
   DAC_OVERRIDE in the permitted and ambient sets ONLY long enough to exec a
   tiny `app.nas_compat_runtime_entry` module.
2. That module immediately clears *ambient*, *inheritable* and *effective*
   DAC_OVERRIDE before importing any Worker task/DB/scheduler modules.
   After startup, `CapPrm=0x2, CapEff=0, CapInh=0, CapAmb=0`. A new
   exec'd child has no effective DAC permission.
3. Only the foreground handler for a named
   `media-organizer-preview`, `media-organizer-execute` or
   `media-organizer-cleanup` WorkJob may temporarily raise CapEff to
   `0x2`. Execute and cleanup require the independent mutation flags,
   exact WorkJob ID, nonempty confirmation and literal job-specific
   maintenance-window acknowledgement. Ordinary jobs never raise DAC.
4. The handler finally block revokes CapEff and rechecks the parked identity;
   an unexpected failure to revoke terminates the Worker rather than
   proceeding with privileged failure logging. Scheduler, cleanup hooks,
   SQLite, heartbeat and normal jobs run without effective DAC.

**Security limitation remains:** DAC_OVERRIDE stays in the permitted set
throughout the Worker process and can be re-enabled by compromised Python
code. Per-job gating is a defense-in-depth restriction, not a kernel-enforced
least-privilege guarantee. A separate narrowly confined helper may still be
required for release. In particular, no code/CI result yet proves hostile
root writer exclusion, ZOS/FUSE capability behavior or safe final cleanup.

The CI scratch probe tests root-owned DAC access **only during** the scoped
WorkJob, no ordinary access before/after, and zero CapEff in an exec'd child.
This is isolated synthetic evidence, NOT NAS acceptance or release approval.
