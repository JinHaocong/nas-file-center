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
