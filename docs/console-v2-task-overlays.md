# Console v2 — Task Center Radix overlay migration

The product owner requested **one final consolidated UI visual acceptance**.
Every individual PR must pass CI and preserve operational safety.

## Migrated components

- Shared `ConsoleSheet` (Radix Dialog right-side sheet), `ConsoleConfirmDialog`
  with explicit busy guards, focus management and layered portal overlays
- Task detail inspector, status/capability/timing panels and native collapsible
  recovery snapshot/payload inspector using the existing `sanitizeContext`
- TaskDeleteButton: native trigger and Radix confirmation, no permission bypass.
  Reuses `getTaskDeleteAvailability`, API and react-query invalidation logic
- TaskHistoryCleanupModal: native terminal-only checkboxes and Radix dialog;
  still resets statuses on open and refuses an empty selection
- TaskActionBar: existing API/status capability gate for pause/resume/cancel/retry,
  with **explicit secondary confirmations** for cancel/retry
- TaskLogTable: native filtered/paginated event tables and mobile cards, expandable
  redacted context, preserve existing status levels and server API
- Independent portal styling for light/dark themes; nested confirm overlays
  stay above inspector, with 360px mobile handling and reduced-motion support

## Compatibility and hard safety requirements

- No modifications to backend APIs, worker execution, auth, PathGuard, NAS files,
  Quarantine, Plan semantics or immutable Audit records.
- Task deletion is restricted to completed, failed and cancelled statuses.
  Queued/running/paused/cancel_requested states must remain blocked.
- Deletion removes task metadata and Task Logs, never NAS files or Audit.
- History cleanup affects **all matching terminal tasks of all types**, not
  just the currently filtered page. Preserve the scope warning verbatim.
- Task actions remain limited by `getTaskActionAvailability`.
- No duplicate submit or dismiss while mutation is pending; user can retry on error.
- Deep-linked `?task=id` and Inspector/Worker polling remain unchanged.
- Log and checkpoint JSON remains sanitized, never bypass redaction.
- Both native dialog components and their portal color variables support
  keyboard/screen readers and preserve explicit confirm UX.
- In-flight retry success displays a link to its newly created task.
- The old task Ant Design popovers/select/dropdowns are retired in this PR.
- Other operations and screens still use Ant and will be migrated separately.

## Acceptance

Dedicated frontend regression tests and the full GitHub Actions suite.
Browser/mobile visual acceptance remains deferred until the complete UI refresh.
No automatic NAS deployment.
