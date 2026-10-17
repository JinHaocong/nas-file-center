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

- During exact-HEAD 768px Chromium validation, an intermediate three-class base selector raised specificity above the later two-class 1160px list sizing rule and reproduced a collapsed title. The corrected base selector uses the same two-class specificity as the original rule and the later list override. Never escalate the Phase2 base table specificity above the list sizing rules; the Workspace browser column-width assertion is the release gate.

## Final Acceptance CSS contrast gap — canonical Pure White tokens (2026-10-16)

- Independent source audit found the `src/styles/tokens.css` shared `--nfc-text-subtle` was still `#858580` in light mode, yielding **3.28:1** on the accent-soft neutral surface and **3.71:1** on white; in dark mode `#94948e` yielded **4.21:1** on `#323230`. Those values missed WCAG AA normal-text **4.5:1** even after the shell (`--v2-subtle`) and Radix portal (Stage 5E-AK) colors were corrected.
- Align the canonical root theme tokens to the already-established shell/portal `#6b6b66` in light and `#9d9d97` in dark. The `--v2-subtle: var(--nfc-text-subtle)` compatibility alias remains intact. Do not reorder imports, replace Pure White with premium-dark, alter status colors or change any API/security behavior.
- `npm test` now calculates normal-text sRGB ratios across **six actual shared surface tokens** in both light/dark themes, checks the existing shell/portal color parity, and confirms native small labels still consume the shared token. The existing read-only `browser-theme-resilience.mjs` script gains **32 actual Chromium scenarios** (8 viewports × 4 light/dark/system variants), checking computed CSS, six backgrounds each and no cross-origin calls or mutating API requests.
- This closes only the **identified canonical small-text contrast defect**, not the high-level CSS ownership / 8-width full-page visual / comprehensive accessibility acceptance items. Older v048–v056 CSS and other component-specific colors still require an exhaustive global review and owner visual sign-off. No deployment or real NAS operation is included.

- First exact-HEAD Chromium test also found a **real CSS cascade override**: global `.nfc-page-eyebrow` computed as `#929aa5` from v049 `--nfc-v49-subtle`, despite the compliant root token. Change only that `v049-workspace.css` eyebrow declaration to `var(--nfc-text-subtle)`, preserving every other v049 rule, import order and breakpoint. Guard with both source-level and computed Chromium regression. This demonstrates why token-only source acceptance is insufficient.

## Stage 5E-AA — mobile historical CSS same-context shadow retirement (2026-10-16)

A conservative source-context audit found **seven exactly shadowed declarations** in historical mobile rules:

- `v049-workspace.css`: the *first* `@media (max-width: 767px)` groups redundantly set header `min-height: 54px`, page header `align-items: stretch` and `gap: 12px`, copy `max-width: 100%`, metric grid `grid-template-columns: repeat(2, minmax(0, 1fr))`, and metric card `min-height: 94px`. The **later** `@media (max-width: 767px)` groups use the **same selectors, identical media condition and same property values**. Only the six earlier declarations were retired, including now-empty copy and grid blocks.
- `v056-right-workspace-v2.css`: the earlier phone `.nfc-app-main .nfc-page-header-copy { max-width: 100%; }` was wholly redundant with the later *same-selector and same-media* responsive-spacing correction, which still sets `width: 100%; max-width: 100%; flex: 0 1 auto;`. Only the early empty block was retired. The separate `@media (max-width: 1199px)` `flex: 1 1 620px` rule for row-layout headers **remains** and the Dashboard-owned column exception introduced by PR #273 also remains.

The original 8 v049 media wrappers, other declarations (mobile header margins/padding, page title and metric card padding), selector specificity, late winners, import order and `!important` authority are preserved. Source regression checks explicitly assert absence of each early shadow and presence of the corresponding late winning property, and retain existing real Chromium 8-width × 4-theme route/overlay checks in CI. Neither component JSX nor backend/security/NAS APIs is modified.

**Scope limit:** these are only seven proven same-context repetitions, not a comprehensive historical CSS consolidation or human full-site visual sign-off. Canonical final acceptance remains **68/74** with six high-level gates open.

### Exact-head 768px visual gate follow-up

PR #276's initial full-route Chromium 768px matrix found **3 of 4** Dashboard theme cases without a measured focus ring, even while all four retained the prior `214×17px` readable filename, `860px` bounded local scrolling and `36–37px` ArrowRight movement. Initially the test checked `:focus-visible` after programmatic `.focus()`, which is not a reliable substitute for real keyboard modality.

A second **exact-HEAD** attempt used genuine `Tab → Shift+Tab` navigation back to the scroll region and made the root evidence conclusive: **4 of 4** themes reported `isFocused=true` and `focusVisible=true` but `outlineWidth=0`. This is an actual missing computed keyboard focus ring in the earlier PR #275 table surface, not merely a test false-positive. Source-level `:focus-visible` styling alone had not guaranteed the computed focus border. The isolated owned Console v2 rule is now reinforced as `.nfc-v2-shell .nfc-v2-recent-scans-scroll:focus-visible` with explicit 2px `!important` outline and `transition: none !important`. No other controls, table widths, routes, APIs or security paths are changed.

The real Chrome audit retains **Tab → Shift+Tab → computed `:focus-visible`/outline → ArrowRight** and saves `outlineWidth`, `outlineColor`, theme accent token and computed transition duration in the Manifest. It must fail closed if the ring is still 0px, in any of the four theme cases. Both failed candidate runs must remain failures; only a new exact HEAD with fully successful 16 Checks / 4 Workflows, clean mergeability and stable main base can merge. Overall acceptance remains **68/74**.


## 2026-10-17 — historical native CSS shadow retirement: v049 + v056 (scoped tranche)

After the previous Stage 4C and Stage 5E-AA cleanups, an exact-selectors-and-`@media`-ancestry audit of the historical CSS layers found **15 more earlier declarations** with later exact-selector/identical-at-rule-context winners. The earlier declarations are now retired without changing the winning final values, selector specificity, CSS import order, browser behavior, or backend authority:

| Earlier stylesheet / context | Earlier shadow(s) removed | Later owner preserved |
| --- | --- | --- |
| `v049-workspace.css` desktop header | 1 old background | Neutral floating header `background: color-mix(... --nfc-nav-surface ... ) !important` |
| `v049-workspace.css` desktop filter/bulk toolbar | 4 old min-height, padding, border and background | 56px toolbar, 9×12px padding, soft border/panel background with existing `!important`; independent early `box-shadow: none !important` retained |
| `v049-workspace.css` first `@media (max-width: 767px)` | 9 old page header margin/padding, title/description sizes, metric padding, panel header height/padding, panel description display, Settings body padding | Last `@media (max-width: 767px)` rules continue owning 14px/16px headers, 22px/11px typography, 12×13px metric spacing, 56px/12×14px panel headers, visible panel descriptions, and 14px Settings body |
| `v056-right-workspace-v2.css` desktop Dashboard rail | 1 early `gap: 16px` block | Later exact-selector `gap: 14px` plus existing 1199px/767px rail breakpoints |

The first mobile `v049` block keeps its independent `min-height: auto` page header, row/action sizing, `9px 10px` filter toolbar, metric border edges and all other live CSS. The historical `@media (max-width: 420px)`, reduced-motion and reduced-transparency contexts remain. The previous browser focus and responsive authority work is unaffected.

`frontend/scripts/css-historical-cascade-convergence.test.mjs` now enumerates *leaf CSS rules with their exact at-rule ancestry*, verifies all **15 early shadow retirements and corresponding unchanged late winners**, checks independent early properties and import order, and asserts that existing exact-HEAD read-only Chromium 8-width × 4-theme workspace/dense/status/overlay evidence remains in CI. The test runs automatically in `npm test`. Real browser evidence is gathered by the existing visual/overlay CI jobs against the candidate HEAD; no NAS storage/API mutation is permitted.

**This is a scoped source consolidation tranche, not the final historical CSS theme-system consolidation or the 8-width human visual acceptance.** The remaining historical CSS/computed-style audit, comprehensive accessibility sign-off, real NAS test and owner deployment authorization remain open. Accordingly the high-level count stays **69/74 (93.2%)** pending those distinct closure conditions.


## 2026-10-17 — historical cross-file header CSS authority: v048-detail → v049 (scoped tranche)

After the same-file v049/v056 convergence in PR #283, the remaining high-volume overlap is **between historical version imports**. This tranche specifically removes **16 desktop, unconditional earlier declarations** from `v048-detail.css` which are superseded by **the exact same selectors and properties, with the same importance, in the later `v049-workspace.css`**:

| v048-detail source rule | Retired early properties | Authoritative subsequent rule |
| --- | --- | --- |
| `.nfc-header-workspace` | `min-width`, `max-width` (2) | v049 132px / 210px |
| `.nfc-header-workspace-kicker` | `color`, `font-size`, `font-weight`, `letter-spacing` (4) | v049 subtle token, 8px, 730, .14em |
| `.nfc-header-workspace-name` | `margin-top`, `color`, `font-size`, `font-weight`, `letter-spacing` (5) | v049 3px, text token, 11px, 650, -.01em |
| `.nfc-header-status` | `gap`, `padding`, `border`, `border-radius`, `background` (5) | v049 3px, 2px, v49 border, pill radius; subsequent v049 neutral surface background |

The completely shadowed *unconditional desktop* `.nfc-header-status` rule is removed, but **its distinct responsive @media status rules remain** (mobile max-width, scrolling and scrollbar). The earlier `padding-right` on workspace is intentionally retained because v049 uses a `padding` shorthand, not the exact property: no broad shorthand/longhand rewrite is made. Kicker/name `overflow: hidden`, `text-overflow: ellipsis` and `white-space: nowrap` survive untouched; all status badge colors, responsive breakpoints, index styles, reduced-motion rules and selector specificity remain unchanged.

`frontend/scripts/css-historical-cross-layer-ownership.test.mjs` now validates **the earlier file and the later file together**, enumerates actual CSS leaf declarations with their at-rule ancestry, asserts all 16 old shadows stay retired, asserts the exact live v049 final values, preserves mobile-only ancestors and independent declaration owners, checks actual ordered `main.tsx` imports, and checks that the read-only 8-width × 4-theme Chromium workspace/overlay/ledger matrix remains in the exact-HEAD CI. It runs as part of `npm test`; CI additionally runs the real read-only Chromium matrix and standard frontend/backend/Docker/security gates.

**Scope:** another conservative cross-layer cleanup, **not a completed historical theme consolidation**. CSS files with grouped selectors, shorthand/longhand mixing, `!important` importance differences and distinct media conditions are not bulk-pruned. A full real-browser computed-style/theme ownership and one consolidated human visual/accessibility acceptance are still open, as is real NAS/owner sign-off. Formal completion stays **69/74 (93.2%)**; no NAS mutation, production deployment or backend/security edit.


## 2026-10-17 — v055 → v056 desktop header ownership (scoped follow-up)

Following PR #284, audited the `src/main.tsx` import order: `v055-workspace-breathing.css` loads before `v056-right-workspace-v2.css`. Four **unconditional, exact-match selectors** in v055 contained **14 earlier declarations** already superseded by v056 rules at equal specificity, importance, and at-rule context:

| Selector | Earlier v055 declarations retired | Preserved v056 unconditional authority |
| --- | --- | --- |
| `.nfc-app-main .nfc-page-header` | `min-height`, `margin`, `padding`, `align-items`, `gap`, `border`, `border-radius`, `background`, `box-shadow` (9) | Flat workspace header: 0 minimum height, 24px bottom margin, 20px bottom padding, flex-end, 28px gap, 0 border plus independent 1px hairline bottom border, transparent background, no shadow |
| `.nfc-app-main .nfc-page-header-copy` | `max-width` (1) | `min(980px, 74vw)` |
| `.nfc-app-main .nfc-page-title` | `line-height` (1) | `1.18` |
| `.nfc-app-main .nfc-page-description` | `max-width`, `margin-top`, `line-height` (3) | `82ch`, `8px`, `1.58` |

The now-empty **unconditional** v055 rule blocks are removed; **all scoped responsive rules** (1800px, 1399px, 980px and narrow-screen branches), custom tokens, pseudo-elements, action layout, legacy dense-page selectors, and later v056 declarations are preserved. No shorthand/longhand equivalence was inferred: the entire earlier `border` and `padding` shorthands are replaced by the later same-name shorthands, while independent late `border-bottom` remains in place. This does not alter import order, theme tokens, `!important` rules or application/Plan/NAS operations.

The dedicated `frontend/scripts/css-historical-v055-v056-ownership.test.mjs` enumerates leaf rules with exact at-rule ancestry; pins all 14 v056 winners, prevents retired v055 declarations reappearing, verifies retained responsive and independent properties, and checks existing isolated read-only Chromium matrices remain gated by the PR workflow. It is registered in `npm test`.

**Still open:** exhaustive CSS theme consolidation, final human visual and a11y sign-off, real NAS isolation testing and owner-authorized production deployment. The formal **69/74 (93.2%)** high-level checklist is unchanged.


## 2026-10-17 — v055 → v056 workspace frame and panel-body authority (scoped follow-up)

After PR #285, reviewed the same **unconditional, equal-specificity, equal-importance** cascade across `v055-workspace-breathing.css` and the subsequently imported `v056-right-workspace-v2.css`. Retired **4 earlier same-property shadows** that already have unchanged v056 winners:

| Earlier v055 selector | Retired properties | Later v056 owner |
| --- | --- | --- |
| `.nfc-app-main .nfc-page-content` | `padding` (1) | `18px clamp(24px, 2.15vw, 42px) var(--nfc-w2-page-bottom)` |
| `.nfc-app-main .nfc-page-content > *` | `width`, `margin-inline` (2) | `min(100%, var(--nfc-w2-content-max))`, `auto` |
| `.nfc-app-main .nfc-data-panel-body:not(:empty)` | `min-width` (1) | `0`, alongside later independent overflow/border/radius/surface |

Only those three now-empty unconditional v055 blocks are removed. Its **higher-specificity, grouped wide-ledger width exception** remains intentionally preserved, as do responsive token definitions at 1800/1399/980 and narrow widths, page composition, theme variables and the later v056 content/scroll-padding/panel contracts. No CSS import reorder, `!important` changes, React, API, RBAC, Plan lifecycle, Worker, NAS, or deployment operations.

Extended `css-historical-v055-v056-ownership.test.mjs`, already registered in `npm test`, with exact-context leaf-rule checks for all four unchanged v056 winner values, retired early blocks, independent panel/scroll ownership, dense exceptions, responsive tokens and the existing isolated read-only Chromium gates.

This is **not** full historical CSS/theming consolidation or final visual/accessibility acceptance. Formal high-level acceptance stays **69/74 (93.2%)**.


## 2026-10-17 — v055 → v056 operational surface ownership (scoped batch)

After #286, audited unconditional exact-selector, exact-property shadows across the unchanged `src/main.tsx` v055→v056 import order. Removed **19 former v055 declarations** in 15 selectors, grouped by UI contract:

| Area | Retired v055 properties | Later v056 owner |
| --- | --- | --- |
| Page action row | `padding` (1) | `0 0 1px` |
| Dashboard command deck + metric grid | `gap`, `border-radius` (2) | `10px`, `0` |
| Dashboard metric cards + snapshot note | `min-height`, `padding` × 2, `border-radius` (4) | `96px`, `14px 15px`, `10px 12px`, `var(--nfc-w2-radius-sm)` |
| Dashboard layout, main column + rail | `gap` × 3 | `18px`, `18px`, `14px` |
| Tasks worker strip + Media metrics/alert | `margin-bottom` × 2, `margin` (3) | `28px`, `28px`, `12px 14px 14px` |
| Quarantine command center + bulk action bar | `padding`, `gap`, `padding-top`, `gap` (4) | `0`, `0`, `10px`, `8px` |
| Plan action surface + Workflow editor | `margin-bottom`, `gap` (2) | `24px`, `28px` |

The source-rule cleanup **only removes earlier equal-specificity, equal-importance, unconditional declarations already superseded by later unconditional v056 declarations**. Preserve every other v055 declaration, the dashboard command-deck 28px margin-bottom (not removed despite later v056 `margin` shorthand), the page-actions flex contract, scoped responsive overrides (1399px, 767px and narrower), custom theme/dense-width variables, v056 final declarations, and all frontend/backend security and NAS behavior. No shorthand/longhand equivalence is assumed.

Extended the registered `css-historical-v055-v056-ownership.test.mjs` to assert **19 retired exact-property shadows**, each unchanged last v056 winning value, responsive and independent v055 controls, and import order. Exact-HEAD PR validation still executes `npm test` and the isolated, read-only Chromium 8-width × 4-theme visual interaction gates.

This is **not** comprehensive historical CSS/theme consolidation or final human visual/accessibility acceptance. Formal high-level acceptance stays **69/74 (93.2%)**; no NAS mutation or production deployment.

The existing TypeScript `console_v2_legacy_v05_css.test.ts` historical-retirement inventory was also made maintenance-safe: its arbitrary `v055.length > 9000` byte-count requirement is replaced with checks for **actual native v055 semantic owners and 1800/1399/767px responsive contexts**. Unchanged v050/v051 checks and comprehensive dedicated v055→v056 leaf-declaration checks continue to run. This ensures future proven deletion of dead v055 declarations does not spuriously fail a test that was intended to guard active behavior.


## 2026-10-17 — v049 → v056 filter + description ownership (scoped batch)

Following #287, audited **five unconditional exact-match selectors** in the older `v049-workspace.css` against the later-imported `v056-right-workspace-v2.css`. Retired **16 old declarations** which have identical selector specificity, unconditional at-rule ancestry and CSS importance, and are superseded by explicit v056 declarations:

| Earlier v049 selector | Retired declarations | v056 remains the final owner |
| --- | --- | --- |
| `.nfc-filter-control` | `gap`, `color`, `font-size`, `font-weight` (4) | 7px spacing, v056 muted text, 11.5px / 600 |
| `.nfc-description-item` | `min-height`, `padding`, `border-color` (3) | 78px, 14px 16px, v056 hairline |
| `.nfc-description-item dt` | `margin-bottom`, `color`, `font-size`, `font-weight` (4) | 7px, v056 subtle text, 11px / 620 |
| `.nfc-description-item dd` | `color`, `font-size` (2) | v056 muted text, 12.5px |
| `.nfc-description-item dd.nfc-description-emphasis` | `color`, `font-size`, `font-weight` (3) | v056 text, 14px / 650 |

Those five now-empty **unconditional v049 blocks** are removed, with unchanged import order. Retain the separate `.nfc-responsive-descriptions` container's existing `!important` frame contract, independent filter input rules, all v049 responsive/reduced-motion/reduced-transparency behavior and v056 winning declarations. No shorthand/longhand substitution, selector grouping change, theme change, API, Worker, Plan, NAS mutation or deployment.

Added exact-context, full-property safeguards to the already registered `css-historical-cascade-convergence.test.mjs`: old selectors must remain retired, the 16 specific v056 declarations remain pinned, and existing important description frame and responsive rules persist. Existing real read-only Chromium 8-width × 4-theme checks are unchanged.

**Scope limitation:** additional conservative cross-layer cleanup, not completion of all historical CSS/theme ownership. Final human visual/a11y acceptance and isolated real NAS/deployment approval remain outstanding. Formal progress remains **69/74 (93.2%)**.


## 2026-10-17 — v049 → v056 dashboard quick actions + summary row (scoped batch)

After #288, retired **16 unconditional older v049 declarations** in five selectors whose exactly matching v056 declarations already win by later import order, equal selector specificity, and identical importance:

| Retired early selector | Retired properties | v056 final owner |
| --- | --- | --- |
| `.nfc-dashboard-page .nfc-quick-action` | `min-height`, `padding`, `grid-template-columns`, `border-bottom-color` (4) | 66px, 11px 14px, 32px grid icon, v056 hairline |
| `.nfc-dashboard-page .nfc-quick-action-icon` | `width`, `height`, `border`, `border-radius`, `color`, `background` (6) | 32 × 32px, zero border, 9px, v056 muted foreground/strong surface |
| `.nfc-dashboard-page .nfc-quick-action-copy strong` | `font-size` (1) | 12.75px |
| `.nfc-dashboard-page .nfc-quick-action-copy span` | `font-size` (1) | 11.5px |
| `.nfc-dashboard-page .nfc-summary-row` | `min-height`, `padding-inline`, `border-bottom-color`, `font-size` (4) | 48px, 14px, v056 hairline, 12.5px |

Only those obsolete, now-empty v049 blocks are removed. Preserve other earlier dashboard layout/rail properties, especially the important rail surface contract, responsive and reduced-motion/transparency overrides, Pure White light/dark/system tokens and unchanged v056 winners/import order. No backend, API, RBAC, NAS or deployment mutation.

Extended the registered `css-historical-cascade-convergence.test.mjs` to pin all **16 final v056 property winners** and absence of earlier blocks, plus independent v049 layout and important rail styling. Replaced an old `v049.length > 35000` legacy TypeScript test sentinel with checks for concrete native workspace, keyboard and accessibility/media selectors, so legitimate dead CSS retirement is not penalized by file size. Existing full frontend/backend, Docker, security audit and read-only Chromium 8-width × 4-theme workflows remain mandatory on exact PR HEAD.

This does **not** claim comprehensive historic CSS/theme ownership or final manual visual/a11y verification. Formal high-level progress remains **69/74 (93.2%)**; real NAS and production deployment still require separate approval.
