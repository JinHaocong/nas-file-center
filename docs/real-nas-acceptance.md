# V1.6 real NAS acceptance

Status: **RELEASE BLOCKED — HOST EVIDENCE AND SEPARATE APPROVAL REQUIRED**

## Current final Maintenance Window lifecycle harness (2026-11-20)

This section is authoritative for the current Draft PR #397 candidate and
supersedes the older primitive-only harness instructions below.

The pinned helper `scripts/v16_nas_maintenance_acceptance.py` runs directly
on the NAS host as a root controller. It creates one random, inode-pinned
disposable fixture beneath the supplied existing SATA data root; it does not
walk or mount existing media directories, alter the installed API/Worker,
modify the production config/quarantine trees, pull/build an image, or enable
the installed service. Temporary API and Worker containers use only that
fixture and a separate temporary config, with restricted identities,
capabilities, read-only container roots and no network.

The candidate is pinned independently from the helper source:
- Docker image: `kerwinjhc/nas-file-center@sha256:3c33ce5387e71475875d34802cb654182153cd96d49882bc3e2e57b04325120c`
- OCI revision expected by `--candidate-sha`: `153ae05780d6eebdc8db2723914e6b446119d4a2`
- Helper source: exact GitHub PR #397 HEAD; verify its SHA-256 before execution.
  The helper commit SHA is not the image OCI revision.

The helper exercises three disposable organizing units:
1. Mixed images/videos: 2 pictures and 1 video.
2. Bucket boundary: 201 pictures (200 in `P`, 1 in `P_1`) and 1 video.
3. Historical/conflicting layout: pre-existing classification directories plus
   mixed source media.

**Each scenario** must exercise a simulated interruption after publication,
explicit execution recovery, a simulated interruption at the cleanup
zero-scan checkpoint, explicit cleanup recovery, final file-count and
SHA-256/inventory reconciliation, and a canonical second scan with
`needed_moves=0` and `renamed_count=0`.

The runtime mode is explicitly `maintenance_window`. Keep all other writers
out of the newly created fixture from before the first organizer mutation
through publication, cleanup and recovery. The application lock coordinates
cooperating internal tasks only. This mode intentionally reports
`namespace_exclusive_custody_proven=false`; it does not establish isolation
against root/admin, same-UID programs, or SMB/NFS/NAS clients that violate the
maintenance window. Do not represent this as strict namespace custody.

Success requires both `status=PASS_MAINTENANCE_LIFECYCLE` and
`NFC_MAINTENANCE_EXIT=0`. This is disposable real-filesystem acceptance
evidence only. It does not close independent security review #398, open
findings #399/#401/#402, the separate cleanup review #400, or authorize merge,
production deployment, or execution against original media.


The existing one-shot Docker Compose task tests real-filesystem primitives,
flat publication and refusal of grouped publication on an approved disposable
NAS directory. It does **not** test complete V1.6 cleanup/recovery or establish
exclusive namespace custody. No self-hosted GitHub runner is required.

At commit `ae95b60e8c11fb6e38a377039547291f1cd37f81`, focused workflow
`Semantic Media Organizer V1.6 TDD`, run `44364472632`, passed, including
`scripts/test_v16_cleanup_cross_uid.sh`: actual distinct Linux UIDs exercised
execution, cleanup and explicit recovery on disposable CI files. This is
synthetic storage evidence; it does not establish NAS UID mapping, ACL/SMB
exclusion or real-mount durability. On that same commit, all nine non-release
workflows succeeded; `Scheduler S5 Closure` run `44364473023` includes full
backend/frontend/build validation. `Release Validation` run `44364472586` was
skipped because the PR is Draft; it is not a release-validation pass.

The acceptance container has a read-only root filesystem, no network, and
**two writable bind mounts**: the disposable acceptance root and the host
evidence directory. The script itself is a third, read-only bind mount.

## Step 0: Zero-mutation NAS host permissions preflight (#403)

Run this **read-only** diagnostic on the NAS host, from a checkout of the
exact Draft PR candidate. It is not the acceptance test and does **not**
start containers, create directories, fix permissions or touch media contents.

Use the existing **host** bind-source paths for `/config` (NVMe) and
`/data` (SATA). They are not the container's `/config` and `/data` paths.

```bash
python3 scripts/v16_nas_readonly_preflight.py \
  --config-dir "/absolute/host/path/to/current-config" \
  --data-dir "/absolute/host/path/to/SATA-media-root" \
  --api-uid 10001 \
  --worker-uid 10002 \
  --shared-gid 10000
```

Requirements: Python 3.10+ on the NAS host; no external packages and no root
privileges required for normal readable metadata. It only reads inode/mode/GID
metadata for known configuration files/directories and mount information from
`/proc/self/mountinfo`. Each root is opened with a metadata-only `O_PATH`
directory descriptor; its `/proc/self/fdinfo` mount ID selects the actual
mount record. Record order and longest pathname prefixes cannot identify the
visible filesystem reliably when mounts are stacked or hidden. Unavailable
or ambiguous descriptor-bound metadata blocks the check. This remains a
point-in-time observation, not proof of a backing disk or exclusive custody.
It never lists or opens files below the SATA media
root. Up to 1,000 archive **report directory** entries may be checked for
file metadata; names, file contents and host paths are not included in JSON.

The JSON result prints to standard output without writing a report file:

- Exit `0`, `config_metadata=CHECKS_PASS`: the selected known POSIX
  **metadata checks** passed. This is **not** a deployment approval.
- Exit `2`, `config_metadata=BLOCKED`: incompatible existing modes/GIDs,
  a symlink, missing mount, unreadable metadata or bounded audit uncertainty.
  Inspect `blocking_checks`; do **not** auto-run chmod/chown scripts.
- `media_exclusive_namespace=NOT_PROVEN`,
  `nas_acl_and_smb_custody=NOT_PROVEN`, and `release_ready=false`
  are **always** emitted, even when the known metadata passes.

This gate intentionally refuses to claim that a same-GID or root/SMB process
cannot mutate source names during organizer execution. Linux bind mounts and
file-mode observations are insufficient to prove exclusive NAS namespace
custody. A separate owner-approved disposable **same-mount** permission
and actual filesystem end-to-end test is necessary before enabling V1.6.
No production `/config`, SATA or NAS ACL change is performed here.

Before designing the real custody issuer, collect the host kernel and Docker
versions, rootless/user-namespace configuration, actual container UID/GID maps,
numeric ACLs (including inherited/default rules) on the selected source/final
parents, and the applicable SMB/NFS identity and write policies. Use read-only
inspection; omit credentials and use numeric identities. POSIX metadata alone
does not establish exclusion of other same-UID, shared-group or privileged
content/namespace writers. `app/batch/media_organizer_custody.py` remains
default-deny even when execution flags are set.



## Step 0b: Scoped namespace and ACL metadata preflight (#402/#399/#401)

After Step 0 has identified the existing SATA mount and before considering any
custody design, inspect **one existing organizing unit** using the new
read-only metadata collector. This is not a write probe and must not be pointed
at a production unit unless the owner explicitly wants its directory metadata
reviewed. The command opens directory components with `O_NOFOLLOW`, reads
POSIX access/default ACL xattrs and mount IDs, and never enumerates or opens
media files:

```bash
python3 scripts/v16_nas_namespace_custody_preflight.py \
  --data-root "/absolute/host/path/to/SATA-media-root" \
  --unit "/absolute/host/path/to/SATA-media-root/existing-disposable-unit" \
  --worker-uid 10002 \
  --api-uid 10001 \
  --shared-gid 10000
```

The JSON records directory UID/GID/mode, mount ID/filesystem/read-only state,
visible POSIX access/default ACL entries, path-ancestor ownership and
whether the Worker appears able to create entries under a POSIX metadata
model. That model assumes the supplied Worker UID and `--shared-gid` as its
primary group, with no supplementary groups. It checks owner/named-user/group/
other precedence and ACL masks; it does not perform a real access or write
probe. Unknown access ACL metadata produces an unknown assessment, not a
definitive denial. Container identity mapping, ancestor traversal, mount
read-only state and NAS/FUSE enforcement remain separate observations. A
group-derived grant does not satisfy the exclusive-writer requirement.
It deliberately emits
`smb_nfs_write_exclusion=NOT_PROVEN`,
`same_uid_process_exclusion=NOT_PROVEN`,
`root_admin_exclusion=NOT_PROVEN`,
`namespace_exclusive_custody_proven=false` and
`release_ready=false` for every result. `POSIX_SCOPE_RESTRICTED` means only
that the observed directory metadata has no detected non-Worker POSIX writer
within this narrow snapshot; it is **not** an execution credential or proof
against root, same-UID processes, remote SMB/NFS clients, server-side ACLs,
or changes after the observation. `REVIEW` or `BLOCKED` must not be bypassed.
The tool performs no chmod/chown/setfacl, mkdir, unlink, rename or file-content
read. Never use it to inspect a media file or recursively walk a library.

Collection errors include a structured errno and the failing directory depth
and path role where known. Depth zero is `/`; each subsequent component adds
one. Private paths/component names and exception messages are omitted. The
collector uses `O_RDONLY | O_DIRECTORY | O_NOFOLLOW`, so the invoking account
needs directory read/traverse access even though no children are enumerated.
An authorized administrator may collect metadata where the login account
cannot; this does not test or grant the Worker's runtime access.

### Owner-reported NAS namespace observation — 2026-11-19

Source: the owner's pasted output from the pinned `c96c6ea` collector, with
host names, private path components and inode values omitted here. This is
reported NAS evidence, not a command executed by CI or by a repository agent.

| Observed scope | UID:GID | Mode | Interpretation |
| --- | --- | --- | --- |
| Data root and its non-temporary ancestors in the SSH view | 0:0 | 0755 | No group/other namespace write permission visible in these mode bits |
| Temporary-directory ancestor | 0:0 | 1777 | Sticky directory; the relevant following component is root-owned |
| Existing primitive acceptance root | 10001:10000 | 2770 | API-owned and shared-group writable |
| Existing organizer acceptance child | 10001:10000 | 2770 | API-owned and shared-group writable |

The relevant data/root/child observations were on the same visible writable
`zfuse.zfsv3` mount. POSIX access and default ACL xattrs were reported ABSENT;
this is not proof that NAS server-side access rules are absent. Login UID
1001 failed opening the acceptance-root component at depth 6; administrator
UID 0 collected all eight directory records successfully.

The old `10001:10000` layout matches the primitive harness contract below.
It must not be reclassified as a failed Worker-only setup or automatically
chowned/chmodded. The original `worker-cannot-create-in-unit` diagnostic was
incomplete: its helper considered only ownership/named-user ACL permission.
Ordinary POSIX permissions would allow the modeled `10002:10000` identity
through the shared group. The valid remaining objections are the API-owned
unit and ancestor, shared unit write permission, and mutable parent binding.
There has been no actual Worker create attempt in this observation.

Next, record the actual API/Worker effective IDs, supplementary groups,
capabilities, container/host UID and GID maps, and selected data binds. Host
numeric ownership must follow verified mapping, not just container UID names.
Mount IDs are namespace-local; compare each opened root within its own
namespace and correlate the intended bind source's filesystem/device/inode.

After identity is established, use a **new absent sibling** beneath the
trusted data parent for the Worker permission fixture. Do not put it beneath
the old API-owned mutable acceptance root. With verified identity mapping,
a root-owned parent and Worker-owned unit, both 0750 with the shared read
group, are a possible scoped layout. Provision only the new inodes and
verify the filesystem's actual resulting owner/mode/ACL state.

Actual zero-capability Worker create/write/fsync/owned-cleanup probes and API/
foreign-UID denial probes belong only in that disposable fixture. Test both
the intended API read-only bind and the underlying POSIX denial on a fixture
writable bind; a read-only mount alone does not test filesystem permissions.
These results still do not prove remote SMB/NFS service exclusion, absence
of same-UID writers, or privileged/root exclusion. The production custody
issuer and every release gate remain unchanged.

### Subsequent owner-reported container identity evidence — 2026-11-19

The owner subsequently supplied selected `docker inspect`, default
`docker exec`, PID 1 and host-process map evidence for the running services.
This is a point-in-time observation, not a repository-agent NAS execution.

| Observed property | Worker | API |
| --- | --- | --- |
| Configured and actual UID:GID | 10002:10000 | 10001:10000 |
| Effective group set | 10000 only | 10000 only |
| UID/GID maps in observed host/container processes | Direct identity mapping | Direct identity mapping |
| Permitted/effective/bounding capabilities | Zero | Zero |
| NoNewPrivs | 1 | 1 |
| Privileged / added capabilities | False / none | False / none |
| Dropped capabilities | ALL | ALL |
| Canonical `/data` bind | Read-only | Read-only |
| Runtime `/data` read-only flag | True | True |

Both opened container roots matched the previously observed host data root
by device and inode. The earlier identity-mapping question is therefore
resolved for these observed processes. This does not attest other host
processes, alternate bind paths or SMB/NFS/backing-store writers.

The next step is the separately scoped disposable Worker permission test
specified in
[`2026-11-19-v16-worker-permission-acceptance-design.md`](superpowers/specs/2026-11-19-v16-worker-permission-acceptance-design.md).
Its temporary test containers mount only a new synthetic unit. Existing
containers retain their read-only canonical data binds. The old API-owned
primitive acceptance directories remain unchanged.

## Step 0c: Disposable Worker permission enforcement test

`scripts/v16_nas_worker_permission_acceptance.py` implements the next scoped
step. Unlike the metadata collectors, this command **writes synthetic test
files**. Its required `--create-disposable-fixture` flag makes that scope
explicit. Run it on the NAS host as an authorized administrator after
reviewing the pinned script:

```bash
sudo python3 -I -S -B scripts/v16_nas_worker_permission_acceptance.py \
  --data-root "/absolute/host/path/to/SATA-media-root" \
  --worker-container nas-file-center-worker \
  --api-container nas-file-center-api \
  --create-disposable-fixture
```

The controller uses the local Docker Unix socket and the existing Worker's
exact installed image ID, without pulling or building an image. It first
revalidates the host/controller and service UID/GID maps, actual runtime
identities, capabilities and canonical read-only data binds. It requires
root-owned trusted data ancestors and understood ACL metadata. Unsupported
or unexpected metadata is a stop condition, not a request to repair the NAS.

After those checks it exclusively creates one new sibling named
`nfc-v16-worker-permission-<random>` directly inside the supplied data root.
The parent is root:10000 mode 0750; its `unit` child is 10002:10000 mode 0750.
Ownership and mode operations apply only to these newly created inodes.
Existing primitive fixtures and existing media are not traversed or changed.

Five temporary Python containers run sequentially. Their image root is
read-only, network is disabled, all capabilities are dropped, and
no-new-privileges is required. Only the new `unit` is bind-mounted. The
controller inspects each created container before starting it, and each
probe checks its actual identity, maps, capabilities and bound directory
before operating. Image health checks and declared data volumes cannot
introduce application jobs or extra data mounts.

| Role | Unit bind | Expected observation |
| --- | --- | --- |
| Worker 10002:10000 | Read/write | Synthetic create/write/read-back/fsync and owned scratch cleanup succeed |
| API 10001:10000 | Read/write | Canary reads succeed; write, unlink, rename, rmdir, mkdir and create are denied |
| API 10001:10000 | Read-only | Same reads and mutation denials; runtime bind is confirmed read-only |
| Foreign 65534:10000 | Read/write | Shared-group reads succeed; all six mutations are denied |
| Foreign 65534:65534 | Read/write | Unit search, canary read and entry creation are denied |

Only permission-denial errors count. An unexpected success, wrong identity,
unavailable primitive, missing canary or changed evidence stops the matrix.
On each negative probe, including an errored probe, the controller verifies
the frozen synthetic inventory, inode metadata and content. It first stops
and removes its own temporary container; an uncertain cleanup is reported
as a failure rather than treating a possibly live writer's evidence as
frozen. Existing service containers are not reconfigured or restarted.

The JSON report is printed to the terminal. Once its evidence file has been
created, the controller also writes it to the new fixture parent's
`acceptance-report.json` with root-only permissions. The new fixture is
retained on success and failure; the script never recursively removes it.
If a prerequisite fails before creation, `fixture` is null and the terminal
report identifies the failure. Retain the report for review rather than
changing permissions or rerunning against an existing fixture.

Success requires **both exit code 0 and terminal
`status=PASS_LOCAL_PERMISSION_BOUNDARY`**. If the final report write/fsync
fails, an on-disk file can already contain the earlier provisional status;
`EVIDENCE_WRITE_FAILED` in the terminal or an unsuccessful exit invalidates
that saved file as acceptance evidence. Successful acceptance means the
tested local identities behaved as expected through these mounts during
this run. `namespace_exclusive_custody_proven` and `release_ready` remain
false even on success. Root/admin, same-UID processes, remote services,
backing-store aliases and future isolation remain unproven. This test does
not exercise FD-pinned publication, the complete P/V organizer lifecycle,
cleanup/recovery or second-scan convergence, and it does not satisfy #398.

### Owner-reported Worker permission acceptance — 2026-11-19

The owner ran the exact helper at
`3500e51b8472340e3a61032434c3ab68c0bdfee5`, whose SHA-256 was
`26bfd1d816d7094c51ef4b1a22496e3028d525ed6b6a2c870478e89a498adf05`.
The terminal reported `PASS_LOCAL_PERMISSION_BOUNDARY` and
`NFC_ACCEPTANCE_EXIT=0`. This was an owner-executed real NAS run, not a CI
or repository-agent execution. Private paths and inode values are omitted.

| Probe | Observed result |
| --- | --- |
| Worker 10002:10000 on read/write test bind | PASS: synthetic write/read-back, file/directory fsync and owned scratch lifecycle completed |
| API 10001:10000 on read/write test bind | All six attempted mutations returned EACCES (13); frozen inventory unchanged |
| API 10001:10000 on read-only test bind | Write returned EACCES (13); create/mkdir/rename/rmdir/unlink returned EROFS (30); frozen inventory unchanged |
| Foreign 65534:10000 on read/write test bind | All six attempted mutations returned EACCES (13); frozen inventory unchanged |
| Foreign 65534:65534 on read/write test bind | Existing-entry traversal/stat, read and create returned EACCES (13); frozen inventory unchanged |

Every probe attested the expected numeric identity, direct UID/GID maps,
zero permitted/effective/bounding capabilities, NoNewPrivs=1, intended
read-only/read-write flag and the same synthetic unit device/inode. The
retained unit was Worker-owned mode 0750; synthetic files were mode 0640.
The live API/Worker canonical data binds remained read-only. The helper
used the installed Worker's local immutable image ID.

This completes the local-identity permission matrix for that fixture. It
does not establish exclusive namespace/content custody or accept full
organizer execution, cleanup/recovery or release. The report retained both
`namespace_exclusive_custody_proven=false` and `release_ready=false`.

The remaining operating-boundary decision is recorded separately in the
[maintenance-window proposal](superpowers/specs/2026-11-19-v16-maintenance-window-proposal.md).
That proposal is not approved and does not replace the strict contract.

## Configuration backup, candidate validation and rollback (#403)

This is a sequence for a **separately approved maintenance window**, not a
request to change the current NAS. Replace all paths/service names below with
reviewed values. The backup archive, candidate config and original config must
be separate, non-nested locations outside the media tree. Commands assume Bash
and GNU tar with ACL/xattr support, run by an authorized account able to preserve
numeric ownership; stop on any error rather than dropping preservation options.

1. Record the current image digest, resolved deployment configuration and bind
   sources privately. The repository's application Compose files still select
   `1.4.6`; prepare a candidate configuration pinned to the reviewed candidate
   image digest, with distinct project/container names. Use an isolated candidate
   network: attaching identically named services to the production proxy network
   can also reuse service DNS aliases even when container names differ. Preserve the
   old image/config pair for rollback. Wait for active tasks to finish, stop the
   Worker, then the API, and confirm both stopped. Keep every other writer to
   this config tree stopped throughout backup/copy; a live `cp app.db` is not a
   consistent backup of a WAL-mode database and its evidence.
2. Archive the **whole stopped config tree**, including any existing `app.db`,
   `app.db-wal`, `app.db-shm`, lock, reports, immutable manifests/plans, private
   receipts and progress journals. Do not delete sidecars or checkpoint the
   original merely to prepare the copy. The built-in `app/db.py::backup_database`
   uses SQLite online backup before schema migration, but does not back up all
   evidence or host permissions and is not a substitute for this snapshot.
   If quarantine payloads live below the config bind source, the archive includes
   them too: confirm backup capacity before starting. Preserve the canonical
   `/quarantine/.nas-file-center-trash` mount path used by historical DB records.
   Config and media bind sources must be disjoint in both directions, including
   resolved host aliases. Otherwise the writable config mount can expose media
   even when `/data` itself is mounted read-only.
   The Komodo template masks its known `/config/.nas-file-center-trash` alias
   read-only in the API as well as the canonical quarantine path. Other nested
   bind/symlink/hard-link layouts require their own verified isolation; an arbitrary
   external quarantine source is not covered by that one mask. Cross-storage
   overlays keep `HOST_QUARANTINE_DIR` as the parent of `.nas-file-center-trash`
   and replace the same leaf mount, rather than shadowing an inherited leaf with
   a different parent bind. No stored quarantine paths are rebased.

   ```bash
   set -euo pipefail
   NFC_CONFIG_HOST="/absolute/host/path/to/current-config"
   NFC_CONFIG_BACKUP="/absolute/host/path/to/new-backup/config-before-candidate.tar"
   NFC_CANDIDATE_CONFIG_HOST="/absolute/host/path/to/new-candidate-config"

   # The backup parent already exists; the archive and candidate must be new.
   (umask 077; set -o noclobber
    tar --acls --xattrs --xattrs-include='*' --numeric-owner \
      -C "$NFC_CONFIG_HOST" -cpf - . > "$NFC_CONFIG_BACKUP")
   sync -f "$NFC_CONFIG_BACKUP"
   sha256sum "$NFC_CONFIG_BACKUP"
   tar -tf "$NFC_CONFIG_BACKUP" > /dev/null
   mkdir -m 0700 -- "$NFC_CANDIDATE_CONFIG_HOST"
   tar --acls --xattrs --xattrs-include='*' --numeric-owner --same-owner \
     -xpf "$NFC_CONFIG_BACKUP" \
     -C "$NFC_CANDIDATE_CONFIG_HOST"
   ```

3. Check the extracted database while respecting its WAL; do not use
   `immutable=1` or separate the database from its copied sidecars. Require
   `integrity_check` to return only `ok` and no foreign-key violations:

   ```bash
   python3 - "$NFC_CANDIDATE_CONFIG_HOST/app.db" <<'PY'
   from pathlib import Path
   import sqlite3, sys
   uri = Path(sys.argv[1]).resolve(strict=True).as_uri() + "?mode=ro"
   with sqlite3.connect(uri, uri=True) as db:
       assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
       assert db.execute("PRAGMA foreign_key_check").fetchall() == []
   print("CANDIDATE_DATABASE_INTEGRITY_OK")
   PY
   ```

4. Review an explicit permission conversion for the **candidate copy only**.
   Shared config directories require the trusted GID and setgid/group access;
   DB/WAL/SHM/init-lock files require `0660`. Shared review artifacts use `0640`,
   while Worker-private progress journals/receipts and the media stage retain
   their private contracts. Do not recursively chmod/chown the tree or manufacture
   missing evidence. Run the Step 0 preflight against the candidate config and
   actual data bind source. A metadata pass is necessary but does not validate
   every old report, container mapping or secret-volume handoff.
5. Point only the candidate deployment at the candidate config. Validate its
   resolved model:

   ```bash
   NFC_CANDIDATE_COMPOSE="/absolute/path/to/reviewed-candidate-compose.yaml"
   docker compose -f "$NFC_CANDIDATE_COMPOSE" config -q
   ```

   Keep both organizer gates false; initial deployment checks also keep media
   mounts read-only and mutation/delete disabled. Keep the Worker stopped while
   reviewing copied queued jobs and schedules. Keep candidate startup, tests
   and conversion within the reviewed maintenance/test scope. Old
   completed shared-mode jobs lacking the checkpoint digests described in
   [the execution gate](media-organizer-v16-execution-gate.md#shared-review-compatibility)
   remain blocked; permission repair alone cannot make them trustworthy.
   Verify the effective shared-secret volume selected by both services, not an
   unused definition in the YAML. A new isolated candidate volume must match the
   configured API UID/shared GID and `2770` root contract; the legacy root-owned
   `0700` channel is not compatible. Changing `driver_opts` in a file does not
   prove the existing engine volume changed. Do not remove active production
   secrets or attach the candidate to the production password channel.
6. For rollback **before media changes**, stop the candidate Worker and API,
   retain the candidate config for diagnosis, and restore the saved old image
   digest plus the untouched original config binding. Validate that resolved
   model before restarting the old API/Worker. If restoration from the archive
   is needed, extract into a new empty restore directory with the same preservation
   options, check database integrity, then bind that entire tree. Never overwrite
   an active database or mix an older DB with newer WAL/SHM. If any media mutation
   occurred, a config rollback cannot undo it: preserve the matching evidence
   and use reviewed task-specific recovery before switching authority.

## Fresh installation without legacy-data migration

The owner may choose a **fresh V1.6 installation** instead of copying the
1.4.6 configuration/database. In this mode:

- Keep the existing 1.4.6 containers, config tree, database, volumes and proxy
  deployment unchanged. Do not stop them for a database migration because no
  legacy state is imported.
- Create a new, sibling NVMe config directory and a separate disposable data
  root. The new config must be provisioned specifically for API UID 10001,
  Worker UID 10002 and shared GID 10000; never recursively alter the old config.
- Use `compose.komodo.v16-fresh-install.yaml` with distinct container names,
  project/network and tmpfs secret volume. It has no attachment to the old
  `nginx_network`, publishes no host port, and initially mounts the candidate
  data root read-only in both services. Inspect initial health using
  `docker exec`; arrange browser/proxy access separately.
- The candidate database and administrator account start empty. Old task
  history, users, reports, schedules, quarantine records and recovery evidence
  are intentionally not imported.
- Keep `ALLOW_MUTATION`, `ALLOW_DELETE`, organizer execution and namespace
  quiescence flags false. The candidate's loopback HTTP cookie setting is for
  isolated local acceptance only; production access requires a separately
  reviewed TLS/proxy configuration.
- GitHub Actions builds the reviewed commit and pushes only
  `kerwinjhc/nas-file-center:v1.6-candidate-<full-commit-sha>`. It verifies a
  fresh non-root API bootstrap and waits for that commit's nine non-release
  workflows before pushing the tested image. The existing main-only stable
  publisher is separate; candidate publication never updates `1.4.6`,
  `1.6.0` or `latest`.
- Set `NFC_V16_IMAGE` to the resulting `repository@sha256:...` registry digest
  from the publication evidence. Komodo pulls this image; the fresh-install
  template has no build section, and no NAS compilation is needed.
- Fresh installation does not waive the independent same-mount acceptance,
  exclusive namespace custody, API mutation-boundary audit or non-author
  security sign-off. The candidate Worker must not receive a writable
  production media mount. A separate owner-approved disposable SATA scope is
  required before any media write test.

The fresh-install Compose model is validated in CI using temporary directories;
that validation does not create NAS directories or prove NAS/FUSE UID/GID
semantics. First provision and verify only the new config directory. If
`chown`, setgid, ACL or non-root access is unsupported by the NAS filesystem,
stop and do not fall back to root or broaden permissions.

## Required host layout

The owner-created root must already exist and contain exactly these two child directories:

```text
<your SATA root>/
└── nas-file-center-v1.6-acceptance/
    ├── nfc-organizer-c5-acceptance/
    └── nfc-scheduler-s5-acceptance/
```

The directories must be real directories, not symlinks. The scheduler child must remain empty. The organizer child may contain only previous `.nfc-v16-run-*` evidence directories.

**Never point this test at the production media root.**

## What the Compose task can touch

The acceptance container receives these two writable binds:

```text
HOST: <your SATA>/nas-file-center-v1.6-acceptance
  -> CONTAINER: /nas/v16-acceptance
HOST: <your approved evidence directory>
  -> CONTAINER: /evidence
```

It does **not** mount the production `/data` root, the application config directory, the quarantine directory, or the rest of the SATA tree.

The first bind permits disposable filesystem tests; the second stores their
JSON report. Both must be writable by the image's effective non-root UID
(`10001:10000` in the current Dockerfile), with ownership/ACLs reviewed in
advance. The wrapper does not repair permissions. The script bind is read-only.

The container also runs with `network_mode: none` and `no-new-privileges`.

## Run the limited primitive harness after separate approval

From the repository checkout on the NAS, on the exact candidate commit:

```bash
export V16_ACCEPTANCE_HOST_ROOT="/absolute/path/to/nas-file-center-v1.6-acceptance"
export V16_EVIDENCE_HOST_DIR="./v16-nas-evidence"
export CANDIDATE_SHA="$(git rev-parse HEAD)"

bash scripts/run_v16_real_nas_acceptance.sh
```

The wrapper first validates the two existing child directories, their names, symlink status, device identity, and reserved scheduler root. It refuses to create or clean the acceptance root.

Before the one-shot run, it also executes:

```bash
docker compose -f compose.v16-real-nas-acceptance.yaml config -q
```

so the resolved Compose model is checked before the container starts.
`config -q` validates the resolved model without starting services; it does
not test host permissions or grant execution approval.

The actual execution is:

```bash
docker compose -f compose.v16-real-nas-acceptance.yaml \
  run --rm --build v16-real-nas-acceptance
```

`--rm` removes the temporary container after it exits. Fixture and report
files remain on the two host binds.

## Primitive harness result

A successful run must report:

```text
PASS_FLAT_AND_GROUP_HOLD
```

and prove:

- actual SATA/filesystem capability probe passed;
- no-replace publication primitives are usable;
- pure-image flat publication preserves SHA-256 across original/stage/public paths;
- original/stage/public paths share the frozen inode identity;
- the second preview is blocked with zero needed moves until deferred cleanup is explicitly completed;
- mixed P/V publication is rejected before public group promotion;
- original mixed-media fixtures remain byte-exact;
- no public P/V group is created;
- grouped publication remains explicitly unauthorized.

The acceptance script deliberately retains its uniquely named evidence directory for manual inspection. It does not delete test artifacts automatically.

## After the run

The generated evidence is kept in:

```text
nfc-organizer-c5-acceptance/
└── .nfc-v16-run-<candidate>-<random>/
    ├── acceptance.json
    ├── private/
    └── ...
```

and the host-side report is written under `v16-nas-evidence/`.

Review the report and logs, then remove the entire `nas-file-center-v1.6-acceptance` directory when you are satisfied. Do not use broad Docker/host cleanup commands such as `docker system prune` or filesystem-wide delete commands for this acceptance.

## Important release limitation

This gate is **not** evidence that grouped P/V publication is ready. The current safety contract intentionally keeps grouped publication disabled. It validates the real filesystem primitives and proves that mixed P/V publication fails closed.

V1.6 release remains blocked pending the final candidate CI/review gates,
actual host identity/ACL/custody evidence, approved config migration/rollback,
and a separately approved disposable end-to-end run covering grouped/retained
layouts, explicit cleanup, interrupted recovery and a zero-change final scan.
`PASS_FLAT_AND_GROUP_HOLD` alone satisfies none of those additional gates.


## Owner-authorized first SATA primitive acceptance (published image)

For candidate `a812a48ead1c513bd1a4692280d28cebd51bf90a`, the NAS acceptance
Compose task reuses the exact GitHub-built and Docker-Hub-published image digest
`kerwinjhc/nas-file-center@sha256:c5ceaf32813ddc1b3955b661c91c9ca923040ec34d58961003d47e17642d0d32`.
The NAS wrapper runs `docker compose pull` followed by `docker compose run --rm`;
it has no build stanza and never invokes `--build`. The container runs as the
image's non-root default UID 10001:GID 10000, with a read-only root filesystem
and no network. Only the explicitly supplied disposable SATA acceptance root
and a separately provisioned evidence directory are writable binds. The test
creates a uniquely named evidence run under the organizer child and retains it
for manual review. The filesystem capability probe uses private random scratch
under the authorized acceptance root and removes only entries whose exact
inode identities it created; any unknown residue blocks and is retained.

The required SATA directory tree must be created by the owner in advance, with
the root and organizer child writable by UID 10001:GID 10000. The scheduler
child must remain empty. The evidence directory may be a separate temporary
NVMe or tmpfs directory, also writable by UID 10001:GID 10000. The wrapper
refuses missing paths and does not create/chown/chmod them. The first-round
harness only tests actual-mount primitives, flat synthetic publication and
SEC-12 mixed-group refusal. It deliberately retains its run evidence and does
not exercise Worker cleanup, finalization, grouped publication or a true
zero-change second scan.
