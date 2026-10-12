# Console v2 — Ant Design Tail Inventory (PR #175)

**Source:** repository-wide recursive import audit against `frontend/src` with
`node frontend/scripts/check-ant-design-tail.mjs` (run inside `frontend`).

## Policy

Only the exact one runtime module below may import `antd` or
`@ant-design/icons` until their corresponding native migrations land.
The test script denies new unapproved import sites **and** fails if an
allowlisted file no longer imports AntD but was not removed from this list.
This gate scans all TS, TSX, JS, JSX and CSS source files and is executed
by `npm test` before TypeScript test compilation.

Do **not** uninstall `antd`/`@ant-design/icons` while this inventory is
nonempty, and do **not** edit the npm lockfile independently of package
manifest changes.

## Remaining direct AntD runtime imports (1 file)

| Path | Current dependency / migration consideration |
|---|---|
| `src/contexts/ThemeContext.tsx` | AntD ConfigProvider, locale and theme tokens; remove only once all consumer components migrate |

## PR #181 — consolidate native Organizer fields; remove orphan AntD form

- Removed unreferenced `src/components/workflows/OrganizerProfileFields.tsx`, an obsolete Form.useFormInstance/useWatch implementation. Both active consumers already use the same controlled native `OrganizerSnapshotFields` editor: Organizer `ProfileFormModal` and workflow `OrganizerStepEditor`.
- Existing `hydrateWorkflowOrganizerSnapshot`, `patchWorkflowOrganizerAdvancedRule`, `validateWorkflowOrganizerSnapshot`, and `organizerProfileFormPayload` preserve typed fields, immutable imported snapshots, advanced rules, Stage A/B limits, and allowlisted submission. Added dedicated regression coverage.
- No runtime form/API behavior change, no new root authority, no filesystem operation.

## PR #180 — native Plan Detail lifecycle and ledger

- `src/pages/Plans/PlanDetail.tsx` — native Freeze/Validate/Execute/Undo actions, stable confirmation snapshots, single-flight guard, existing Journal and Stale Rebuild, hardlink/reflink warnings, semantic desktop/mobile PlanItem and pagination.
- `src/utils/planDetailActions.ts` — tested fail-closed lifecycle eligibility for status, Safe Mode, journal evidence and active WorkJob.

## PR #179 — native legacy Workflow Preview / Draft

- `src/pages/Workflows/WorkflowPreviewPanelLegacy.tsx` — native File/Dedupe/Organizer preview, managed roots, readonly Dedupe evidence and explicit immutable compile/preview-digest-bound Draft confirmation.
- `src/utils/workflowLegacyDraft.ts` — standalone safe Draft request normalization and confirmation snapshot guard.

## PR #178 — native Utility Workflow Preview and Draft

- `src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx` — native read-only utility Preview, selectable READY candidates only, explicit desktop/mobile checkboxes, immutable digest/revision-bound Draft confirmation, stale-context fencing and PREVIEW_CHANGED invalidation.
- `src/utils/workflowUtilityDraft.ts` — reusable tested candidate filtering and fail-closed Draft readiness model; does not add runtime root override or execution authority.

## PR #177 — native Completed Scan Picker and Login

- `src/components/workflows/CompletedScanPicker.tsx` — searchable native list with completed-only ScanJob selection; strict safe-integer manual ID, fresh `getScanDetail` status verification and stale-response fencing.
- `src/pages/Login/index.tsx` — native credentials form and tri-state theme select; same AuthContext login and dashboard redirect with single-flight submit.

## PR #176 — native Operation Journal

- `src/pages/Plans/OperationJournalDrawer.tsx` — native read-only ConsoleSheet; all four raw evidence JSON fields, before/after paths, size/inode, server pagination and error/retry preserved.

## PR #175 — migrated modules (seven runtime files)

- `src/pages/Audit/index.tsx` — native desktop/mobile audit ledger and read-only Radix metadata details.
- `src/components/tasks/TaskStatusTag.tsx` — native status badge, canonical Task labels retained.
- `src/components/tasks/WorkerStatusCard.tsx` — native Worker health/heartbeat/loading/error.
- `src/components/plans/StaleRebuildDrawer.tsx` — native guarded digest-authority rebuild sheet, **Draft only**.
- `src/contexts/AuthContext.tsx` — native login/logout notification while retaining authentication API, redirect and session semantics.
- `src/pages/Organizer/index.tsx` — native save success/error notification, same profile mutations.
- `src/hooks/useResponsive.ts` — native resize subscription preserving md ≥768px, xl ≥1200px breakpoints.

## Follow-ups

1. Remove the global AntD ConfigProvider from ThemeContext without changing theme persistence or system mode behavior.
4. Run this import gate plus full frontend, backend, Docker and dependency-audit checks.
5. Only at **zero imports**, remove `antd` / `@ant-design/icons` from package and regenerate the lockfile.
6. Consolidate historical styling overrides and conduct one consolidated browser visual acceptance.

No physical NAS operations, deployment or broad authority changes are part of this inventory.
