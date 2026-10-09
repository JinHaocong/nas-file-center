# Console v2 — Task Center UI migration

## Scope

This iteration migrates the Task Center listing layer to the existing
Console v2 component design system using real `lucide-react` icons:

- Native responsive desktop table and mobile task cards
- New keyboard-accessible `ConsoleSelect` for status/type filters
- Existing `ConsoleButton`, `ConsoleEmpty`, `ConsolePagination` and
  `StatusBadge`, including 20/50/100/200 server-side page size options
- Loading/empty/connection-error states; never show stale tasks as current
  data after a failed query
- `TaskProgress` uses native semantic HTML `progress` with a CSS
  spinner for running tasks whose progress total is unknown

## Invariants

- All seven task status choices and five explicit job types remain available
- Task API filters, pagination and cache keys are unchanged
- Active tasks continue to poll every 3 seconds; elapsed/ETA display
  continues to update each second only when a task is running
- ETA and percentage are calculated by the existing task_utils functions.
  For indeterminate running jobs no fabricated percentage is displayed
- `?task=<id>` deep links and next-task navigation remain supported
- Existing TaskDetailDrawer, TaskDeleteButton, TaskHistoryCleanupModal
  and WorkerStatusCard still own their original behavior and approvals
- No changes to backend, auth, Worker, filesystem mutations, file
  deletion, PathGuard or audit logging

## Intentional next stage

Detail drawer, task deletion confirmation, history cleanup dialog and
other operations pages still use Ant Design; replace these only alongside
carefully tested Radix confirmation/sheet primitives. Native select
rather than new Radix Select package is deliberate at this stage to keep
touch/keyboard accessibility and avoid lockfile drift.

The product owner requested one combined final UI visual acceptance.
This PR is governed by automated CI. No NAS deployment here.
