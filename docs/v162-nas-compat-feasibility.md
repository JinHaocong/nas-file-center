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
