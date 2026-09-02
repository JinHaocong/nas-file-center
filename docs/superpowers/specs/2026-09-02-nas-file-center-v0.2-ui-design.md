# NAS File Center v0.2 UI + ZFS Compatibility Design

## Goal

Turn the existing API-first NAS File Center into a Chinese, browser-first administration tool while fixing ZFS unsigned 64-bit filesystem identifiers that currently overflow SQLite INTEGER columns.

## Scope

v0.2 includes:

- ZFS-safe persistence for `st_dev` / `st_ino`, including values above signed int64.
- Chinese dashboard with safety-mode visibility.
- Scan creation and scan-result pages.
- Duplicate-group browsing and reclaimable-space summary.
- Dedupe-plan creation with balanced, newest, oldest, first-root, path-priority, and relative-path-priority policies.
- Plan lifecycle UI: draft -> freeze -> validate -> execute, with execute disabled when mutation is disabled.
- Batch rename preview UI.
- 少女映画 P/V/size organizer preview UI.
- Persistent index enqueue and path-match preview UI.
- Work-job, audit-log, and settings pages.
- No external CDN dependency; assets are shipped inside the image so the UI works on a LAN/offline NAS.

## Architecture

Keep a single FastAPI application image. Server-side pages are rendered with Jinja2. Bootstrap 5.1.1 and Bootstrap Icons are bundled locally for the visual component layer, with a small project CSS/JavaScript layer for layout, confirmations, and auto-refresh. No Node/Vite/React build step or runtime CDN dependency is introduced.

The existing JSON API remains stable. UI routes call the same `FileCenterService` methods as the API, so safety checks and execution semantics stay centralized.

## ZFS filesystem IDs

Linux `st_ino` is unsigned and ZFS may return values greater than SQLite's signed int64 maximum. Filesystem identifiers are therefore encoded as non-numeric text before binding to SQLite and decoded back to Python integers on read. The text encoding is deliberately non-numeric so SQLite INTEGER-affinity columns in existing databases do not coerce large values to REAL and lose precision.

This compatibility type is used for device/inode fields in duplicate records, incremental index rows, and frozen batch-plan metadata. Existing small integer rows remain readable.

## Safety

- UI cannot bypass `ALLOW_MUTATION` or `ALLOW_DELETE`.
- Execute controls are visibly disabled in preview-only mode.
- Scan/index/preview operations remain available in read-only mode.
- Dedupe plans still require freeze and SHA256 validation before execution.
- Permanent deletion is not introduced by the UI; quarantine remains the default destructive action.

## UI information architecture

- `/` Dashboard
- `/ui/scans` scans and scan creation
- `/ui/scans/{id}` scan details and duplicate groups
- `/ui/plans` plan list
- `/ui/plans/{id}` plan details and lifecycle actions
- `/ui/rename` batch rename preview
- `/ui/organizer` 少女映画 organizer preview
- `/ui/indexes` persistent index
- `/ui/path-match` direct path matching preview
- `/ui/batch` generic batch-plan creation
- `/ui/jobs` worker jobs
- `/ui/audit` audit events
- `/ui/settings` runtime safety/configuration

## Testing

- Regression test persists and round-trips the real observed ZFS inode `12164156718799206349`.
- UI smoke tests cover dashboard/navigation, scan form submission, scan detail rendering, plan action guards, rename preview, organizer preview, jobs/audit/settings pages.
- Existing API and execution tests must remain green.
