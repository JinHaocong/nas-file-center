# NAS File Center v0.3.6 — Gate6-A Architecture Freeze
# Quarantine Bulk Restore + COMPAT Transactional Permanent Purge

**Document Version:** 1.0.0  
**Date:** 2026-09-13  
**Status:** APPROVED / ARCHITECTURE FROZEN  
**Baseline Production HEAD:** `8e7e2a669268117c2b7f0c83e14e6e32199fc8ba`  
**Baseline Release:** `v0.3.5.1`  
**Canonical Branch:** `v0.3.6-gate6a-quarantine-bulk-operations`  
**Target Platform:** 极空间 NAS / ZSpace OS / Linux amd64 / Docker / `zfuse.zfsv3`  
**Priority Order:** Data Safety > Correctness > Recoverability > Performance > UI > Features  
**Authority:** User-approved Gate6-A Architecture Freeze  
**Implementation Status:** AUTHORIZED AFTER THIS FREEZE; MUST FOLLOW STRICT TDD  

---

## 1. Scope and Non-Scope

Gate6-A adds two user-facing quarantine capabilities:

1. **Bulk Restore** of selected active quarantine entries.
2. **Bulk Permanent Purge** of selected active quarantine entries, including the `COMPAT_TRANSACTIONAL` zfuse path that Gate5-G intentionally refused.

Gate6-A is NOT a redesign of Gate5-G. All Gate5-G quarantine, restore, authoritative-anchor, write-once generation, worker lease, preserve-first, and fail-closed semantics remain CLOSED and authoritative except for the narrowly scoped permanent-purge authority defined in this document.

Gate6-A does NOT authorize:

- recursive blind deletion of `.tx` namespaces;
- direct API mutation of transactional restore or transactional purge;
- destructive handling of unknown/foreign objects;
- automatic purge of multiple independent active quarantine rows that happen to share a payload;
- database schema migration unless later evidence proves one unavoidable;
- weakening Gate3 physical identity or SHA256 authority;
- permanent deletion outside the explicit user-confirmed purge flow;
- frontend shortcuts that bypass Draft -> Freeze -> Validate -> Execute.

---

## 2. Preserved Safety Chain

All bulk mutations MUST preserve the existing mutation chain:

```text
Read-only Preview
    -> Explicit Generate Draft
    -> Freeze
    -> Validate
    -> Execute (Worker authority)
```

Preview has a strict **zero-mutation contract**. Preview must not create plans, change quarantine rows, hash/write payloads unnecessarily, allocate generations, create directories, or perform filesystem mutations.

Generate Draft does not execute filesystem mutation. Freeze/Validate remain the safety gates before Worker Execute.

---

## 3. Production Evidence that Drives This Freeze

Real-NAS read-only inspection on the production zfuse filesystem established:

- `551` active quarantine entries existed at inspection time.
- `551 / 551` were transactional (`tx_phase='active'`) and had authoritative anchors.
- every authoritative anchor existed;
- every public quarantine view existed;
- every public view resolved to the same `(st_dev, st_ino)` as its authoritative anchor;
- every active entry had exactly two same-inode private paths in its own `.tx/entry-*` namespace: `anchor` and `captured_source`;
- `509` anchors reported `st_nlink == 2` even though three known same-inode pathnames (`anchor`, `captured_source`, public view) were observable;
- `42` anchors reported `st_nlink == 4`;
- each of those `42` active entries had one same-inode historical candidate anchor owned by another quarantine row in `state='conflict'`, `tx_phase='conflict'`, with `authoritative_anchor_path IS NULL` and historical candidate qualification failure.

Therefore the following rule is frozen:

> **`st_nlink` MUST NEVER participate in purge authority, completeness proof, last-link detection, or safe-destruction decisions on the target zfuse filesystem.**

The v0.3.5.1 production finding is also preserved:

> For SHA-backed regular files on this zfuse filesystem, read/hash activity can advance ctime. `ctime` is diagnostic only where read-induced change is possible and MUST NOT become an authoritative purge/restore identity requirement. Authoritative identity remains regular-file type + device + inode + size + mtime + SHA256 plus path/namespace ownership and descriptor-bound safety checks.

---

## 4. Gate6-A1 — Bulk Restore Architecture

### 4.1 Core Rule

Bulk Restore MUST reuse the existing BatchPlan/Worker transactional restore authority. It MUST NOT be implemented as an HTTP/API loop over `restore_quarantine_entry()`.

Transactional restore requires valid Worker authority/lease. Bulk Restore therefore follows:

```text
Select ACTIVE entries
    -> Bulk Preview
    -> Generate BatchPlan Draft
    -> Freeze
    -> Validate
    -> Worker Execute
    -> existing transactional restore core
```

### 4.2 Selection

- Selection contains explicit `entry_ids`.
- Empty selection is invalid.
- Duplicate IDs are invalid; do not silently deduplicate.
- Only `state='active'` entries are eligible.
- Missing/non-active entries fail closed at generation.
- UI filtering does not weaken backend revalidation.

### 4.3 Conflict Policy

Bulk Restore supports only:

- `skip` (default)
- `rename`

Bulk Restore MUST NOT support:

- `manual`
- per-entry `custom_target`

For `rename`, the exact destination is generated during Preview/Generate using the existing deterministic restore rename naming logic and is persisted in the plan item. Execute MUST NOT silently select a different target if the frozen target becomes occupied. Target occupation after Preview is a stale-plan/validation/execution conflict and must preserve no-overwrite semantics.

### 4.4 Plan Item

Recommended representation:

```text
BatchPlan.kind = quarantine-bulk-restore
BatchPlanItem.operation = restore
BatchPlanItem.source_path = quarantine/public source path
BatchPlanItem.target_path = exact frozen restore destination
metadata_json:
  quarantine_entry_id
  conflict_policy
  preview_digest
```

Worker execution reuses the existing `execute_transactional_restore()` path for COMPAT entries.

---

## 5. Gate6-A2 — Narrow COMPAT Permanent Purge Amendment

### 5.1 Relationship to Gate5-G

Gate5-G correctly freezes `ACTIVE_COMPAT` permanent payload deletion as `EOPNOTSUPP` because no destructive authority existed at that gate.

Gate6-A does NOT remove that protection. The existing direct single-entry guard remains authoritative for direct/API purge of transactional entries.

Gate6-A adds exactly one narrow destructive authority:

> **Only an explicitly user-confirmed, Worker-owned, lease-fenced transactional purge engine operating from a frozen validated plan may destroy payload-bearing aliases that it has proven are owned by NAS File Center and belong to the selected authoritative payload.**

No other code path gains permission to unlink transactional payloads.

### 5.2 Meaning of `purged`

For Gate6-A, `state='purged'` means:

> All NAS File Center-owned quarantine references that the engine can prove belong to the selected quarantine payload have been retired and destroyed, and no known NFC-managed restorable payload alias remains.

This state does NOT claim that arbitrary hard links independently created by a user or third-party application outside NFC-managed namespaces have been destroyed. Because `st_nlink` is unreliable on the production zfuse filesystem, Gate6-A MUST NOT claim global inode-link exhaustion.

### 5.3 Cross-Entry Historical Candidate Alias

A historical candidate anchor owned by another quarantine row may be destroyed as part of the selected active entry's purge closure ONLY when ALL conditions hold:

1. pathname is inside a recognized NFC private transaction namespace (`<quarantine_root>/.tx/entry-<id>/attempt-<gen>/...`);
2. owner row exists in DB;
3. owner row is a non-authoritative historical conflict (`state='conflict'`, `tx_phase='conflict'`, `authoritative_anchor_path IS NULL`);
4. the candidate is re-qualified against the selected active authoritative payload using frozen physical/hash identity;
5. no other active/restoring/restored authoritative quarantine row claims the same payload as its own authority;
6. the candidate is captured into the selected purge transaction's private write-once namespace before destructive unlink.

The historical conflict DB row MUST remain historical evidence. It MUST NOT be rewritten as `purged`, deleted, or made to appear successful. The purge operation records an audit event describing that the preserved historical candidate alias was retired during purge closure of the selected active entry.

### 5.4 Cross-Entry Blocking Matrix

If a same-payload alias belongs to:

| Owner classification | Result |
|---|---|
| selected active entry | eligible after qualification |
| historical non-authoritative `conflict` candidate | eligible after full requalification |
| another `active` entry | BLOCK: `SHARED_ACTIVE_PAYLOAD` |
| another `restoring` entry | BLOCK |
| another `restored`/authoritative lineage that still owns payload | BLOCK |
| unknown/missing DB owner | BLOCK |
| unrecognized private pathname | BLOCK |
| foreign/unknown inode/object | PRESERVE + FAIL CLOSED |

v0.3.6 MUST NOT automatically link multiple active entries into one purge request merely because they share an inode/hash.

---

## 6. Transactional Purge Protocol

### 6.1 State Transition

The only normal entry point is:

```text
active -> purging -> purged
```

`restoring` and `purging` are mutually exclusive transitions from `active`.

Once `purging` is durably committed, the engine MUST NOT roll the row back to `active`, because an irreversible payload mutation may already have happened. Recovery must reconcile and resume or fail closed with preserved evidence.

No DB migration is required for these states because current columns are strings and `purged_at` already exists.

### 6.2 Frozen Phase Order

```text
PREVIEW (0 mutation)
  -> classify topology + build canonical manifest
GENERATE DRAFT
  -> recompute Preview + digest check
FREEZE
VALIDATE
EXECUTE
  -> BEGIN IMMEDIATE + worker lease assertion
  -> verify row still active and frozen manifest identity
  -> commit state/tx_phase='purging'
  -> allocate unique generation under existing monotonic allocator
  -> create exclusive purge private namespace
  -> CAPTURE eligible aliases one filesystem mutation at a time
  -> RE-QUALIFY captured aliases in private namespace
  -> CLOSURE CHECK
  -> DESTRUCT exact qualified captured aliases one at a time
  -> verify NFC-owned closure
  -> commit state/tx_phase='purged', purged_at
  -> audit per selected entry and linked historical aliases
```

### 6.3 Capture Before Destruction

The purge engine MUST NOT perform `check(path); unlink(path)` against public or historical source pathnames.

Every payload-bearing alias selected for destruction is first retired by an ordinary `rename()` into a unique write-once private purge slot owned by a newly allocated generation, for example:

```text
<quarantine_root>/.tx/entry-1103/attempt-2/purge/
  public-view
  current-anchor
  captured-source
  linked-conflict-562-anchor
```

Slot names are deterministic within the manifest and MUST NOT be reused after a rename attempt. Attempt directory creation remains exclusive.

If the source pathname is replaced between classification and rename, rename preserves the replacement inside the private slot instead of deleting it. Post-capture qualification then detects foreign/unknown identity and the engine MUST preserve it and fail closed.

### 6.4 Qualification

For expected regular-file payload aliases, qualification must verify:

- descriptor-bound regular-file type;
- expected device;
- expected inode where same-inode alias identity is required;
- expected size;
- expected mtime;
- expected SHA256;
- NFC namespace ownership and expected manifest source/slot binding;
- no symlink traversal.

`ctime` is diagnostic only for the read-induced zfuse scenario and MUST NOT become an authoritative equality requirement.

`st_nlink` is forbidden as authority.

### 6.5 Destructive Phase

Only exact, already captured, fully qualified payload aliases may be unlinked.

Forbidden:

- `shutil.rmtree()` on transaction roots;
- recursive blind `os.walk(...).unlink()` cleanup;
- unlink of foreign/unknown objects;
- unlink of an unrecognized payload path;
- deletion merely because inode/hash appears to match without namespace ownership proof.

Allowed cleanup after payload closure:

- exact qualified captured payload aliases;
- exact known non-payload metadata owned by the purge attempt;
- `rmdir()` of verified-empty directories.

If unknown content remains in a private namespace, leave it in place and audit it. Do not recursively clean it.

---

## 7. Lease, Crash, Retry, and Recovery

### 7.1 Per-Mutation Lease Discipline

Gate5-G's lease discipline remains frozen:

```text
renew/assert Worker lease
  -> exactly ONE payload-affecting filesystem syscall
renew/assert Worker lease
  -> next payload-affecting syscall
```

No SQLite write transaction may be held across a potentially blocking zfuse syscall.

### 7.2 Crash Recovery

Recovery must be idempotent and evidence-driven.

If crash occurs after `state='purging'`:

- inspect the durable purge topology manifest and allocated generation;
- classify existing purge slots before issuing any new mutation;
- never reuse a write-once destination that already contains an object;
- if a captured slot contains expected qualified payload, resume from that evidence;
- if it contains foreign/unknown payload, preserve and fail closed;
- if an expected alias was already destroyed, record that fact and continue only if manifest/recovery evidence proves the destruction belongs to the same purge transaction;
- final `purged` transition occurs only after NFC-owned closure is proven.

A stale worker may execute at most one previously fenced mutation before the next lease assertion rejects it.

---

## 8. Gate6-A3 — Bulk Orchestration Contract

Bulk execution is a serial orchestration of independent entry-level transactions. It is NOT a giant filesystem transaction.

Frozen behavior:

- execute selected entries serially;
- continue after an individual item failure unless the Worker/job itself loses authority;
- previously successful items are never rolled back merely because a later item failed;
- per-entry state/result is durable and auditable;
- aggregate response/job state summarizes item results without inventing atomicity.

Per-entry outcome classes:

- `succeeded`
- `skipped`
- `failed`
- `blocked`

Each result includes `entry_id` and a stable machine-readable/error reason where applicable.

---

## 9. Gate6-A4 — Preview Identity Enforcement

### 9.1 Endpoints

Frozen API surface:

```text
POST /api/quarantine/bulk-preview
POST /api/quarantine/bulk-plan
```

Existing single-entry endpoints remain compatibility APIs.

### 9.2 Preview Request

Conceptual request:

```json
{
  "action": "restore",
  "entry_ids": [1103, 1104],
  "conflict_policy": "skip"
}
```

or:

```json
{
  "action": "purge",
  "entry_ids": [1103, 1104]
}
```

Validation:

- non-empty explicit ID list;
- duplicate IDs => 422;
- bounded request size sufficient for production usage; initial max SHOULD be 5000 unless measured constraints require a smaller documented limit;
- restore policy only `skip|rename`;
- purge rejects restore-only policy fields.

### 9.3 Canonical Preview Digest

Preview returns a deterministic `preview_digest`. Canonical digest material MUST bind at least:

- action;
- canonical sorted selected entry IDs;
- conflict policy where applicable;
- per-entry DB state and tx_phase;
- original path;
- quarantine path;
- authoritative anchor path;
- active attempt generation;
- device/inode/size/mtime/content hash;
- exact restore target for restore;
- purge topology/ownership manifest for purge;
- any blocked eligibility reason affecting generation.

Canonical JSON serialization MUST be stable (`sort_keys`, stable separators, explicit UTF-8 encoding or equivalent frozen canonicalization).

### 9.4 Generate Draft

Generate requires `expected_preview_digest` and recomputes current Preview from authoritative DB/filesystem facts.

If any digest-bound fact changed:

```text
HTTP 409 PREVIEW_CHANGED
0 BatchPlan
0 BatchPlanItem
```

Generate MUST fail closed if ANY selected item is missing, non-active, or blocked. It MUST NOT silently drop invalid members from the selection.

### 9.5 Purge Confirmation Binding

Purge generation additionally requires:

- authenticated administrator;
- `ALLOW_MUTATION=true`;
- `ALLOW_DELETE=true`;
- explicit batch confirmation token `DELETE`;
- the exact `expected_preview_digest` being confirmed.

One user confirmation covers the exact digest-bound batch. A changed Preview requires a new Preview and confirmation.

---

## 10. Gate6-A5 — Plan Model

No database migration is authorized/expected.

Plan kinds:

```text
quarantine-bulk-restore
quarantine-bulk-purge
```

Restore item:

```text
operation = restore
source_path = frozen quarantine/public path
target_path = exact frozen restore target
metadata_json:
  quarantine_entry_id
  conflict_policy
  preview_digest
```

Purge item:

```text
operation = quarantine_purge
source_path = selected quarantine/public path
target_path = null
metadata_json:
  quarantine_entry_id
  preview_digest
  purge_topology_manifest
```

`purge_topology_manifest` is durable evidence for recovery. It does NOT authorize blindly trusting stale paths: Worker Execute and recovery must revalidate live identity/ownership before each mutation.

---

## 11. Authorization Rules

### Bulk Restore

- authenticated user;
- `ALLOW_MUTATION=true`;
- active entries only;
- no delete permission required;
- Worker authority required at Execute.

### Bulk Purge

- authenticated administrator;
- `ALLOW_MUTATION=true`;
- `ALLOW_DELETE=true`;
- active entries only;
- exact batch confirmation token;
- exact expected preview digest;
- Worker authority required at Execute.

Frontend visibility is not authorization. Backend must recheck all rules.

---

## 12. UI Freeze

Quarantine page adds multi-select checkboxes and two bulk actions:

```text
批量恢复
批量永久删除
```

Selection UX SHOULD support:

- current-page select;
- explicit selection of all entries in the current filtered result.

“All filtered” MUST resolve to explicit entry IDs before Preview. There is no hidden server-side wildcard selection whose membership can drift between Preview and Generate.

Bulk Restore modal:

```text
冲突处理
  跳过（默认）
  自动重命名
```

Bulk Purge modal clearly displays selected count and irreversible warning. Confirmation generates a Draft; it MUST NOT execute deletion immediately.

After Draft generation, normal plan UI/safety lifecycle is reused: Freeze -> Validate -> Execute.

---

## 13. Audit Requirements

Audit remains per entry, not merely one batch-level row.

At minimum record:

- bulk restore success/skip/failure with entry ID, frozen target, conflict policy;
- bulk purge success/failure with entry ID and preview digest;
- historical conflict candidate alias retirement, including historical owner entry ID and selected active entry ID;
- blocked shared-active/unknown-owner/foreign-object findings;
- recovery/resume outcome after interrupted purge.

Historical conflict rows remain immutable historical state unless a separate future architecture explicitly authorizes state repair.

---

## 14. Fail-Closed Error Classes

Implementation should use stable error codes/messages for at least:

```text
PREVIEW_CHANGED
EMPTY_SELECTION
DUPLICATE_ENTRY_ID
QUARANTINE_ENTRY_NOT_FOUND
QUARANTINE_ENTRY_NOT_ACTIVE
INVALID_BULK_RESTORE_POLICY
PURGE_CONFIRMATION_REQUIRED
PURGE_ADMIN_REQUIRED
MUTATION_DISABLED
PERMANENT_DELETE_DISABLED
SHARED_ACTIVE_PAYLOAD
UNKNOWN_PURGE_ALIAS_OWNER
UNRECOGNIZED_PURGE_NAMESPACE
FOREIGN_PURGE_OBJECT
PURGE_QUALIFICATION_FAILED
WORKER_LEASE_LOST
```

HTTP mapping should preserve existing project conventions while making `PREVIEW_CHANGED` exactly 409.

---

## 15. Required Test Matrix

Strict TDD is mandatory. At minimum cover:

### Preview / Generate

- empty ID list;
- duplicate IDs;
- missing ID;
- non-active states (`abandoned`, `conflict`, `inconsistent`, `restored`, `purged`);
- stable canonical digest independent of input ID ordering;
- Preview zero mutation;
- Preview changed on DB identity/state change;
- Preview changed on restore destination/topology change;
- mismatch returns 409 and persists zero plan rows;
- blocked member causes whole Generate to fail closed.

### Bulk Restore

- skip conflict policy;
- rename policy frozen target;
- manual/custom target rejected;
- no-overwrite race after Preview;
- serial partial failure aggregation;
- transactional Worker authority required;
- per-entry audit.

### COMPAT Purge

- direct API purge of transactional entry remains refused by old guard;
- Worker plan path is the only transactional purge authority;
- admin/mutation/delete/confirmation enforcement;
- `st_nlink` does not influence eligibility/closure;
- ctime-only read-induced change does not reject SHA-backed payload;
- mtime/size/hash/device/inode mismatch fails closed;
- expected active aliases are captured before destructive unlink;
- historical conflict candidate alias can be retired only after full qualification;
- historical conflict DB row remains conflict;
- another active owner blocks with `SHARED_ACTIVE_PAYLOAD`;
- unknown/missing DB owner blocks;
- unrecognized private file blocks/preserves;
- foreign replacement captured then preserved; zero destructive unlink;
- crash boundaries between every capture/destructive step;
- stale worker fencing;
- idempotent reconciliation;
- no recursive blind deletion;
- final `purged` only after NFC-owned closure.

### Regression

- all Gate5-G transactional quarantine/restore tests;
- v0.3.5.1 zfuse ctime regression;
- planning/Freeze/Validate/Worker lifecycle regression;
- existing single-entry restore/purge API compatibility;
- frontend typecheck/build.

---

## 16. Real-NAS Acceptance Gate

Gate6-A cannot be marked PASS/CLOSED from source review alone.

Required real-NAS acceptance on an isolated/safe selection:

1. Bulk Restore small batch: Preview -> Draft -> Freeze -> Validate -> Execute; verify original paths, quarantine states, no overwrite, and audit.
2. Bulk Purge small batch of transactional active entries: Preview -> Draft -> Freeze -> Validate -> Execute; verify selected NFC-managed aliases retired, state `purged`, no unknown/foreign loss, and audit.
3. When safely available, include at least one active entry whose payload also has a historical conflict candidate alias to prove cross-entry closure.
4. Docker linux/amd64 image identity and API/Worker same immutable image verification before production closure.

Production data must not be used as disposable test material without explicit user authorization.

---

## 17. CLOSED Invariants That Gate6-A Must Not Reopen

- Gate5-G authoritative anchor model.
- Candidate qualification before authority.
- Unique monotonic attempt generations.
- Write-once capture destinations.
- Foreign/unknown preserve-first behavior.
- Per-mutation Worker lease fencing.
- No-overwrite restore semantics.
- Gate3 as physical identity/SHA authority for plan lifecycle.
- v0.3.5.1 zfuse ctime compatibility semantics.
- Preview zero mutation.

---

## 18. Authorization Statement

The user explicitly approved this Gate6-A Architecture Freeze on 2026-09-13.

Implementation is therefore AUTHORIZED on the canonical branch only, subject to:

```text
Strict TDD
RED -> GREEN -> REFACTOR
-> focused regression
-> full backend regression
-> frontend typecheck/build
-> Docker linux/amd64 validation
-> real NAS acceptance
-> independent review / closure
```

No implementation result may be called PASS/CLOSED until required evidence has actually been produced and reviewed.
