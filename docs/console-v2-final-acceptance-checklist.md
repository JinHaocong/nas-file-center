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
- [ ] Shared dialogs, select, checkbox, forms and destructive confirmation primitives.
- [x] Workflow builder native action bar, read-only status, Radix mode reset / unsaved-exit / rollback confirmations (PR #149).
- [x] Workflow builder native name/description fields, accessible mode radios, trim validation and dirty guards (PR #150).
- [x] Workflow StepList native add-step action menu, empty state, topology/RBAC safeguards and keyboard support (PR #151).
- [x] Workflow RevisionDrawer Radix sheet, semantic revision history, exact SHA256 copy, guarded rollback (PR #152).
- [x] WorkflowList native unified pagination, responsive list, RBAC-gated archive/permanent-delete confirmations (PR #153).
- [x] Workflow StepCard semantic native card, move/delete/read-only guards; native rename, quarantine and dedupe specification editors (PR #154).
- [x] Native Scan/Move/Touch editors with registered Index Roots, 16-root cap, exact relative subpath and local mtime_ns conversion (PR #155).
- [x] Native Utility managed-root editor and recursive Filter AST: matrix, list values, depth/leaf caps and readonly protection (PR #156).
- [x] Native workflow-only Organizer snapshot import and editable fields: deep-copied profile, live templates, advanced staged rules, readonly and responsive tabs (PR #157).
- [x] Standalone Organizer ProfileFormModal native Radix form, guarded CRUD payload and managed DirectoryPicker root (PR #158).
- [x] Native Organizer ProfileList desktop/mobile table/cards, pagination, guarded copy/delete and Radix JSON import/export (PR #159).
- [x] Organizer ProfilePreview native read-only proposals, root/digest invalidation, Stage A/B conflict gating and shared pagination (PR #160).
- [x] Native first-level directory/file Rename editors using one controlled schema, literal-mode preview, conflict-safe Plan and responsive results (PR #161).
- [x] Native Advanced Regex Rename: typed wire schema, root/rule-bound readonly Preview, collision-safe Plan, semantic responsive results and native mode switch (PR #162).
- [x] Native Filename Audit: read-only scoped Preview, advisory issues, selected-only rechecked Rename Draft, stale-response guards, CSV protection and responsive results (PR #163).
- [x] Native Directory Diff: two-root guarded read-only Preview, canonical single-file SHA256, stale-response isolation, semantic desktop/mobile results and CSV formula protection (PR #164).
- [x] Native Path Match: typed multi-root read-only Preview, native responsive groups, keep-first Quarantine Draft with fail-closed server re-preview, stale-request guards and final Plan lifecycle reminders (PR #165).
- [x] Native Batch: semantic native operation radios, managed path and mapping inputs, checked Draft-only Quarantine/Touch/Move/Rename payloads, duplicate guards and responsive styles (PR #166).
- [x] Native Settings: read-only host security flags, guarded audit/quarantine/resource policy saves, refreshed Audit cleanup confirmations, self-audited clear, RBAC-gated session revocation and accessible responsive native controls (PR #167).
- [x] Native Plan cleanup controls: safe per-plan deletion, legacy metadata cleanup, terminal-only Plan history checklist with Radix confirmations and no AntD; Plans ledger native Toast (PR #168).
- [x] Native single-entry Quarantine restore/unlink confirmations: controlled Radix dialogs, skip/rename/manual path conflict safety, exact DELETE token and dual runtime gates, truthfully scoped hardlink/copy advisory and guarded single-flight execution (PR #169).
- [x] Native Quarantine bulk Restore/Purge dialogs: selection-bound fresh Preview, fail-closed blocked checks, digest-bound Draft-only Plan, exact DELETE and admin/server switches for purge, advisory-only hardlinks, single-flight controls and accessible Radix panels (PR #170).
- [x] Native Quarantine ledger: semantic table/mobile cards, active-only selection, filtered explicit-ID snapshots with stale-result protection, native search/select/pagination/toast and safe Radix confirmation for single and filtered terminal-record cleanup (PR #171).
- [x] Native Indexes root ledger: desktop/mobile semantic records, truthful missing/blocked path state, server pagination, native Radix root selection and safe metadata-only remove confirmations with active-WorkJob guard (PR #172).
- [x] Native Scheduler ledger, typed five-target editor, fixed workflow revision/SHA, Utility Preview-only authority, accessible history sheet and guarded admin Run-now/enable actions (PR #173).
- [x] Native Media integrity ledger: desktop/mobile accessible results, corrupt-only admin selections, read-only analyze/SHA256 queues, exact preview ID/digest fail-closed guards and explicit Plan→Freeze→Validate→Worker deletion confirmation (PR #174).
- [x] Ant Design tail tranche: native Audit ledger/details, Task status/Worker health, guarded Stale Rebuild Draft drawer, Auth/Organizer toasts and responsive Hook; CI-enforced 8-file residual import inventory (PR #175).
- [x] Native Plan Operation Journal read-only evidence sheet: original before/after/metadata JSON, responsive ledger, retry and pagination (PR #176).
- [x] Native Completed Scan Picker and Login: completed-only ID verification, stale-response fencing, guarded native credentials and theme selector (PR #177).
- [x] Native Utility Workflow Preview: only selectable READY IDs, read-only Preview, version/compile-digest-bound Draft confirmation, stale-response guards and PREVIEW_CHANGED recovery (PR #178).
- [x] Native legacy Workflow Preview: managed roots, completed Scan authority, Dedupe safety evidence, Organizer Stage A/B, immutable digest-bound Draft confirmation (PR #179).
- [x] Native Plan Detail: Freeze/Validate/Execute/Undo snapshot-bound lifecycle guards, explicit destructive Radix confirmation, read-only Operation Journal, safe-delete and Stale Rebuild, responsive PlanItem ledger (PR #180).
- [x] Native Organizer field consolidation: both CRUD ProfileFormModal and workflow OrganizerStepEditor already use controlled OrganizerSnapshotFields; remove orphan AntD Form/useWatch module, preserve defaults/payload and advanced Stage A/B safety (PR #181).
- [x] Native ThemeContext: remove final AntD ConfigProvider/locale; preserve light/dark/system preference, `nfc_theme_mode`, media listener and CSS tokens; runtime direct AntD import gate now zero (PR #182).
- [x] Remove `antd` and `@ant-design/icons` from npm manifest and lockfile together, prune unreachable transitive packages, assert lock closure and `npm ci` identity (PR #183).
- [x] CSS ownership cleanup tranche 1: remove dead AntD selectors from Console v2 shell and native Settings composition, enforce zero legacy selectors across owned Console v2 CSS, document cascade boundaries (PR #184).
- [x] CSS cleanup tranche 2: retire 44 AntD-only blocks and 3 mixed AntD selectors from historical v048-detail.css, preserve native mobile pagination/focus/reduced-motion, extend CI zero-selector audit to reviewed legacy layer (PR #185).
- [x] CSS cleanup tranche 3: retire 39 AntD-only blocks and 2 mixed selectors from v048.css; extend native CSS audit to 48 files and provide dry-run-first branch-cleanup utility (PR #186).
- [x] CSS cleanup tranche 4: retire 46 AntD-only blocks and one mixed rule in v050/v051/v055; expand reviewed CSS audit to 51 files and add native focus/responsive regression (PR #187).
- [x] CSS cleanup tranche 5: retire 14 AntD-only blocks and 3 mixed selectors from v052 final audit; expand CSS audit to 52 files (PR #188).
- [x] CSS cleanup tranche 6: retire 94 AntD-only blocks and 4 mixed selectors from v049 workspace, preserving native keyboard focus and mobile pagination; expand audit to 53 files (PR #189).
- [x] CSS cleanup tranche 7: retire 81 AntD-only blocks and 6 mixed selectors from v054 premium workspace; preserve native focus, form notes, reduced motion/transparency and audit 54 files (PR #190).
- [x] CSS cleanup tranche 8: retire 50 AntD-only and 4 mixed selectors from v056 right workspace; preserve native focus, mobile card and ledger surfaces; expand CSS audit to 55 files and update obsolete AntD visual tests (PR #191).
- [x] CSS cleanup tranche 9: retire 287 AntD-only blocks and 10 mixed selectors from root index.css; preserve 901 native rule groups and 39 media wrappers, update legacy native visual contracts and audit 56 files (PR #192).
- [x] CSS cleanup tranche 10: retire 38 AntD-only blocks and 2 mixed selectors from v047 shell/primitives/overlays/responsive; preserve 86 native rule groups, expand audit to 60 sheets and protect native Radix overlays (PR #193).
- [x] CSS cleanup tranche 11: retire 36 AntD-only and 1 mixed selector from components.css, preserve 162 native rules and audit eight already-clean v046/v047 files; raise CSS audit coverage to 69 of 74 (PR #194).
- [x] CSS cleanup tranche 12: retire final 22 AntD-only and 2 mixed selectors in five remaining page layers, preserve native dark theme/responsive composition and add complete 74/74 CSS audit with future-file detection (PR #195).
- [ ] Consolidate remaining historical UI CSS overrides into an owned, maintainable theme system.
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
