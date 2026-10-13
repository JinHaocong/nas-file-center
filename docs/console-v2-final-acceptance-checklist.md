# Console v2 Migration — final-acceptance checklist

The product owner requested **one unified visual acceptance at the end**.
Intermediate PRs are gated by automated tests, build, Docker and security checks;
they are not separate visual sign-off requests.

## Visual target

Current approved target is **Pure White v2.1**: neutral white/soft-gray navigation,
charcoal emphasis and clean light workspace. Dedicated dark/system modes remain.
The earlier dark premium shell is historical and is no longer the visual target.

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
- [x] Pure White v2.1 foundation (separate visual redesign): neutral light/dark tokens, white sidebar/header, keyboard-visible charcoal selection, monochrome primary actions, mobile shell, Radix Portal palette, ten detailed CSS regressions. This is **source-level change only**, not final visual sign-off; see `docs/pure-white-v2-visual-contract.md`.
- [x] Pure White v2.1 detail tranche: true Dashboard loading/error placeholders, aligned compact tables, flat quick-action list, native scan status/count typography, mobile records, dark/keyboard interaction; dedicated regressions (PR #197). Source-level only, browser sign-off still open.
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


## Pure White browser Overlay smoke (Stage 5A)

- The UI Validation GitHub Actions workflow now checks actual Chromium computed CSS for the real React ScanCreate / nested DirectoryPicker Radix dialogs at eight widths and four theme/system combinations (32 read-only mocked-API cases).
- Evidence: artifact named `pure-white-overlays-<exact PR HEAD SHA>` containing real Chromium screenshots. Run uses local Vite preview and intercepts `/api/**` exclusively; mutating calls are rejected with 405. The browser never connects to production NAS.
- Check no backdrop blur, confirm modal/scrim z order, background and primary text light/dark contrast, dialog viewport containment, hit testing and inner Escape handling. This covers two modal flows only, not all pages or the user's existing deployment screenshot.
- Before final sign-off, compare actual deployed site and original blurry screenshot, across 360/390/430/768/1024/1280/1440/1920 in light/dark/system; inspect nested modal keyboard focus, busy states, directory allowlist errors and unsafe actions without executing them.


## Pure White browser Tasks / History smoke (Stage 5B)

- UI Validation adds a second read-only Chromium test script covering actual `/tasks` page and Task Sheet → delete confirmation + independent history cleanup modal; 32 theme/viewport cases, 64 screenshots.
- Assert 1100/1101 Sheet, 1300/1301 nested confirm stacking, no backdrop blur, keyboard Escape leaving the parent sheet visible, dark/light content surface, no viewport escape, hit-testing, and no-selected-state destructive action disabled.
- API responses are fixture GET only. POST/PUT/DELETE rejected 405. **No destructive confirm click and no NAS connection**. The screenshots and CI do not replace deployed-site visual acceptance.


## Pure White Stage 5C Quarantine / Plan dialog browser evidence

- Feature-owned z-index fix pairs the existing shared Radix confirm scrim at 1300 with single Quarantine, bulk Quarantine and Plan History **open** dialog content at 1301. No broad/global z-index override or business logic edits.
- CI browser script `frontend/scripts/browser-quarantine-plan-overlays.mjs` checks 32 actual Chromium viewport/theme combinations using read-only synthetic GET APIs, opening Quarantine Restore/Purge and Plan History dialogs without executing restore, unlink, deletion or history clear.
- Evidence: 96 screenshots in `frontend/artifacts/browser-quarantine-plan`, uploaded along with the preceding 96 screenshot files under a PR HEAD-derived artifact. Validate z-index, no blur, pointer hit-test, modal bounds, DELETE exact uppercase, three restore policy choices, and plan no-selection disablement.
- This is not a claim that the original production NAS deployment already contains the fix or that all production UI/permissions have passed end-to-end acceptance.


## Pure White Stage 5D-A — Quarantine Bulk Restore/Purge browser acceptance

- Added fourth real Chromium script: `frontend/scripts/browser-quarantine-bulk-overlays.mjs`; **8 viewports × 4 theme/system combinations = 32 cases** on actual built React/Radix `/quarantine`. Four screenshots per case (blocked/ready Restore and ready/blocked Purge) = **128 screenshots**. Prior stages plus this one target **128 viewport/theme cases and 320 screenshots**, pending exact-HEAD CI.
- Validates 1300/1301 scrim/dialog stack, computed no-blur scrim, dark/light backgrounds, viewport bounds, pointer hit-test, Escape close and retained selection after Restore cancel.
- Exercises active-only selection; disabled controls before selection; Restore skip/rename; policy-change Preview invalidation; blocked-any-member Draft denial; strict uppercase DELETE for Purge; hardlink-survivor and independent-copy advisory distinction.
- **Read-only route safety:** Browser network is limited to localhost Vite. GET API receives synthetic data. The only allowed POST is `/api/quarantine/bulk-preview`, mocked entirely within Playwright and never reaching the backend. Every other non-GET route, especially `/api/quarantine/bulk-plan` and execute/delete routes, is rejected HTTP 405 and asserted absent. Tests never click Generate Draft or any execute/delete confirmation.
- This is not production NAS acceptance. Workflow/Plan lifecycle and remaining visual/CSS review are separate follow-up stages; original deployed blur screenshot must be retested in the real NAS environment.


## Pure White Stage 5D-B — Plan Lifecycle / Stale Rebuild browser acceptance

- A fifth real Chromium runner (`frontend/scripts/browser-plan-lifecycle-overlays.mjs`) covers **8 widths × 4 theme/system combinations = 32 cases**, with four screenshot states per case (**128 new screenshots**): Ready Execute confirmation, read-only Operation Journal sheet, Stale Workflow Rebuild Preview sheet, and Completed Undo confirmation. The expected cumulative matrix after exact-HEAD CI is **160 viewport/theme cases / 448 screenshots**.
- Source-level regression covers Draft Freeze availability (without pressing Freeze), Frozen Validate availability (without pressing Validate), Ready Execute confirmation (never confirming), allow_mutation=false Ready Execute disabled, active-WorkJob Validate/Execute disabled, stale plan Execute absent, stale Workflow rebuild Preview, stale Dedupe requires rescan, Completed Undo confirmation without submitting, and read-only journal disclosure.
- Validate real Radix confirm scrim/dialog **1300/1301** and Sheet scrim/drawer **1100/1101** layers, no backdrop blur, computed light/dark surfaces, mobile bounds, pointer hit-tests, and Escape dismissal.
- Network contract: localhost Vite origin only; GET API is mocked. Only `POST /api/plans/104/rebuild-preview` is permitted as a **locally fulfilled, read-only synthetic Preview**, never forwarded to a backend. All other POST/PUT/PATCH/DELETE (including Freeze, Validate, Execute, Undo, Rebuild Draft and plan removal) are rejected with 405 and asserted absent. No NAS connection or file mutation.
- This is browser evidence for simulated Plan Detail, not production deployment verification. **Workflow Builder Preview and Draft confirmation remain a separate Stage 5D-C task**, as do remaining CSS cascade review and original NAS blur screenshot acceptance. Do not close final Pure White visual sign-off solely from these tests.


## Pure White Stage 5D-C — Workflow Preview / Generate Draft confirmation browser acceptance

- Sixth read-only Chromium runner, `frontend/scripts/browser-workflow-preview-overlays.mjs`, exercises actual Workflow Builder, Legacy File Preview, and Utility Preview at **8 viewport widths × 4 light/dark/system combinations (32 cases)**. Four screenshots per case capture File Draft confirmation, dirty editor, historical revision r1 confirmation and Utility Draft confirmation: **128 new images**. Expected cumulative target after exact-HEAD CI: **192 cases / 576 screenshots**.
- File mode: no Draft before read-only Preview; revision-2 compile-digest Preview permits confirmation without submitting it; changing the registered Index Root invalidates Preview; dirty unsaved editor blocks Preview and Draft. Historical r1 editor is read-only yet can Preview and confirm only its matching revision.
- Utility mode: READY candidate initially selected; even when the simulated server proposes a BLOCKED candidate, it stays unselected and disabled. No selected READY candidates means no Draft. Re-selecting READY allows an explicit confirmation showing only one candidate. Dirty Utility blocks Preview and Draft; archived workflows block both.
- Real Radix confirmation uses 1300/1301 mask/dialog stacking, no blur, correct light/dark surface, pointer hit-testing, viewport containment and Escape closing.
- **Network guard:** local Vite origin only. GETs return synthetic fixtures. Only `POST /api/workflows/41/preview` and `POST /api/workflows/42/preview` are permitted, and these are locally fulfilled read-only Playwright fixtures that never touch a backend. All other POST/PUT/PATCH/DELETE, including `generate-plan`, save, rollback, Freeze, Validate, Execute and Worker actions, receive HTTP 405 and are asserted absent; Draft confirm is NEVER clicked.
- This is simulated browser evidence, not production NAS acceptance. Organizer/Dedupe Preview browser coverage, production blur screenshot retest, remaining CSS convergence and owner sign-off remain open.


## Pure White Stage 5D-D — Organizer Advanced / Dedupe browser acceptance

- Seventh real Chromium script `frontend/scripts/browser-organizer-dedupe-overlays.mjs` covers **8 viewport widths × 4 light/dark/system modes = 32 cases**, four screenshots per case (**128 new**). Target cumulative evidence after exact-HEAD CI: **224 viewport/theme cases / 704 images**.
- Organizer Advanced: a blocking conflict disallows Stage B Draft; Stage A structural Preview requires a fresh Preview before later Stage B; missing `organizer_summary.preview_digest` keeps Stage B disabled even when compile digest exists; ready Stage A and Stage B open separate real Radix Draft confirmations without submitting them.
- Dedupe Workflow: no Preview until a completed Scan is selected; running Scan is not selectable; missing `dedupe_summary` blocks Draft. A fresh summary exposes compile digest, revision r2, selected Scan Job ID, scorer/source/decision digests and `protect_last_file` safety. Changing the Scan ID invalidates Preview and disables Draft; all synthetic Preview requests must pin the exact Workflow revision and completed Scan identity.
- Both confirmations verify computed 1300/1301 mask/dialog stack, **no backdrop blur**, light/dark surfaces, viewport containment, pointer hit tests and Escape.
- **Network isolation:** only localhost Vite. GET API calls are synthetic. The sole allowed non-GET requests are `POST /api/workflows/51/preview` and `POST /api/workflows/52/preview`, fully answered locally by Playwright with readonly fixtures; every other write (Generate Draft, Save, Rollback, Freeze, Validate, Execute, purge) receives 405 and must not occur. No production NAS, Worker or file changes.
- This is browser validation with synthetic inputs, not real NAS deployment acceptance. Remaining CSS cascade review, expanded visual review, and original blur screenshot verification remain outstanding. Do not claim all production states or physical identity have been verified.


## Pure White Stage 5E-A — v056 CSS cascade convergence / real page responsive evidence

- Reviewed Right Workspace v2 (`frontend/src/styles/v056-right-workspace-v2.css`) and **retired 17 source shadows** whose CSS declarations or entire earlier rule blocks were superseded by later selectors or by a stronger earlier `!important`. This is a cascade-preserving reduction (the computed CSS authority is unchanged), not a new visual redesign. Notably Ledger `margin-bottom: 26px` could not win against the existing `0 !important` heading rhythm; Dashboard spacing now has only effective declarations in its original specificity bridge. Preserved mobile media and all API/business/permission code.
- Added real Chromium read-only `browser-workspace-cascade.mjs`: **8 viewport widths × 4 light/dark/system effective themes = 32 browser cases** across actual Dashboard, Plans and Tasks pages, **96 new screenshots**. Test native workspace scroll ownership (one desktop page scroller, mobile normal scrolling), effective theme, layout bounds, Dashboard metric grid, and ledger heading zero margin vs page-owned gap. Candidate cumulative target after exact-head CI: **256 cases / 800 screenshots**, subject to actual job PASS.
- Added source tests that pin the remaining v056 CSS winners and import order; previous seven Chromium suites and CSS ownership audit still run. All GET API data simulated inside Playwright. **Every non-GET API request receives 405 and must be absent; all off-origin traffic blocked.** No NAS, file action, workflow Execute or deployment.
- Only v056 CSS, tests, workflow wiring and acceptance document touched. This does **not** close Stage 5E or final Pure White: comprehensive historical CSS audit beyond v056, wider route visual comparison, real NAS original-blur screenshot acceptance, and production validation remain open.
