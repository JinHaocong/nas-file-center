# V1.6 real NAS acceptance

Status: **READY FOR DIRECT NAS EXECUTION — NO GITHUB SELF-HOSTED RUNNER REQUIRED**

The final V1.6 filesystem gate is intentionally executed **on the NAS itself** as a one-shot Docker Compose task. GitHub Actions remains responsible for repository CI and synthetic tests, but the real-NAS gate does not need to be routed through GitHub Actions.

This avoids installing or maintaining a GitHub Actions runner on the NAS. Docker Compose's `run --rm` mode is appropriate for one-off test/administrative workloads and removes the temporary container after completion. The acceptance service uses a read-only container root filesystem, no network, and only one writable bind mount: the owner-created SATA acceptance root. citeturn202967search0turn118607search0

## Step 0: Zero-mutation NAS host permissions preflight (#403)

Run this **read-only** diagnostic on the NAS host, from a checkout of the
exact Draft PR candidate. It is not the acceptance test and does **not**
start containers, create directories, fix permissions or touch media contents.

Use the existing **host** bind-source paths for `/config` (NVMe) and
`/data` (SATA). They are not the container's `/config` and `/data` paths.

```bash
python3 scripts/v16_nas_readonly_preflight.py \
  --config-dir "/absolute/host/path/to/NasFileCenter" \
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

The acceptance container receives exactly:

```text
HOST: <your SATA>/nas-file-center-v1.6-acceptance
  -> CONTAINER: /nas/v16-acceptance
```

It does **not** mount the production `/data` root, the application config directory, the quarantine directory, or the rest of the SATA tree.

The bind mount is intentionally read-write because the test must exercise real filesystem publication primitives. Docker bind mounts are host filesystem access, so the host path is restricted to the disposable acceptance root and the container filesystem itself is read-only. citeturn707171search3turn118607search0

The container also runs with `network_mode: none` and `no-new-privileges`.

## Run

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

so the resolved Compose model is checked before the container starts. Compose supports required interpolation such as `${VAR:?message}`, and `config -q` validates the resolved model without starting services. citeturn595651search0turn595651search1

The actual execution is:

```bash
docker compose -f compose.v16-real-nas-acceptance.yaml \
  run --rm --build v16-real-nas-acceptance
```

Compose's `run` is a one-off service command and `--rm` removes that temporary container after the command exits. citeturn202967search1

## Acceptance result

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

The V1.6 release therefore remains blocked until the repository CI gates, this direct NAS acceptance, and the final disposable end-to-end dry run are all green.
