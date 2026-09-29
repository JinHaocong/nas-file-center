# Real NAS acceptance entry

Status: **ENTRY READY IN SOURCE; ACTUAL NAS RUNNER / EVIDENCE STILL REQUIRED**

This repository has two closure gates that cannot be satisfied by GitHub-hosted runners:

- Organizer Advanced Rules C5;
- Scheduler S5.

Both require their existing acceptance harness to execute against an **actual target NAS filesystem** while using only fresh synthetic fixtures. Production NAS data must never be used.

## Workflow

Use `.github/workflows/real-nas-acceptance.yml` only after a repository self-hosted runner is registered on the target NAS, or on a host that mounts the exact target NAS filesystem being accepted.

The runner must carry all of these labels:

```text
self-hosted
linux
x64
nas-file-center-acceptance
```

The custom `nas-file-center-acceptance` label is a hard separation boundary. GitHub-hosted runners cannot satisfy this workflow.

## Required isolated roots

Create two **already-existing, empty, non-symlink** directories on the actual NAS filesystem:

```text
.../nfc-organizer-c5-acceptance
.../nfc-scheduler-s5-acceptance
```

Never point either input at a media library, downloads directory, production Organizer root, application config directory, quarantine directory, backup directory, or any directory containing user data.

The underlying harnesses create only owned synthetic children inside those roots and require the roots to be empty again after completion.

## Dispatch inputs

From **Actions → Real NAS Acceptance → Run workflow**, provide:

- `candidate_sha`: the exact merged `main` commit being accepted;
- `organizer_root`: the absolute real-NAS path ending in `nfc-organizer-c5-acceptance`;
- `scheduler_root`: the absolute real-NAS path ending in `nfc-scheduler-s5-acceptance`;
- `confirmation`: exactly `I_UNDERSTAND_REAL_NAS_ISOLATED_SYNTHETIC_ONLY`.

The workflow checks out exactly `candidate_sha`, builds that exact linux/amd64 Docker candidate, and refuses non-empty, symlinked, wrongly named, or non-absolute test roots.

## Acceptance performed

The workflow runs:

1. Organizer C5 full staged synthetic fixture on the actual NAS filesystem;
2. Scheduler S5 scheduled index + fclones scan synthetic fixture on the actual NAS filesystem;
3. zero-residue checks for both roots;
4. evidence binding to the exact candidate SHA where supported by the harness;
5. artifact upload containing runner identity, observed filesystem type, Docker version/build evidence, logs, and JSON acceptance evidence.

Passing this workflow is evidence collection, not an automatic roadmap state mutation. After a successful run, the observed artifact data must be reviewed and committed into the Organizer C5 and Scheduler S5 closure records before either gate is marked CLOSED.

Until a labeled self-hosted NAS runner actually completes this workflow successfully, repository CI/synthetic evidence must not be described as real-NAS acceptance.
