# v0.3.6 Gate6-A2 Safe Permanent Purge — Implementation Plan

**Goal:** Replace the release-blocked permanent-purge surface with a new pathname-scoped, unlink-based permanent-clear implementation for both single-entry and bulk quarantine operations, while preserving the old inode-global purge operation as permanently fail-closed.

**Architecture:** Introduce a new `quarantine_unlink_purge` operation and a dedicated unlink-purge core. The core authorizes only a frozen manifest of NFC-owned quarantine paths, revalidates exact pathname identity immediately before each unlink, and never truncates or overwrites inode payload data. Hard-link-survivor and same-content-copy discovery are read-only advisory layers restricted to currently indexed roots. Bulk execution remains Preview → Draft → Freeze → Validate → Execute; single-entry clear reuses the same mutation core with the same safety checks and result vocabulary.

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy/SQLite, pytest, React 18, TypeScript, Ant Design, Node 22, project custom frontend test runner, Docker Buildx linux/amd64.

**Spec:** `docs/superpowers/specs/2026-09-15-gate6a2-unlink-purge-design.md`

**Baseline:** `main@4abd312086c7ef0f363a4da4d13b51cb470d8cba`

**Implementation branch:** `feature/v0.3.6-gate6a2-unlink-purge`

**Release rule:** This is still v0.3.6. Gate6-A2 must close before returning to Gate6-B. Do not change production NAS or redeploy production during implementation/testing.

---

## Non-negotiable invariants

1. New production code must never call `ftruncate`, zero-fill, overwrite, or otherwise mutate the shared inode payload as part of permanent clear.
2. Existing operation `quarantine_purge` remains `EOPNOTSUPP`/fail-closed for stale, handcrafted, or historical plans.
3. New operation identity is `quarantine_unlink_purge` and must not alias to the old operation name.
4. Unlink authority is pathname-scoped: only exact NFC-owned paths frozen for the selected `QuarantineEntry` may be removed.
5. A same-inode path owned by another quarantine entry is never removed merely because its `(device, inode)` matches.
6. Symlink, path escape, ABA replacement, identity drift, unknown private objects, or stale frozen authority fail closed before widening mutation authority.
7. Hard-link survivor discovery is limited to currently indexed roots and is advisory. Failure to discover advisory data must never be reported as “fully deleted”.
8. Same-content/different-inode copies are informational only and must be visually and semantically separated from hard-link survivors.
9. `ALLOW_MUTATION`, `ALLOW_DELETE`, admin authorization, Preview digest binding, Freeze, Validate, worker lease fencing, audit, and crash truthfulness remain mandatory.
10. No DB schema migration is planned. Persist new bulk authority/results in existing `BatchPlan.metadata_json`, `BatchPlanItem.metadata_json`, task/audit JSON, and existing quarantine fields. If implementation proves these are insufficient, stop and amend the architecture before adding a migration.

---

# Task 1 — Lock the new safety contract with RED tests

**Files:**
- Create: `tests/test_gate6a2_unlink_purge_core.py`
- Create: `tests/test_gate6a2_unlink_purge_advisory.py`
- Create: `tests/test_gate6a2_unlink_purge_api.py`
- Create: `tests/test_gate6a2_unlink_purge_executor.py`
- Create: `tests/test_gate6a2_unlink_purge_recovery.py`
- Reference only: existing Gate6-A / Gate5-G quarantine tests

### RED 1.1 — External hard link survives

Create a real regular file in a temporary indexed root, create the NFC-owned quarantine aliases required by an active `QuarantineEntry`, then create a separate external hard link with `os.link()`.

Assert the future unlink-purge operation:

- removes only the selected entry's NFC-owned paths;
- leaves the external path present;
- leaves its bytes/hash unchanged;
- leaves its `(device, inode)` unchanged;
- reports the external path as an indexed-scope survivor when indexed.

Expected now: FAIL because unlink purge does not exist.

### RED 1.2 — Last NFC-owned link removal succeeds without payload zeroization

Use a selected entry with no indexed external survivor. Assert the selected NFC paths disappear and the operation reports `survivor_status=verified_none` or equivalent scoped status.

Monkeypatch `os.ftruncate` to raise immediately if invoked. The test must still pass after implementation.

Expected now: FAIL.

### RED 1.3 — Cross-entry same inode cannot cause cross-entry unlink

Create two active `QuarantineEntry` rows whose NFC-owned paths hard-link to the same inode. Purge only entry A.

Assert:

- A-owned paths are removed;
- B-owned paths remain;
- B remains active;
- B bytes remain unchanged.

Expected now: FAIL.

### RED 1.4 — Old operation remains permanently blocked

Construct an old/stale/handcrafted `BatchPlanItem(operation="quarantine_purge")` and exercise the production executor path.

Assert:

- result is failed/unsupported with `EOPNOTSUPP` or the exact existing refusal code;
- zero filesystem mutation occurs;
- the new unlink core is not called.

Expected now: existing behavior should PASS and becomes a locked regression.

### RED 1.5 — Symlink / ABA / path escape fail closed

Add tests for:

- public quarantine path replaced with symlink;
- frozen path replaced with a different inode between freeze and execute;
- malformed path outside quarantine root;
- private path attributed to another entry;
- unknown payload-bearing object in a selected private namespace.

Assert zero unintended unlink.

### RED command

```bash
python -m pytest -q \
  tests/test_gate6a2_unlink_purge_core.py \
  tests/test_gate6a2_unlink_purge_advisory.py \
  tests/test_gate6a2_unlink_purge_api.py \
  tests/test_gate6a2_unlink_purge_executor.py \
  tests/test_gate6a2_unlink_purge_recovery.py
```

Record the failing assertions before implementation. Do not weaken tests to obtain GREEN.

---

# Task 2 — Implement read-only indexed-scope advisory discovery

**Files:**
- Create: `app/quarantine/purge_advisory.py`
- Test: `tests/test_gate6a2_unlink_purge_advisory.py`
- Reference: `app/models.py`

### RED 2.1 — Same-inode indexed survivor

Insert `IndexedPath` candidate rows matching selected `(device, inode)`. Make one candidate live and one stale.

Expected result shape should include at least:

```python
{
    "scope": "indexed_roots_only",
    "status": "verified_found",
    "hardlink_survivors": ["/data/..."],
    "stale_candidates": [...],
}
```

The exact field names may be refined once, then frozen in tests.

### GREEN 2.2 — Candidate lookup + live verification

Implement a pure/read-only service that:

1. queries `IndexedPath` by selected `device + inode`;
2. confirms candidate path belongs to a currently configured `IndexRoot`;
3. excludes selected NFC-owned quarantine/private paths;
4. uses `os.lstat()` on candidates only;
5. rejects symlinks/non-regular files;
6. verifies exact live `(device, inode)`;
7. returns only live verified survivors;
8. marks stale/disappeared candidates diagnostically rather than treating them as survivors.

Do not use `st_nlink` as authority.

### RED/GREEN 2.3 — Same-content independent copies

Using `DuplicateGroup.content_hash` + `DuplicateFile`, assert same hash but different `(device, inode)` is returned separately as an independent copy and never as a hard-link survivor.

Label this evidence as scan/index-context advisory because duplicate scan data may be stale.

### RED/GREEN 2.4 — Advisory failure is incomplete, not a mutation blocker

Inject DB/read/lstat advisory failure. Return a scoped `incomplete` diagnostic; never claim no survivors.

The mutation authority must not depend on advisory success.

### REFACTOR 2.5

Keep advisory code filesystem-read-only and independent of mutation code. No unlink/remove/truncate imports in this module.

---

# Task 3 — Build the canonical NFC-owned unlink manifest

**Files:**
- Create: `app/quarantine/unlink_purge.py`
- Modify only if reusable identity helpers are needed: `app/quarantine/bulk.py`
- Test: `tests/test_gate6a2_unlink_purge_core.py`

### RED 3.1 — Allowlisted owned roles only

Lock a deterministic manifest for an active entry containing only recognized NFC-owned path roles that are valid for the current transaction topology, e.g. current authoritative anchor, captured source where valid, and public quarantine view.

The implementation must derive the exact valid set from current Gate5-G/Gate6-A topology; it must not invent a missing alias.

### RED 3.2 — No cross-entry ownership widening

A path under another entry's `.tx/entry-<id>/...` namespace must never enter the selected manifest even if inode identity matches.

### RED 3.3 — Unknown/private malformed objects block mutation authority

Any object that makes ownership ambiguous must produce an explicit blocker rather than being silently ignored or recursively deleted.

### GREEN 3.4 — Implement `build_unlink_manifest(...)`

Manifest must freeze:

- selected entry id;
- current generation / transaction identity required to bind authority;
- role + exact absolute lexical path for every allowed NFC-owned link;
- expected object type;
- expected `device`, `inode`, `size`, `mtime_ns`, and authoritative content hash where available;
- an explicit semantics/version marker such as `unlink_v1`.

Canonicalize ordering so Preview digest and Freeze validation are stable.

### GREEN 3.5 — Implement manifest revalidation

Immediately before mutation, revalidate:

- path still under expected NFC namespace;
- not symlink;
- expected regular-file type;
- exact frozen `(device, inode)` and required identity facts;
- selected entry state/transaction identity still valid;
- no ABA replacement.

Return stable blocker codes for tests/API/audit.

### REFACTOR 3.6

Keep old `app/quarantine/purge.py` destructive core dormant. Do not call or repurpose its `ftruncate` destruction path.

---

# Task 4 — Implement the idempotent unlink mutation core

**Files:**
- Modify: `app/quarantine/unlink_purge.py`
- Modify as needed for journaling/state integration: `app/service.py`
- Test: `tests/test_gate6a2_unlink_purge_core.py`
- Test: `tests/test_gate6a2_unlink_purge_recovery.py`

### RED 4.1 — Exact owned-path unlink only

Freeze a valid manifest and execute. Assert only listed selected-entry paths are removed.

Patch/spy on filesystem mutation primitives and assert:

- `os.unlink`/descriptor-safe equivalent is used only for authorized leaf paths;
- `os.ftruncate` is never called;
- recursive deletion (`shutil.rmtree`) is never called;
- unrelated paths are unchanged.

### RED 4.2 — Crash after partial unlink is truthful and resumable

Inject a crash after one selected owned path is unlinked but before completion.

On resume/reconcile, assert:

- already-authorized-and-journaled missing path is treated idempotently;
- remaining frozen paths may complete only after revalidation;
- no new path is added to authority;
- terminal `purged` state is not committed early;
- audit/result records partial/recovered execution truthfully.

### GREEN 4.3 — Persist irreversible intent before unlink

Before the first unlink, persist enough existing-DB metadata/journal authority to recover the exact frozen manifest after restart. Prefer existing JSON metadata/journal structures; do not add schema casually.

State transition should make crash position explicit (`active` → purge-in-progress state/phase → `purged`) and remain consistent with existing reconciliation conventions.

### GREEN 4.4 — Descriptor-safe unlink sequence

For every frozen path:

1. revalidate exact path identity;
2. open/validate parent safely using existing PathGuard/descriptor helpers where applicable;
3. unlink the exact leaf from its parent descriptor;
4. fsync directory where current project safety conventions require it;
5. persist/checkpoint role completion so retry can distinguish expected absence from foreign mutation.

Never unlink by inode search. Never unlink a path discovered solely by survivor scanning.

### GREEN 4.5 — Terminal result

After all required owned paths are confirmed removed:

- set entry `state="purged"` and `purged_at`;
- clear/settle transaction phase consistently;
- produce structured result with removed roles/count and advisory survivor/copy data;
- emit audit with `purge_semantics="unlink_v1"`.

### REFACTOR 4.6

Separate three concerns:

- manifest/authority;
- mutation/recovery;
- advisory survivor/copy reporting.

This prevents advisory data from accidentally becoming deletion authority.

---

# Task 5 — Route single-entry Clear through the new core

**Files:**
- Modify: `app/service.py`
- Modify: `app/api/router.py`
- Modify request/response models only as needed
- Test: `tests/test_gate6a2_unlink_purge_api.py`

### RED 5.1 — Authorization and flags

Lock existing behavior:

- non-admin → blocked;
- `ALLOW_MUTATION=false` → blocked;
- `ALLOW_DELETE=false` → blocked;
- wrong confirmation → blocked;
- non-active entry → blocked.

### RED 5.2 — Single Clear semantic result

For an eligible active entry, assert API response includes:

- entry id / purged outcome;
- owned links removed roles/count;
- `survivor_scope="indexed_roots_only"`;
- survivor status + verified paths;
- independent same-content copies separately;
- no statement equivalent to global secure erase.

### GREEN 5.3 — Replace single-entry routing

Keep the public single-entry endpoint compatible where practical, but route it to the new unlink core. Do not call dormant old destructive purge logic.

If response shape must expand, maintain fields required by existing frontend while adding structured Gate6-A2 fields.

### REFACTOR 5.4

Single and bulk must call the same authority/mutation helper rather than maintaining two filesystem deletion implementations.

---

# Task 6 — Enable safe bulk Preview and Draft generation

**Files:**
- Modify: `app/api/quarantine_bulk.py`
- Modify: `app/api/quarantine_bulk_plan.py`
- Modify: `app/quarantine/bulk.py` only for shared canonical digest helpers
- Test: `tests/test_gate6a2_unlink_purge_api.py`

### RED 6.1 — Purge Preview no longer blanket-deferred

Replace the old expected `PERMANENT_PURGE_DEFERRED_UNSAFE_HARDLINK_SCOPE` behavior for the **new** Gate6-A2 surface with per-entry safe-unlink eligibility.

Assert:

- eligible active selected entries return `eligible=True` when owned-path manifest is safe;
- an external indexed hard-link survivor is informational and does not block;
- ownership/path/identity blockers still make that entry ineligible;
- mixed selection returns truthful blocked/eligible counts;
- unselected entries are never included.

### RED 6.2 — Preview digest binds destructive authority

Digest material must include, per selected entry:

- persisted quarantine identity;
- unlink semantics/version;
- exact canonical owned-path manifest;
- selected IDs.

Advisory survivor lists should not silently widen mutation authority. Decide whether they are digest-bound for presentation consistency; if bound, stale advisory change must trigger re-preview without changing deletion authority. Freeze the decision in tests.

### GREEN 6.3 — Draft uses new operation name

`bulk-plan` for action purge must generate `BatchPlanItem.operation="quarantine_unlink_purge"`, never `quarantine_purge`.

Persist per-item exact manifest and expected identity in `metadata_json`. Persist plan-level Preview digest/semantics in `metadata_json`.

Keep admin + mutation/delete flag checks and strict `confirmation="DELETE"`.

### RED/GREEN 6.4 — Stale Preview protection

Change entry state, identity, selected manifest, or relevant frozen authority after Preview and before Draft. Assert plan generation returns conflict/blocked and creates no destructive new-op items from stale authority.

---

# Task 7 — Bind Freeze / Validate to unlink authority

**Files:**
- Modify: `app/quarantine/bulk_lifecycle.py`
- Modify any central plan freeze/validate integration points required by current architecture
- Test: `tests/test_gate6a2_unlink_purge_executor.py`

### RED 7.1 — Freeze persists exact unlink authority

Assert Freeze does not derive a fresh/wider manifest from current filesystem state. It must bind the Preview/Draft-selected manifest and then verify it is still current.

### RED 7.2 — Validate rejects authority drift

After Freeze, mutate one of:

- selected entry state;
- selected path inode;
- selected path type;
- selected path ownership/generation;
- symlink state.

Validate must fail before execute.

### GREEN 7.3 — Add `quarantine_unlink_purge` lifecycle support

Extend existing lifecycle dispatch narrowly for the new operation while preserving existing restore behavior.

No second worker or generic alternate executor.

### REFACTOR 7.4

Keep operation-specific validation helpers in the unlink-purge module; orchestration layer should coordinate, not duplicate filesystem rules.

---

# Task 8 — Add exact executor/recovery dispatch while preserving old refusal

**Files:**
- Modify: `app/execution/executor.py`
- Modify recovery/reconcile integration only where required by the current worker architecture
- Keep dormant: `app/quarantine/purge.py`
- Test: `tests/test_gate6a2_unlink_purge_executor.py`
- Test: `tests/test_gate6a2_unlink_purge_recovery.py`

### RED 8.1 — New op dispatch

`execute_item(operation="quarantine_unlink_purge")` must call the new core with frozen metadata and worker/lease authority.

### RED 8.2 — Old op refusal survives

`execute_item(operation="quarantine_purge")` must still fail before filesystem mutation with the existing unsupported contract.

Test both names in the same test module so future refactors cannot accidentally alias them.

### RED 8.3 — Lease fencing

Lose worker lease immediately before unlink. Assert zero filesystem mutation and no stale-worker terminal state write.

### GREEN 8.4 — Recovery/reconcile new operation

Teach restart reconciliation only the new operation's idempotent journal/manifest semantics. Recovery must never route old `quarantine_purge` into the new unlink implementation.

### RED/GREEN 8.5 — Exactly-once terminal audit semantics

Crash/retry must not create misleading duplicate terminal success events. Bind audit details to plan id, item id, quarantine entry id, Preview digest, semantics version, and survivor scope.

---

# Task 9 — Frontend contracts and tests first

**Files:**
- Modify: `frontend/tests/gate6a_quarantine_bulk.test.ts`
- Modify: `frontend/tests/gate6a_quarantine_bulk_ui_wiring.test.ts`
- Create: `frontend/tests/gate6a2_unlink_purge.test.ts`
- Modify: `frontend/scripts/run-tests.mjs`
- Modify types under: `frontend/src/types/`

### RED 9.1 — Bulk button no longer hardcoded disabled

Test that bulk permanent clear is enabled only when:

- at least one active entry is selected;
- current user is admin;
- `ALLOW_MUTATION=true`;
- `ALLOW_DELETE=true`.

Assert no `disabled={true}` hardcoding remains.

### RED 9.2 — Preview survivor warning is non-blocking

Given safe Preview with one verified indexed hard-link survivor:

- modal shows indexed-scope warning + survivor path;
- user can still type exact uppercase `DELETE`;
- Draft button becomes eligible if Preview has no mutation blockers.

### RED 9.3 — Scoped wording

Test UI contains scoped wording such as:

- “当前已建立索引的目录” / “索引范围内”;
- “仍发现 hard link” or “未发现其他 hard link”.

Test UI does **not** claim “数据已彻底物理销毁”, “磁盘字节已完全擦除”, or equivalent absolute secure-erasure language.

### RED 9.4 — Independent copy classification

Same-content/different-inode copies are shown in a separate section from same-inode hard-link survivors.

### Test runner update

Add `tests/gate6a2_unlink_purge.test.ts` to both TypeScript compile and `node --test` command lists in `frontend/scripts/run-tests.mjs`.

Run:

```bash
cd frontend
npm ci
npm test
```

Expected before UI implementation: new tests FAIL.

---

# Task 10 — Implement unified single + bulk UI

**Files:**
- Modify: `frontend/src/pages/Quarantine/index.tsx`
- Modify: `frontend/src/pages/Quarantine/BulkPurgeModal.tsx`
- Modify: `frontend/src/pages/Quarantine/PurgeConfirmModal.tsx`
- Modify: `frontend/src/api/quarantine.ts`
- Modify: relevant `frontend/src/types/*`
- Test: frontend Gate6-A2 tests

### GREEN 10.1 — Bulk button wiring

Remove the v0.3.6 blanket-deferral tooltip/hardcoded disabled state. Derive button state from real selection/admin/mutation/delete conditions.

### GREEN 10.2 — Bulk Preview / Draft UX

Reuse the existing BulkPurgeModal flow:

1. Preview;
2. display mutation blockers separately from advisory survivors/copies;
3. require exact uppercase `DELETE`;
4. generate Draft only when no mutation blocker exists;
5. navigate/use existing plan lifecycle for Freeze → Validate → Execute.

### GREEN 10.3 — Single Clear result UX

Use the same result terminology as bulk:

- NFC-owned links cleared;
- indexed-scope hard-link survivor status/paths;
- independent same-content copies;
- explicit indexed-root scope.

### GREEN 10.4 — Error truthfulness

If advisory status is incomplete, show “无法在索引范围内完整确认” rather than converting it to “no survivors”.

### REFACTOR 10.5

Extract shared display formatter/component only if it reduces duplicated single/bulk result semantics. Do not create a second API workflow.

Run:

```bash
cd frontend
npm test
npm run typecheck
npm run build
```

All must be GREEN.

---

# Task 11 — Backend focused GREEN + restore regressions

**Files:** tests only unless a failure reveals a justified implementation defect.

Run focused Gate6-A2:

```bash
python -m pytest -q \
  tests/test_gate6a2_unlink_purge_core.py \
  tests/test_gate6a2_unlink_purge_advisory.py \
  tests/test_gate6a2_unlink_purge_api.py \
  tests/test_gate6a2_unlink_purge_executor.py \
  tests/test_gate6a2_unlink_purge_recovery.py
```

Then explicitly run existing quarantine/Gate6-A/Gate5-G regression subsets identified in the repository before implementation. At minimum they must cover:

- Bulk Restore selected-only;
- skip/rename and NEVER overwrite;
- frozen target/digest freshness;
- worker lease/reconcile;
- old purge EOPNOTSUPP;
- path/symlink/ABA safety.

Do not edit historical tests merely to make the new semantics pass. If an old test intentionally freezes the v0.3.6 blanket purge refusal, supersede it only with an explicit Gate6-A2 amendment test while preserving the old operation-name refusal.

---

# Task 12 — Full regression and static safety checks

### Backend

```bash
python -m pip install -e '.[test]'
pytest --disable-warnings -q
```

Expected: full suite PASS.

### Frontend

```bash
cd frontend
npm ci
npm test
npm run typecheck
npm run build
```

Expected: all PASS.

### Diff/safety checks

From repository root:

```bash
git diff --check 4abd312086c7ef0f363a4da4d13b51cb470d8cba...HEAD

git grep -n 'ftruncate' -- app

git grep -nE 'quarantine_purge|quarantine_unlink_purge' -- app tests

git diff --unified=0 4abd312086c7ef0f363a4da4d13b51cb470d8cba...HEAD -- app \
  | grep -E '^\+[^+].*(rmtree|unlink\(|os\.remove\(|os\.unlink\()' || true
```

Review every newly-added deletion primitive manually. New unlink sites must be explainable by the Gate6-A2 owned-path manifest. Any new `ftruncate` in release-reachable Gate6-A2 code is an automatic BLOCKED result.

---

# Task 13 — Add a dedicated Gate6-A2 CI closure workflow

**Files:**
- Create: `.github/workflows/gate6a2-closure.yml`
- Do not repurpose historical `.github/workflows/gate6a-closure.yml`

The new workflow should trigger on `feature/v0.3.6-gate6a2-unlink-purge` and manual dispatch, and use baseline:

```text
4abd312086c7ef0f363a4da4d13b51cb470d8cba
```

Required jobs/evidence:

1. candidate identity / merge-base check;
2. focused Gate6-A2 tests;
3. full backend regression;
4. frontend `npm test`;
5. frontend `npm run typecheck`;
6. frontend `npm run build`;
7. security grep proving old/new operation identities remain distinct;
8. explicit scan for new/changed `ftruncate`, recursive-delete, and unlink sites;
9. linux/amd64 Docker build;
10. API/Worker shared-image identity check;
11. upload all logs/evidence as artifacts.

Build command should follow the existing closure workflow pattern:

```bash
docker buildx build \
  --platform linux/amd64 \
  --load \
  --tag "kerwinjhc/nas-file-center:0.3.6-gate6a2-${SHA7}" \
  .
```

Do not alter production compose tag during candidate CI.

---

# Task 14 — Exact-candidate source review gate

After implementation is frozen:

1. record exact candidate SHA;
2. compare `4abd312...` → exact candidate;
3. enumerate every filesystem mutation site changed/added;
4. verify every `quarantine_unlink_purge` path is covered by tests;
5. verify `quarantine_purge` remains blocked;
6. verify no `st_nlink`-based safety claim was introduced;
7. verify single + bulk use the same core;
8. verify no business change leaked into Gate6-B or later roadmap scope.

Primary implementation self-review is not sufficient for closure. Obtain an independent review against the exact frozen candidate. Final independent verdict must be only:

```text
PASS
```

or

```text
BLOCKED
```

Do not accept CI green as a substitute for implementation review.

---

# Task 15 — Isolated real-NAS acceptance plan (do not execute during implementation)

Only after exact-candidate independent review = PASS.

Use a brand-new sacrificial zfuse subtree and fresh isolated `/config`; do not use production `app.db`, production data subtree, or production API/Worker containers.

Acceptance fixtures must include at least:

### Case A — Hard-link survivor

Create one payload and one external hard link inside an indexed acceptance root. Quarantine the selected side through the supported NFC path, then execute single and/or bulk Gate6-A2 clear.

Verify:

- selected NFC quarantine paths are gone;
- external hard-link path remains;
- external path SHA256 before/after is identical;
- external path size and content unchanged;
- UI/API reports that survivor path in indexed scope;
- zero `ftruncate` behavior.

### Case B — No indexed survivor

Create a payload with no other live hard link. Clear it and verify:

- NFC-owned paths gone;
- result says only “索引范围内未发现其他 hard link”;
- it does not claim secure erase.

### Case C — Cross-entry shared inode

Create two NFC entries sharing one inode. Clear only one and verify the unselected entry and its payload remain intact.

### Case D — Stale/ABA refusal

Mutate a frozen test path before Execute. Validate/Execute must fail closed and leave foreign replacement untouched.

Acceptance must capture before/after tree, `stat`, SHA256, API response, plan/item/audit state, and container image identity.

Only after all acceptance cases PASS may a production candidate image be promoted/redeployed.

---

# Task 16 — Production release preparation only after closure

This task is explicitly deferred until:

```text
Focused tests PASS
+ full regression PASS
+ frontend PASS
+ linux/amd64 build PASS
+ independent exact-candidate review PASS
+ isolated real-NAS acceptance PASS
```

Then prepare a deliberate v0.3.6 production update using the exact accepted image/digest. Do not overwrite or silently mutate the already-accepted v0.3.6 artifact identity.

After deployment, run read-only production checks first; only then perform a deliberately chosen low-risk functional verification if separately authorized by the user.

When Gate6-A2 is PASS/CLOSED, return to the roadmap at Gate6-B. Do not enter v0.3.7.

---

## Definition of Done

Gate6-A2 is complete only when all of the following are true:

- single Clear and bulk Permanent Clear use `quarantine_unlink_purge` semantics;
- only exact NFC-owned frozen paths are unlinked;
- external hard links remain byte-for-byte intact;
- same-inode survivor paths are shown only within indexed scope and live-verified;
- independent same-content copies are shown separately;
- no release-reachable new code uses `ftruncate`/payload zeroization;
- old `quarantine_purge` remains fail-closed;
- crash/retry/reconciliation is idempotent and truthful;
- admin/mutation/delete gates remain enforced;
- Bulk Restore regressions remain green;
- full backend/frontend CI is green;
- exact-candidate independent review = PASS;
- isolated zfuse NAS acceptance = PASS;
- production is not modified before those gates close.
