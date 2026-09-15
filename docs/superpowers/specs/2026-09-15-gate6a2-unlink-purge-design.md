# v0.3.6 Gate6-A2 — Unlink-Based Permanent Purge Design

**Date:** 2026-09-15  
**Status:** DESIGN APPROVED IN CHAT; IMPLEMENTATION NOT STARTED  
**Branch:** `feature/v0.3.6-gate6a2-unlink-purge`  
**Base:** `main@4abd312086c7ef0f363a4da4d13b51cb470d8cba`

## 0. Roadmap position

This work remains inside **v0.3.6**. It is a Gate6-A follow-up safety/product amendment and is named **Gate6-A2 — Safe Permanent Purge**.

It does **not** start v0.3.7. After Gate6-A2 is closed, development returns to the existing v0.3.6 roadmap order:

1. Gate6-B — Workflow Utility Integration + Recursive Directory Balanced Dedupe
2. Gate6-C — Media Metadata + Integrity
3. Gate6-D — Similarity
4. Gate6-E — Notifications
5. Gate6-F — Advanced Auth
6. Gate6-G / v0.3.6 release closure
7. only then v0.3.7 — Organizer Advanced Rules

The already deployed v0.3.6 production image is not modified in place. Gate6-A2 requires a new exact candidate, review, artifact, and NAS acceptance before any redeploy.

## 1. Goal

Restore a usable single-entry and bulk permanent-clear function with normal filesystem deletion semantics comparable to a NAS file manager's “permanent delete”. The operation removes NAS File Center (NFC)-owned quarantine links/paths with `unlink`-style semantics. It must never zero or overwrite a shared inode payload.

The implementation must also explain what happened after deletion:

- whether NFC-owned quarantine links were removed;
- whether any other hard-link path is still known inside currently indexed directories;
- where those verified indexed hard-link survivors are;
- whether separately stored, same-content copies are known from existing duplicate-scan data.

The survivor/copy information is advisory and must not block an otherwise safe unlink-based purge.

## 2. Non-goals

This design does **not** provide secure erase, block overwrite, cryptographic erasure, or a proof that bytes no longer exist anywhere on the NAS.

It does not scan all of `/data`. Hard-link survivor discovery is limited to directories that are already represented by the current NFC index.

It does not treat `st_nlink` as authority on zfuse.

It does not revive the v0.3.6 `ftruncate(fd, 0)` COMPAT destructive protocol.

## 3. Product semantics

### 3.1 “Clear” means unlink-based permanent removal

Single-entry **Clear** and bulk **Permanent Clear** use the same deletion semantics:

1. validate the selected quarantine entry and its NFC-owned paths;
2. capture a frozen manifest of the exact NFC-owned pathnames that are authorized for this entry;
3. revalidate pathname identity immediately before unlinking;
4. unlink only those NFC-owned pathnames;
5. never modify file contents through the inode;
6. mark the quarantine entry `purged` only after the owned-path cleanup reaches a terminal success state.

If the last filesystem link to the inode is removed and there are no other live references, the filesystem may reclaim the underlying storage. If another hard link exists elsewhere, that other path remains intact and the underlying data remains referenced.

### 3.2 UI wording

The UI must not claim “physical bytes definitely destroyed”. Instead it should report one of the following scoped results:

- **NFC quarantine data cleared; no surviving hard link found in indexed scope.**
- **NFC quarantine data cleared; surviving hard links found in indexed scope.**
- **NFC quarantine data cleared; indexed-scope survivor status could not be fully verified.**

The UI must explicitly label the scope as **currently indexed directories**.

## 4. Safety model

### 4.1 Path authority replaces inode-global destruction

The destructive authority is pathname-scoped, not inode-global.

A purge may unlink only paths that NFC can prove it owns for the selected `QuarantineEntry`. The engine must not use `ftruncate`, payload zeroization, content overwrite, or any primitive whose effect propagates through every hard link to the inode.

### 4.2 Owned-path manifest

Introduce one canonical helper that builds the selected entry's unlink manifest. The manifest contains only allowlisted NFC-owned roles and paths for that entry, such as the current public quarantine view and recognized private transaction artifacts belonging to the same entry/generation.

Unknown files, symlinks, malformed paths, paths outside the quarantine root, paths belonging to another entry, or identity mismatches fail closed for mutation.

Cross-entry aliases are never unlinked merely because they share the same `(device, inode)`.

### 4.3 Identity checks

Before unlinking each path:

- use `lstat`/descriptor-safe path handling;
- reject symlinks;
- require a regular file where a regular payload is expected;
- require the frozen `(device, inode)` identity to still match when applicable;
- require the path to remain inside the expected NFC-owned namespace;
- fail closed on ABA replacement or path mutation.

Missing paths may be treated as idempotently complete only when the operation can prove they were part of the frozen owned-path manifest and prior progress/journal state makes absence expected. Otherwise, absence is a conflict that requires reconciliation.

## 5. Operation versioning and stale-plan safety

Do **not** simply re-enable the old destructive `quarantine_purge` execution path.

Introduce a new operation identity, for example:

`quarantine_unlink_purge`

The old `quarantine_purge` operation remains permanently fail-closed with `EOPNOTSUPP` so stale, handcrafted, or historical Gate6-A/v0.3.6 plans cannot silently acquire new semantics.

Single-entry and bulk purge both route to the new unlink-based engine.

## 6. Single-entry flow

The existing single **Clear** UI remains an admin-only destructive action and continues to require `ALLOW_MUTATION=true` and `ALLOW_DELETE=true`.

After confirmation, the backend uses the same unlink-purge core used by bulk execution. The response returns a structured result including:

- `entry_id`;
- `purged: true/false`;
- number and roles of NFC-owned links removed;
- indexed hard-link survivor verification status;
- verified survivor paths;
- known independent same-content-copy paths, when available;
- an explicit scope label such as `indexed_roots_only`.

## 7. Bulk flow

Bulk purge keeps the existing Preview → Draft → Freeze → Validate → Execute lifecycle.

### Preview

For each selected active entry:

- validate state and NFC-owned path topology;
- build a read-only unlink manifest;
- discover indexed hard-link survivor candidates;
- perform live `lstat` verification only for the candidate paths returned from the index;
- collect same-content-copy information from existing duplicate-scan data as advisory metadata.

External hard-link survivors do **not** make the entry ineligible. They are shown as informational warnings because unlinking NFC-owned paths does not mutate those external files.

### Draft / Freeze

Persist the selected entry identity and exact owned-path manifest into plan metadata. Freeze binds the exact unlink authority and the Preview digest.

### Validate

Immediately before execution, revalidate entry state, manifest paths, pathname identity, and plan freshness. A changed owned path or identity blocks that entry rather than widening authority.

### Execute

Unlink only the frozen, revalidated NFC-owned paths. Never `ftruncate` or overwrite payload bytes.

Execution must be idempotent and journaled so a crash after unlinking some owned paths can resume or reconcile safely without touching unrelated paths.

## 8. Indexed hard-link survivor discovery

`IndexedPath` already contains `absolute_path`, `device`, `inode`, `size`, and `mtime_ns`. Use database lookup by `(device, inode)` to find fast candidate paths within the current index.

For every candidate:

1. exclude NFC quarantine/private paths owned by the selected purge itself;
2. require that the candidate is still under a currently configured indexed root;
3. run live `lstat`;
4. verify regular-file type and exact `(device, inode)`;
5. include only candidates that pass live verification.

Stale index rows are omitted from the verified-survivor list and may contribute to an `incomplete`/`stale_candidates` diagnostic.

The result must be described as **indexed-scope** evidence only. Absence of a verified candidate is not a global proof that no hard link exists outside indexed roots.

## 9. Same-content independent copies

Same-content copies are informational only and are distinct from hard links.

Use existing duplicate-scan data (`DuplicateGroup.content_hash` plus `DuplicateFile` paths/device/inode) when a matching content hash is available. A path with the same content hash but a different `(device, inode)` is an independent same-content copy.

Because duplicate-scan data can be stale, the UI must label these as known copies from the latest available scan/index context. They do not block purge.

## 10. Result model and UI

Each completed purge result should expose a compact summary similar to:

```text
NFC 清除：成功
NFC-owned links removed: 3/3
Hard-link survivors in indexed scope: 1
  /data/archive/photo.jpg
Independent same-content copies known: 2
  /data/backup/photo-copy.jpg
  /data/export/photo.jpg
```

When no indexed hard-link survivor is found:

```text
NFC 清除：成功
索引范围内未发现其他 hard link
```

Do not render this as “physical bytes definitely destroyed”.

Bulk UI must show per-entry results and an aggregate count:

- success;
- blocked/conflict;
- surviving hard link found;
- survivor verification incomplete.

## 11. Audit and observability

Audit events for single and bulk unlink purge must record at minimum:

- operation name/version;
- entry id;
- plan id/item id for bulk;
- Preview digest where applicable;
- frozen owned-path roles;
- successfully unlinked path roles;
- survivor-discovery scope;
- verified indexed survivor paths/count;
- same-content-copy count;
- terminal result/error code.

No audit field should claim global secure erasure.

## 12. Error handling

Fail closed before mutation for:

- entry not active at required stage;
- malformed or out-of-root NFC path;
- symlink where a regular owned payload is expected;
- owned-path identity mismatch;
- ABA replacement;
- path attributed to another quarantine entry;
- unknown object inside a private namespace that would require widening deletion authority;
- stale Preview/Freeze identity.

A failure to query or verify advisory survivor/copy information does **not** widen deletion authority and does not by itself make safe unlink impossible. The purge may complete with survivor status marked `incomplete` if the owned-path mutation path was independently proven safe.

## 13. Required tests

### Backend unit/integration

- single unlink purge removes only selected NFC-owned paths;
- bulk unlink purge removes only selected NFC-owned paths;
- no production path invokes `ftruncate` for the new operation;
- old `quarantine_purge` remains `EOPNOTSUPP`;
- external hard link survives unchanged after purge;
- two quarantine entries sharing one inode cannot cause cross-entry unlink;
- symlink/ABA/path-escape cases fail closed;
- crash after partial owned-path unlink resumes/reconciles idempotently;
- stale index candidate is not reported as a verified survivor;
- live same-inode indexed path is reported correctly;
- same-content/different-inode copy is classified separately;
- survivor lookup failure yields scoped `incomplete` metadata without silently claiming full deletion.

### Frontend

- bulk purge button is enabled only for eligible admin/mutation/delete conditions;
- Preview shows indexed-scope survivor warnings without blocking safe purge;
- single and bulk result views use the same terminology;
- UI never states absolute physical destruction based only on indexed-scope evidence.

### Regression

- existing Bulk Restore behavior remains unchanged;
- Gate6-A stale/handcrafted old purge plans still fail closed;
- `ALLOW_MUTATION`, `ALLOW_DELETE`, and admin authorization remain enforced;
- production Linux/amd64 build and current backend/frontend suites remain green.

## 14. Gate6-A2 closure and acceptance constraints

This is a **v0.3.6 Gate6-A2 behavior change**, not a v0.3.7 feature.

Before production redeployment:

1. write an implementation plan and exact test matrix;
2. implement with strict TDD;
3. run focused tests, full backend regression, frontend typecheck/build, and linux/amd64 Docker build;
4. independently review the exact candidate rather than relying only on green CI;
5. perform isolated NAS acceptance using test data that includes a real hard-link survivor;
6. verify the survivor remains byte-for-byte intact after NFC purge;
7. verify a no-survivor test case removes NFC-owned paths without any `ftruncate`/payload overwrite;
8. only after acceptance, build and deploy the new v0.3.6 production candidate;
9. close Gate6-A2 and continue to Gate6-B.

No implementation or deployment step in this design authorizes direct mutation of the current production NAS before the new candidate passes those gates.
