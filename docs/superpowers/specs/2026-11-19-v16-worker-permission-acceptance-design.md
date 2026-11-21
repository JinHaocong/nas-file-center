# V1.6 disposable Worker permission acceptance

Status: scoped implementation for the next owner-authorized NAS evidence step.
This is an opt-in synthetic write test, not a read-only collector or an
execution-custody issuer. Production execution and release gates stay closed.

## Evidence and problem

The owner reported actual runtime evidence on 2026-11-19: the deployed
Worker is UID 10002, the API is UID 10001, and both use primary GID 10000
with no additional effective groups. The exec process and PID 1 have zero
permitted/effective/bounding capabilities and NoNewPrivs=1. Container and
host-process UID/GID maps are the direct identity mapping. Both canonical
`/data` binds are read-only, including runtime `fstatvfs`, and their opened
device/inode identities match the host data root.

Those observations resolve the identity-mapping question. They do not test
Worker writes or API denial through a writable bind. The old primitive
fixture is intentionally API-owned and shared-group writable. Changing its
ownership would both destroy historical evidence and retain an unsuitable
ancestor layout. A separate, newly created sibling is required.

## Chosen scope

Add a standalone standard-library script with an explicit, unabbreviated
`--create-disposable-fixture` option. An authorized host administrator runs
it with an existing absolute host `--data-root`. The default live-container
names are `nas-file-center-worker` and `nas-file-center-api`. Numeric test
identities are fixed at Worker 10002:10000, API 10001:10000, and foreign
UID 65534 with shared and unrelated GIDs. Unexpected live identities or
mapping stop the test before provisioning.

Revalidate selected live Docker configuration and actual runtime identity,
maps, capabilities, NoNewPrivs, read-only data bind and opened-root identity.
Do not retrieve or print application environment secrets. Use the installed
Worker image's immutable local ID; never pull, build or start application
jobs. Reject image-declared volumes. Override the entrypoint and run Python
with `-I -S -B`, from `/`, with any image healthcheck disabled.

## Filesystem boundary

Pin each existing data-root ancestor with no-follow directory descriptors.
Require trusted root ownership and no group/world write, except a trusted
root-owned sticky temporary ancestor whose next component is root-owned.
Reject unexpected or unknown access/default ACL evidence. No existing
directory ownership, mode or ACL is changed.

Create one unique absent `nfc-v16-worker-permission-<random>` sibling
directly below the verified data root. Initially create new directories
0700, then modify only their newly opened, identity-checked descriptors:

| New directory | UID:GID | Mode | Purpose |
| --- | --- | --- | --- |
| Fixture parent | 0:10000 | 0750 | Preserve host-controller evidence |
| `unit` child | 10002:10000 | 0750 | Synthetic Worker-owned test scope |

Re-read ownership, permissions, filesystem identity and ACL state after
provisioning. Only the unit is mounted in temporary containers. The parent
and report remain outside that bind. Enumerating and reading the small,
new synthetic unit is permitted; production data is neither enumerated nor
opened. The fixture and report are retained after success or failure.

## Probe matrix

Create temporary containers sequentially with read-only image root, no
network, all capabilities dropped and no-new-privileges. Use `--mount`,
which does not create a missing bind source, and inspect the created
container before starting it. There must be exactly the intended unit bind
and no extra Docker data mounts. Bound execution time and remove only
containers created by this invocation. Stop a timed-out probe before
checking its retained filesystem evidence.

Every probe first verifies its own identity, complete effective group set,
maps, zero capabilities, NoNewPrivs, bind read-only state and unit device/
inode. Live-container observations cannot substitute for this attestation.

| Probe | Bind | Expected result |
| --- | --- | --- |
| Worker 10002:10000 | Read/write | Create, write, read-back, fsync, directory creation and cleanup of its own scratch entries succeed |
| API 10001:10000 | Read/write | Read synthetic canaries; mutations denied |
| API 10001:10000 | Read-only | Read synthetic canaries; mutations denied and bind confirmed read-only |
| Foreign 65534:10000 | Read/write | Shared-group read succeeds; mutations denied |
| Foreign 65534:65534 | Read/write | Separate existing-entry stat/search, canary read and entry creation denied |

Set canary files to 0640 and canary directories to 0750 explicitly. Each
negative operation uses its own sacrificial entry. Shared-group probes
first prove the intended canary is readable, then attempt the mutation.
Accept only permission-denial errnos; missing entries, wrong mounts or
identities are failures. A read-only test records the actual errno rather
than assuming every denial comes from the mount flag.

Stop on the first unexpectedly successful mutation. Do not restore,
recursively delete or continue probing changed evidence. The host compares
the frozen synthetic inventory, entry identities and content after every
negative probe, including a probe error. Record primitive support failures
separately from permission denials; no privileged or pathname-based
fallback may turn an unsupported operation into a pass.

## Result contract

Exit code zero together with terminal `PASS_LOCAL_PERMISSION_BOUNDARY`
means only that all requested local test
identities behaved as expected on this new fixture, with the attested
mounts. It is not a statement that mode bits were the only enforcement
mechanism. Always retain `namespace_exclusive_custody_proven=false` and
`release_ready=false`. Root/admin, same-UID peers, SMB/NFS/FUSE services,
backing-store aliases and future lifetime isolation remain unproven.

This step neither runs the full P/V organizer lifecycle nor enables its
deny-by-default custody issuer. It does not satisfy independent production
security approval (#398). No installed service is restarted or reconfigured.

If report write/fsync fails, the terminal and unsuccessful exit are
authoritative. A partially persisted report can contain an earlier status
and cannot independently establish acceptance.

## Verification

Use focused TDD for guard rejection, effective identities/maps, safe Docker
construction, ACL errno handling, denial semantics, early stopping and
retained evidence. Run a scoped independent review before publication.
Separate local synthetic verification from pending CI and owner-executed
NAS evidence. No local run is represented as a ZOS/FUSE test.
