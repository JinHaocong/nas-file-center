# Stage #70 — Indexes mobile records inherit navy v056 surfaces

## Actual mounted Chromium finding

After PR #350 was squash-merged as `main 8d200ab0110d1e0dd92967859958d204491d9723`, the read-only exact-HEAD
[390px Chromium artifact](https://github.com/JinHaocong/nas-file-center/actions/runs/40308753749/artifacts/12644135388)
still showed a visibly blue-black **Indexes** mobile record area in dark and system-dark modes.
The same dark surface was independently reproduced from the
[360px artifact](https://github.com/JinHaocong/nas-file-center/actions/runs/40308753749/artifacts/12643534215).
At screenshot pixel `(20,400)`, both widths yielded `rgb(21,25,31)` (`#15191f`) on the large
Indexes mobile list background, whereas the surrounding Pure White v2.1 canvas was
neutral `rgb(23,23,22)`. A [1440px desktop artifact](https://github.com/JinHaocong/nas-file-center/actions/runs/40308753749/artifacts/12645025916)
showed a normal neutral table instead; this issue is scoped to the responsive mobile record view.

These are *actual* Chromium screenshot pixels, not an inference from stylesheet declarations.
The pre-fix 360/390/1440 manifests showed `captured=100`, `failures=[]` and no per-case problems,
demonstrating why screenshot-count checks alone did not detect this color defect.

## Root cause and narrow fix

`frontend/src/styles/console-v2-indexes.css` already defines neutral
`--nfc-idx-bg: var(--v2-paper)` for both light and dark themes.
However, imported earlier `v056-right-workspace-v2.css` has more specific selectors:

```css
.nfc-app-main .nfc-mobile-record-list {
  background: var(--nfc-w2-surface);
}
.nfc-app-main .nfc-index-mobile-card {
  background: var(--nfc-w2-surface);
}
```

Its inherited dark token was still `--nfc-w2-surface: #15191f`, so the
mobile container and card did not use Indexes' neutral local paint.
Rather than replace shared legacy theme tokens, the existing Indexes CSS owner now maps
`--nfc-w2-surface: var(--nfc-idx-bg)` **on Indexes' root only**.
This resolves to `#ffffff` in light mode and `#242422` in dark mode.
Other pages, shared v056 selectors and old `!important` barriers remain unchanged.

## Fail-closed checks

`frontend/scripts/browser-full-route-visual.mjs` now checks the **final computed styles**
of both the mounted Indexes mobile list and visible mobile card in all four
light/dark/system states at widths 360, 390 and 430. It reports
`indexMobileNeutralPaint` in each case manifest and fails with a descriptive
`problems` entry on missing, too narrow or non-neutral painted surfaces.

`frontend/scripts/full-route-visual.test.mjs` enforces CSS ownership,
v056 import order and the mounted Chromium audit registration.

This is a targeted CSS-only fix. It does not modify React routes, API calls,
file operations, NAS data, deployment or accessibility workflows.

## Acceptance boundary

Any successful automated CI or visually improved screenshot proves only this
specific reproduced discrepancy was fixed at the tested states.
Human CSS-risk signoff #70, all 800-case visual review decisions #71,
manual screen-reader/keyboard signoff #72, isolated NAS #73 and owner GO/NO-GO #74
remain **OPEN**. Formal acceptance stays **69/74 = 93.2%**.
