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


## 2026-10-17 — v049 → v056 metric typography and Dashboard snapshot ownership

After #289, reviewed **four exact, unconditional single selectors** in the older
`v049-workspace.css` against the later imported `v056-right-workspace-v2.css`.
Retired **17 same-property, equal-specificity, equal-importance declarations**
already owned by the later rules:

| Earlier v049 selector | Safely retired properties | Unchanged v056 authority |
| --- | --- | --- |
| `.nfc-metric-label` | `color`, `font-size`, `font-weight`, `letter-spacing` (4) | muted foreground, 11.5px / 610, zero tracking |
| `.nfc-metric-value` | `color`, `font-size`, `font-weight`, `letter-spacing` (4) | text foreground, responsive clamp, 660, -0.045em |
| `.nfc-metric-meta` | `margin-top`, `color`, `font-size` (3) | 9px spacing, subtle foreground, 11.5px |
| `.nfc-dashboard-page .nfc-snapshot-note` | `margin-bottom`, `padding`, `border`, `border-radius`, `color`, `background` (6) | 20px spacing, 11px 14px padding, zero border, v056 surface/text |

Retained the **independent** historical `.nfc-metric-value { margin-top: 12px; }`
and snapshot `box-shadow: none`, plus all eight original v049 media
conditions, responsive v056 metric overrides, import order, theme tokens,
and other dashboard properties. No shorthand substitutions, selector grouping,
`!important` or dark/light/system behavior changes were made.

Extended the existing `css-historical-cascade-convergence.test.mjs` regression
with 17 exact declaration-winner checks, old-declaration absence checks,
independent-property preservation and media/viewport invariants. Exact-HEAD
frontend/backend/CI and isolated read-only Chromium validation are still mandatory.
No NAS data, RBAC, Plan, Worker, API or production deployment behavior is changed.

This is **not** the complete CSS/theme consolidation, manual visual or a11y
sign-off, real NAS acceptance or production authorization. Formal high-level
progress remains **69/74 (93.2%)**.


## 2026-10-17 — v049 → v056 workspace frame, page actions and metric grid

Following PR #290, retired **16 unconditional exact-property v049 declarations**
already superseded by the later imported **v056**, under identical selector,
at-rule context, CSS importance and cascade specificity:

| Earlier v049 selector | Retired declarations | Existing later v056 authority |
| --- | --- | --- |
| `.nfc-page-content` | `position`, `width`, `min-width`, `padding` (4) | relative, 100%, zero min-width, theme-aware outer gutters |
| `.nfc-page-content > *` | `width`, `margin-inline` (2) | constrained content max and automatic horizontal margins |
| `.nfc-header-action-label` | `color`, `font-size` (2) | muted foreground, 12px |
| `.nfc-page-actions` | `align-self`, `gap` (2) | end-aligned actions, 8px gap |
| `.nfc-metric-grid` | `overflow`, `gap`, `border`, `border-radius`, `background`, `box-shadow` (6) | overflow visible, 12px gap, flat transparent surface |

Preserved independent `z-index: 1` in the historical page-content rule
and the late v049 page-actions `padding-bottom: 0`. Removed an additional
**already-empty** metric-grid rule, which is not counted as a declaration.
All eight original historical `@media` conditions remain, notably
420px/767px metric grid columns, as do reduced motion/transparency,
responsive gutters, the unchanged v056 full owner, CSS import order and
Light/Dark/System theme variables.

Extended the existing `frontend/scripts/css-historical-cascade-convergence.test.mjs`
with an exact 16-property final-winner matrix, deleted-shadow assertions,
independent-property retention, media-ancestry and entrypoint-order checks.
All 8-width × 4-theme, local fixture-only Chromium CI matrices remain
mandatory; no real NAS or production operation is involved.

This scoped CSS cleanup **does not complete** historical CSS/theme migration
or final visual, accessibility or real-NAS acceptance. Formal status remains
**69/74 (93.2%)** pending independent comprehensive closure and explicit
deployment authorization.


## 2026-10-17 — v049 → v054 header identity and overlay/code owners

After PR #291, audited **14 exactly shadowed, unconditional, normal-importance
v049 declarations** against later-imported v054 declarations with matching
single selectors, specificity, context, and CSS property:

| Historical v049 rule | Declarations retired | Later v054 owner |
| --- | --- | --- |
| `.nfc-header-workspace-kicker` | `color`, `font-size`, `letter-spacing` (3) | 8.5px, subtle canonical text, 0.14em |
| `.nfc-header-workspace-name` | `font-size`, `font-weight`, `letter-spacing` (3) | 12px, 680, -0.01em |
| `.nfc-code-block` | `padding`, `border-radius`, `color`, `background`, `font-size` (5) | 12px 13px, 10px radius, canonical muted code surface and 10px |
| `.nfc-overlay-section-header` | `min-height`, `padding`, `background` (3) | 52px height, 11px 13px, muted section surface |

Retain all independent historical declarations: workspace kicker `font-weight:
730`, workspace name `margin-top` and `color`, code `border-color`,
and overlay `border-bottom-color` (including its separate earlier empty
block). Do not modify shorthand/longhand relationships, grouped selectors,
CSS import order, themes, reduced-motion/transparency, or responsive media
overrides. In particular, `v054` keeps its **420px code padding/font-size**
and **767px overlay padding** rules.

Extend the registered CSS cascade regression with exact property owner
assertions, explicit independent-retention checks, breakpoint contracts,
and canonical import-order enforcement. The existing v048→v049
cross-layer test also keeps its **16 original retirement checks** while
recognizing the six Header properties now owned by v054; it continues to
pin all remaining independent v049 declarations. The Stage 5E-D Media /
Quarantine test similarly retains its original **12-declaration historical
coverage** while moving three overlay properties' final authority from v049
to v054 and keeping the independent v049 divider unchanged. Existing read-only Chromium eight
width / four-theme CI matrix, frontend/backend/Docker validation and
review gate remain mandatory for this exact PR HEAD.

This is **a partial CSS consolidation only**, not complete historical/theme
closure, manual final visual/a11y acceptance, real NAS verification or
production approval. Formal progress remains **69/74 (93.2%)**.

**PR #292 CI-specific read-only browser stabilization:** The initial exact-HEAD
430px visual job reported one near-empty `/scans/1` route in `dark-light`
mode, with no reported route redirect or React exception. The fixture
previously waited only for shell insertion and 160ms after navigation.
The dynamic scan-detail case now waits up to six seconds for real main
content (at least 25 text characters), failing closed on timeout. The
existing whole-route blank-page threshold, every width/theme screenshot,
no-NAS-write assertions and error/overflow checks are unchanged. This
does **not** waive the full restarted PR CI or claim manual visual sign-off.


## 2026-10-19 — v049 → v056 workflow steps and row actions

After PR #292, safely retired **nine** unconditional v049 leaf
declarations already overridden by **identical single selectors** with
the same at-rule context, CSS priority and exact CSS property in the
later imported v056 layer:

| Earlier v049 selector | Retired properties | Existing v056 owner |
| --- | --- | --- |
| `.nfc-row-actions` | `gap`, `opacity` (2) | 2px gap, 0.56 normal opacity |
| `.nfc-workflow-builder-page .nfc-workflow-step-card.is-expanded` | `background`, `box-shadow` (2, both `!important`) | canonical surface and 3px inset accent |
| `.nfc-workflow-builder-page .nfc-workflow-step-heading` | `min-height`, `padding` (2) | 62px, 11px 15px |
| `.nfc-workflow-builder-page .nfc-workflow-step-editor` | `padding`, `border-top`, `background` (3) | 18px 16px 20px, hairline divider, soft surface |

Retained the **independent** `.nfc-row-actions:focus-within`
keyboard-visible `opacity:1`, the separate v049 **767px**
`.nfc-row-actions` `opacity:1` rule, grouped mobile
workflow step `padding-inline:10px`, all eight v049 historical
media wrappers, CSS import order, themes and reduced motion/transparency.
The v056 winners and all grouped/more-specific browser rules are unchanged.

Extended the registered
`frontend/scripts/css-historical-cascade-convergence.test.mjs`
with exact nine-property owner validation, retired selector guards,
important declaration checks, and independent focus/mobile retention.
The existing `console_v2_legacy_v049_css.test.ts` inventory now verifies
that v056 owns the normal 0.56 opacity/2px gap while v049 retains 767px
`opacity:1` and keyboard `:focus-within` behavior; its outdated
normal-state `0.72` assertion is retired without relaxing mobile checks.
PR CI still needs frontend/backend/Docker/security checks and the full
eight-width × four-theme isolated Chromium matrices on the exact HEAD.

This is **incremental CSS ownership cleanup**, not proof of complete
historical CSS/theme consolidation, full manual visual or accessibility
sign-off, real NAS verification, or production approval. The formal
high-level count remains **69/74 (93.2%)**.


## 2026-10-19 — v054 → v056 title, description and panel-title typography

Retire **13 unconditional, same-selector, same-property and same-priority
v054 shadows**, already superseded by later-imported v056 normal-importance
values:

| Historical v054 selector | Retired declarations | Final v056 owner |
| --- | --- | --- |
| `.nfc-app-main .nfc-page-title` | `font-size`, `font-weight`, `line-height`, `letter-spacing`, `text-wrap` (5) | 27–31px clamp, 620, 1.18, -0.014em, balance |
| `.nfc-app-main .nfc-page-description` | `max-width`, `margin-top`, `font-size`, `line-height` (4) | 82ch, 8px, 13px, 1.58 |
| `.nfc-app-main .nfc-data-panel-title` | `font-size`, `font-weight`, `line-height`, `letter-spacing` (4) | 14px, 620, 1.42, -0.004em |

Preserved independent v054 `color` for each selector
(`--nfc-text` / `--nfc-text-muted`), all media rules including
767px and 420px typography overrides, later v056 responsive winners,
CSS import order and reduced-motion/transparency ownership.
This is an exact single-selector property migration, not a shorthand
or selector-specificity transformation.

Extended registered CSS cascade regression to assert all **13** removed
v054 declarations, exact v056 values, independent retained colors,
responsive context and import order. Frontend/backend/Docker/dependency
Checks and full read-only 8-width × 4-theme actual Chromium routes
remain required on the precise PR HEAD.

This is incremental historical CSS cleanup, **not** complete
CSS/theme acceptance, human visual/a11y approval, real NAS verification
or production deployment. Formal milestone **69/74 (93.2%)** unchanged.


## 2026-10-19 — v054 → v056 page-header geometry and panel description

Retired **10 unconditional historical declarations** in the v054 layer
already overridden by identical, later-imported v056 selectors, with the
same CSS properties, specificity, at-rule context and normal priority:

| v054 historical single selector | Removed properties | Existing v056 canonical values |
| --- | --- | --- |
| \`.nfc-app-main .nfc-page-header\` | \`min-height\`, \`margin\`, \`padding\`, \`align-items\`, \`gap\`, \`border-bottom\` (6) | 0; 0 0 24px; 0 0 20px; flex-end; 28px; w2 hairline |
| \`.nfc-app-main .nfc-page-header-copy\` | \`max-width\` (1) | min(980px, 74vw) |
| \`.nfc-app-main .nfc-data-panel-description\` | \`margin-top\`, \`font-size\`, \`line-height\` (3) | 5px; 11.5px; 1.52 |

The two obsolete v054 single-selector blocks are removed entirely.
Preserved the v054 panel-description independent \`max-width: 86ch\`
and \`color: var(--nfc-text-subtle)\`, the separately owned
\`.nfc-app-main .nfc-page-header::after\` ornament, v055 decoration,
the v056 \`border: 0\` reset and later exact \`border-bottom\` winner,
1199px/767px responsive rules, 420px rules, CSS import order, focus,
Light/Dark/System themes and reduced-motion/transparency rules.

Extended \`frontend/scripts/css-historical-cascade-convergence.test.mjs\`
with exact v056 property-owner checks, guards preventing ten historical
declarations from returning, independent v054 declarations, ornament
retention, responsive flex/layout overrides and import-order invariants.
CI's read-only Chromium eight-width/four-theme matrix and all security
and build checks remain required for the final PR head.

Stage cumulative historical **redundant declaration** cleanup:
**179** (169 previously merged + 10 in this batch).
This does **not** finish full historical CSS/theme convergence, human
visual/a11y acceptance, isolated real NAS verification or deployment.
Formal milestone remains **69/74 (93.2%)**.

## 2026-10-19 — v054 → v056 panels, Media, root labels and Workflow

Retired **10** additional unconditional historical declarations. Each is an
exact single-selector, same-property, same-specificity, normal-priority
shadow of a later-imported unconditional v056 rule:

| Earlier v054 selector | Properties retired | v056 canonical authority |
| --- | --- | --- |
| `.nfc-app-main .nfc-data-panel-header` | `min-height`, `padding`, `background` (3) | 0; panel header token padding; transparent |
| `.nfc-app-main .nfc-media-page .nfc-page-alert` | `margin` (1) | 12px 14px 14px |
| `.nfc-app-main .nfc-root-list-label` | `color`, `font-size` (2) | w2 text-subtle; 11px |
| `.nfc-app-main .nfc-workflow-editor-layout` | `gap` (1) | 28px |
| `.nfc-app-main .nfc-workflow-mode-option` | `min-height`, `border-radius`, `background` (3) | 76px; w2 small radius; w2 soft surface |

Removed two now-empty single-selector v054 rule blocks. Preserved the panel
header `gap` and `border-bottom-color`, historical Root label `font-weight`,
`letter-spacing` and `text-transform`, workflow option `padding` and
`border` shorthand (v056 only overrides its `border-color`), separate
v056 Media border/background rule, and all other selectors.

Preserved 767px panel Header overrides, 980px Workflow gap, 420px
`!important` Workflow grid, original CSS import order, theme variables,
keyboard/focus behavior and reduced-motion/reduced-transparency rules.
Registered historical-cascade regressions now enforce the ten v056
owner values, all independent declarations and responsive contexts.
Full frontend/backend/Docker/dependency and isolated read-only
Chromium 8-width/4-theme CI remains mandatory on the exact PR HEAD.

Historical redundant declaration total after this batch: **189**
(179 previously merged + 10 newly retired).
Formal progress remains **69/74 (93.2%)**: incremental source cleanup
is not final CSS/theme, manual visual/a11y, real NAS, or production approval.

### PR #296 — exact-HEAD browser gate investigation and stabilization

Initial PR HEAD `7813ede` failed `browser-overlay-smoke` at
`Purge system-dark-360`: the scrim intercepted the dialog pointer
hit test immediately after Playwright observed the Radix portal as visible.
The preceding Restore/Purge cases and the Quarantine Plan matrix passed;
the trace showed no failing CSS owner, build or backend assertion.

The read-only bulk-overlay browser script now waits (maximum **5 seconds**)
for an **open** dialog to become hit-test reachable, using animation-frame
polling, before running the same comprehensive `inspect()` assertions.
A persistently obstructing scrim **still fails**; exact `z-index` 1300/1301,
themes, no-blur, safe viewport bounds, pointer reachability, DELETE gate,
read-only network guards, and all width/theme combinations are unchanged.
No safety threshold or test coverage was removed. Full CI must rerun
from the new exact PR HEAD; the earlier failed HEAD is not acceptable
evidence for merge.

## 2026-10-19 — v048-detail → v056 description item typography and geometry

Retired **11** unconditional normal-priority v048-detail declarations
shadowed by **identical single selectors and CSS properties** in the
later imported v056 layer (no specificity, media or importance changes):

| v048-detail selector | Retired properties | Final v056 values |
| --- | --- | --- |
| `.nfc-description-item` | `min-height`, `padding` (2) | 78px, 14px 16px |
| `.nfc-description-item dt` | `margin-bottom`, `color`, `font-size`, `font-weight` (4) | 7px, w2 text-subtle, 11px, 620 |
| `.nfc-description-item dd` | `color`, `font-size` (2) | w2 text-muted, 12.5px |
| `.nfc-description-item dd.nfc-description-emphasis` | `color`, `font-size`, `font-weight` (3) | w2 text, 14px, 650 |

All four v048-detail rules retain their **independent** properties:
grid-cell `border-right`/`border-bottom`/`background`, label
`letter-spacing`, definition `line-height`, and emphasized value
`letter-spacing`. In particular no shorthand border or text
cascade conversion was attempted.

Retain v048-detail's 1199px/767px/420px responsive wrappers,
phone item min-height/padding, even-column and last-item borders,
native row-action focus and reduced-motion. No `!important`,
theme tokens, import order, grouped selector or keyboard state
was modified. The registered historical-cascade regression
now pins all **11** v056 values, the independently retained v048
declarations and mobile inheritance/override contracts.

Full read-only Chromium 8-width/4-theme route, overlays, backend, Docker
and dependency gates remain required on the exact PR HEAD.
After merge, cumulative redundant CSS declaration removals: **200**
(189 previously merged + 11 now reviewed). This incremental cleanup
does **not** constitute complete CSS/theme ownership closure,
manual visual/a11y acceptance, real NAS acceptance or deployment.
Formal high-level milestone stays **69/74 (93.2%)**.

## 2026-10-19 — v049 → v056 Dashboard geometry and form-grid ownership

Retired **8** unconditional normal-priority v049 declarations shadowed by
the exact same single selectors and CSS properties in later-imported v056:

| Earlier v049 selector | Removed properties | Existing v056 same-selector values |
| --- | --- | --- |
| `.nfc-dashboard-page .nfc-dashboard-layout` | `margin-top`, `grid-template-columns`, `gap` (3) | 24px; minmax(0, 1fr) minmax(300px, 340px); 30px |
| `.nfc-dashboard-page .nfc-dashboard-main-column` | `gap` (1) | 26px |
| `.nfc-dashboard-page .nfc-dashboard-rail` | `position`, `top`, `gap` (3) | sticky; 76px; 22px |
| `.nfc-form-grid` | `gap` (1) | 16px 22px |

All four old unconditional blocks became empty and were removed.
Crucially, the **higher-specificity** v056 Dashboard rail pair still
owns separate `gap: 14px` / `position: static` values when applicable;
the table above records **same-selector declarations**, not an assertion
that those declarations always determine the final computed style.

Retained v049's Dashboard rail cards' `!important` border/background,
1600px wide-layout gap, 1199px tablet grid and rail placement, and
767px mobile grouped gaps/rail columns. No theme, keyboard focus,
reduced-motion, reduced-transparency, group selector or CSS import order
was changed. Registered historical cascade regression protects
exact v056 owners, more-specific rail override, responsive contracts
and preserved independent styles.

CI must still validate the exact final PR HEAD, including 8 viewport
widths × 4 theme combinations, full overlay matrices, backend, Docker
and dependency audit. Isolated mock-browser checks are not human or
real-NAS acceptance.

Cumulative historical redundant CSS declarations after this batch:
**208** (200 previously merged + 8 reviewed here).
Formal milestone remains **69/74 (93.2%)** until a full high-level
acceptance task is independently closed.

### PR #298 — align historical Dashboard regression with canonical v056 owner

The first PR HEAD `02a6b87` had a frontend test failure because the
pre-existing `v049 dashboard layout and important native rail` regression
still asserted the **obsolete** v049 desktop layout declarations existed.
The new exact-selector retirement regression already passed. The older
regression was updated rather than removed: it now asserts the retired
unconditional declaration block stays absent, checks the exact canonical
v056 `margin-top` / `grid-template-columns` / `gap`, and continues to
require the original 1600px wide gap, 1199px tablet grid and **all four**
important Dashboard rail-card declarations. This tightens ownership
coverage without weakening any visual, responsive or safety thresholds.
Run the full CI suite again on the **new exact final HEAD**; checks from
the initial failed HEAD are not merge evidence.

## 2026-10-19 — v049 → v056 page and panel text authority

Retired **9** normal-priority, unconditional historical v049 declarations.
Each is overridden by a later v056 rule with the **same single selector,
CSS property, specificity and at-rule context**:

| Old v049 selector | Retired properties | Later v056 values |
| --- | --- | --- |
| `.nfc-page-title` | `color`, `line-height`, `letter-spacing` (3) | w2 text; 1.18; -0.014em |
| `.nfc-page-description` | `max-width`, `color` (2) | 82ch; w2 muted text |
| `.nfc-data-panel-header` | `gap` (1) | 18px |
| `.nfc-data-panel-title` | `color`, `letter-spacing` (2) | w2 text; -0.004em |
| `.nfc-data-panel-description` | `color` (1) | w2 subtle text |

The five now-empty v049 unconditional blocks were removed. Separate
later v049 declarations for title font-size/weight, description spacing
and line-height, panel-header min-height/padding/border-bottom color
and background, and panel-title/description typography were retained.
These remain guarded in the historical cascade regression alongside
v054's higher-specificity theme text rules and v056 final owners.

Preserved all existing 767px mobile styles, theme variables, grouped
selectors, `!important` priority, keyboard focus, reduced-motion and
reduced-transparency contexts, and CSS import order. No shorthand
substitution or cross-specificity retirement was attempted.
Automated 8-width × 4-theme read-only Chromium, full backend, Docker
and dependency checks are still mandatory on the exact final PR HEAD.

After merge historical CSS redundant declaration total: **217**
(208 previously merged + 9 in this batch).
Formal high-level acceptance remains **69/74 (93.2%)**; manual visual,
a11y, real isolated NAS, and deployment sign-off are not yet complete.

### PR #299 — keep Stage 5E-C/H and v049 historical acceptance guards current

The first PR HEAD `2bbca810` failed frontend validation in existing
Stage 5E-C, Stage 5E-H and v049 historical test cases because they
still demanded an earlier unconditional v049 block or historical
values now safely retired by the later v056 canonical owner.
The new nine-property v049→v056 regression itself passed.

Rather than suppress or delete those suites, updated them to enforce
the stronger current contract: only one independent late v049 block
survives for each retired selector, the obsolete CSS properties do not
return, the exact v056 canonical property values remain correct,
v049's independent typography and header/panel geometry are kept,
and the original 24/23/13 historical check counts remain intact.
Unrelated responsive, theme, accessibility and read-only browser
coverage is unchanged. Full 16-check/4-workflow validation must rerun
on the replacement final PR HEAD; previous results are not mergeable.

### PR #299 — top-level owner ordering, not substring matches

A subsequent frontend test run isolated one remaining legacy guard failure:
`indexOf('.nfc-page-title {')` matched an earlier indented mobile rule,
while `indexOf('.nfc-data-panel-header {')` matched a qualified selector.
The test now anchors those matches at column zero to check the intended
**unconditional top-level owner** positions, still requiring the exact
relative order of all six selectors. Responsive rules and qualified
selector coverage remain unmodified. Complete CI must rerun from the
newest PR HEAD before merging.

## 2026-10-19 — v054 → v055/v056 header and eyebrow cascade

Retired **4** unconditional, normal-priority v054 declarations.
Every removed property was an exact single-selector, exact CSS property,
equal-specificity loser to a later-imported rule:

| v054 selector | Retired property | Later canonical owner |
| --- | --- | --- |
| `.nfc-app-main .nfc-page-eyebrow` | `display` (1) | v056 `none` |
| `.nfc-app-main .nfc-page-eyebrow` | `margin-bottom` (1) | v055 `10px` |
| `.nfc-app-main .nfc-page-actions .nfc-action-bar` | `gap` (1) | v055 `9px` |
| `.nfc-header.nfc-header` | `min-height` (1) | v056 `68px` |

The v054 action-bar gap rule became empty and was removed. Preserve
the eyebrow's six independent alignment/typography declarations
and `::before` ornament, header's historical padding/border-bottom
color, and v055 `justify-content: flex-end`. The earlier eyebrow
properties are intentionally kept even though v056 sets display none:
the cleanup relies strictly on exact cascade shadow evidence, not
assumptions about an element's visibility.

Preserve separate 767px header `min-height: 54px`, the
reduced-transparency `backdrop-filter: none !important`, all other
media/theme/focus declarations and the v054→v055→v056 source order.
The registered regression locks both the removed shadows and retained
values; full 8-width/4-theme read-only Chromium, backend, Docker,
and dependency validation are required on the final PR HEAD.

After merge: historical redundant CSS declaration total **221**
(217 previously merged + 4 in this tranche).
Formal milestones remain **69/74 (93.2%)**; partial historical
CSS cleanup does not close comprehensive theme ownership, manual
visual/a11y, isolated NAS or production sign-off.


## 2026-10-19 — v049 → v056 metric-card surfaces and hover authority

Retired **8** unconditional, normal-priority, exact-selector v049 property
shadows, all overwritten in later-imported v056 with the same CSS property,
specificity and unconditional at-rule context:

| Historical v049 selector | Retired declarations | v056 exact-selector authority |
| --- | --- | --- |
| `.nfc-metric-card` | `min-height`, `padding`, `border-radius`, `background`, `box-shadow` (5) | 104px; 16px 17px; w2 medium radius; w2 mixed surface; no shadow |
| `.nfc-metric-card:hover` | `transform`, `border-color`, `background` (3) | none; w2 strong hairline; w2 surface |

Preserved the v049 metric-card independent `border` shorthand and four-part
`transition`, distinct last-child border-right, hover **box-shadow**, and
original v049 mobile 767px min-height/padding and 420px metric-grid columns.
The surviving hover `box-shadow` and v056 `box-shadow: none` belong to
different state selectors; no cross-selector equivalence was assumed.
Retained all `!important`, focus, theme, reduced-motion and
reduced-transparency rules and original CSS import order.

Added leaf-rule exact-context/property-owner regression checks for all eight
retired declarations, and updated the Stage 5E-C/H historical acceptance
tests to follow five successor-layer rules while preserving their original
24/23 coverage counts. No browser matrix, read-only guard, or CI gate
was removed. Real read-only Chromium 8-width/4-theme validation, all PR
CI and main post-merge checks remain mandatory.

Cumulative safely retired historical CSS declarations after this tranche:
**229** (221 previously merged + 8 new retirements).
Formal milestones remain **69/74 (93.2%)** pending comprehensive CSS/theme
closure, human visual/a11y approval, isolated NAS verification and deployment
sign-off.


## 2026-10-19 — v056 right-workspace semantic text contrast contract

Instead of another declaration-deletion batch, this stage audits the
v056 semantic foreground palette against its four solid background surfaces.
Source-level WCAG AA normal-text contrast (4.5:1) exposed three token issues:

| Token | Before | After | Reason |
| --- | --- | --- | --- |
| Light `--nfc-w2-text-muted` | `#66707c` | `#596572` | 4.44:1 on strong surface was below 4.5:1 |
| Light `--nfc-w2-text-subtle` | `#8a94a1` | `#626d78` | 2.71–3.07:1 on light surfaces was below 4.5:1 |
| Dark `--nfc-w2-text-subtle` | `#7f8995` | `#89939f` | 4.29:1 on strong surface was below 4.5:1 |

Added `frontend/scripts/css-w2-theme-token-contrast.test.mjs` to the
existing full `npm test` runner. Its 24 foreground/surface combinations guard
both themes and all 11 explicitly paired semantic colors; it also retains
the original import-order and read-only 8-viewport/System Dark fixture checks.
Light text/muted/subtle hierarchy and dark inverse hierarchy are enforced.

Only three semantic color values changed. Original responsive breakpoints,
layout, focus and hover selectors, reduced-motion/transparency, importance,
sidebar styles, existing contrast tests, Chromium matrices and CI remain.
**Scope limitation:** the assertion covers opaque source-declared solid
surfaces, not computed blending, gradients, overlays, disabled states or
every rendered pixel. Manual visual and accessibility acceptance, full CSS
convergence, isolated NAS testing and production approval are still pending.
Historical redundant declaration count stays **229**; formal high-level
milestones stay **69/74 (93.2%)**.

## 2026-10-19 — computed semantic palette evidence on real React workspaces

The v056 source-level 24-pair check from PR #303 does not alone prove
that the same CSS variables remain effective after the complete import
cascade or under all responsive and theme modes.

Extended the existing **read-only** `browser-workspace-cascade.mjs` suite,
rather than replacing or shortening its accepted screenshot matrix.
After the existing page-geometry check for each of the six actual React
routes (Dashboard, Plans, Tasks, Indexes, Media, Quarantine), Chromium now
reads seven `--nfc-w2-*` tokens using `getComputedStyle(.nfc-app-main)`,
verifies the effective Light/Dark/System theme and its typography hierarchy,
and checks all **12 text-role / solid-surface WCAG AA 4.5:1 pairs**.

| Evidence dimension | Required coverage |
| --- | --- |
| Rendered routes | 6 workspace pages |
| Browser widths | 360, 390, 430, 768, 1024, 1280, 1440, 1920 |
| Theme modes | explicit light, explicit dark, System light, System dark |
| Browser snapshots | 32 width/theme combinations × 6 routes = 192 actual-page cases |
| Contrast pair assertions | 192 × 12 = **2,304** computed CSS-token comparisons |
| Artifact | `frontend/artifacts/browser-workspace-cascade/w2-computed-theme-audit.json` |
| Existing screenshot evidence | Original 352 screenshots remain unchanged |

The new JSON evidence preserves route, width, chosen/system/effective theme,
all seven computed tokens, compared pair count and minimum ratio. Registered
`css-w2-theme-token-contrast.test.mjs` now protects this real-browser audit
from removal. The original synthetic-GET-only browser isolation, write/outbound
denials, focus keyboard evidence, dense ledgers, responsive and CSS source
tests remain mandatory. No production or NAS data is accessed.

**Interpretation boundary:** this proves inherited **computed CSS custom
property** values on the real workspace scope across 192 route/theme/width
cases, not the final painted foreground/background of every element, alpha
blending, gradient overlays, all focus/disabled states, human visual
acceptance, screen-reader behavior or complete CSS/theme convergence.
These remain explicit high-level acceptance work.

Historical redundant declarations retired stays **229**; high-level
milestone remains **69/74 (93.2%)**.

## 2026-10-19 — actual painted ledger heading contrast (PR following #304)

Prior checks cover **opaque source theme tokens** (PR #303) and actual
**computed custom-property values** on six React workspaces (PR #304).
Neither alone proves the text/background pair that Chromium renders.

Extend the **same isolated read-only Chromium workspace matrix** to inspect
the visible real accessible heading on the five operational ledger routes
(Plans, Tasks, Indexes, Media, Quarantine). At **8 viewports × 4 theme
variants × 5 routes = 160 heading cases**, read `getComputedStyle` for the
actual foreground and each ancestor's background. Alpha-composite all
translucent layers back to a provably opaque painted ancestor. Reject
unrecognized CSS color spaces, out-of-gamut values, gradient/image
ancestors, opacity effects and any missing opaque base rather than
silently inventing a white background. Assert **WCAG AA 4.5:1** normal
text contrast on this measured solid-paint scope.

Record route, viewport, selected/system/effective theme, original and
normalized computed foreground, painted background, ancestor layers
and numeric contrast in `painted-ledger-heading-audit.json`.

**CI evidence delivery correction:** explicitly upload the already
generated `w2-computed-theme-audit.json` from PR #304, the new
`painted-ledger-heading-audit.json` and the existing checkbox keyboard
JSON alongside unchanged 352 screenshots. Keep all original 16 PR
checks, 4 workflows, eight viewport audits, read-only GET interception
and post-merge branch-cleanup gates.

**Scope:** heading ink over flat, compositable ancestors; this is not
whole-page pixel-level, gradient, pseudo-element, overlay or human
accessibility/visual sign-off. Dashboard's separate hero remains
covered by prior layout/token tests, not the new heading-paint claim.
All high-level remaining acceptance milestones stay open. No NAS
mutation, no production approval, historical declarations retired
stay **229**, formal progress **69/74 (93.2%)**.

## 2026-10-19 — real Dashboard/Media metric card normal + hover contrast

PR #305 established actual painted ledger heading ink/background evidence.
The metric cards retain a separate cross-generation cascade: early
Console v2 Dashboard uses high-specificity `!important` surface and typography
while v056 later owns the workspace card family and regular hover state.
Comparing inherited palette tokens alone cannot verify either computed winner.

The original read-only 8-viewport × 4-theme Chromium workspace suite now
checks the first actual rendered Dashboard and Media metric cards in **normal
and real Playwright pointer-hover states**, comparing both visible metric
label and value text with alpha-composited actual CSS ancestor backgrounds.
That is **2 routes × 8 widths × 4 themes × 2 states × 2 text roles = 256**
foreground/painted-background pairs at the WCAG AA 4.5:1 normal-text gate.

Every calculation preserves the exact route, width, selected/system/effective
theme, normal/hover state, computed card background, foreground, composited
painted background, layer ancestry and numeric ratio in
`metric-hover-painted-contrast-audit.json` and uploads the artifact to CI.
Unsupported color spaces, non-solid backgrounds/gradients, opacity layers,
unresolvable alpha, or missing actual text fail closed rather than passing
with an assumed white backdrop. No data mutation or outgoing NAS calls.

The metric audit runs **after the previously accepted page screenshot**,
preserving 352 existing screenshots, populated ledgers, 192 computed-token
cases, 160 heading cases, native keyboard focus tests, all breakpoints and
4 exact-HEAD PR workflows. There are no CSS style changes.

Scope: ordinary painted metric label/value ink only; complex pseudo
elements, gradients, icon masks, hover tooltips, entire-page pixels and
screen-reader/manual review remain separate acceptance criteria.
Historical redundant CSS declaration retirement stays **229**; formal
high-level progress stays **69/74 (93.2%)**.

## 2026-10-19 — same-document right-workspace CSS theme inversion and restoration

Previous fixed-theme screenshots, computed tokens, painted ledger text and
metric normal/hover audits do not establish whether a **mounted** workspace
properly invalidates the browser CSS cascade after the effective root theme
changes and then recovers the original computed styles.

The same read-only Chromium workspace matrix now checks Dashboard and Media
metric cards on **8 widths × 4 initial Light/Dark/System fixtures × 2 routes
= 64 same-document inversion-and-restore sequences**. After the accepted
screenshots and normal/hover evidence, the check reads four computed v056
semantic tokens plus actual metric card label/value foreground and its
alpha-composited painted background. It then temporarily changes the
document root's **effective CSS theme only**, without navigation, and
re-measures opposite-theme palette ownership and the actual metric ink.
Finally it restores the root theme and original inline color-scheme,
asserts exact token and ink restoration, and verifies persisted provider
mode has not changed. All inverse and restored text/background pairings
must meet 4.5:1 (64 × 2 phases × 2 roles = **256 comparisons**).

**Important limitation:** direct DOM effective-theme manipulation is a
CSS cascade invalidation probe, **not a user-facing ThemeProvider control
test**. The existing `browser-theme-resilience.mjs` independently tests
actual theme selection, cross-tab updates, system preferences, and storage
denial on the login UI; neither suite alone certifies every overlay gradient
or human interaction/a11y experience.

Evidence is uploaded to `live-metric-theme-cascade-audit.json` beside
the earlier computed-token, painted-heading, normal/hover metric and
checkbox/focus JSON evidence. Preserve the same 352 accepted screenshots,
GET-only requests, outbound denials, 8 width × 4 theme browser matrix,
frontend/backend/Docker CI, and exact-HEAD merge gates.

No product CSS, app logic, theme provider code, data or production changes;
229 redundant historical CSS declarations retired and formal progress
69/74 (93.2%) remain unchanged.

### 2026-10-19 — live CSS theme probe render-frame synchronization

Initial PR #307 UI CI failed at the first `light-dark-360` route:
immediately after changing `data-theme`, the v056 semantic tokens and card
background were already dark, while an old Console v2 metric label
still returned the light computed ink `rgb(105, 105, 101)`. This is an
**intermediate frame**, not sufficient evidence of the stable theme owner.

The Chromium probe now waits for two `requestAnimationFrame` callbacks
after *each* CSS-only root inversion and restoration, so the browser can
resolve pending style invalidation/paint and very short reduced-motion
transitions before measuring normal-text contrast. The probe **still**
requires 4.5:1 on actual painted backgrounds, actual metric ink to differ
between themes, and an exact color/token recovery after restoring the
original theme; failed steady-state visuals must fail CI.

This does not claim transient frames are visually acceptable or constitute
a pixel-level transition audit. A separate future interaction study could
evaluate transient theme-switch flashes with real user controls.


## 2026-10-20 — real authenticated workspace ThemeProvider control / metric paint

The previous PR #307 exercise directly changed the root effective CSS theme,
then restored it. That is valuable CSS-cascade invalidation evidence, but it
cannot prove that an actual logged-in user selection in the Header menu flows
through React's ThemeProvider, persists explicit/System mode, and repaints
the mounted Dashboard/Media metric cards correctly.

Extended the existing read-only Chromium workspace matrix **after** each
accepted screenshot and existing normal/hover/CSS-only probes. Using the
real Header summary (aria-label `切换界面主题`) and its actual theme buttons
at >= 768px, or the real mobile navigation drawer's accessible theme buttons
at < 768px,
each Dashboard/Media page now switches from the initially selected
Light/Dark/System fixture to the opposite **explicit** mode, then restores
the initial choice **through the same user control**. System must return to
System (not an explicit equivalent). For every step the browser checks
the selected `aria-pressed` button, root `data-theme`, color-scheme,
persisted `nfc_theme_mode`, computed workspace semantic tokens, real
metric label/value foreground over alpha-composited painted backgrounds,
and exact palette/paint restoration.

Coverage: **2 real routes × 8 viewports × 4 initial mode/system fixtures =
64 user-action / recovery sequences**, with **256 changed/restored painted
metric foreground/background comparisons**, each required to be >= 4.5:1.
**Actual issue found on first CI attempt:** mobile `console-v2.css` intentionally
hides the desktop Header theme dropdown below 768px without offering a
replacement control. A real 360px Playwright click timed out because the DOM
node was not visible. Fixed the product gap by adding three `aria-pressed`
Light/Dark/System choices inside the existing mobile nav drawer (with 44px
minimum touch targets and focus-visible styling); after a choice, the drawer
closes. The phone browser test now opens the real drawer, selects a theme,
and checks the same ThemeProvider, storage and painted metric state as desktop.
No hidden-control or forced-click workaround is permitted.

The check waits for two animation frames before steady-state contrast
sampling, without relaxing the threshold. It writes
`provider-metric-theme-user-action-audit.json`; the UI workflow uploads it
alongside all earlier screenshot/JSON evidence. Existing 352 accepted
screenshots, synthetic GET-only fixtures, backend write/outbound denials,
ThemeProvider login resilience and CSS-only inversion remain unchanged.

**Limitations:** this is a real-user-control **steady-state** browser test,
not frame-by-frame or pixel-level validation of intermediate flashes;
gradients, pseudo-elements, overlays, human visual and assistive-technology
sign-off still need independent work. No app business logic, production
deployment or real NAS filesystem changes. Historical redundant CSS
declarations remain **229** and formal milestone completion remains
**69/74 (93.2%)** pending comprehensive closure.


## 2026-10-20 — ThemeProvider rendered-frame metric text contrast audit

PR #308 verified **steady state** after clicking the actual authenticated
Header or mobile navigation theme controls, but only after two browser paint
ticks. Earlier CSS-only theme inversion had shown a short-lived disagreement
between already-dark card surfaces and stale historical Console v2 metric ink;
steady-state checks intentionally could not determine whether a real rendered
frame could show sub-AA contrast.

Extend the existing actual-user ThemeProvider workspace matrix to arm a
`MutationObserver` on the effective root `data-theme` **before** each
real UI selection. Beginning on the following `requestAnimationFrame`,
capture the **first 12 animation-frame computed-style samples** for the real
Dashboard/Media metric label and value. Alpha-composite actual solid ancestor
backgrounds to a verifiably opaque layer, and assert each sampled ink/surface
pair maintains **4.5:1**. Refuse unsupported color spaces, gradients,
opacity/compositing beyond the flat-paint model and missing visible text
rather than guessing a background.

The same evidence is captured during both theme change and return to
the original explicit/System mode:
**2 routes x 8 widths x 4 initial modes = 64 real user-action sequences**;
**64 x 2 directions x 12 frames x 2 text roles = 3,072 contrast comparisons**.
Evidence is written to
`frontend/artifacts/browser-workspace-cascade/provider-metric-theme-frame-audit.json`
and included in the existing UI Action artifact upload. All original 352
screenshots still precede UI theme interactions; existing storage, click,
steady-state, CSS-only invalidation, GET-only synthetic fixture and forbidden
write/outbound checks remain intact.

**Interpretation boundary:** each sample is a computed CSS foreground over
measured solid ancestor layers at a browser animation frame callback,
not a screenshot/pixel-level observation of composited pixels, device
sub-frame flicker, pseudo-elements, overlays, gradients, or every element.
The browser matrix uses `prefers-reduced-motion: reduce`; normal-motion
transitions and independent human visual/assistive-technology acceptance
still require separate evaluation. This cannot by itself close the
CSS/theme high-level milestone. No production or real NAS data operation.
Formal milestones stay **69/74 (93.2%)**; historical redundant declarations
retired remain **229**.


### 2026-10-20 — first frame-level CI failure and scoped paint-transition fix

The first candidate of PR #309 failed its actual Chromium frame sample at
`light-dark-360`, **real mobile ThemeProvider Dark -> Light recovery**:
the first sampled frame had a newly white
`rgb(255, 255, 255)` metric-card background while the previous dark
text `rgb(182, 182, 176)` was still computed, yielding **2.037:1**
for the label. The value also temporarily retained its old inverse ink.
The existing stable two-rAF contrast assertions were not relaxed.

Source review identified two independently animated historic palette layers:
`index.css` / v049 transitioned metric card **background** while
`index.css` transitioned metric value **color**, allowing a color/background
mismatch when the root theme changes. v056 now explicitly owns the
`transition-property` for actual `.nfc-app-main` metric elements:
cards preserve hover `transform`, `box-shadow` and `border-color`
transitions but no longer interpolate theme-bearing `background`;
metric values/icons preserve `transform` while removing `color`
transition; labels have no transition. All previous geometric, normal/hover,
reduced-motion and theme token rules remain unchanged. The first-frame
4.5:1 assertion stays in force and will be retested on the new final HEAD.

A source-level regression test pins this ownership without claiming
that CSS source checks replace rendered frame samples. Historical
redundant CSS declaration count **229** and milestones **69/74** unchanged.


## 2026-10-20 — normal-motion ThemeProvider frame acceptance (PR #310)

The prior PR #309 per-frame matrix exercised Chromium contexts with
`prefers-reduced-motion: reduce`. For this separate, non-redundant
acceptance gate, the same mounted real Dashboard/Media UI, test login
and read-only synthetic GET fixture now explicitly switch the browser
to `prefers-reduced-motion: no-preference` before invoking the **actual**
Header dropdown or mobile drawer user control. The check validates
that reduced motion is truly disabled and that computed card hover
border transitions and value transform transition are present. It rejects
`all`, `color` or `background` in metric card, label and value
transition properties, then executes the previous first-12-rAF
4.5:1 foreground/opaque-ancestor contrast capture for both the switch
and restoration of the original Light/Dark/System preference.

Coverage: 3 representative breakpoint widths (360px mobile, 768px
tablet boundary, 1440px desktop) x 4 explicit/system mode fixtures
x Dashboard/Media = **24 normal-motion real user sequences**;
24 x 2 directions x 12 frames x 2 text roles =
**1,152 independently verified normal-motion contrast pairs**.
The original 64 reduced-motion cases / 3,072 painted pairs remain
unchanged and are still tested in every build. All 352 screenshot
baselines remain captured before theme interactions, with no outgoing
or write requests; browser emulation is returned to reduce mode
within `finally`. UI Action uploads the new
`provider-metric-theme-normal-motion-frame-audit.json` separately
from existing reduced-motion frame evidence.

Limit: a sampled rAF computed flat CSS paint pair is not a captured
compositor pixel, video flash analysis, pseudo-element/gradient overlay,
human visual sign-off, or complete assistive-technology pass. No claim
of production or real NAS validation. Formal milestone count stays
**69/74 (93.2%)**, and historical safe CSS retirement stays **229**.


## 2026-10-20 — real composited portal tint and hidden hero gradient audit (PR #311)

Prior PRs #309–#310 audit real Dashboard/Media metric paint during
ThemeProvider changes in reduced/normal-motion modes. They explicitly
reject gradients, backdrop effects and translucent text when those cannot
be modeled as an opaque flat ancestor.

This increment checks two **different real rendered app surfaces**:
- Actual Dashboard hero at 8 viewports x 4 theme/system fixtures. Its
  decorative `.nfc-v2-hero-illustration` contains CSS gradients, but is
  intentionally `display: none` in the Pure White design. The browser
  asserts it has no layout boxes (so readable copy is **not** laid over
  that unmodeled gradient) and checks eyebrow, heading, description and
  caption against alpha-composited **opaque solid** ancestor paints.
  **32 actual route/theme cases x 4 text roles = 128 AA comparisons**.
- Actual nested ScanCreate -> DirectoryPicker Radix body portals.
  Select the synthetic read-only directory through its real React button,
  requiring an active `li.is-selected` whose CSS uses translucent
  `color-mix(in srgb, var(--nfc-dialog-accent) 8%, transparent)`.
  Walk computed paint layers from each real text node to a proven opaque
  ancestor and alpha-composite in stacking order. Reject unknown color
  formats, image/gradient layers, node opacity, filters and backdrop blur
  instead of claiming unverified pixels. Check selected name/path and
  portal title/description ink, plus both alpha-bearing scrims and
  z-order. **8 widths x 4 themes = 32 nested portal cases x 6 real
  text roles = 192 WCAG-AA painted comparisons**.

The fixtures deny every mutating API request and now explicitly block
outbound origins. Each accepted browser screenshot is still captured
**before** the new user selection or hero check. Artifacts:
`frontend/artifacts/browser-workspace-cascade/dashboard-hero-gradient-isolation-audit.json`
and `frontend/artifacts/browser-overlay/composited-portal-text-contrast-audit.json`,
both uploaded by UI Validation. No app product CSS/token change, NAS
write, deployment, or production traffic.

**Scope boundary:** this proves gradient *isolation* from hero text and
flat-alpha-composited computed style in actual portals, NOT full pixel
analysis of visible gradients, human overlay visual acceptance,
blur/image backdrops or arbitrary CSS pseudo-elements. Do not close the
high-level CSS/theme, human visual or a11y milestones based on this
automated subset. Formal milestones remain **69/74 (93.2%)**; historical
redundant declarations safely removed remain **229**.


### PR #311 Chromium finding — inherited frosted Dashboard header

The first Dashboard hero audit failed at 360px/light on the actual
`.nfc-page-header` ancestor with computed
`backdrop-filter: blur(16px) saturate(1.2)`. The legacy
`v049-workspace.css` global page-title style still owned this effect,
even though the later Pure White `.nfc-v2-dashboard-hero .nfc-page-header`
has a deliberately transparent background and no frosted card surface.
Awaiting animation completion cannot make inherited blur a supported
flat-paint layer.

The fix is **specific to** `.nfc-v2-shell .nfc-v2-dashboard-hero
.nfc-page-header` in `console-v2.css`, loaded after v049. It explicitly
sets both `backdrop-filter: none` and `-webkit-backdrop-filter: none`,
without changing the global title/header rules or other translucent
surfaces. Static regression tests pin CSS cascade ownership while the
real Chromium Dashboard hero audit still rejects actual computed
gradients, filters and translucent/unresolved ancestors. All original
contrast and screenshot expectations remain unchanged.


## 2026-10-20 — selected DirectoryPicker keyboard focus against translucent paint (PR after #311)

PR #311 verified six real portal text roles on translucent selected rows,
but did not prove that the **native checkbox keyboard focus indicator** remains
legible on the same composited surface. The existing isolated Chromium
ScanCreate → DirectoryPicker scenario now checks the actual row selection,
focuses its directory-open button and presses **Tab** to the adjacent real
checkbox. It fails closed unless that selected, checked checkbox is the
active element with `:focus-visible` and an opaque solid outline at least
2px wide with 1px offset.

The audit alpha-composites the checkbox's **label/selected-row background**
through actual DOM ancestors to the first provably opaque surface, rejecting
unsupported gradients, filters, opacity effects, and unknown computed colors.
It compares the actual computed outline against that painted surface at the
**3:1 non-text indicator** threshold, adding **32 independently measured
keyboard-focus pairs** across eight widths and four theme/system scenarios.
Existing **192 text comparisons >=4.5:1**, both portal scrims, page screenshots
and all safety gates remain untouched. Each accepted case also captures a
new `directory-selected-focus-<mode>-<system>-<width>.png` evidence image,
and the existing `composited-portal-text-contrast-audit.json` now contains
the focus style, offset, width, painted background and measured ratio.

This is **computed flat-paint focus evidence**, not pixel-level output or
complete keyboard/screen-reader/manual approval. The fixture blocks outbound
requests and non-GET APIs; no NAS mutations, production operations, or
stylesheet/application runtime changes. Historical redundant CSS declarations
stay **229**; high-level milestones stay **69/74 (93.2%)**.


## 2026-10-20 — real DirectoryPicker read-error/retry contrast (PR following #312)

The prior selected-row keyboard audit covered normal directory browsing, but
not the explicit `DirectoryPickerModal` `role="alert"` branch for a failed
directory GET or the keyboard-reachable Retry button. The same mounted
ScanCreate → DirectoryPicker Chromium smoke suite now injects a **local-only
HTTP 503 GET response** into the existing isolated Playwright route fixture.
The failure originates after actual user search input changes the React Query
key; the test waits for the real error state (including normal Query retries)
and then tabs from Search to the live **重试** button.

At **390px mobile + 1440px desktop × 4 light/dark/system variants = 8
read-error/retry interactions**, inspect actual computed, opaque solid error
banner and retry button paints. Reject unsupported images, opacity/filters or
translucent calculated colors rather than guessing a background. Test both
alert text and Retry label at **>=4.5:1**, and the actual focused Retry
outline against both error banner and button surface at **>=3:1**. Validate
visibility/viewport containment and that a successful locally mocked retry
removes the alert while preserving the selected path. New
`directory-error-retry-contrast-audit.json` and eight scoped error-state
screenshots accompany existing artifacts. The original 32 selected-row
keyboard focus cases, 192 composited normal-text pairs, 32 focus pairs and
baseline portal screenshots are not replaced.

Only synthetic `GET /api/filesystem/list` receives a forced error; every
non-GET API request remains denied and every external-origin request aborted.
No production NAS read/write, runtime API/CSS/permissions change, human a11y
approval or pixel-rendered gradient analysis. Formal milestone count remains
**69/74 (93.2%)**, and historical safe CSS declaration retirement stays
**229**.
