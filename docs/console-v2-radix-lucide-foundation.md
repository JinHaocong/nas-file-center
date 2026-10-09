# Console v2 — Official Radix UI and Lucide React foundation

## Status

This PR installs and **actually renders** both libraries; earlier Console v2
PRs only used an independent shadcn-inspired aesthetic and local SVG icons.

### Exact runtime packages

- `@radix-ui/react-dialog@1.1.23` (React 18-compatible accessible dialog).
- `lucide-react@1.47.0` (official Lucide icon components).

All transitive dependencies are resolved by a real `npm install
--package-lock-only` run on GitHub Actions and pinned in
`frontend/package-lock.json`; no handwritten placeholder integrity hashes.

The temporary branch-scoped lock-generation workflow was **removed from the
final PR**. Normal checks must pass `npm ci`, TypeScript, tests and build.

### UI migration

- The existing `ConsoleIcon` API is preserved, but each icon now renders
  its official `lucide-react` component instead of our hand-authored path map.
  Shell, navigation, Dashboard, badges, buttons and feature pages inherit this
  without bulk API changes.
- The administrator password modal is now implemented with Radix
  `Dialog.Root/Portal/Overlay/Content/Title/Description`. Radix handles
  focus trapping and Escape semantics.
- The existing server password-change API, validation rules, pending-request
  dismissal protection and toast messages stay intact.
- Modal portal styles include explicit overlay/content stacking and responsive
  light/dark support. No overlay dismissal without explicit Cancel/close.

### shadcn/ui vocabulary

shadcn/ui is a **copy-into-project component approach**, not a library that
automatically replaces existing Ant Design screens. ConsoleButton,
ConsolePagination, ConsoleEmpty and scoped tokens implement a compatible
product design direction; this PR starts on the official Radix foundations.
There is no claim that `shadcn` CLI, Tailwind or all shadcn templates are
already installed.

### Scope / safety / rollout

Frontend-only. No changes to NAS filesystem, API contracts, authorization,
Plan/Worker/Quarantine execution, recovery or destructive confirmations.
Other business screens still use Ant Design during staged migration.

The owner will conduct **one final unified visual acceptance** after all
component/page migrations. No NAS deployment in this PR.
