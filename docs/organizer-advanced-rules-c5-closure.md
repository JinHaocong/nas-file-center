# Organizer Advanced Rules — C5 Closure Record

Status: **C5 CURRENT — REPOSITORY CLOSURE / REAL-NAS ACCEPTANCE PENDING**
Product baseline: **v0.4.7**
C4 integrated baseline: `main@00a0ddb7db115f4299ae3f38643dac1be569ac84`
Architecture authority: [`organizer-advanced-rules-architecture-freeze.md`](organizer-advanced-rules-architecture-freeze.md)

## 1. Closure boundary

C5 closes Organizer Advanced Rules only when all frozen C0 acceptance conditions are proven:

1. full backend regression passes;
2. full frontend tests, TypeScript typecheck and production build pass;
3. linux/amd64 Docker candidate builds successfully;
4. the isolated Organizer C5 acceptance harness passes on the actual target NAS filesystem;
5. the NAS project test root is empty after the run;
6. no C5 change expands product mutation authority;
7. the final evidence is bound to the exact candidate commit.

Repository CI can prove items 1–3, 5 in the synthetic runner harness, and 6.
It **cannot** prove item 4 unless the actual NAS filesystem is mounted or the harness is run on that NAS. GitHub-hosted runner evidence must not be relabeled as real-NAS evidence.

## 2. C5 acceptance harness

The authoritative harness is:

```text
scripts/organizer_advanced_c5_acceptance.py
```

Safety properties:

- requires an already-created, empty directory whose basename is exactly
  `nfc-organizer-c5-acceptance`;
- requires explicit `--confirm-synthetic-only YES`;
- creates one unique `.nfc-organizer-c5-*` child and does not use sibling
  paths as scratch space;
- configures `allow_mutation=true` only for the synthetic fixture and keeps
  `allow_delete=false`;
- uses the real Organizer API, BatchPlan lifecycle and worker path;
- does not monkeypatch the filesystem capability probe;
- refuses a non-empty or incorrectly named test root;
- never treats GitHub runner filesystem behavior as evidence for the target NAS;
- removes only its unique owned run directory and verifies the project test root
  is empty afterward.

The harness exercises the complete V1 staged lifecycle:

```text
read-only Advanced Preview
→ Stage A structural Draft
→ Freeze
→ Validate
→ Execute
→ exact MOVE → rmdir_empty completion
→ old Stage A preview digest rejected with zero new Draft
→ fresh Preview
→ Stage B rename Draft
→ Freeze
→ Validate
→ Execute
→ final numbered files
→ zero test residue
```

The fixture also verifies that file bytes survive both stages and that
`allow_delete=false` remains in force.

## 3. Repository closure workflow

`.github/workflows/organizer-advanced-c5-closure.yml` records:

- exact candidate identity and merge-base against the C4 integrated baseline;
- focused `tests/test_organizer_advanced_rules_*.py` regression;
- standalone synthetic execution of the C5 acceptance harness;
- full backend regression;
- frontend tests;
- frontend TypeScript typecheck;
- frontend production build;
- scope review proving C5 changed no `app/**` product mutation code relative to
  C4;
- linux/amd64 Docker build and runtime Organizer compiler import;
- retained CI evidence artifacts.

Release Validation remains an independent second full-regression/Docker gate.

## 4. Real-NAS execution procedure

Create a dedicated empty test directory on the NAS. Do not point this command at
a media library, download directory, production Organizer root, quarantine root
or any directory containing user data.

Example, with the real dedicated path substituted:

```bash
mkdir /path/to/project-test-area/nfc-organizer-c5-acceptance

python scripts/organizer_advanced_c5_acceptance.py \
  --project-test-root /path/to/project-test-area/nfc-organizer-c5-acceptance \
  --confirm-synthetic-only YES \
  --evidence-json /safe/evidence/location/organizer-c5-real-nas.json
```

The run is accepted only when all of the following are true:

- process exit code is `0`;
- output includes `C5_ACCEPTANCE_RESULT=PASS`;
- evidence reports `result: PASS`;
- evidence reports `zero_residue: true`;
- Stage A operations are exactly `["move", "rmdir_empty"]`;
- the old Stage A preview digest is rejected after Stage A completes;
- Stage B operations are the expected rename set;
- Stage A and Stage B preview digests differ;
- final file bytes and names match the fixture assertions;
- `nfc-organizer-c5-acceptance` is empty after the run.

If filesystem capability probing reports unsupported behavior, the acceptance
result is **FAIL**, not a waiver. C3 remains fail-closed on that filesystem.

## 5. Evidence record

The final real-NAS evidence must record, without guessing:

```text
CANDIDATE_GIT_SHA:
TARGET_NAS_MODEL:
TARGET_NAS_OS:
TARGET_NAS_ARCH:
TARGET_FILESYSTEM:
DOCKER_VERSION:

FOCUSED_ORGANIZER_REGRESSION:
FULL_BACKEND_REGRESSION:
FRONTEND_TESTS:
FRONTEND_TYPECHECK:
FRONTEND_BUILD:
LINUX_AMD64_DOCKER:
SYNTHETIC_C5_ACCEPTANCE:

REAL_NAS_C5_ACCEPTANCE:
REAL_NAS_STAGE_A_OPERATIONS:
REAL_NAS_STAGE_A_STATUS:
REAL_NAS_OLD_PREVIEW_REJECTED:
REAL_NAS_STAGE_B_OPERATIONS:
REAL_NAS_STAGE_B_STATUS:
REAL_NAS_ZERO_RESIDUE:

MUTATION_AUTHORITY_DIFF:
KNOWN_LIMITATIONS:
FINAL_C5_VERDICT:
```

Historical Gate5-G NAS evidence must not be copied forward as current C5
evidence. The filesystem, NAS software and candidate commit must be observed for
this C5 run.

## 6. Current verdict

C0–C4 are closed.

C5 remains **CURRENT** until the exact merged candidate is run on the actual NAS
under the isolated project test root and zero-residue evidence is captured.
Repository CI success alone is necessary but not sufficient to mark Organizer
Advanced Rules fully closed.

## 7. Protected real-NAS entry

The shared manual acceptance entry is `.github/workflows/real-nas-acceptance.yml`.
It can run only on a self-hosted Linux x64 runner carrying the custom
`nas-file-center-acceptance` label. The procedure and safety boundary are
recorded in [`real-nas-acceptance.md`](real-nas-acceptance.md).

This entry does not itself close C5. C5 remains CURRENT until the workflow is
actually executed on the target NAS filesystem, passes with zero residue, and
the observed evidence is committed into this closure record.
