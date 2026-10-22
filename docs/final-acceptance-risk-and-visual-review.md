# Final acceptance: Stage 70 risks and Stage 71 human visual evidence

Status snapshot: 2026-10-22. Baseline main SHA: 57019586728f2aa800a0df92170cc2ce9350366b (PR #339 merged).

This is an evidence handoff and operator review aid, not CSS closure, human visual acceptance, accessibility approval, NAS acceptance or production deployment approval. The formal count stays **69/74**.

## Stage 70 — evidence and unresolved risks

| Risk | Verified scope | Remaining gate |
| --- | --- | --- |
| Historical nine-layer same-selector, same-property and same-media overlaps | 641 shadow declarations retired; the six remaining earlier important declarations are protected, with native Chromium computed-style evidence for Header, DataPanel Header and mounted Task Inspector. | Retain these important properties. Never delete them simply to reach zero duplicate count. |
| Intersecting selectors and CSS specificity | Existing actual React/Chromium checks protect targeted mounted pages, header, overlays and state-specific owners. | Site-wide differently-written matching selectors, specificity and dynamic class changes are not exhaustively proven. |
| Shorthand vs longhand, inheritance and media/support conditions | Exact-overlap inventory intentionally excludes these interactions. | Examine border, background, font, layout spacing, conditional and reduced-motion interactions at actual winning declarations. |
| Live portal and global painting | Eight widths and four theme/system combinations are exercised, with specialized modal and ledger suites. | Full visual layout, screenshot differences, all opened/failed/dense states, focus and keyboard journeys remain subject to independent review. |
| Human visual result | CI captures 800 actual React route screenshots on synthetic fixtures. | Human owner must inspect and record findings against Pure White v2.1. Automated green is never pixel approval. |

Stage 70 remains **OPEN** until selector intersections, shorthand and cascade interaction risks are reviewed and resolved or explicitly justified; actual browser paint evidence is assessed, and the relevant human visual authority confirms the remaining CSS behavior. The six important-precedence entries are intentional priority barriers, not six automatically confirmed defects.

## Automated single-ZIP review handoff (from this CI enhancement)

Every **new UI Validation PR run** now includes a `human-visual-review-pack`
job that depends on all eight `full-route-visual-audit` jobs succeeding.
The job downloads the eight artifacts from **that same workflow run**,
checks the exact PR HEAD embedded in their names, rejects missing/duplicate
widths, then validates all 800 screenshot paths and JSON manifests.
It uploads one additional artifact named `human-visual-review-800-<PR HEAD SHA>`
with these two directories:

- `visual-review-pack/index.html`, `review-worklist.csv`, `evidence.json`
- `full-route-visual/{360,390,430,768,1024,1280,1440,1920}/` screenshot PNGs and manifests

Download that **one ZIP** from the successful UI Validation run, extract the
entire ZIP to one directory, and open `visual-review-pack/index.html`.
Do not open only the HTML outside the ZIP; screenshot links are relative.
All 800 cases start as UNREVIEWED. The operator must review screenshots and
export explicit decisions; artifact creation does not imply any human pass.
Artifacts retain the existing 14-day expiration window.

**Safety:** no CI write API requests, no NAS access, no background deployment,
no auto-accept state, no weakening existing browser/security gates. The
bundle job itself fails if any upstream full-route job fails. The exact-HEAD
bundle is valid for its PR HEAD; after subsequent production CSS/UI edits,
refresh it for the new inspected HEAD before final owner sign-off.

## Stage 71 — existing exact-HEAD artifacts

PR #339 exact HEAD: 7b561c89988f5298f08d7894b1b4642020cd7db3.
GitHub UI Validation run: https://github.com/JinHaocong/nas-file-center/actions/runs/39733538029

The run completed successfully and uploaded a separate full-route-visual artifact for each width. Every width contains a manifest with 25 routes × 4 theme/system combinations and real Chromium PNGs. This is synthetic read-only screenshot evidence, NOT production images or any human review. Artifacts have a configured 14-day retention.

| Width | Artifact link |
| ---: | --- |
| 360 | https://github.com/JinHaocong/nas-file-center/actions/runs/39733538029/artifacts/12405403853 |
| 390 | https://github.com/JinHaocong/nas-file-center/actions/runs/39733538029/artifacts/12406456261 |
| 430 | https://github.com/JinHaocong/nas-file-center/actions/runs/39733538029/artifacts/12406132994 |
| 768 | https://github.com/JinHaocong/nas-file-center/actions/runs/39733538029/artifacts/12405878496 |
| 1024 | https://github.com/JinHaocong/nas-file-center/actions/runs/39733538029/artifacts/12406282911 |
| 1280 | https://github.com/JinHaocong/nas-file-center/actions/runs/39733538029/artifacts/12406371390 |
| 1440 | https://github.com/JinHaocong/nas-file-center/actions/runs/39733538029/artifacts/12406092047 |
| 1920 | https://github.com/JinHaocong/nas-file-center/actions/runs/39733538029/artifacts/12406028535 |

Use the newest common exact reviewed HEAD if later code changes affect rendering. Never mix artifacts from different SHAs or runs.

### Build the offline 800-case review pack

Use GitHub CLI authenticated for this repository, from the repository root:

    SHA=7b561c89988f5298f08d7894b1b4642020cd7db3
    RUN=39733538029
    for width in 360 390 430 768 1024 1280 1440 1920; do
      mkdir -p "frontend/artifacts/full-route-visual/$width"
      gh run download "$RUN" --repo JinHaocong/nas-file-center \
        --name "full-route-visual-$width-$SHA" \
        --dir "frontend/artifacts/full-route-visual/$width"
    done
    cd frontend
    node scripts/build-visual-review-pack.mjs \
      artifacts/full-route-visual artifacts/visual-review-pack "$SHA"

Open frontend/artifacts/visual-review-pack/index.html in a local browser. This does not require a live NAS connection.

The generator rejects missing widths, routes, theme pairs, PNGs, duplicate records, wrong manifest matrix dimensions, and all nonempty browser failure/problem arrays. It creates:
- index.html: local screenshot gallery with width/route/theme filters, manual PASS/DEFECT/FOLLOW_UP selections and notes, initially **800 UNREVIEWED**.
- review-worklist.csv: exactly 800 worklist lines, none pre-approved.
- evidence.json: exact user-supplied reference SHA, matrix size, manualApproved=0, manualReviewComplete=false.
- Browser-exported JSON: explicit user-authored decisions and notes, also importable if the SHA and all 800 row identities agree.

The generator **cannot authenticate artifact filenames or GitHub identity** merely from the extracted ZIP payload: the operator must first verify that the eight downloaded artifact names share the correct exact GitHub HEAD and that the original UI Validation succeeded. An export is a working record, not official visual or deployment sign-off.

Review primary shots and supplemental failure/long-content/modal/keyboard screenshot states. Verify text/fonts, alignment, scrolling, mobile widths, clipped names, theme colors, overlay z-index, focus rings, form errors and destructive-confirmation appearance. Do not equate static screenshots with tested interaction semantics.

## Stage 72–74 boundaries

#72: existing automatic focus/contrast/reduced-motion guards do not replace manual keyboard trap/restore, ARIA, error semantics or screen-reader acceptance.

#73: isolate a real NAS test environment and agree on boundaries, rollback/backup and separate authorization for any destructive actions. Synthetic browser fixtures cannot satisfy real-device acceptance.

#74: an owner's single consolidated acceptance and **explicit production deployment authorization** are still required.

Do not increase 69/74 merely because this pack was generated or CI became green.
