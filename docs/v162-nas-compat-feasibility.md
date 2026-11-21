# V1.6.2 — Simple NAS Root Worker compatibility mode

**Owner decision: 2026-11-22.** The owner accepted the simpler two-container
profile to avoid whole-tree ACL migration and per-directory authorization.

## Intended experience

Open the web UI → select a directory under \`/data\` → read-only preview →
explicit confirmation → organize files. No SSH ACL migration and no third
container.

Existing organizer rules remain unchanged: recursive selection, per-directory
P/V groups, collision-safe names, and skip already-homogeneous directories.

## Deployment model

| Component | Ordinary mode | NAS compatibility mode |
|---|---|---|
| API UID | 10001 | 10001 |
| API \`/data\` | read-only | read-only |
| API capabilities | none | none |
| Worker UID:GID | 10002:10000 | **0:10000** |
| Worker capabilities | none | **DAC_OVERRIDE only** |
| Containers | 2 | 2 |

Worker compatibility is explicitly opt-in:
\`NFC_NAS_COMPAT_ROOT_WORKER_ENABLED=false\` by default. When enabled, Worker
startup requires:

- real/effective/saved UID exactly 0;
- real/effective/saved GID exactly 10000, with no supplementary groups other than the configured GID 10000;
- \`NFC_SHARED_CONFIG_GID=10000\`;
- only \`CAP_DAC_OVERRIDE\` in permitted/effective/bounding sets;
- empty inheritable and ambient capability sets;
- \`no-new-privileges:true\`;
- \`MEDIA_ORGANIZER_EXECUTION_MODE=maintenance_window\`.

The Worker runs its normal \`python -m app.worker\` entry point. There is no
root-to-non-root launcher, ambient capability handoff, per-WorkJob capset
switching, privileged container, Docker socket, SETUID/SETGID or CHOWN
capability. The API never enables the root Worker flag.

**Intentional trade-off:** DAC_OVERRIDE is available to the whole Worker
process and therefore to all WorkJobs handled by that Worker, not only the
media organizer. The API remains non-root and media-read-only. The Worker
container's root filesystem stays read-only; only its declared bind mounts
are writable.

## Operational constraint

This mode is simpler, not isolated from other root-capable NAS applications.
The NAS has other root-capable writers. During an organizing job, those
programs must not modify the selected directory. The existing maintenance
confirmation and NFC Worker lease coordinate NFC jobs, but they do not lock
OpenList/Rclone/SMB or other external writers. Do not run concurrent changes
against the same selected folder.

Existing files retain their ownership when moved. Newly created P/V directories
are created by the Worker as \`root:10000\`; their final mode is determined by
the existing publication logic. This mode does not recursively chown/chmod
the media tree.

## Validation

- \`scripts/probe_nas_compat_capability.sh\` compares UID 10002 with the direct
  UID 0:GID 10000 + DAC_OVERRIDE profile using a new CI temporary directory.
  It verifies CapEff/CapPrm/CapBnd, NoNewPrivs and actual read/write behavior.
- \`compose.v162-nas-compat-scratch.yaml\` checks the two-container topology.
  It requires new scratch config/data roots and keeps
  \`ALLOW_MUTATION=false\`, \`ALLOW_DELETE=false\` and
  \`MEDIA_ORGANIZER_EXECUTION_ENABLED=false\` in both services.
- Neither test starts a container against the NAS or changes production
  Compose, ACLs, app.db, backups, progress DB or media.

## Still required before release

The simpler Worker profile addresses the UID/DAC mismatch only. It does not
automatically close the existing source-name race findings #399/#401/#402,
the finalization workflow #400, or the independent security review #398.
The current code still depends on the explicit maintenance-window assumption
for concurrent-writer exclusion. The exact profile must also pass a separately
owner-approved disposable directory on the same ZOS/zfuse mount. Only then
can Release Validation and independent review approve a production overlay.

**Current state:** development branch only; PR #406 remains Draft. No production
image, Komodo update, NAS write, ACL migration or real-media test is authorized
by this document.


## One-shot ZOS/zfuse same-mount lifecycle acceptance (prepared, not executed)

The existing durable full-lifecycle driver
\`scripts/v16_nas_maintenance_acceptance.py\` now accepts
\`--nas-root-worker\` for the owner-approved **disposable** NAS test.
It retains the original non-root mode when the flag is omitted. The root
mode creates a fresh randomly named fixture beneath one existing explicitly
approved scratch parent, mounts only that fixture's fresh \`data\` and
\`config\` children into two no-network temporary containers, and requires
an immutable candidate Docker image ID/revision. API stays UID 10001,
\`/data:ro\`, no caps; Worker uses UID 0:GID 10000 plus only DAC_OVERRIDE.

The tool exercises the real API, synthetic P/V grouping, real WorkJob
execution, interrupted publication recovery, explicitly confirmed cleanup,
cleanup recovery, and a zero-change second preview. It retains the
\`acceptance-report.json\` and fixture evidence for review; do not
automatically delete the fixture or manually remove unknown leftovers.
The existing script confirms container identity before force-removing
only its own test containers.

**Requires a separately agreed existing scratch parent on the same ZOS mount,
a locally loaded exact-commit candidate Docker image, a stopped external
writer window and explicit permission to write scratch files.** Not a
generic command to run against original media. A pass is an NAS scratch
compatibility observation, not proof against hostile concurrent writers.

Illustrative *after explicit approval* (placeholders are not executable):

\`\`\`bash
sudo python3 scripts/v16_nas_maintenance_acceptance.py \
  --data-root "/approved/existing/disposable-scratch-parent" \
  --image "sha256:<immutable-built-candidate-image-id>" \
  --candidate-sha "<exact-40-char-PR-commit>" \
  --nas-root-worker
\`\`\`

No task has been started against the owner's NAS or current Komodo stack.
