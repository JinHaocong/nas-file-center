# Console v2 — Scan Detail read-only duplicate groups

## What changed

- Replace Ant Design Scan Detail buttons, indicators, Table, nested Table,
  Tooltip, Pagination, Empty, Alert and Spin with native Console v2
  equivalents and official Lucide icons.
- Desktop duplicate-group table with accessible expanded rows and a semantic
  nested table for root ID, relative/full paths and member size. Full content
  hash remains available through the native title tooltip.
- Mobile duplicate-group cards and member detail expansion remain.
- Preserve server-side 10/20/50/100 pagination, clear expansions on page and
  scan changes, and maintain 3-second polling for queued/running scans.
- Distinguish scan detail API errors, invalid IDs, group query errors, loading
  and genuinely empty result sets without fabricating zero-result data.
- Reuse the shared responsive descriptions, CodePath renderer, Radix scan
  deletion guard, and current diagnostic / classic-plan modals.

## Safety and operation contracts

- This is a **read-only snapshot presentation migration**, not a new
  deduplication algorithm or a file operation.
- Scan deletion retains the existing terminal-only and dependent-plan guard.
- Classic Dedupe Plan and Advanced Dedupe are offered only for completed
  scans with positive group counts. Their underlying Plan / SHA256 / Execute
  authority remains unchanged.
- No backend/API/Worker, filesystem write, quarantine, audit or PathGuard
  code changes. No new npm dependency.
- The classic plan creation modal, diagnostic modal, shared CodePath component
  and the Scan History new-scan form still contain legacy Ant Design code.
  They need their own safe, focused migrations.

## Validation and acceptance

Six focused frontend regression tests plus normal frontend/CI/build and
backend/Docker checks. This PR is not full Ant removal; user requested one
unified final visual acceptance after the entire UI migration, not per PR.
No deployment to production NAS.
