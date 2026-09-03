# NAS File Center V1 — Expanded Design Spec

Date: 2026-09-02
Status: Approved

## 1. Goal

Build a Docker-deployable NAS file batch-processing and duplicate-management center for datasets measured in tens of TB. The service uses mature existing engines where they are strongest (fclones for exact duplicate discovery and persistent hash caching) and a thin Python layer for user-specific policies, previewable batch operations, safety checks, execution, audit, and organizer profiles.

The central product concept is not “a duplicate finder”. It is a **plan engine for filesystem changes**:

`select/index -> build plan -> preview -> freeze -> verify -> execute -> audit -> optional post-process`.

## 2. V1 capabilities

### 2.1 Batch file/directory operations

V1 supports previewable plans for:

- rename files or directories
- regex search/replace
- prefix/suffix insertion
- sequential numbering and zero-padding
- parent-name/path-based name composition
- move files or directories within allowed roots
- touch/mtime refresh in an explicit order
- quarantine files instead of permanent deletion
- remove empty directories only when explicitly requested
- flatten one wrapper-directory level when the destination is conflict-free

Every mutation must have dry-run output, collision detection, allowed-root validation, and audit events.

### 2.2 Metadata/stat naming templates

A template engine can derive directory names from recursive content statistics.

Required variables:

- `{images}`
- `{videos}`
- `{files}`
- `{folders}`
- `{size}`
- `{name}`
- `{index}`

The existing MediaCollection convention is a profile using a template equivalent to:

`{name} [{images}P {videos}V {size}]`

When videos are zero the profile may omit the `V` token. Repeated previous stat suffixes are stripped before rendering, while semantic brackets such as `[存疑]` are preserved.

### 2.3 Exact duplicate discovery

fclones remains the V1 duplicate discovery engine.

Used features:

- recursive multi-root scanning
- `--cache`
- JSON output
- `--isolate` when requested
- size/path/name filters
- configurable threads

The app never calls fclones destructive subcommands.

### 2.4 Duplicate keep policies

A duplicate group is discovered by exact content. The policy engine then decides which path survives.

V1 policies:

- `keep-first-root`
- `keep-newest`
- `keep-oldest`
- `balanced-roots`
- `path-priority`: ordered path/pattern priorities choose the survivor
- `relative-path-preference`: prefer a replica whose relative path best matches a configured preferred path rule

Shared constraints:

- at least one replica survives
- optional top-level-directory “never empty” protection
- paths must remain within allowed roots
- symlinks are never deletion targets
- deterministic tie-breaking by normalized path

### 2.5 Path matching

Path matching is a selection/policy feature, separate from content equality.

V1 can:

- find same relative path across two or more roots
- find same basename/stem
- regex-normalize a path before matching
- intersect path matches with exact-content duplicate groups

Default destructive dedupe always requires exact-content verification. Path matching alone never authorizes deletion.

### 2.6 Time-aware handling

Supported time sources in V1:

- filesystem mtime
- indexed first-seen timestamp

Policies may retain newest or oldest. Ordered mtime refresh is a batch operation so users can deliberately make one root newer than another after processing.

EXIF/media-embedded timestamps are deferred to V2.

### 2.7 Incremental index

The service maintains its own lightweight file index for UI/filter/path operations while fclones maintains the expensive content-hash cache.

Indexed fields:

- absolute path
- root id
- relative path
- basename/stem/suffix
- size
- mtime_ns
- device/inode
- is_dir
- first_seen_at
- last_seen_at
- scan_generation

Unchanged entries are identified by stable metadata. fclones cache remains authoritative only for scan acceleration, never deletion safety.

### 2.8 Dry run, frozen plans, execution

All mutations use the same plan lifecycle:

- `draft`
- `frozen`
- `validating`
- `ready`
- `executing`
- `completed | partial | failed | cancelled`

Frozen plan items capture expected metadata and cannot be silently rewritten.

### 2.9 Deletion safety and quarantine

Default “delete” behavior is quarantine, not unlink.

Quarantine path lives under a configured root such as `/data/.nas-file-center-trash/<plan-id>/...` and preserves enough relative path information to restore manually.

Permanent unlink requires an explicit operation type plus `ALLOW_DELETE=true`.

For exact-dedupe plan items immediately before mutation:

1. keep/delete files exist and are regular files
2. neither is a symlink
3. paths resolve inside allowed roots
4. sizes match expected values
5. filesystem identities differ
6. streaming SHA-256 of keep and delete match
7. protected-directory constraints still hold
8. audit event is written for success/skip/failure

### 2.10 Resumability

Plans execute item by item with persisted state. A restarted container can resume uncompleted items without repeating completed operations.

Only one disk-intensive task may run at once.

### 2.11 Audit and rollback information

Every action records:

- plan id/item id
- operation kind
- source path
- destination/keep path where applicable
- expected metadata
- actual result
- timestamp
- reason/error

Rename/move/quarantine operations record enough information for a future V1.1 “reverse plan” command. Automatic rollback UI is not required in initial V1.

## 3. Architecture

Single image V1:

- FastAPI + server-rendered Jinja UI
- SQLite/WAL
- fclones 0.35.0 binary
- Python modules for indexing, planning, execution, rename/stat templating and organizer profiles

Persistent mounts:

- `/config/app.db`
- `/config/home/.cache/fclones`
- `/config/reports`
- `/config/logs`

Data is mounted beneath `/data`.

## 4. Module boundaries

- `app/indexing/`: enumerate and incrementally index paths
- `app/scanners/`: fclones invocation and report parsing
- `app/planning/`: duplicate keep policies
- `app/batch/`: generic mutation plan builders (rename/move/touch/quarantine/flatten)
- `app/execution/`: preflight checks and guarded mutations
- `app/organizers/`: optional domain profiles such as MediaCollection
- `app/web/`: HTTP/UI

No organizer code may be imported by the generic scanner/planner/executor modules.

## 5. V2 explicitly deferred

- perceptual image duplicate detection
- video fingerprint/transcode-similarity detection
- EXIF/media metadata preference policies
- hardlink/reflink/block-level dedupe
- scheduled unattended destructive jobs
- distributed workers
- multi-user permissions

## 6. Acceptance criteria

V1 is acceptable when:

- exact duplicate discovery uses fclones and persistent cache
- existing policy tests pass, including balanced A/B behavior
- rename/stat template plans are deterministic and collision-safe
- same-relative-path matching can be previewed without authorizing deletion by itself
- quarantine is the default destructive destination
- permanent deletion cannot occur unless explicitly enabled
- exact-dedupe execution re-hashes both replicas before mutation
- plans persist item states and can resume
- every mutation is audited
- Docker Compose defaults dataset mounts to read-only
- the MediaCollection profile can reproduce the P/V/size suffix and ordered mtime workflow used manually previously
