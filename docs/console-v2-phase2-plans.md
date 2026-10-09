# Console v2 — Phase 2A: Plans list migration

## User acceptance policy

Visual/user acceptance happens **once at the end of the entire UI migration**, not on
each partial PR. Individual PRs must still pass typecheck, automated frontend/backend
regressions, dependency audit and Docker validation.

## Delivered in this scope

- Native React/HTML `ConsoleButton`, `ConsoleEmpty`, and `ConsolePagination`.
- Unit-tested pagination model handling empty data, late pages and invalid inputs.
- Plans ledger uses a native `table` on desktop and retains dedicated mobile cards.
- Server-side pagination, 3-second active-plan polling, refresh and route navigation
  retain existing API and cache behavior.
- Native console UI layer uses light/dark workspace tokens, keyboard focus states and
  responsive layout; no Ant Table/Pagination/Empty on this page.
- Confirmed the existing `PlanDeleteButton`, `PlanHistoryCleanupModal` and
  `LegacyPlanCleanup` still own their previous deletion safeguards.

## Explicitly deferred

The Plan deletion confirmation, history cleanup and notification adapter **still
use Ant Design** in this phase. This is intentional to avoid weakening irreversible
operations during a page layout migration. Migrate them only together with a
tested accessible confirmation/dialog primitive.

No new npm dependencies are installed by Phase 2A. We are migrating to an
independent shadcn-inspired component system; actual Radix/Lucide package
installation and lockfile update are a later atomic dependency PR.

## Safety

UI-only; backend paths, auth, API contracts, Plan lifecycle, Worker, Audit,
Quarantine, safe-mode gating and file writes remain untouched.
No NAS deployment.
