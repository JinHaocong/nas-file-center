# Console v2 — Ant Design Tail Inventory (PR #175)

**Source:** repository-wide recursive import audit against `frontend/src` with
`node frontend/scripts/check-ant-design-tail.mjs` (run inside `frontend`).

## Policy

Only the exact eight runtime modules below may import `antd` or
`@ant-design/icons` until their corresponding native migrations land.
The test script denies new unapproved import sites **and** fails if an
allowlisted file no longer imports AntD but was not removed from this list.
This gate scans all TS, TSX, JS, JSX and CSS source files and is executed
by `npm test` before TypeScript test compilation.

Do **not** uninstall `antd`/`@ant-design/icons` while this inventory is
nonempty, and do **not** edit the npm lockfile independently of package
manifest changes.

## Remaining direct AntD runtime imports (8 files)

| Path | Current dependency / migration consideration |
|---|---|
| `src/components/workflows/CompletedScanPicker.tsx` | AntD Select/InputNumber/Tag; must keep completed-only ScanJob selection and manual ID verification |
| `src/components/workflows/OrganizerProfileFields.tsx` | AntD Form instance/useWatch and extensive nested rule editor; migrate together with host profile forms |
| `src/contexts/ThemeContext.tsx` | AntD ConfigProvider, locale and theme tokens; remove only once all consumer components migrate |
| `src/pages/Login/index.tsx` | AntD credential form and theme dropdown; preserve auth redirect and theme/keyboard semantics |
| `src/pages/Plans/OperationJournalDrawer.tsx` | AntD audit journal drawer; preserve physical before/after details |
| `src/pages/Plans/PlanDetail.tsx` | AntD destructive Plan lifecycle controls and detail ledger; preserve each transition guard |
| `src/pages/Workflows/UtilityWorkflowPreviewPanel.tsx` | AntD Preview/Draft controls and utility candidate selection; retain RBAC + revision snapshot |
| `src/pages/Workflows/WorkflowPreviewPanelLegacy.tsx` | AntD legacy preview and dedupe pipeline; retain dirty-state, latest preview request and digest-bound Draft |

## PR #175 — migrated modules (seven runtime files)

- `src/pages/Audit/index.tsx` — native desktop/mobile audit ledger and read-only Radix metadata details.
- `src/components/tasks/TaskStatusTag.tsx` — native status badge, canonical Task labels retained.
- `src/components/tasks/WorkerStatusCard.tsx` — native Worker health/heartbeat/loading/error.
- `src/components/plans/StaleRebuildDrawer.tsx` — native guarded digest-authority rebuild sheet, **Draft only**.
- `src/contexts/AuthContext.tsx` — native login/logout notification while retaining authentication API, redirect and session semantics.
- `src/pages/Organizer/index.tsx` — native save success/error notification, same profile mutations.
- `src/hooks/useResponsive.ts` — native resize subscription preserving md ≥768px, xl ≥1200px breakpoints.

## Follow-ups

1. Finish PlanDetail / OperationJournal and Workflow Preview safety surfaces.
2. Migrate legacy organizer form fields, completed-scan picker and login.
3. Remove the global AntD ConfigProvider once its final consumers have migrated.
4. Run this import gate plus full frontend, backend, Docker and dependency-audit checks.
5. Only at **zero imports**, remove `antd` / `@ant-design/icons` from package and regenerate the lockfile.
6. Consolidate historical styling overrides and conduct one consolidated browser visual acceptance.

No physical NAS operations, deployment or broad authority changes are part of this inventory.
