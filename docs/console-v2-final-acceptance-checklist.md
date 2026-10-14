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


## Pure White Stage 5E-B — index.css historical cascade / six-page workspace evidence

- Reviewed `frontend/src/index.css` against the later same-selector winners and the actual main.tsx import order. Removed **18 early property declarations** already overwritten later by unconditional same-specificity selectors: Page Eyebrow (3), Page Title (4), Page Description (3), Metric Value (5), Dashboard Layout (3). Preserved their independent first-block properties, later winning declarations, all responsive breakpoints, light/dark tokens, and separate v049/v050/v054/v056 ownership.
- Inspected `v050-layout.css` and `v054-premium-system.css` for same-context duplicate-rule shadowing; neither had candidates for this specific safe cleanup, so they remain untouched. The additional `v049` historical conflicts require a separate tested batch rather than an unverified global reorder.
- Expanded the **existing** real-Chromium `browser-workspace-cascade.mjs` matrix to also cover Indexes, Media and Quarantine ledger pages. Each existing 8-width × 4-theme/system matrix case now screenshots **six actual routes**, checking computed theme, desktop single-scroller/mobile normal scrolling, viewport bounds, ledger PageHeader spacing and Media metric-grid containment: **32 matrix cases, 192 screenshots** (**96 additional screenshots** versus 5E-A).
- Synthetic GET-only fixtures, off-origin blocked and all non-GET API requests denied with HTTP 405 and asserted absent. No production NAS request, file mutation, Worker, Draft, Execute, Purge or deployment. New source-level test pins 18 retired properties, later index winners, import order and the six-page safety/CI contract.
- Target cumulative Stage 5-series Chromium evidence after exact-HEAD success: **256 matrix cases / 896 screenshots**; prior individual suites and their expected counts are unchanged. This still does **not** constitute real production NAS visual sign-off. CSS cleanup outside this narrow batch, dense record states, original blur screenshot comparison and deployment acceptance remain open.


## Pure White Stage 5E-C — historical v049 CSS authority and dense ledgers

- Removed **24** earlier CSS declarations from `frontend/src/styles/v049-workspace.css` after verifying that they were unconditionally shadowed by later declarations of the **same selectors**, with the same or stronger importance. Domains: utility header (5), page header (8), page header copy (1), actions (1), panel header (1), metric grid (6) and metric card (2). No replacement CSS rules or change to runtime components, backend, permissions, dependencies or navigation.
- Extended the existing 8-width × 4 light/dark/system real Chromium workspace matrix: first preserve all **six existing empty-state routes** (Dashboard, Plans, Tasks, Indexes, Media, Quarantine), then visit **populated Plans, Tasks and Indexes ledgers** in the same browser context using synthetic records with long names/paths, failed status/errors, large file counts and active-job badges. Assert two real rows or cards per dense route, mobile card horizontal bounds and desktop table scrollport ownership. **32 matrix cases, 9 screenshots each = 288 screenshot images**, subject to latest-exact-HEAD CI.
- Safety remains unchanged: only localhost Vite, synthetic GET responses, all non-GET API calls rejected with 405 and asserted absent, all external requests denied. No workflow submission, Plan execution, NAS mount, file mutations or deployment.
- Source contracts pin removed shadow declarations, later winners and responsive browser behavior; all previous Chromium suites still execute. Cumulative target after 5E-C PASS: **256 matrix cases, 992 images**.
- Further cascade cleanup, wider populated pages, precise production screenshots, original mask blur reproduction and real NAS sign-off are still open; synthetic fixtures are NOT proof of production NAS visual state.


## Pure White Stage 5E-D — Media / Quarantine dense state, CSS cleanup

- Audited v049 later same-selector cascade and retired **12** fully shadowed earlier properties from `frontend/src/styles/v049-workspace.css`: dense panel border radius; quiet panel border/background; overlay section border/background/radius; overlay section header height/padding/border/background; directory picker gap; mobile pagination background. Verified importance parity for the late winning declarations; no replacement properties, production component changes or backend modifications.
- Expanded the existing 8-width × 4-theme Chromium workspace matrix with **two additional populated routes**: Media (healthy+verified, corrupt+changed with explicit delete eligibility, unknown+unverified), Quarantine (active, conflict, restored). Read-only fixture records use long paths; each route verifies **three real rows on desktop or three cards on mobile**, visible status badges, bounded mobile cards, desktop table-owned horizontal overflow, and exact enabled/disabled selection fences. Previous six empty-state routes and Plans/Tasks/Indexes dense routes remain covered.
- Browser evidence now targets **32 viewport/theme cases × 11 screenshots = 352 images** in this runner (64 new images); cumulative target **256 cases / 1056 screenshots** after exact-HEAD CI. Existing earlier browser suites are unchanged.
- **No NAS operations:** all test API reads locally synthesized, all non-GET API requests denied with HTTP 405 and asserted absent, external origins blocked. The tests do not click destructive actions, create Draft, freeze/validate/execute Plans, mutate files, or deploy.
- This expands automated fixture-based UI evidence only. Production NAS original blur evidence, broader CSS audit and live deployment visual acceptance remain open.


## Pure White Stage 5E-E — Tasks complex-state Chromium acceptance

- Added isolated real Chromium matrix `frontend/scripts/browser-task-ledger-states.mjs` at **8 viewport widths × 4 light/dark/system cases = 32 cases**, with **4 screenshots per case = 128 new screenshots** (long unbroken error in actual Task Detail Sheet, server-side page 2, combined empty filters, and recoverable list API failure). Combined established stage-series target after exact-HEAD CI: **288 matrix cases / 1184 screenshots**. This is a cumulative testing count, not 288 distinct product functions.
- The synthetic task list uses 51 records and checks that page 2 requests `page=2`, that changing status/type resets to `page=1`, and that failure/retry does not mutate task state. Mobile 360/390/430px cards, filter bar, pagination, error alert and Task inspector widths must stay inside the viewport; drawer layer and dim-only overlay are explicitly inspected.
- **Strict read-only gate:** actual Vite/React/Playwright only; every GET API response is served by the local test route, including injected HTTP 503; all non-GET API requests are rejected HTTP 405 and asserted absent, and all non-localhost origins are blocked and asserted absent. No real NAS connection, Plan Draft/Freeze/Validate/Execute, Task delete/retry submission, purge, or production deployment.
- This is an isolated acceptance addition; earlier Stage 5E-D 352 screenshot matrix and historical source assertions are preserved unchanged. The original production NAS overlay blur still requires a fresh deployment screenshot and operator acceptance; synthetic Chromium results cannot close that production concern.

## Pure White Stage 5E-F — Indexes complex-state acceptance

- Added `frontend/scripts/browser-indexes-ledger-states.mjs` running actual Indexes page in Chromium at **8 widths × 4 theme/system combinations = 32 cases**, with **5 screenshots per case = 160 new screenshots**: dense long-path and state badges, page 2, empty create-index form, metadata-only removal confirmation, HTTP 503 list error. Cumulative target after exact-HEAD CI: **320 matrix cases / 1344 screenshots**.
- Uses 21 synthetic index roots, including available with active Worker job, blocked (outside allowed roots), missing and available idle states. Asserts active roots cannot remove metadata, blocked/missing roots cannot reindex, create-index submission is disabled without a root path, and the removal confirmation explicitly states it does not delete NAS files. Tests the real dialog z-index, dim-only scrim, Escape dismissal, pointer hit-test, mobile long-path/card bounds, desktop table scrollport and API-driven page 2.
- **Safety:** browser only visits localhost Vite, every GET API request returns a local simulated response, including the injected 503; all POST/PUT/PATCH/DELETE calls return HTTP 405 and must be absent, and off-origin traffic is blocked and asserted absent. Tests never submit indexing, remove metadata or execute a filesystem operation; no NAS access, production deployment or external API.
- Source-level contract test and exact-HEAD CI artifact upload added. One narrow feature-owned CSS fix: `.nfc-v2-index-create-dialog[data-state='open'] { z-index: 1301; }` places the actual index-create dialog above its `1300` scrim (the generic dialog inherited `1101`, confirmed by the first Chromium RED run at 360px). This adds no new layout or business behavior. No React, backend, schema, permission or configuration modifications. Stage 5E-E and earlier matrices remain in CI. Real NAS original scrim blur remains unverified and needs fresh production screenshots / operator acceptance.

## Pure White Stage 5E-G — Media search/filter, queue-dialog stacking

- Introduced `frontend/scripts/browser-media-ledger-states.mjs`: **8 widths × 4 light/dark/system theme combinations = 32 Chromium cases**, each capturing **7 states / 224 screenshots**: dense 50-row long-path media list with eligible corrupt vs blocked healthy/unknown selection; server-driven page 2; compound video+corrupt+changed filter with page reset; no-result search; analyze queue dialog; SHA256 verify queue dialog; and injected media GET 503 error and retry. With the previously retained suites, the new cumulative acceptance target is **352 viewport/theme cases / 1568 screenshot files** after exact-HEAD CI.
- Index-root options are synthetic and explicitly include available and blocked states; both queue dialogs must start disabled until an available root is chosen. Browser clicks never submit the queue, permanently delete, run a Preview, create/freeze/validate/execute a plan or access NAS. Destructive selection resets on page/filter/search transitions. Long option labels, search controls, mobile cards and desktop table overflow are covered.
- Fixed a Media-owned Radix portal stacking conflict: `.nfc-v2-media-queue-dialog[data-state='open'] { z-index:1301; }` overrides the generic `1101` content layer to sit above the existing shared dim-only `1300` overlay. As in Stage 5E-F, the test asserts the actual dialog z-index and pointer hit-test across all widths/themes; the overlay remains dim-only without blur. This is a narrowly scoped CSS correction, no React component, backend, schema, permissions or new dependency change.
- **Safety**: localhost-only Vite with synthetic GET responses, all non-GET API requests rejected HTTP 405 and asserted absent, off-origin requests denied and asserted absent. Does not run any real NAS job or change production. The original production NAS blur report still needs fresh deployment screenshots and operator sign-off.

## Pure White Stage 5E-H — v049 unconditional CSS cascade audit

- Reviewed the early vs late **identical selectors** in `frontend/src/styles/v049-workspace.css` and retired **23** earlier declarations that had later unconditionally applied counterparts with matching `!important` priority. Scope: floating workspace header (4), header status (1), page header (1), panel header (2), metric card and hover/last-child (7), metric value (1), Settings grid/panels (5), directory browser row (2). **Five** early blocks became empty and were removed.
- Preserved all later winning CSS declarations, every retained early independent property, import order, responsive media queries, focus styles, overlays, feature-owned native CSS, and approved sidebar. This is an isolated historical CSS cleanup; no React behavior, backend, database, NAS mounts, permissions, dependencies, or filesystem operations changed.
- Source regression `frontend/tests/console_v2_pure_white_v049_stage5e_h.test.ts` pins exactly **23** retired property shadows, retained base styles (including `position:sticky`, metric border-right and Settings safety surfaces), exact late winners, and existing read-only Chromium gates.
- **No additional browser cases or screenshot count claimed for this phase**. Rerun all preexisting Chromium suites (including Dashboard/Plans/Tasks/Indexes/Media/Quarantine, modal overlays and complex state matrices) on the latest PR HEAD. Prior target remains **352 matrix cases / 1568 images**; report actual counts only after latest-head CI succeeds.
- Synthetic browser GET fixtures, deny-all non-GET HTTP 405 assertions, and off-origin blockade remain intact; no real NAS activity. Original production NAS blur and live deployment screenshots remain **open**, and source-level CSS convergence does not prove production acceptance.

## Pure White Stage 5E-I — v056 last-winner convergence / remaining-work inventory

- Removed **2** proven shadowed unconditional declarations in `frontend/src/styles/v056-right-workspace-v2.css`: the early Dashboard rail `gap:22px` (late desktop winner `14px`) and early Media page alert `margin:14px 0 18px` (later `12px 14px 14px`). Both early selector blocks became empty. The later rules, breakpoint overrides, independent Media warning styles, native-owned CSS and imported cascade order remain unchanged.
- Regression `frontend/tests/console_v2_pure_white_v056_stage5e_i.test.ts` pins both last winners, medium/mobile responsive rail behaviors, CSS no-Ant boundary, actual workspace layout fixture, localhost-only GET fence and presence of full existing Chromium acceptance in CI. No feature logic, API, mutation authority, dependency, filesystem or NAS change; **no additional screenshot count claimed**.
- **Source checklist snapshot at this phase's starting baseline (`main@9d3f3dfbeb8863b0ed43465d722101e06e98026a`): 67 of 74 checkbox items checked; 7 still unchecked.** Checkbox count is *not* a percent-complete estimate because entries vary greatly in scope and some require production/human authority. Two categories are primarily further code/consolidation: shared native dialogs/select/checkbox/forms/destructive primitives and historical CSS/theme ownership. The other five unchecked categories address full final gates, consolidated browser review, keyboard/focus/contrast/reduced-motion/safety confirmation, real NAS verification, and owner's explicit visual acceptance/deployment authorization.
- **Separately open NAS closure gates**: Organizer C5 and Scheduler S5 require the dedicated labeled self-hosted NAS acceptance workflow on fresh isolated synthetic roots with zero residue; local/synthetic browser and hosted CI cannot close them. H4 Hardlink/Reflink runtime path-pair support remains per-filesystem positive-probe dependent. No percentages or real NAS success should be inferred from source CI.
- Existing Chromium target stays **1568 screenshot files** across all preserved suites until actual candidate-head CI upload is verified. Original production deployment blur and consolidated owner visual sign-off remain OPEN.

## Pure White Stage 5E-J — shared native checkbox consolidation

- Introduced **`frontend/src/components/ui/ConsoleCheckbox.tsx`**, a forwardRef-controlled native `<input type="checkbox">` with explicit `checked`/`onCheckedChange(boolean)` and intrinsic disabled, fieldset, keyboard, focus, accessible name, title and per-page class support. The component itself owns **no RBAC, selection eligibility or mutation behavior** and cannot take `defaultChecked` or override native `type`.
- Migrated **5** explicit checkbox call sites with no DOM element-type change: Media queue root options (available-only, busy fieldset), Media corrupt-only row and page selection (admin, evidence, busy Preview/delete gates), Quarantine active-only row and page selection (including explicit-ID bulk protection). Selection-state snapshots, Preview → Plan lifecycle and shared `ConsoleConfirmDialog` busy/disabled behavior remain caller-owned and untouched. Native input markup/CSS classes, aria labels, disabled predicates and click keyboard semantics are retained.
- Updated existing Media/Quarantine source contract assertions and added `frontend/tests/console_v2_pure_white_shared_checkbox_stage5e_j.test.ts` to pin shared primitive and these five safety gates. No new browser scripts: complete existing read-only synthetic GET Chromium suites, including Media eligibility, Quarantine active-only, overlays and legacy desktop/mobile layouts, must pass on latest PR HEAD before merge.
- Does not mark the broad **shared dialogs/select/checkbox/forms/destructive-confirm primitives** acceptance checkbox complete: other form/dialog ownership still needs scoped audit; owner visual and real-NAS sign-off remain open. Existing screenshot target **1568** images, not a new count. No backend/DB/dependency/permissions/filesystem/NAS activity.

## Pure White Stage 5E-K — shared Select + Confirm fail-closed callbacks

- Audited native shared `ConsoleSelect`, `ConsoleConfirmDialog`, `ConsoleSheet`, Task action/delete and Quarantine cleanup call sites. The owner of RBAC, busy state, destructive eligibility, plan digest and mutation lifecycle remains the **calling feature**, not the shared UI control.
- `ConsoleSelect` now supports `option.disabled` natively and validates each emitted browser change against **exactly one current, enabled option**, rejecting stale, unknown, disabled and duplicate-value events. Existing valid filters (Tasks / logs / Quarantine) are unchanged; the shared primitive never invents a fallback option, selects for a caller or invokes a request.
- `ConsoleConfirmDialog` now defensively checks `busy` before both explicit close callbacks and checks **both `busy` and `disabled` before invoking `onConfirm`**, beyond the existing disabled DOM button, Radix Escape gate and outside-pointer dismissal block. Existing confirmation UI, z-index, text, state owner, per-feature synchronous/async guards and delete authority remain intact.
- Pure `selectModel.ts` provides direct value/option identity regression; new `frontend/tests/console_v2_pure_white_shared_controls_stage5e_k.test.ts` covers disabled/unknown/duplicate filter values, callback locks and existing per-feature authorities. Existing Tasks source tests updated for filtered native `onChange`.
- No new Chromium scripts or screenshot quota: entire existing localhost synthetic GET Chromium matrix, including Tasks nested Sheet + Confirm, Quarantine, Media and the responsive workspace, must rerun at **latest exact PR HEAD**; prior target is **1568 screenshot files**, confirmed only after current CI upload.
- This bounded control safety hardening **does not** close the broad shared dialogs/select/forms/destructive-confirmation migration checkbox or constitute final real-NAS/owner visual sign-off. No server API, backend, database, dependency, mutation, filesystem, production NAS or deployment change.

## Pure White Stage 5E-L — terminal history form single-flight and native control review

- Audited `TaskHistoryCleanupModal`, `PlanHistoryCleanupModal`, shared native Checkbox/Confirm/Select, and other Radix form dialogs. Identified a concrete Task history cleanup **rapid repeated-confirm window**: relying only on React Query `isPending` did not synchronously lock a second handler invocation before React state could commit. The Task handler now acquires a `useRef` guard before **awaiting `mutateAsync`**, posts a cloned terminal-only option snapshot and releases its lock in `finally`. The API, result invalidation, error notices and explicit confirmation remain unchanged.
- Task history **Escape, Radix onOpenChange, close/cancel buttons and checkbox toggling** now also respect that synchronous lock. Existing Plan history already had a synchronous single-flight guard; its explicit close/cancel callbacks and checkbox changes now also check it, closing a dismissal gap when query invalidations outlive a visible pending flag. Neither modal can intentionally submit a second request during the first mutation.
- Both history status selectors now render the existing `ConsoleCheckbox` native `<input type="checkbox">` primitive with the same surrounding labels, status values, fieldsets, semantics and CSS. Tasks permits only **completed, failed, cancelled**; Plans permits only **completed, failed**. Both retain metadata-only cleanup warnings, Audit preservation, server guards and prohibition on deleting real NAS files.
- Added `frontend/tests/console_v2_pure_white_history_stage5e_l.test.ts` with five safety contracts and updated the existing Tasks overlay source assertion. Existing source tests and the complete read-only Vite/React/Chromium suite remain compulsory on the **latest exact PR HEAD**; no new screenshot count is claimed (previous target **1568 PNG**).
- This is a bounded fix, **not** a claim that all shared Dialog/Form integrations have been consolidated or that real NAS acceptance is closed. No new dependency, backend, database, API shape, permissions, filesystem operation or production deployment.

## Pure White Stage 5E-M — scan form single-flight and advanced dedupe callback safety

- Final shared-form/confirmation audit isolated two concrete gaps rather than general refactoring. **Scan creation** only relied on React Query `isPending`, leaving an immediate double-submit window before the next render. `ScanCreateModal` now acquires a synchronous `useRef` lock before an awaited `createMutation.mutateAsync(payload)`, releases it in `finally` on success or failure, and refuses close, Escape or field updates while either the ref lock or `isPending` is set. Existing validation, `ALLOWED_ROOTS` backend authority, exact API payload, toast, invalidations and scan-details navigation remain intact.
- Scan Isolate / A-B checkbox now uses the previously adopted **native** `ConsoleCheckbox` control: same labeled input, checked/disabled states, CSS, keyboard semantics and caller-owned value; no new control library or implicit selection.
- **DedupeActionDialog** now gates close, cancel and confirm callback invocation on `busy` (and present `kind` for confirm), in addition to the already disabled UI buttons, Escape protection and outside-click ban. Ownership of preview digest, action selection, RBAC and Draft → Freeze → Validate → Execute remains outside the dialog. Hardlink/reflink warnings and error recovery are unchanged.
- Updated `frontend/tests/console_v2_scan_create.test.ts` and registered **6 Stage 5E-M safety tests** in `frontend/tests/console_v2_pure_white_modal_guards_stage5e_m.test.ts`; the complete established read-only localhost Vite+Chromium suite must run against the latest exact PR HEAD. No additional visual screenshot quota (existing **1568 PNG** target must be verified from actual CI upload).
- No schema, backend, permission, external dependency, direct NAS access, filesystem modification or production deployment. The high-level shared UI convergence checkbox remains OPEN until an owner-approved consolidated audit; real NAS Organizer C5/Scheduler S5 checks, deployed blur verification and final visual sign-off remain separate gates.


## Pure White Stage 5E-N — Task/Scan delete and password submission single-flight

- Audited shared Confirm/Select/Checkbox and feature-owned forms after Stage 5E-M. Found three remaining feature-owned timing gaps, not an issue requiring another shared dialog implementation: Task delete used only React Query `isPending`; Scan history delete was a fire-and-forget parent `mutate()` callback; administrator password change relied only on React `submitting` state. Rapid callbacks could enter before the next React render.
- Task deletion now synchronously fences the confirm handler with `useRef` and awaits `mutateAsync` through settlement, including the existing async task-list invalidation. Confirmation dismissal is blocked during the synchronous gap; existing terminal-status policy, Task Logs invalidation and toast ownership remain unchanged.
- Scan deletion now uses a feature-owned synchronous `useRef` lock and local busy state. Both desktop and mobile callers pass the awaited parent `mutateAsync`, preserving dashboard/scans invalidation, page-back navigation and failure toast. Close/Escape/Cancel are guarded while in flight, and failed requests remain retryable. Only scan metadata and duplicate-group records are affected, never NAS files.
- Password change now acquires a synchronous lock before the authenticated API request and releases it in `finally`. Repeated submit, close/Escape and changes to the three password fields are blocked during the timing gap. Old-password verification, validation, toast, success close, secret handling and server session invalidation semantics are unchanged.
- Stage 5E-N source-contract tests are registered alongside the full pre-existing frontend suite, and existing Task/Scan/password assertions were reconciled. The exact PR HEAD must pass the existing full CI (including synthetic read-only Chromium); **do not treat those results as production NAS or owner visual acceptance**. No backend/DB/schema/dependency change, storage operation, deployment, or new screenshot quota.
- Shared primitive consolidation and final Pure White sign-off remain OPEN; Organizer C5, Scheduler S5, real-NAS Hardlink/Reflink capability and production backdrop/keyboard/contrast/reduced-motion review remain separate.


## Pure White Stage 5E-O — production screenshot follow-up: nested picker and Plan list title

- Owner-provided deployed screenshots (2026-10-14) show two **still-open production visual regressions**: (1) the Indexes create-root dialog covers its nested DirectoryPicker browser at the side edges, and (2) the Plans list name collapses into a near-vertical column. These issues were not caught by the previous isolated modal screenshot/ledger tests. This is a targeted repair, **not** final deployed acceptance.
- Root cause for Indexes: the create dialog reused the destructive confirmation overlay at **1300** and an extra **1301** content override, covering its own DirectoryPicker at **1200/1201**. Give the create dialog the base Radix overlay/content pair **1100/1101**; keep DirectoryPicker at **1200/1201** and the picker-owned favorite deletion confirmation at **1300/1301**. Metadata removal confirmation remains at **1300/1301**. No new overlay CSS framework, backdrop blur or change to directory selection/ALLOWED_ROOTS authority.
- Root cause for Plans list: `console-v2-plan-detail.css`'s shared `.nfc-v2-plan-table th:first-child { width:70px }` leaked from the PlanItem detail ledger into the 7-column **plan LIST**. Scope PlanDetail table rules to `.nfc-plan-detail-page`; give the list its own stable column widths and long-name wrapping in `console-v2-phase2.css` without affecting the small-screen cards or the PlanItem lifecycle ledger.
- Existing Indexes Chromium runner now asserts the actual nested picker is above the create modal, receives pointer hits, fits the viewport and closes independently on Escape across the existing 8-width/4-theme matrix; Workspace Cascade asserts the real populated Plans list name column does not collapse. **No extra screenshot quota**; existing 1568 synthetic read-only PNG targets remain subject to successful current CI upload. Stage 5E-O source regression registered and legacy Stage 5E-F assertion updated.
- UI Validation continues to block all non-GET and outbound requests in its localhost synthetic dataset; **no production NAS writes**. Real NAS Organizer/Scheduler, Hardlink/Reflink, full deployed visual verification, focus/contrast/motion review and owner sign-off remain separate OPEN gates. No API, backend, permissions, DB, task execution or filesystem operation changed.


## Pure White Stage 5E-P — native DirectoryPicker keyboard focus restoration

- Audit of the remaining shared-dialog/accessibility acceptance gate found a concrete omission in the controlled DirectoryPicker browser: its `Dialog.Root` is opened from native feature-owned buttons and does **not** use Radix `Dialog.Trigger`, so the ordinary Radix implicit trigger-ref focus return cannot be assumed on Escape/cancel. Stage 5E-O checked stacking and pointer hits but did not assert keyboard focus restoration.
- The shared `DirectoryPicker` stores the exact enabled button used to open the browser (single Select, multi Select, or multi empty-state trigger) in a component-owned ref and passes it to the Radix modal; `onCloseAutoFocus` returns focus **only if the opener remains connected and enabled**, and otherwise leaves Radix's ordinary fallback behavior intact. Do not focus a disabled or unmounted launcher; callers retain path/selection and `ALLOWED_ROOTS` authority.
- Expanded the **existing** Indexes 8-viewport × 4-theme Chromium matrix: Escape first closes the nested directory dialog while keeping the create dialog open, focus returns to its launcher, keyboard Enter reopens the directory dialog, Tab remains inside the active nested dialog, and the reopened picker can close explicitly without dismissing its parent. Repeated immediate Escape is not used as a second focus-restoration assertion, avoiding nested Radix FocusScope teardown timing in this synthetic matrix. No additional fixture writes or screenshot quota; the existing 1568 read-only synthetic PNGs must be verified on the latest HEAD. Native user-trigger behavior on live NAS remains to be accepted by the owner.
- This targeted focus fix **does not** claim the full shared primitive audit, final 8-width manual browser review, keyboard/dark/contrast/reduced-motion sign-off, historical CSS consolidation, real NAS Organizer C5/Scheduler S5 or deployment accepted. No backend/API/schema/permissions/filesystem/production operation changed.


## Pure White Stage 5E-Q — disabled caller invalidates open/stale directory selection

- Audited the shared `DirectoryPicker` after Stage 5E-P keyboard focus recovery. Found a separate **caller-disabled transition gap**: the native launcher/input is disabled, but a previously opened controlled Radix directory browser was not closed when its parent became busy; a selection already awaiting best-effort recent-path recording could still invoke the caller's onChange callback after that transition. This is not a claim of a proven live-NAS exploit.
- Fail closed at both boundaries: the shared picker closes its browser on a newly disabled caller, renders its modal closed immediately while disabled, and checks a latest-prop ref before any selection callback. The Radix directory modal also refuses a disabled selection and fences the post-`recordRecent` callback by latest disabled/open state **and** a per-open/session revision (so a previous session cannot write into a reopened picker).
- Keep existing `ALLOWED_ROOTS` server authority, browse/favorites/recent actions, manual path entry, keyboard focus return only to connected/enabled launchers, and exact API request behavior. Add Stage 5E-Q source-contract regressions to the complete frontend test suite and keep all existing 1568 synthetic Chromium screenshots. This source-level async-transition fence is **not** a new real-browser transition simulation or final production visual sign-off.
- No backend, database, permissions, filesystem operation, NAS traffic, dependencies, production deployment, or new screenshot quota. Broad shared-controls acceptance, final CSS consolidation, keyboard/theme/contrast/reduced-motion review, real NAS Organizer C5/Scheduler S5 and owner acceptance remain OPEN.
