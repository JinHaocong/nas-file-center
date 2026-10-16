# Console v2 — full-site mock visual audit (real Chromium)

Status: **new automated visual-evidence gate; NOT visual owner approval**.

## Scope: exhaustive router coverage

Audit all **24 actual React Router routes**, including `/login`, the 19 top-level authenticated navigation pages, and the four parameterized detail/editor routes (`/scans/:id`, `/scans/:id/dedupe`, `/workflows/:id`, `/plans/:id`), plus non-navigation Archive Recovery and other routes as declared in `frontend/src/router/index.tsx`. The test derives the router inventory and fails when it differs from the visual case list; new routes cannot silently bypass the audit.

For each route, the built production React frontend is visited in **8 viewport widths** (360/390/430/768/1024/1280/1440/1920) × **4 theme cases** (light, dark, system-light, system-dark). The 8 CI matrix jobs provide **768 route/theme/width renders**, each with its own actual Chromium screenshot and diagnostic entry. At 390 and 1440 light the script captures full-page screenshots to inspect below-the-fold controls; the remaining cases capture the visible viewport.

Each screenshot manifest includes final browser pathname, effective CSS theme, document title, heading text, visible content length, document horizontal overflow, shell presence and uncaught page errors. A missing/redirected page, empty render, unexpected root overflow, theme error or uncaught exception fails the job. All screenshots and the JSON defect manifest are uploaded even on failure.

## Mock coverage and strict NAS isolation

All `/api/**` calls are intercepted by Playwright **before contacting a backend**. Synthetic read-only fixtures include an authenticated test user, fail-closed settings, populated scans/plans/workflow examples, indexed root, dashboard summary and a sample Download Verification mismatch. Other unmodeled GET collections default to the safe empty state. All non-GET API calls are blocked with 405; any origin outside the loopback Vite preview is denied and recorded as a hard error.

This suite is **not a full workflow exercise** and does not verify each data shape's populated/error/large-table behavior: existing specialized overlay/workspace/ledger suites cover additional cases. No real NAS, Dockerized production service, actual WebDAV endpoint or operator file action is accessed.

## Evidence and acceptance boundary

Workflow: `.github/workflows/ui-v044-validation.yml`, job `full-route-visual-audit`, 8 matrix widths.

Source: `frontend/scripts/browser-full-route-visual.mjs`, guarded by `frontend/scripts/full-route-visual.test.mjs`.

For each successful PR HEAD, download the eight `full-route-visual-<width>-<sha>` Action artifacts and inspect the actual PNGs, especially headings, form grouping, column alignment, cropped labels, 360–430px mobile controls, modal stacking, non-overflowing wide tables, contrast, and long empty/loading/error messages. Record user-visible defects with screenshots; fix and rerun **all latest-head checks**. CI automation alone does not substitute for a human visual comparison and user approval.

Do not mark the high-level eight-width final browser review, CSS consolidation, full keyboard/a11y, real NAS, or owner/deployment boxes complete solely on the automated screenshot run.

## Next required evidence

1. Actual Action run 8/8 matrix jobs success for exact newest PR head; review 768 screenshot captures and JSON manifests.
2. Compare representative samples across each page and width; log concrete errors and directly repair regressions (no CSS-theme reversion).
3. Close the eight-width visual item only after complete final screenshot review; owner approval is separate and explicit.

## Actual PNG review findings and immediate repair

First trial Chromium output was downloaded and inspected, not just inferred from log assertions:

- **1024px light:** a 24-page visual contact sheet showed five blank pages caused by invalid synthetic API shapes. These were mock **test-fixture** defects; data were aligned to the real typed `ScanJob`, workflow array/list, Dashboard, and Settings/resource-policy/session contracts. No business API was modified.
- **390px light:** the new Download Verification screen rendered its remote-directory label inline with a cramped input, while a six-column history table collapsed into broken narrow columns. The real mobile PNG supplied the reproduction. Added an owned responsive form grid with vertically stacked field labels and an internal horizontal-scrolling evidence table, with no global horizontal scroll or legacy-theme fallback. Source and browser computed-geometry regressions now guard both cases.
- **390px Plans:** legacy-count text displayed `undefined` because the mock `/api/plans/legacy/summary` did not return the typed counters. Corrected the fixture, without changing production logic.
- **Download Verification detail:** the browser also clicks the real `查看条目` action and captures the path-by-path SHA256 result panel in every width/theme (32 additional interactive screenshots). The final evidence goal is **768 route snapshots + 32 selected detail snapshots = 800 screenshot PNGs** across eight artifacts.

These fixes do not claim that every page's typography, colors or interaction states are manually signed off. All real NAS routes stay blocked in the browser.

## Screenshot-based mobile header review — Stage 5E post-merge

Screenshot source: PR #264 Chromium `main` evidence artifacts at 360px, 390px, 768px, 1024px and 1440px; no external NAS. The human comparison of the 24 light-mode page screenshots at these five widths (120 route images) shows a reproducible **360px header breadcrumb wrap**: both the parent `工作台` and current page title split into multiple lines. Longer route titles (e.g. `下载完整性校验`) also wrap at 390px. The two safety/status badges and user menu should remain visible.

Scoped repair: `console-v2-mobile-header.css` (last CSS import) hides only the redundant parent breadcrumb and separator on mobile; it keeps the current page name as a single, ellipsized flex item, with a stricter 360px width cap. It does **not** hide Safe Mode, Worker Status, user actions or the navigation drawer. A **real Chromium** `browser-full-route-visual.mjs` assertion now checks the single-line computed current-page title, hidden duplicate parent crumb, absence of header action overlap, and viewport clipping on all 23 authenticated React route cases for **360, 390, 430px** and the 768px boundary's mobile side. The eight-width/four-theme matrix remains 800 screenshots total.

The 120 light-mode review is a **targeted visual pass**, not complete frame-by-frame human approval of all 800 light/dark/system images or all content states. Full eight-width design sign-off remains open pending review of all theme cases and active UI states. The formal final-acceptance gate count remains **68/74**.


## Keyboard-first route and reduced-motion follow-up

The same eight-width / four-theme route screenshot CI now exercises native `Tab` and `Enter` in the actual production React app, for each of the 23 authenticated routes, with a strictly synthetic, read-only backend. It verifies the new first-Tab skip link is in view and has a visible focus outline, Enter moves DOM focus to `#main-content` (not only the hash), and the header navigation's real computed transitions/animations are at most 1ms in the already-requested reduced-motion browser context. New CSS is scoped to the skip control and does not hide Safe Mode or Worker indicators.

This is **736 keyboard / reduced-motion route cases**, not a comprehensive manual keyboard/contrast/assistive-technology assessment or human sign-off. The existing 768 page screenshots and 32 Download Verification detail screenshots remain unchanged.

## Focus-link computed contrast and motion guard

The first-Tab route audit now checks the actual focused skip-link `getComputedStyle()` foreground, opaque background and outline in Chromium, after all historical CSS layers and light/dark/system overrides. It enforces at least **4.5:1** normal-text contrast and **3:1** visible focus-outline contrast, and saves measured ratios to the per-route manifest. The visible hit area must be at least **44px** tall. Both the header toggle and skip-link computed motion must be suppressed under `prefers-reduced-motion: reduce`.

These checks run across the existing **23 authenticated routes × 8 widths × 4 theme cases (736 cases)**, with no added screenshots, writable API requests or UI changes. Other forms, overlays, full visual review, assistive-technology review and owner sign-off remain open; the high-level tally stays **68/74**.

## Tablet 768px header screenshot regression (Issue #271)

Actual PR #268 Chromium screenshot evidence shows the authenticated 768px desktop-style navigation header compressing `工作台 / 仪表盘` into vertically wrapped text despite the 360–767px fix; 1280/1440 screenshots do not exhibit this. This isolated tablet repair preserves the current page identity as a single ellipsized line and hides only its redundant parent crumb and username *text* on the 768–899px compact-desktop breakpoint. The avatar/admin trigger, Safe Mode/Worker badges and navigation remain present.

The existing 8-width × 4-theme mock CI now also performs the real computed breadcrumb single-line/overlap/bounds geometry checks on every authenticated 768px route. This is a scoped header fix, not a full visual sign-off. **A distinct 768–1024px Dashboard hero empty-space issue also appears in the real screenshots and remains open under Issue #271 pending computed-layout evidence**; no speculative Dashboard CSS change is made. Overall acceptance stays **68/74**, and no real NAS or production action is taken.

## Tablet Dashboard vertical whitespace fix (Issue #271)

Actual PR #268/#272 screenshots reveal a large 768/1024px blank strip between Dashboard description and `刷新数据`, absent at 360 and 1280/1440px. CSS cascade analysis pinpoints historical `v056-right-workspace-v2.css` assigning `flex: 1 1 620px` to the `PageHeader` copy under 1199px. The Dashboard's header uses **column flex-direction**, so 620px becomes vertical height instead of desktop text-column width.

The Dashboard-owned stylesheet now restores its 768–1199px copy to content-sized `flex: 0 1 auto`, leaving other pages' layouts intact. The 8-width / 4-theme real Mock Chromium audit records computed flex-basis, flex-growth, hero height, action gap and metrics gap in the per-route manifest. At 768px and 1024px, oversized gaps, missing actions or collapsed metrics fail the CI job. Actual post-fix PNG review is required before issue closure. No NAS, backend or production action; owner sign-off and six high-level acceptance gates remain open (**68/74**).

## Tablet 768px Recent Scans filename readability (Issue #274)

Real Chromium light and dark Dashboard PNGs from PR #273 revealed a 768px six-column `最近扫描` table compressed until the synthetic filename wrapped one glyph per line, despite no page-level horizontal overflow. The underlying file names and navigation are intact; this is a table sizing fault.

Only the Dashboard **Recent Scans** table gets `min-width: 860px` at **768–899px**, enclosed by its existing `overflow-x: auto` region. Other tables and mobile cards are unchanged. The region has an accessible label, `tabIndex={0}`, and a visible `:focus-visible` outline. The actual 768px × 4-theme Chromium audit checks table and filename geometry, locally bounded scroll width and overflow, and **actually presses ArrowRight on the focused scroller** after the baseline screenshot. This does not access the real NAS or mutate backend resources.

This fix is **not** the final manual visual or WCAG/AT review. Formal final acceptance remains **68/74**, with six gates pending.

## Shared native filter select keyboard/focus contrast follow-up

A targeted remaining shared-primitives review found that `ConsoleSelect`'s CSS keyboard ring used a **24%-opaque** `color-mix(..., transparent)` while its text, background and border were already tokenized. The shared native select now uses an **opaque 3px Pure White theme-accent outline**, with a 2px offset and no animated transition during focus. This applies to existing Tasks status/type and Quarantine state filters, not the entire form system.

In the existing **25-route × 8-width × 4-theme** read-only real Chromium audit, the Tasks and Quarantine routes now exercise actual `Tab → Shift+Tab` keyboard focus for each of the three native selects. Per-control Manifest evidence records associated HTML `label`, accessible name, select tag, selected option preservation, geometry, resolved foreground/background and outline colors, outline thickness, focus-visible state and calculated sRGB contrast. Checks fail closed below **3:1 focus-ring contrast**, **4.5:1 normal-text contrast**, absent keyboard focus, inaccessible labels, clipped controls, or missing options. No select change events, writes or real NAS requests are issued.

This is a scoped shared-control accessibility improvement, **not** complete assistive-technology/manual keyboard review or full final owner acceptance. Six high-level gates remain open; formal progress stays **68/74**.

## Shared native checkbox keyboard and computed contrast audit (next tranche)

The Media ledger and Quarantine ledger both use the same controlled native `ConsoleCheckbox` without changing their eligibility/permission authorities. The existing dense `browser-workspace-cascade.mjs` fixture includes exactly one eligible item per page — **Media #802 (corrupt with frozen deletion evidence)** and **Quarantine #901 (active)** — plus two native-disabled protected records per page. This fixture, rather than the purposely empty full-route landing fixture, is now used for a real keyboard contrast check.

Each of 8 responsive widths × 4 light/dark/system combinations checks **both** pages (**64 computed-focus records** total). After capturing the same baseline screenshots, Chromium focuses the eligible native checkbox, enters genuine keyboard modality with `Tab → Shift+Tab`, and reads `:focus-visible`, actual outline width/color, the painted panel background, contrast ratio, selected/disabled state, accessible name and in-viewport dimensions. A broken native-disabled state, changed checkbox selection, missing focus, outline below **3px**, computed contrast below **3:1**, or nonzero focus-transition duration fails the workflow. Existing GET-only interception, outbound denial, full-grid screenshots, and the proven server-side safety contracts remain intact.

Media and Quarantine **only** receive scoped, immediate, opaque 3px focus rings using their existing Pure White theme tokens. The measured `checkbox-keyboard-audit.json` is retained beside the screenshot evidence in the UI Validation artifact. No simulated click/select to generate a Plan and no POST, Delete, Worker or NAS write is performed. This is a scoped shared-checkbox keyboard improvement, not full manual assistive-technology/contrast review or owner visual sign-off. Overall high-level acceptance remains **68/74**.

### Exact-head Chromium finding: transparent panel background

The first candidate encountered `rgba(0,0,0,0)` for the dense ledger's `.nfc-data-panel-body`. This is **not an opaque painted background**, so the strict `computedContrastRatio()` checker correctly rejected it rather than producing a false WCAG pass. The browser evidence now resolves backgrounds starting at the eligible checkbox's actual parent node, walks its DOM ancestor paint layers and alpha-composites them over the first opaque ancestor. An invalid CSS color or a missing opaque backing layer still fails closed; the calculator itself retains its strict opaque-input contract.

A historical source-level Quarantine regression that required the obsolete desktop-only focus selector was aligned with the new shared desktop/mobile selector. Both initial failures remain recorded in CI; require a **new exact HEAD** with all checks green before squash merging. The 68/74 high-level acceptance count is unchanged.

### Chromium CSS Color 4 mix resolution

The next exact-head browser pass uncovered a second browser-normalized format: `color(srgb 0.960784 0.960784 0.952941 / 0.36)` from a translucent `color-mix()` panel layer. This is not invalid CSS; it is a legitimate Chromium computed sRGB color with alpha. The background compositor now parses both opaque/alpha `rgb()` / `rgba()` and `color(srgb r g b / a)`, converts normalized sRGB channels to 0–255 before layering, rejects unknown color spaces, NaN/out-of-gamut channels and alpha outside 0–1, and still requires a genuinely opaque ancestor. A source-driven frontend regression tests the **actual browser parser regex** with the observed computed color and invalid display-p3 syntax. No assertion threshold or security guard was relaxed; the next exact HEAD must fully pass the 64 read-only browser cases to be merged.
