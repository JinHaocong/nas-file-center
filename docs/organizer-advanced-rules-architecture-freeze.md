# Organizer Advanced Rules — C0 Architecture Freeze

Status: **C0 FROZEN FOR IMPLEMENTATION**  
Product baseline: **v0.4.7**  
Source baseline: `main@0db594f90c3d3493f9c0217b72d5dceca8631401`  
Mutation implementation: **NOT STARTED**  
Next implementation gate: **C1 — schema + shared read-only compiler**

## 1. Scope

Organizer Advanced Rules extends the existing Organizer Profile → Preview →
BatchPlan lifecycle. It does **not** create a second filesystem executor.

V1 scope is:

1. preserve root and depth-1 directory names;
2. allow directory rename rules only from depth >= 2;
3. recursively rename regular files with per-parent numbering;
4. optionally prefix the uniquely newest child directory with `New `;
5. optionally collapse an eligible single-child directory wrapper;
6. retain existing statistics/template semantics;
7. keep Preview read-only and keep all mutations behind Draft → Freeze →
   Validate → Execute.

Similarity, Notifications, Advanced Auth, Hardlink/Reflink and Scheduler are not
part of this gate.

## 2. Current source ownership audit

### Persistence / API

`OrganizerProfile` currently stores explicit columns for root, recursive mode,
extensions, rename/statistics templates, preserve/cleanup rules, directory
numbering and mtime behavior.

Organizer API request models are defined in `app/api/router.py` and expose
CRUD, import/export, read-only preview and Plan generation.

`app/service.py` owns:

- profile validation/serialization;
- import/export;
- preview snapshot caching;
- standalone Organizer Plan generation.

The current standalone Plan path calls the generic `create_plan()`. That
generic persister intentionally keeps only generic fields plus
`protected_dir`; it is **not sufficient** for new structural wrapper metadata.

### Organizer engine / planner

`app/organizers/engine.py` is read-only and already provides:

- no-follow traversal;
- global/quarantine exclusions;
- subtree statistics;
- natural sorting;
- template rendering;
- NAME_MAX / PATH_MAX checks;
- target collision checks;
- cycle detection input.

Its current proposal type is directory-oriented.

`app/organizers/planner.py` currently emits only `rename` and optional
`touch` operations. Renames are ordered bottom-up and dependency chains are
topologically sorted.

### Workflow integration

Organizer workflow mode already snapshots Organizer profile configuration and
reuses `generate_organizer_proposals()` + `plan_organizer_operations()`.
Advanced rules therefore must be implemented once in a shared Organizer
compiler and consumed by both standalone Organizer and Workflow Organizer.

### Existing single-child wrapper authority

Gate6-B already has the structural safety primitive required by this feature:

- `discover_single_child_wrappers()` performs descriptor-bound, no-follow,
  repeated identity/membership verification and capability probing;
- candidate IDs bind wrapper/child/target physical facts;
- utility workflow compilation emits exact `MOVE → rmdir_empty` pairs;
- `_resolve_utility_empty_wrapper_cleanup_authority()` only authorizes the
  exact frozen pair;
- live wrapper cleanup rechecks binding and physical emptiness immediately
  before one non-recursive `rmdir`;
- target appearance, symlink/ABA changes, incomplete cleanup and unsupported
  filesystems fail closed.

Organizer Advanced Rules MUST reuse this authority. It MUST NOT introduce a
generic recursive delete, direct `rmdir`, shell move, or alternate no-clobber
implementation.

## 3. Profile schema decision

Add one persisted JSON-text field:

```text
OrganizerProfile.advanced_rules_json
```

Default:

```json
{}
```

The API exposes it as a validated `advanced_rules` object. Unknown keys are
rejected.

Canonical V1 shape:

```json
{
  "version": 1,
  "directory_depth": {
    "enabled": false,
    "rename_from_depth": 2
  },
  "file_numbering": {
    "enabled": false,
    "start": 1,
    "padding": 3,
    "sort": "natural_name",
    "extension_mode": "preserve"
  },
  "latest_child_prefix": {
    "enabled": false,
    "prefix": "New ",
    "timestamp": "mtime_ns"
  },
  "single_child_wrapper_collapse": {
    "enabled": false,
    "wrapper_depth": 2,
    "child_type": "directory"
  }
}
```

Rules:

- all advanced rules default disabled;
- a legacy profile with `advanced_rules={}` must produce byte-for-byte
  equivalent semantic proposals to the current engine;
- any enabled advanced rule requires `recursive=true`;
- `rename_from_depth` is V1-fixed to >= 2;
- wrapper collapse is V1-fixed to depth 2 and directory-only.

### Import / export compatibility

Profile export moves to `schema_version: 2`.

Import accepts both schema versions:

- V1 → migrate in memory with `advanced_rules={}`;
- V2 → validate `advanced_rules` strictly;
- export always emits V2 after this gate.

Existing database rows migrate with `advanced_rules_json='{}'`.

`OrganizerProfileSnapshot` in workflow schema gains the same validated
`advanced_rules` object so standalone and Workflow Organizer compile the same
semantics.

## 4. Shared Organizer compiler

Introduce a shared read-only compiler under `app/organizers/`.

Inputs:

- canonical profile snapshot;
- selected root;
- ALLOWED_ROOTS / quarantine exclusion;
- global exclude-dir policy;
- safety limits.

Outputs:

- canonical config digest;
- source snapshot digest;
- preview digest;
- summary;
- typed preview proposals;
- planned-operation intents;
- compile context.

Standalone Preview and Workflow Organizer MUST call this same compiler.

Advanced Plan generation MUST bind to the Preview via
`expected_preview_digest`. A changed source/config requires a fresh Preview and
must create **zero** draft rows.

Legacy profiles may continue accepting the old request shape for compatibility;
when advanced rules are enabled, `expected_preview_digest` is mandatory.

## 5. Depth semantics

Depth is always relative to the selected Organizer root:

```text
root = depth 0
root/A = depth 1
root/A/B = depth 2
root/A/B/C = depth 3
```

The root is never renamed.

When `directory_depth.enabled=true`:

- depth 1 directories are always preserved;
- directory template/cleanup/directory-numbering rules apply only at
  `depth >= rename_from_depth`;
- V1 requires `rename_from_depth >= 2`.

Traversal still gathers subtree statistics for template rendering.

## 6. Recursive file numbering

When enabled, every non-symlink regular file whose parent is depth >= 1 is
eligible.

Numbering is independent per parent:

```text
A/
  001.jpg
  002.mp4

A/B/
  001.png
  002.txt
```

V1 ordering:

1. `natural_sort_key(original_name)`;
2. exact original filename as deterministic tie-break.

V1 filename output:

- numeric stem starts at configured `start`;
- width uses configured `padding`;
- the exact final suffix, including original case, is preserved;
- files without a suffix receive only the numeric stem;
- symlinks and non-regular objects are never renamed.

Before a proposal becomes actionable, validate:

- target component is non-empty and has no separator/NUL;
- NAME_MAX and PATH_MAX;
- target remains under ALLOWED_ROOTS and outside reserved quarantine storage;
- no existing target;
- no casefold/planned-target collision;
- no rename cycle.

Child/file renames execute before ancestor directory renames.

## 7. Latest-child prefix

This rule is evaluated independently inside every eligible parent at depth >= 1.

Eligibility:

- direct child must be a real, non-symlink directory;
- excluded/quarantine paths are ignored;
- timestamp authority is `st_mtime_ns`;
- **ctime is not used**.

Selection is fail-closed:

- one unique highest `mtime_ns` → eligible;
- two or more children tied at the highest `mtime_ns` → emit
  `LATEST_CHILD_TIE` blocking conflict for that parent.

V1 only adds the configured prefix to the selected child's proposed target when
it is not already present. It does **not** strip matching text from non-selected
directories because origin ownership cannot be proven.

To avoid self-induced timestamp instability, V1 rejects the combination:

```text
latest_child_prefix.enabled = true
AND
mtime_mode = "ordered"
```

## 8. Single-child wrapper collapse

V1 is intentionally narrow.

Candidate shape:

```text
root/depth1/wrapper/depth3-child
```

Requirements:

- `depth1` itself is preserved;
- wrapper is exactly depth 2;
- wrapper contains exactly one entry;
- that sole entry is a real directory;
- hidden entries count as entries;
- symlinks are never followed;
- target `root/depth1/<child-name>` must not exist;
- filesystem/capability probe must report a supported no-clobber path.

C1 source audit found an important boundary in the existing Gate6-B helper:
`discover_single_child_wrappers()` performs disposable capability probes that
temporarily create and clean probe entries. Those probes are correct for
authoritative utility compilation, but they are not compatible with the stricter
Organizer C1 promise that Preview performs zero namespace writes.

Therefore the freeze is amended as follows:

- **C1 Preview** performs probe-free, descriptor/non-following shape discovery
  only and reports eligible-looking wrappers as `CAPABILITY_UNVERIFIED`;
- C1 never treats a wrapper candidate as mutation-authorized;
- **C3 structural Plan compilation** MUST re-run the existing authoritative
  Gate6-B discovery/capability path and bind its candidate digest immediately
  before draft generation;
- no capability result from C1 Preview may be cached or promoted into execution
  authority.

This is a safety tightening, not a new mutation path.

### Structural operation staging

Wrapper collapse is a structural mutation and is intentionally separated from
rename/touch mutation in V1.

If collapse is enabled:

1. **Stage A — Structural Preview / Plan**
   - preview wrapper candidates;
   - generate exact paired `move` + `rmdir_empty` operations;
   - execute through the existing structural safety primitive.
2. after Stage A completes, **Stage B requires a fresh Organizer Preview**;
3. only then may directory/file/prefix rename operations generate their Plan.

This avoids compiling rename targets against a tree that Stage A is about to
reshape.

### Executor authority amendment

The existing cleanup authorizer currently accepts only Workflow Utility plans.
C3 implementation may extend that authority to a dedicated Organizer structural
plan context, but only by preserving every existing binding:

- exact plan context allowlist;
- exact candidate ID;
- wrapper/child/target metadata;
- valid frozen wrapper identity;
- immediately preceding completed MOVE;
- same source/target binding;
- live descriptor-bound emptiness and pathname binding;
- one non-recursive `rmdir`.

No other Organizer Plan gains `rmdir_empty` authority.

## 9. Proposal and conflict model

The shared compiler uses typed proposal kinds:

```text
directory_rename
file_rename
latest_child_prefix
wrapper_collapse
touch
```

Preview rows expose the user-facing proposal; wrapper collapse may map to two
execution items internally.

Any blocking conflict prevents Plan generation. At minimum:

- TARGET_EXISTS
- PLANNED_TARGET_COLLISION
- CASE_ONLY_COLLISION
- NAME_TOO_LONG
- PATH_TOO_LONG
- RENAME_CYCLE
- SYMLINK_BLOCKED
- OUTSIDE_ALLOWED_ROOT
- RESERVED_QUARANTINE_PATH
- LATEST_CHILD_TIE
- WRAPPER_NOT_SINGLE_CHILD
- WRAPPER_CHILD_NOT_DIRECTORY
- WRAPPER_TARGET_EXISTS
- WRAPPER_IDENTITY_CHANGED
- PREVIEW_CHANGED
- UNSUPPORTED_FILESYSTEM

## 10. Plan persistence

Do not route advanced Organizer structural operations through the current
generic `create_plan()`; it does not preserve the metadata required by the
paired structural authority.

Add a dedicated Organizer compilation persister that stores:

- canonical profile/config digest;
- preview/source snapshot digest;
- stage (`structural` or `rename`);
- profile ID;
- root;
- advanced-rules version;
- per-item expected identity;
- complete structural candidate metadata when applicable.

The existing Freeze / Validate / Execute lifecycle remains mandatory.

## 11. UI contract

Profile editor adds an **Advanced Rules** section. It is collapsed by default
for existing profiles.

Preview clearly separates:

- Stage A structural wrapper candidates;
- Stage B rename/prefix/file proposals;
- blocking conflicts.

When Stage A is required, the UI must not offer a Stage B Plan from the stale
pre-collapse Preview. After Stage A execution it prompts for a fresh Preview.

No advanced rule gets an "execute now" button.

## 12. Implementation gates

### C1 — Schema + shared read-only compiler

- DB migration for `advanced_rules_json`;
- V1/V2 import compatibility;
- shared compiler and digest model;
- depth-aware directory proposals;
- file numbering proposals;
- latest-child prefix proposals;
- wrapper discovery integration;
- **no new mutation authority**.

### C2 — Rename-stage Plan generation

- expected Preview digest binding;
- dedicated Organizer Plan persistence;
- file/directory/prefix rename ordering;
- Freeze / Validate / Execute regression;
- standalone and Workflow Organizer parity.

### C3 — Structural wrapper Plan authority amendment

- dedicated Organizer structural Plan context;
- reuse existing MOVE + `rmdir_empty` pair;
- extend cleanup authority only for this exact context;
- recovery/retry/ABA/no-clobber tests.

### C4 — Frontend

- Advanced Rules editor;
- staged Preview;
- conflict states;
- Stage A → fresh Preview → Stage B UX;
- mobile/dark regression.

### C5 — Closure

- full backend + frontend regression;
- linux/amd64 Docker build;
- isolated real-NAS acceptance under project test root;
- zero test residue;
- closure record.

## 13. Required TDD matrix

C1/C2 must cover at least:

- depth 1 never renamed;
- depth 2+ directory rename;
- independent per-parent file numbering;
- exact extension-case preservation;
- extensionless file numbering;
- hidden/symlink/special-file behavior;
- NAME_MAX / PATH_MAX;
- existing target and planned-target collisions;
- casefold collision;
- ancestor/child rename ordering;
- preview digest mismatch persists zero draft;
- unique newest child prefix;
- latest-child timestamp tie blocks;
- latest-prefix + ordered-mtime rejected;
- V1 profile migration and V2 import/export;
- standalone/Workflow compile parity.

C3 must reuse and extend the existing Gate6-B safety suite for:

- exact single directory child only;
- hidden second entry blocks;
- target exists;
- wrapper/child symlink;
- unsupported filesystem;
- capability-probe cleanup failure;
- candidate digest mismatch;
- child/wrapper ABA;
- target appears after Freeze/Validate;
- third-party object appears before rmdir;
- missing/incomplete predecessor MOVE;
- mismatched candidate binding;
- non-recursive rmdir only;
- recovery after MOVE completed but cleanup interrupted.

## 14. Acceptance boundary

Repository work does not authorize production NAS mutation.

Real-NAS acceptance must use the isolated project test root and synthetic
fixtures. Production data/config must not be used as scratch space. Acceptance
must leave zero project-specific test residue.

## 15. C0 verdict

Architecture is frozen with these core decisions:

- one shared Organizer compiler;
- profile export schema V2 with backward-compatible V1 import;
- advanced rules disabled by default;
- depth-1 directory preservation;
- per-parent recursive file numbering;
- mtime_ns + tie-blocking latest-prefix semantics;
- existing Gate6-B wrapper-collapse safety primitive reused;
- wrapper structural changes staged before rename changes;
- no generic delete/rmdir authority;
- Preview digest binding required for advanced Plan generation.

Implementation may proceed to **C1**.
