# v0.3.6 Gate6-A2 — Safe Permanent Purge Architecture Freeze

**Date:** 2026-09-15
**Status:** FROZEN — implementation must not deviate without an explicit architecture amendment
**Branch:** `feature/v0.3.6-gate6a2-unlink-purge`
**Baseline:** `main@4abd312086c7ef0f363a4da4d13b51cb470d8cba`
**Design:** `docs/superpowers/specs/2026-09-15-gate6a2-unlink-purge-design.md`
**Plan:** `docs/superpowers/plans/2026-09-15-gate6a2-unlink-purge.md`

## Frozen product semantics

Single **Clear** and bulk **Permanent Clear** use normal filesystem permanent-delete semantics comparable to a NAS file manager deleting a selected file without sending it to a recycle bin.

The destructive primitive is pathname-scoped unlink of NFC-owned quarantine paths. It is **not** secure erase.

For every selected NFC-owned path:

1. prove that the exact pathname is owned by the selected `QuarantineEntry`;
2. freeze the exact pathname and identity authority;
3. revalidate that authority immediately before mutation;
4. unlink only that exact NFC-owned pathname;
5. never modify inode payload contents.

If the removed pathname is the last filesystem link, the filesystem may naturally reclaim the inode/data blocks. If another hard link exists, that other path remains byte-for-byte intact and continues to reference the same inode.

The implementation and UI must never claim that physical bytes were securely erased or globally destroyed.

## Frozen operation identities

The new operation identity is exactly:

`quarantine_unlink_purge`

The historical operation identity:

`quarantine_purge`

remains permanently fail-closed with the existing unsupported/EOPNOTSUPP contract. Historical, stale, or handcrafted `quarantine_purge` plans must never be routed to the new unlink implementation.

## Frozen deletion authority

Deletion authority is **pathname-scoped NFC ownership**, never inode-global ownership.

The new unlink manifest may contain only paths owned by the selected entry. A path must never enter mutation authority merely because it has the same `(device, inode)`.

Consequences:

- no `ftruncate`;
- no zero-fill or overwrite;
- no secure-erase primitive;
- no `st_nlink`-based safety inference;
- no inode search followed by deletion;
- no deletion of survivor-scan results;
- no deletion of paths owned by another quarantine entry;
- no recursive widening of authority.

Existing Gate6-A topology helpers may be reused only for read-only facts that remain valid under this rule. Any helper that enumerates cross-entry same-inode aliases must not become unlink authority.

## Frozen Preview digest rule

The destructive Preview/Draft/Freeze authority digest binds only mutation authority and selected-entry identity, including at minimum:

- canonical selected entry IDs;
- persisted `QuarantineEntry` identity required by Gate6-A2;
- `purge_semantics = "unlink_v1"`;
- exact canonical NFC-owned unlink manifest.

Hard-link survivor lists and same-content independent-copy lists are **advisory** and are not mutation authority. They are therefore **not included in the destructive authority digest**.

An advisory survivor appearing, disappearing, or becoming stale must not by itself invalidate otherwise-safe pathname unlink authority.

## Frozen advisory timing and scope

Hard-link survivor discovery is restricted to **currently indexed directories**:

`IndexedPath candidate lookup by (device, inode)`
`→ live lstat of candidates`
`→ verify regular file + exact live (device, inode)`
`→ report only verified survivors`

Database rows alone are never sufficient proof.

Preview may show advisory evidence as-of Preview time. After successful unlink mutation, the final single/bulk result must perform a fresh advisory query so the user sees post-delete indexed-scope evidence.

Final survivor status is scoped and must be one of the semantic equivalents of:

- `verified_found` — one or more live same-inode paths found in indexed scope;
- `verified_none` — no live same-inode paths found in indexed scope;
- `incomplete` — indexed-scope verification could not be completed truthfully.

`verified_none` is never a claim that no hard link exists outside currently indexed directories.

Same-content independent copies use matching content hash with different `(device, inode)` and are displayed separately. They are informational only and never mutation authority.

## Frozen crash / restart semantics

Before the first unlink, persist enough irreversible intent and exact manifest authority to recover safely after a crash.

A frozen owned pathname that is unexpectedly missing before any durable unlink-intent/progress record exists is a conflict, not success.

After durable intent/progress proves that an exact frozen pathname was authorized and its unlink was started/completed, its absence during restart reconciliation may be treated idempotently only for that exact pathname. Recovery must never add new pathname authority.

Recovery dispatch must preserve operation identity. A Gate6-A2 `quarantine_unlink_purge` recovery path must never fall through to the historical `quarantine_purge` / `ftruncate` core.

## Frozen safety gates

Both single and bulk permanent clear retain:

- admin-only authority;
- `ALLOW_MUTATION=true`;
- `ALLOW_DELETE=true`;
- explicit confirmation;
- PathGuard / descriptor-safe parent handling;
- symlink rejection;
- frozen pathname identity;
- ABA protection;
- Preview → Draft → Freeze → Validate → Execute for bulk;
- worker lease fencing where worker execution is involved;
- truthful audit/result records;
- crash/restart idempotency.

## TDD / release gate

No production implementation code is allowed before a corresponding RED test has been observed failing for the intended missing behavior.

Gate6-A2 cannot close on CI alone. Required closure sequence remains:

Strict TDD → focused regression → full regression → frontend tests/typecheck/build → source diff review → independent exact-candidate review → linux/amd64 artifact → isolated real-zfuse NAS acceptance → separately authorized production deployment.

No production NAS mutation or redeploy is authorized by this freeze document.
