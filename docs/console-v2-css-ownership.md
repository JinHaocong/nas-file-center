# Console v2 — CSS ownership, staged retirement (PR #184)

The CSS migration is distinct from the completed **Ant Design dependency** retirement.
As of PR #183 the application has zero AntD dependencies, but historical CSS still
contains selectors for removed Ant components. Deleting broad history without a
browser pass would risk unintentionally altering the CSS cascade.

## Import and ownership order (actual `frontend/src/main.tsx`)

1. `src/index.css` — historical app defaults, older UI rules and accumulated
   v0.4.x amendments. AntD selectors retired under PR #192; live native declarations remain.
2. `src/styles/v047.css` through `v056-right-workspace-v2.css` — older UI
   versions and workspace refinements. Keep them in existing order while their
   live native selectors and interactions are identified.
3. `src/styles/pages/settings.css` — current Settings page composition authority.
4. `src/styles/console-v2.css`, `console-v2-phase2.css`, and
   `console-v2-*.css` — owned native Console shell, primitives and page modules,
   loaded last. Their layout, dark-mode and responsive rules are retained.

**CSS cascade invariants:** do not reorder entrypoint imports, change specificity,
move a selector across media conditions or silently override `!important`. These
could change actual computed styles even when unit tests still pass.

## PR #184 — first safe cleanup

- Removed obsolete AntD-only styling from `src/styles/pages/settings.css`.
  Preserved native Settings grid, session panel, control layout and responsive
  rules, including native selectors in former mixed Ant/native selector groups.
- Removed the obsolete `.ant-tag` header status override in
  `src/styles/console-v2.css`, retaining native status variants and dark states.
- Introduced `scripts/check-console-css-ownership.mjs`, run by `npm test`, to
  reject new `.ant-*` CSS selectors in all 45 owned `console-v2*.css` files
  and the native Settings page CSS. Other historical styles remain out of
  scope and are not falsely declared clean.
- Added regression tests for ownership boundary, native Settings breakpoints,
  shell status/focus/dark behaviors, import ordering, and Plan/Settings authority.

## PR #185 — second safe cleanup: reviewed v0.4.8 detail layer

- Removed 44 obsolete AntD-only CSS rule blocks from `frontend/src/styles/v048-detail.css` and removed old selectors from 3 mixed declarations, retaining all original native rule bodies and relative cascade positions. Native `.nfc-row-actions:focus-within`, `.nfc-mobile-pagination` and reduced-motion styles remain.
- Removed now-empty historical AntD section headers. The reviewed detail layer contains zero `.ant-*` / `.anticon` selectors.
- Extended the ownership preflight to check the reviewed v048 detail stylesheet alongside the 45 Console v2 and Settings-owned styles (47 total checked files), including `anticon` selectors. Added focused regression coverage and replaced the stale v0.4.8 test that demanded AntD alert and empty-state DOM classes with native details and pagination guarantees.
- The broader `src/index.css`, `v049-workspace.css`, `v054-premium-system.css`, and `v056-right-workspace-v2.css` retain historical rules pending separate review, with no false zero-residual claim.

## PR #186 — reviewed v0.4.8 base CSS and branch maintenance

- Removed 39 pure AntD CSS rule blocks from `src/styles/v048.css` and obsolete selectors from two mixed groups. Preserved native data panels, metrics, snapshot notices, form hints, themed tokens, responsiveness and reduced-motion declarations.
- Added `v048.css` to the CI CSS ownership guard (48 reviewed files), updated the old v048 tests and added a dedicated regression test.
- Added `scripts/cleanup_merged_branches.py` with `docs/merged-branch-cleanup.md` and offline fixture tests. Defaults to dry-run, requires exact merged PR head, prevents deletion of protected, open or unmerged branches, and requires explicit `--execute`. No branches were deleted as part of PR #186.

## PR #187 — reviewed v0.5.0/v0.5.1/v0.5.5 native CSS

- Retired 46 unreachable AntD-only declaration blocks (12 in v050-layout, 33 in v051-product-polish, 1 in v055-workspace-breathing); removed AntD from 1 mixed v051 row-actions selector while retaining native `.nfc-row-actions:focus-within` declarations at the original cascade position.
- Preserved real v050 operational/dashboard layouts, v051 mobile records/overlays and v055 responsive workspace rhythm. No stylesheet reorder or application behavior changes.
- Extended CI's zero `.ant-*`/`.anticon` CSS audit from 48 to **51 reviewed files**, and added native focus/responsive/import-order regression tests.
- Leave `index.css` and `v056-right-workspace-v2.css` pending independent review; no claim of completed browser visual acceptance.

## PR #188 — reviewed v0.5.2 final audit layer

- Removed 14 unreachable AntD-only CSS blocks from `v052-final-audit.css`; removed AntD selectors from 3 mixed groups while preserving native Settings labels, directory secondary-item transitions and reduced-motion rules.
- Preserved native page composition, keyboard focus, directory picker and mobile breakpoints in their original cascade order; no import reordering or business behavior changes.
- Expanded CSS ownership audit from 51 to **52 reviewed files** and added dedicated regressions for native focus/responsive/mixed-selector survival.
- Browser visual acceptance is still pending; this cleanup does not constitute a browser pass or production deployment.

## PR #189 — reviewed v0.4.9 workspace layer

- Retired 94 dead AntD-only CSS rule groups from `src/styles/v049-workspace.css` and removed 4 AntD members from mixed groups. Preserved the exact native declarations and source order, including keyboard `.nfc-row-actions:focus-within`, both native mobile pagination groups, and the native reduced-transparency header/page surface.
- Removed one now-empty AntD-only mobile media block. All other media queries, existing native CSS rule bodies and cascade imports remain intact.
- Expanded the CSS ownership audit from 52 to **53 files**, with 5 focused native regressions registered in the full frontend test runner.
- This is a source/CSS cleanup only; browser visual acceptance and production NAS deployment remain outstanding.

## PR #190 — reviewed v0.5.4 premium workspace layer

- Retired 81 dead AntD-only CSS rule groups and removed AntD selectors from 6 mixed groups in `src/styles/v054-premium-system.css`.
- Preserved all 177 native selector/declaration groups and all original media breakpoints and import order, including status badge, row-actions keyboard focus, reduced-motion surface transitions, form hints, overlay geometry and reduced transparency.
- Expanded zero legacy selector audit to **54 reviewed/owned files** and added 5 native regression tests in the full frontend suite.
- Browser visual acceptance remains pending; no NAS deployment or filesystem mutation.

## PR #191 — reviewed v0.5.6 right workspace layer

- Retired 50 unreachable AntD-only rules and stripped obsolete AntD selectors from 4 mixed rule groups in `src/styles/v056-right-workspace-v2.css`.
- Retained all **339 native selector/declaration groups**, original responsive media queries, cascade order, native keyboard row-action focus, ledger width, shell-card contracts, and mobile card radius.
- Replaced five stale v056 AntD visual test assertions with active native table labels, accessible dialog/footer, ledger headers, card surfaces and focus protection; updated historic ownership expectation.
- Expanded CSS ownership audit from 54 to **55 reviewed files**, registered six dedicated native regression tests.
- `src/index.css` remains for separate historical CSS cleanup; final browser visual acceptance and NAS production deployment are **not** completed.

## PR #192 — reviewed historical `src/index.css`

- Retired 287 obsolete AntD-only CSS groups and removed AntD from 10 mixed groups without replacing any of the **901 preserved native selector/declaration groups**.
- Kept all **39** original media wrappers, themes, mobile hit targets, reduced motion and imported CSS cascade ordering; no wholesale removal of historical CSS.
- Updated historical v0.4.x tests that still asserted AntD navigation, controls and modal/drawer DOM; replaced them with native nav/focus, Radix overlay and touch-target checks.
- Extended CSS audit to **56 files**, including root `src/index.css` with an explicit index path resolver, and added six native legacy index regression tests.
- Browser computed-style and visual acceptance still pending; this is not production NAS deployment.

## PR #193 — retired v047 foundational AntD overrides

- Removed **38 AntD-only CSS blocks** and AntD selectors from **2 mixed groups** across `shell.css`, `primitives.css`, `overlays.css` and `responsive.css`.
- Preserved the original **86 native rule groups** and all seven responsive media groups, including the header status badge and mobile page action bar. The now-empty historical overlay sheet remains in its original import position as an explanatory comment; active Radix dialog and sheet chrome is owned by Console v2.
- Updated stale AntD table/menu/overlay visual assertions to native semantic component contracts. Added six targeted regressions and expanded zero-AntD CSS audit to **60 files**.
- Other unreviewed v047 page/component styles may still contain obsolete AntD selectors; do **not** claim repository-wide zero until all are audited. Final browser visual sign-off remains pending.

## PR #194 — reviewed component layer and already-native v046/v047 files

- Removed **36 AntD-only CSS rule groups** and AntD members of **1 mixed group** in `src/styles/components.css`; all **162 native groups**, six original media wrappers and import order remain intact.
- The mixed group retains `.nfc-overlay-section-flush > .nfc-embedded-table` and its original margin.
- Added `components.css` plus eight already AntD-free stylesheets (`foundation.css`, `tokens.css`, `v046.css`, `v047.css`, `pages/dashboard.css`, `pages/details.css`, `pages/operations.css`, `pages/scheduler.css`) to the zero-selector audit: **69 of 74 CSS files**.
- Added six native component regression tests. The five remaining unreviewed stylesheets are `pages/login.css`, `pages/organizer.css`, `pages/tools.css`, `pages/workflows.css`, and `v048-pages.css`.
- This is source-level CSS cleanup, not a browser visual sign-off or NAS deployment.

## PR #195 — all historical AntD CSS selectors retired

- Removed **22 AntD-only groups** and AntD members of **2 mixed groups** from `pages/login.css`, `pages/organizer.css`, `pages/tools.css`, `pages/workflows.css`, and `v048-pages.css`.
- Preserved all **139 native selector/declaration groups** and existing media queries in the five files, including native organizer dark-theme selectors and premium Dedupe surfaces.
- CSS zero-selector audit now covers **all 74 of 74 CSS files**, including future inventory-completeness checks for new unreviewed CSS files, duplicate registration and missing ownership paths.
- Added six native page layout regressions. This completes **AntD selector retirement**, not browser visual acceptance, CSS computed-style consolidation, owner sign-off or production deployment.

## Stage 4C — first conservative native cascade consolidation

- Reviewed `v049-workspace.css`: removed **13 early declarations** for typography and spacing in five selectors whose later **identical-selector, identical-at-rule-context** rules already set the final value. The earlier rules remain in place with all independently defined properties (text colors, letter spacing where not overwritten, max-width, etc.).
- The later authoritative values are unchanged: page eyebrow margin/font-size/tracking, page title font-size/weight, page description margin/font-size/line-height, panel title font-size/weight and panel description margin/font-size/line-height.
- Kept all import ordering, eight `@media` conditions, original rule order, selector specificity, `!important` handling and responsive focus styles. The 75-file CSS ownership inventory remains unchanged.
- Added five source-level regressions that verify both early declaration removal and late winners. **This is a low-risk targeted source consolidation, not a claim that all historical cascade overlaps have been retired or browser computed-style snapshots have been approved.**
- Further broad pruning of `v049`, `v054`, `v056` and other historical native rules requires computed-style comparison in a real browser; do not infer safety from file name alone.

## Deliberately pending work

- All 74 current frontend CSS files are audited for zero AntD selectors.
  Preserve coverage whenever new files are added; do not equate source-level
  selector retirement with computed-style or browser acceptance.
- Identify overwritten versus still-live native declarations across legacy
  versioned styles. Remove or relocate them in small, reviewed tranches, with
  computed-style evidence when selectors share a cascade.
- Complete a single consolidated **visual acceptance** at widths
  360/390/430/768/1024/1280/1440/1920 in light and dark modes, including
  keyboard focus, reduced motion, overflow, dialogs and destructive confirmation.
- Do not deploy, alter a NAS directory or change Preview/Plan/Worker security
  authority as part of CSS cleanup.


## Stage 5E-R — Plans list versus PlanItem detail table ownership

- After the Stage 5E-O first-column fix, `console-v2-phase2.css` still applied the base `.nfc-v2-plan-table` structural rules (table width/min-width, cell padding, header surface and hover color) to **both** the Plans list and the PlanItem detail ledger. The PlanDetail stylesheet loaded later and overrode much of this, but that cascade coupling was unnecessary and could regress if import order or individual declarations changed.
- Restricted the Phase2 plan-table scroll, structural and row rules to `.nfc-v2-plans-page`. The list retains the same declarations, stable 1160px minimum width and 29% title column. PlanDetail continues to own its separate `.nfc-plan-detail-page` cell spacing, focus treatment and fixed 70px item ID column; no JSX markup or lifecycle operation changed.
- Added exact selector ownership regression and reconciled the old Phase2 source assertion. Continue using the existing 32-case Plans Workspace and Plan lifecycle read-only Chromium matrices (8 widths × 4 theme combinations) and their existing screenshot quota. No claim of a complete historical CSS consolidation; final browser visual sign-off, real NAS acceptance and owner approval remain separate OPEN gates.
