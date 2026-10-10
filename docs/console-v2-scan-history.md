# Console v2 — Scan History ledger and deletion guard

## Migrated

- Scan History responsive semantic table, mobile cards and native pagination
- New Console v2 refresh, diagnostics and create-scan trigger buttons, backed by
  the existing official Lucide React icon map
- Truthful loading/empty/error states: unknown data is never shown as zero or
  a stale 'successful' API result
- Radix `ConsoleConfirmDialog` in shared `ScanDeleteButton` for both Scan
  History and Scan Detail consumers; no Ant Popconfirm/Tooltip dependency there
- Deletion availability still determined by existing
  `getScanDeleteAvailability` (terminal states only; dependent plans block)
- Existing async deletion status, query cache invalidation and last-page
  adjustment, server pagination and 3-second active scan polling are unchanged

## Explicit safety and migration boundary

**New scan creation** remains on the original Ant `Form` + `Modal` and
`DirectoryPicker` (including `ALLOWED_ROOTS` input and multi-root behavior)
until the form controls are safely migrated together. Diagnostic modal, Scan
Detail duplicate-group table, classic Dedupe Plan and Advanced Dedupe surfaces
also remain separate migration targets.

No new feature scope; no backend/API/Worker/Plan/Quarantine/real NAS mutation
code changes. Deleting a scan record removes backend scan metadata, not NAS
files. It is blocked for active scans and records with dependent plans.

Six focused regressions were added to the frontend CI runner; existing
Scan lifecycle and dedupe workflow policy tests remain active.

The user will conduct **one unified visual review when all UI screens have
migrated**, not on this intermediate PR. Do not deploy to NAS automatically.
