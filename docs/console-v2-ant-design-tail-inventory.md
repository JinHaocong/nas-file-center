# Console v2 — Ant Design Tail Inventory (PR #175)

**Source:** repository-wide recursive import audit against `frontend/src` with
`node frontend/scripts/check-ant-design-tail.mjs` (run inside `frontend`).

## Policy

Zero runtime source modules may import `antd` or `@ant-design/icons`.
Any new or resurrected direct import is a CI failure.
The test script enumerates all runtime source modules and fails on any
unapproved AntD import or stale allowlist entry.
This gate scans all TS, TSX, JS, JSX and CSS source files and is executed
by `npm test` before TypeScript test compilation.

The import inventory is empty. The unused `antd` and `@ant-design/icons`
npm packages, and all now-unreachable transitive lockfile nodes, were removed
together from `frontend/package.json` and `frontend/package-lock.json` in PR #183.

## Remaining direct AntD runtime imports (0 files)

No runtime source modules import Ant Design, and the frontend npm manifest
and lockfile no longer contain Ant Design packages.

## PR #183 — remove Ant Design dependency packages and lock tree

- Drop `antd` and `@ant-design/icons` from `frontend/package.json`, and update npm v3 `frontend/package-lock.json` in the same PR; prune 65 now-unreachable transitive packages while preserving all 156 reachable dependency nodes.
- Add an explicit dependency-tree regression requiring exact manifest/lock root agreement, zero AntD/rc-component artifacts, resolution of every mandatory package and peer dependency, and no orphan lock nodes.
- Docker and CI continue to use `npm ci` from the exact pinned lockfile; no changes to Worker/Plan/file APIs or runtime CSS.

## PR #182 — native ThemeContext, zero AntD source imports

- `src/contexts/ThemeContext.tsx` — remove obsolete AntD ConfigProvider and zh-CN locale dependency; preserve public `useTheme` / ThemeMode API, localStorage key `nfc_theme_mode`, system dark-mode listener and cleanup, and root `data-theme`/`colorScheme` ownership of existing native CSS tokens.
- `src/utils/themeMode.ts` — pure, tested stored tri-state normalization (default light) and effective system dark-mode decision.
- The AntD import gate now rejects all direct runtime imports; legacy premium-visual assertion tests the native CSS contract rather than deleted AntD token config.

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

1. Consolidate historical styling overrides into owned native theme CSS without changing interaction semantics.
2. Run import audit, frontend tests/typecheck/build, full backend regression, Docker and dependency-audit checks.
3. Conduct the requested one consolidated browser visual acceptance after style cleanup.

No physical NAS operations, deployment or broad authority changes are part of this inventory.
