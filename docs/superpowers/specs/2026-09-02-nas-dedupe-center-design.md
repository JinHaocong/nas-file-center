# NAS Dedupe Center — Design Spec

Date: 2026-09-02
Status: Approved

## 1. Goal

Build a Docker-deployable NAS duplicate-file management service for very large datasets (tens of TB), using fclones as the scanning/hash engine and a thin Python layer for safety policy, planning, verification, deletion, and optional organizer post-processing.

The system must avoid reimplementing high-performance duplicate detection. It must make destructive actions explicit, reviewable, reproducible, and auditable.

## 2. Non-goals for V1

V1 will not include:

- unattended automatic deletion
- multi-user auth/permissions
- scheduled recurring scans
- email/Slack notifications
- reflink/block-level dedupe
- hardlink replacement
- cloud object storage
- distributed scanning across multiple NAS hosts

These can be added after the core safety model is proven on real data.

## 3. Existing engine: fclones

fclones is the only duplicate-scanning engine in V1.

Capabilities used:

- recursive multi-root scanning
- `--isolate` for cross-root matching
- persistent hash cache via `--cache`
- JSON machine-readable output
- built-in device-aware parallel I/O tuning
- size/filename/path filters

The app does NOT call `fclones remove`, `fclones link`, or `fclones dedupe` in V1.

Reason: fclones should be treated as a discovery engine. The application must independently decide which replica to keep and revalidate before any destructive action.

## 4. High-level architecture

Single Docker image for V1:

- FastAPI web/API server
- fclones binary
- SQLite database
- Python policy/planning/execution modules
- server-rendered HTML UI

Persistent host data:

- `/config/app.db` — SQLite
- `/config/fclones-cache/` — fclones persistent cache
- `/config/reports/` — immutable scan JSON / plan exports
- `/config/logs/` — execution audit logs

NAS datasets are mounted under `/data/...`.

Scanning can run against read-only mounts. Destructive execution requires a read-write mount and an explicit application setting.

## 5. Docker safety modes

Two modes are supported by configuration.

### Safe mode (default)

Dataset volume is mounted read-only:

`/host/data:/data:ro`

Capabilities:

- scan
- inspect duplicate groups
- create plans
- validate metadata/hash
- export reports

Deletion is physically impossible.

### Execute mode

Dataset volume is mounted read-write:

`/host/data:/data:rw`

Deletion is still disabled unless both conditions are true:

1. `ALLOW_DELETE=true`
2. user confirms a frozen plan in the UI

This prevents an accidental compose edit alone from enabling deletion.

## 6. Core data model

### scan_jobs

- id
- name
- mode: normal | isolate
- roots_json
- status: queued | running | completed | failed | cancelled
- fclones_args_json
- started_at
- finished_at
- raw_report_path
- total_groups
- total_files_in_groups
- reclaimable_bytes
- error_text

### duplicate_groups

- id
- scan_job_id
- content_hash
- file_size
- member_count

### duplicate_files

- id
- group_id
- root_id
- absolute_path
- relative_path
- top_level_dir
- size
- mtime_ns
- device
- inode

### plans

- id
- scan_job_id
- policy
- status: draft | frozen | validating | ready | executing | completed | failed
- created_at
- frozen_at
- expected_reclaim_bytes

### plan_items

- id
- plan_id
- group_id
- keep_path
- delete_path
- expected_size
- discovery_hash
- verification_hash
- state
- reason

### audit_events

Append-only records:

- timestamp
- operation
- path
- result
- details_json

## 7. Scan workflow

1. User creates a scan job.
2. App validates roots against an allow-list configured in compose/environment.
3. App invokes fclones as a subprocess.
4. Default fclones flags:
   - `group`
   - `--cache`
   - `--format json`
   - `--no-ignore`
   - `--hidden`
5. Optional cross-root mode adds `--isolate`.
6. Raw JSON output is written to `/config/reports/<job-id>.json` first.
7. Only after fclones exits successfully is the report imported transactionally into SQLite.
8. Failed/interrupted runs never create a partial completed scan.

No filesystem mutation occurs during this workflow.

## 8. fclones cache

`HOME` inside the container points at `/config/home`, so the normal Linux fclones cache path becomes persistent:

`/config/home/.cache/fclones`

The application does not parse or modify the cache database directly.

The cache is strictly an optimization, never a source of truth for deletion. Every destructive plan item is independently verified before deletion.

## 9. Plan policies

V1 policies:

### keep-first-root

Prefer replicas under earlier configured roots.

### keep-newest

Keep the replica with newest mtime.

### keep-oldest

Keep the replica with oldest mtime.

### balanced-roots

For cross-root duplicate groups, distribute deletions as evenly as possible between roots.

For the user's previous A/B use case, even duplicate counts should naturally produce near 50/50 deletion distribution.

### Safety constraints shared by all policies

- never delete every replica of a duplicate group
- never schedule a nonexistent path
- never allow keep_path == delete_path
- optionally protect the final file inside a configured top-level directory
- all planned paths must remain underneath configured allowed roots

## 10. Frozen plan

A draft plan can be regenerated at any time.

Before validation/execution, it must be frozen.

Frozen plan records:

- absolute keep/delete paths
- expected file size
- discovered content hash
- inode/device/mtime snapshot where available
- policy used

Once frozen, changes require creating a new plan version. The app never silently rewrites a frozen plan.

## 11. Independent pre-delete verification

Every plan item is verified by Python immediately before deletion.

Required checks:

1. keep file exists and is a regular file
2. delete file exists and is a regular file
3. neither path is a symlink
4. both paths remain inside allowed roots after realpath resolution
5. expected sizes still match
6. keep and delete are different filesystem entries
7. both content hashes match each other
8. hashes match the expected verification value
9. at least one verified surviving replica remains
10. protected-directory rule will not be violated

### Verification hash

Default: SHA-256.

This deliberately re-reads files selected for actual deletion. The expensive second hash is limited to deletion candidates, not the entire tens-of-TB dataset.

If any check fails, that plan item is skipped and logged; execution continues with other safe items.

## 12. Deletion behavior

Deletion uses Python filesystem calls (`os.unlink`) rather than shell interpolation.

No `shell=True`.

No wildcard deletion.

No recursive directory deletion in V1.

An execution summary reports:

- planned
- deleted
- skipped-safe
- failed
- bytes reclaimed

Audit records are appended for every item.

## 13. Organizer profiles

Post-processing is plugin-like and optional.

A generic dedupe scan never renames folders or touches timestamps unless an organizer profile is explicitly selected.

### `少女映画` profile

Features:

- count images (`P`) by configured extensions
- count videos (`V`) by configured extensions
- sum actual bytes recursively
- strip only recognized trailing statistics blocks
- preserve title brackets such as `[存疑]`
- rewrite exactly one final `[P V SIZE]` block
- optional ordered mtime refresh for multiple roots

Example ordered refresh:

1. 百度网盘2
2. sleep configurable interval
3. 百度网盘1（更新）

This profile is isolated from the generic duplicate engine.

## 14. Web UI V1

Pages:

### Dashboard

- recent scans
- running scan status
- completed plans
- total reclaimable bytes

### New scan

- scan name
- one or more configured roots
- normal vs isolate
- minimum file size (optional)
- filters (optional)

### Scan result

- duplicate group count
- duplicate member count
- reclaimable bytes
- sortable groups
- path/root distribution
- generate plan button

### Plan

- policy selector
- proposed keep/delete per group
- root-level deletion summary
- directory-level deletion summary
- expected reclaim
- freeze plan

### Validation / Execute

- run independent validation
- show pass/fail counts
- execution button only when ready and deletion is enabled
- live/progressive audit output

### Organizer

- choose completed execution
- choose organizer profile
- preview renames
- apply renames
- refresh mtimes

## 15. API surface V1

- `GET /api/health`
- `POST /api/scans`
- `GET /api/scans/{id}`
- `GET /api/scans/{id}/groups`
- `POST /api/scans/{id}/plans`
- `GET /api/plans/{id}`
- `POST /api/plans/{id}/freeze`
- `POST /api/plans/{id}/validate`
- `POST /api/plans/{id}/execute`
- `POST /api/organizers/preview`
- `POST /api/organizers/apply`

Long-running work is represented by persisted job state. V1 uses one worker process at a time to avoid saturating NAS disks with concurrent scans.

## 16. Concurrency and NAS load

Only one disk-intensive task can run at once:

- scan
- SHA verification
- delete execution
- organizer full-tree recount

The app enforces a global lock in SQLite.

fclones default device-aware parallelism is retained initially. Advanced users can override thread settings per scan later.

## 17. Recovery behavior

### Container restart during scan

Mark the previous running scan as interrupted on startup. Raw partial report is retained for diagnostics but not imported as a completed scan.

### Restart during validation

Validation can be rerun from the frozen plan.

### Restart during deletion

Each successfully deleted item was already persisted to audit log. On resume, missing delete files are checked against the completed audit event and treated as already done, not blindly retried.

### Database backup

Before each destructive execution, copy SQLite DB to:

`/config/backups/app-<timestamp>.db`

## 18. Security

- no host Docker socket mount
- no privileged container
- no shell interpolation of file names
- filesystem roots are configured server-side, not arbitrary client paths
- path traversal rejected after resolved-path check
- web service binds to LAN address by compose configuration
- V1 assumes trusted home-LAN users; authentication is deferred

## 19. Performance strategy for tens of TB

- use fclones persistent cache
- keep scan JSON on persistent fast storage
- SQLite in WAL mode
- bulk inserts inside transactions
- only store duplicate members, not every unique file, in V1
- second SHA-256 only for frozen deletion candidates
- prevent parallel scans
- expose minimum-size filtering to avoid wasting I/O when desired

## 20. Testing

### Unit tests

- fclones JSON parser
- each plan policy
- balanced-root allocation
- protected-directory rule
- stat suffix stripping
- organizer P/V/size calculation
- path containment checks

### Integration tests

Create temporary directory trees containing:

- duplicate files
- unique files
- unicode/Chinese paths
- spaces/newlines in filenames where supported
- symlinks
- hardlinks
- files changed after planning
- files deleted between planning and execution

Use a fake or tiny real fclones scan.

### Destructive safety tests

- deletion disabled by default
- read-only mount behavior
- plan cannot execute before freeze+validation
- changed file causes skip
- hash mismatch causes skip
- final protected directory file cannot be removed

## 21. Proposed project structure

```
nas-dedupe-center/
  compose.yaml
  Dockerfile
  pyproject.toml
  app/
    main.py
    config.py
    db.py
    models.py
    scanners/
      fclones.py
      parser.py
    planning/
      engine.py
      policies.py
    execution/
      verifier.py
      executor.py
    organizers/
      base.py
      shaonv.py
    web/
      routes.py
      templates/
      static/
  tests/
  docs/
    superpowers/specs/
  config.example.env
```

## 22. V1 acceptance criteria

V1 is complete when it can safely demonstrate the following on NAS data:

1. Deploy with Docker Compose.
2. Mount a large data root read-only.
3. Run a fclones scan with persistent cache.
4. Import JSON and browse duplicate groups.
5. Create a balanced deletion plan.
6. Show exact expected reclaim and root/directory deletion counts.
7. Freeze the plan.
8. Independently SHA-256 validate all candidates.
9. In read-write + ALLOW_DELETE mode, execute only validated items.
10. Produce a complete audit log.
11. Run the `少女映画` organizer in preview mode and apply mode.
12. Recount P/V/size and perform ordered mtime refresh without changing file count.

## 23. Key implementation decision

fclones is a dependency, not the authority for destructive actions.

Discovery:

`fclones -> JSON -> SQLite`

Destruction:

`SQLite frozen plan -> Python verifier -> Python unlink -> audit log`

This separation is the central safety property of the project.
