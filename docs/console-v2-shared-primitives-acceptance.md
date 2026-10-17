# Console v2 — Shared primitive migration acceptance (2026-10-17)

## Decision and boundaries

This evidence closes **only** the *source-level shared dialogs, select, checkbox, forms and destructive confirmation primitives migration* workstream once the exact PR HEAD and the resulting merged `main` pass their required checks. It does not close the separate full-site human visual review, cross-platform/manual screen-reader and focus accessibility sign-off, historical CSS ownership consolidation, Organizer C5/Scheduler S5 real-NAS safety testing, or product owner/deployment authorization.

The audited live codebase contains **115 TSX source files**. All files were traversed, not a curated list. The automated inventory in `frontend/scripts/shared-primitives-acceptance.test.mjs` now runs in `npm test` and fails if:
- a TSX module reintroduces Ant Design runtime imports or the browser blocking `confirm()`;
- a native JSX `<form>` lacks an explicit `onSubmit` owner or a controlled Radix Root has no Portal/Content in its owner;
- any of the five shared native/Radix primitives (button, checkbox, select, confirmation and sheet) disappears or loses its core keyboard/disabled/label/async guards;
- the existing audited shared usages and the explicit selection and destructive business-owner safety contracts unexpectedly disappear;
- the real read-only Chromium overlay/Quarantine/Workflow/Tasks evidence scripts lose CI registration.

## Live callsite inventory

The starting snapshot (`main` before this tranche: `f85642c2`) was read from all **115** application TSX files. Recorded JSX invocation counts are:

| Kind | Audited uses | Source ownership |
|---|---:|---|
| `ConsoleCheckbox` | 8 | Media (3), Quarantine (2), ScanCreate (1), TaskHistory (1), PlanHistory (1) |
| `ConsoleSelect` | 4 | Tasks filters (2), Quarantine (1), Task logs (1) |
| `ConsoleConfirmDialog` | 21 | Task/Scan/Plan/Quarantine, Media, Scheduler, Settings, Workflow, Indexes, Organizer, Download Verification, DirectoryPicker |
| `ConsoleSheet` | 6 | Task Inspector, Dedupe explain, Stale Rebuild, Workflow Revision, Scheduler History, Plan Operation Journal |
| Native JSX forms | 12 owners | Password, Scan, Dedupe, Indexes, Login, Media, Organizer, Quarantine, Scheduler, Workflow, Download Verification |
| Direct Radix Dialog roots | 22 owners | Modal/detail/confirmation/selection flows across the live components and pages |

The CI test **rediscovers all current TSX sources on every run** rather than assuming these are the only future callers. The counts above record the baseline; the test separately checks minimum coverage and outputs machine-readable owner lists in the Actions log for review.

## Safety invariants audited

1. **Button:** defaults to `type="button"`, supports explicit submit, and disables itself while `loading` with `aria-busy`. It does not perform an API operation itself.
2. **Select:** native labeled `<select>`, controlled value, unique and enabled option identity validation, fail-closed stale event behavior.
3. **Checkbox:** controlled native `<input type="checkbox">`, preserves native label/fieldset semantics and existing caller-owned eligibility. This tranche additionally blocks stale/synthetic `onChange` if the checkbox, a parent fieldset, or an `aria-disabled`, `inert` or `hidden` ancestor is inactive. No permission checks or mutations move into the primitive.
4. **Confirmation:** Radix-owned portal/label/focus, blocked pointer-outside dismissal, explicit `busy` and `disabled` callback gates. The feature owner keeps its RBAC, safe-mode and synchronous single-flight locks.
5. **Sheet:** controlled Radix dialog and description, return focus only to a still-connected, eligible opener.
6. **Forms:** native submit ownership inventoried across all TSX; authority, snapshot and mutation handling remain in each feature. The audit does not grant new delete/restore/write authority.

Supporting CI evidence already includes the full exact-HEAD 8-width × 4-theme Chromium overlays, nested Task/Quarantine confirmation matrices, Media/Quarantine checkbox disabled/focus inspection, select stale-option source tests, native password form focus contrast audit, full-route read-only screenshots, all TypeScript/frontend/backend tests and Docker/dependency validations. All browser APIs are intercepted with synthetic GET data and reject non-GET writes with 405. No production NAS files or database were accessed.

## Closure rule

- Merge this PR only if the precise PR HEAD reports **16/16 successful Checks**, **4/4 successful PR Workflows**, `mergeable=true`, `mergeable_state=clean`, and its base SHA matches the current `main`.
- After Squash Merge, independently confirm the new `main` reports **4/4 successful Checks** and **3/3 successful push Workflows**, the merged PR is closed, and the feature branch is removed.
- **Only after both rounds succeed** is this one source-level workstream counted as closed: **69/74 (93.2%)**. The five remaining high-level sign-off items must stay unchecked. An automated result is not a manual/deployed NAS acceptance.
