# Storage Optimization H4 — Frontend / Closure Contract

Status: **H4 CURRENT — PR #114 CANDIDATE; FINAL EXACT-HEAD CI REQUIRED**
Product baseline: **v0.4.7**
Architecture authority: [storage-optimization-h0-architecture-freeze.md](storage-optimization-h0-architecture-freeze.md)

## 1. Merged prerequisite authority

The Hardlink / Reflink track is cumulative:

| Stage | PR | Final source authority |
| --- | --- | --- |
| H0 Architecture Freeze | #107 | head `56fb090fc9a292fd715538207d45a18f2ddb5a9b`, merge `bfe22896e7126d59123890c295195d097b7e5432` |
| H1 Runtime Capability | #108 | head `b065fe9244af68b2484f1489891d058de14ecff6`, merge `9cde82240a1608aeb06b1462e099ee1d010cea92` |
| H2 Dedupe Plan Integration | #109 | head `f4e7c800e6f8c429b39f2c1fc106b99752214605`, merge `9c96c6cebfd8e3aa76e6fe8212e41b51cc67919c` |
| H3 Worker Execution / Recovery | #110 | head `83fdc2c1468523ea9b996fdad20b00a4c44cb0a2`, merge `ad18d7858275991b1b7e8b58e8291a707a993272` |

PR #113 is an independent UI-only global Ant Design pagination spacing fix and
does not change filesystem mutation authority.

## 2. H4 frontend contract

Advanced Dedupe exposes exactly three storage actions:

```text
quarantine   # default
hardlink     # explicit opt-in
reflink      # explicit opt-in
```

Changing the selected action invalidates the accepted Preview exactly like a
scorer-config change. Preview and Generate both submit the same
`storage_action`, and Generate remains bound to `expected_preview_digest`.

The UI must render backend decisions truthfully:

```text
KEEP
QUARANTINE
HARDLINK
REFLINK
SKIPPED / SAFETY_EXCLUDED
```

Metadata eligibility is read-only Preview evidence. A blocked optimization row
must surface its backend `storage_blocking_reason`; the frontend must not
invent capability support.

## 3. Required user-facing semantics

Hardlink warning:

> Hardlink 后两个路径共享同一个 inode，未来通过任一路径写入都会修改同一份文件内容。

Reflink wording:

> Reflink 会创建独立 inode，并使用 Copy-on-Write（写时复制）；它不是普通完整复制。

These meanings are also repeated on the generated Plan detail surface.

## 4. Capability diagnostics boundary

Capability probing remains a separate explicit administrator action.

The H4 diagnostic:

1. requires an accepted Preview for the currently selected optimization action;
2. chooses an actual duplicate KEEP / SOURCE pair from that Preview;
3. probes the actual `KEEP-parent → SOURCE-parent` route;
4. calls the existing H1 admin-only
   `POST /api/storage-optimization/capabilities` endpoint;
5. never runs implicitly during Preview or Generate;
6. remains gated by backend `ALLOW_MUTATION=true`;
7. never upgrades a prior probe result into Execute authority.

Validate and Worker Execute must still re-check live capability, full SHA-256,
SOURCE/KEEP identity, stale/ABA state, symlink/path authority, transaction
state, and Worker lease fencing.

## 5. Mutation authority remains unchanged

H4 adds no filesystem executor and no synchronous optimization path.

The only mutation chain remains:

```text
Preview
→ Draft Plan
→ Freeze
→ Validate
→ Worker Execute
→ Audit
```

Hardlink / Reflink do not bypass PathGuard, allowed roots, no-clobber
publication, deterministic NFC private transaction paths, durable journal
phases, recovery, or topology fences.

Quarantine behavior remains unchanged and is still the default.

## 6. Required closure evidence

The final H4 PR may merge only when the **final exact PR head SHA** satisfies all
of the following:

- frontend tests: success;
- frontend TypeScript check: success;
- frontend production build: success;
- full backend regression: success;
- storage-optimization H1/H2/H3 regressions: success through the repository
  workflows;
- linux/amd64 Docker jobs: success;
- all other relevant repository workflows/jobs for that exact SHA:
  `completed/success`;
- PR: mergeable;
- merge request: uses `expected_head_sha=<that exact final head>`.

Any head/base change invalidates earlier CI evidence.

## 7. Real filesystem / NAS boundary

Repository CI can close source and Docker behavior but cannot fabricate support
for a specific NAS filesystem.

A real NAS may be described as Hardlink- or Reflink-supported only after the
actual path pair positively passes the runtime capability probe. Real-NAS
acceptance, when performed, must stay isolated from production DATA / CONFIG and
must not be conflated with Organizer C5 or Scheduler S5 acceptance.

No H4 source closure may claim Organizer C5 or Scheduler S5 real-NAS CLOSED.
