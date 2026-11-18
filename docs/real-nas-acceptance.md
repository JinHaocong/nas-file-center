# V1.6 real NAS acceptance

Status: **RELEASE BLOCKED — HOST EVIDENCE AND SEPARATE APPROVAL REQUIRED**

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
`/proc/self/mountinfo`. It never lists or opens files below the SATA media
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
   image digest, with distinct project/container names if needed. Preserve the
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
6. For rollback **before media changes**, stop the candidate Worker and API,
   retain the candidate config for diagnosis, and restore the saved old image
   digest plus the untouched original config binding. Validate that resolved
   model before restarting the old API/Worker. If restoration from the archive
   is needed, extract into a new empty restore directory with the same preservation
   options, check database integrity, then bind that entire tree. Never overwrite
   an active database or mix an older DB with newer WAL/SHM. If any media mutation
   occurred, a config rollback cannot undo it: preserve the matching evidence
   and use reviewed task-specific recovery before switching authority.

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
