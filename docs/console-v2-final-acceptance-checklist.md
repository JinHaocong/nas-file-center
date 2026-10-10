# Console v2 Migration — final-acceptance checklist

The product owner requested **one unified visual acceptance at the end**.
Intermediate PRs are gated by automated tests, build, Docker and security checks;
they are not separate visual sign-off requests.

## Visual target

Dark premium navigation with a clean light workspace by default, matching the
approved NAS File Center mockup. User-selectable dark/system modes remain.

## Workstreams

- [x] Dark/sidebar, responsive shell, header and real-data Dashboard (PR #131).
- [x] Native Plan ledger, pagination, buttons and empty states (PR #132).
- [x] Native administrator password dialog + toast provider (PR #133).
- [x] Official Radix Dialog + Lucide React dependency integration (this PR).
- [x] Task Center list, filtering, pagination, error views and progress UI (this PR).
- [x] Task Inspector Sheet, task actions, delete/cleanup confirmation and event logs (this PR).
- [x] Scan History list/pagination and scan deletion confirmation (this PR).
- [x] Scan Detail read-only duplicate groups, member expansion and pagination (this PR).
- [x] Scan creation native fields, normalization and submission (this PR).
- [x] DirectoryPicker native single/multiple path inputs and allowed-root breadcrumb (partial; PR #140).
- [x] DirectoryPicker browser/favorites/recent Radix modal and Scan creation outer Radix dialog (PR #141).
- [x] Classic Dedupe Plan creation + read-only pair diagnostic dialogs (PR #142).
- [x] Advanced Dedupe native candidate table, page-local filters and server pagination (PR #143).
- [x] Advanced Dedupe page native actions, Radix Draft confirmation and stale-preview recovery (PR #144).
- [x] Shared Advanced Dedupe scorer editor: native accessible mode radios, factor weights, ordered rules and reset (PR #145).
- [x] Advanced Dedupe read-only authority/safety lineage and role-guarded storage action panels (PR #146).
- [x] Advanced Dedupe Radix decision explanation sheet + native read-only preview summary (PR #147).
- [x] Shared copyable CodePath: native full-text path, explicit copy, non-HTTPS fallback and responsive focus (PR #148).
- [ ] Remaining Ant screens and shared controls.
- [ ] Shared dialogs, select, checkbox, forms and destructive confirmation primitives.
- [x] Workflow builder native action bar, read-only status, Radix mode reset / unsaved-exit / rollback confirmations (PR #149).
- [x] Workflow builder native name/description fields, accessible mode radios, trim validation and dirty guards (PR #150).
- [ ] Workflow StepList, RevisionDrawer, WorkflowList, organizer, rename/file tools, settings and remaining pages.
- [ ] Remove all `antd` and `@ant-design/icons` imports and their lockfile dependencies.
- [ ] Consolidate historical UI CSS overrides into an owned, maintainable theme system.
- [ ] Full TypeScript, frontend unit/regression, backend, Docker and dependency-audit gates.
- [ ] One final browser review: 360/390/430/768/1024/1280/1440/1920 px.
- [ ] Keyboard navigation, focus management, dark-mode contrast, reduced motion and
      destructive confirmations.
- [ ] Verify against real NAS when a safe test environment is available.
- [ ] Get owner's single consolidated visual acceptance; deploy only by explicit
      deployment action when approved.

## Guardrails

Do not turn console appearance changes into new capabilities or backend behavior:
auth/session, Plan/Task lifecycle, Worker controls, path guards, quarantines, real
filesystem writes, irreversible operations and audit semantics remain unchanged.
No screenshot-only mock data in runtime.
