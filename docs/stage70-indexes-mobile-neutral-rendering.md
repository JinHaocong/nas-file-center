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

## First CI failure: distinguish direct card paint from composite

The initial HEAD `51c320bfddd13bb07c1d293d26a934640bc11efe`
[UI Validation run](https://github.com/JinHaocong/nas-file-center/actions/runs/40315054034)
correctly stopped the merge: mobile visual audit at 360/390/430 failed.
Real rendered computed styles showed that the **list** was already fully neutral
(`rgb(255,255,255)` light / `rgb(36,36,34)` dark), but the card itself
was deliberately transparent (`rgba(0,0,0,0)`). The actual 430px PNG shows
a visible bounded card sitting on that neutral list; its effective composite
is neutral, not navy. The original assertion incorrectly equated card's direct
paint with visible composite. Revised guard retains strict opaque exact list
color and requires no list/card background image, positive solid card border,
visible card width and actual card containment in the neutral list. Card paint
may be exactly the required opaque color **or** transparent over that verified
neutral surface. No decorative CSS override or weakening of the required
visible backdrop was necessary.

The same 430px CI artifact also exposed an unrelated short
`download-verification` selected-detail interaction capture in system light/dark:
PNG 430×1854 vs *postcapture* document height 1939. The existing fail-closed
full-page assertion remains unchanged. The browser evidence helper now waits
two animation frames and **recaptures up to 3 times** if pixels remain short,
always measuring the real document afterward and preserving the failure if
none of the captures covers it. This addresses a late-layout timing race,
not a lower screenshot-depth standard.

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
