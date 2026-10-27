# Stage #70 — Plans mobile history inherits navy from v056 (2026-10-27)

## Visual evidence on the exact latest merged main

Base `main=39c019259ba6b139e131112cbcd552ba28a5db8e`
(after [PR #352](https://github.com/JinHaocong/nas-file-center/pull/352)).
Independently inspected the real mounted [390px Chromium screenshot ZIP artifact 12703368609](https://github.com/JinHaocong/nas-file-center/actions/runs/40434842422/artifacts/12703368609).

- `plans-dark-light-390.png` shows a visibly large blue-black field around
  the mobile Plan card. In the region x=8..381 and y=180..999 there are
  **53,791 exact `rgb(21,25,31)` / `#15191f` pixels**; y=650, x=14,
  80, 170, 250 and 320 all read exactly `#15191f`.
- `plans-system-dark-390.png` exhibits the same painted navy region. The
  approved neutral Pure White v2.1 dark paper is `#242422`.
- The Plans page `frontend/src/pages/Plans/index.tsx` renders a
  `.nfc-v2-plans-page .nfc-mobile-record-list` containing
  `.nfc-plan-mobile-card`.
- Historical `frontend/src/styles/v056-right-workspace-v2.css` sets
  `--nfc-w2-surface:#15191f` for dark and directly paints
  `.nfc-app-main .nfc-mobile-record-list {background:var(--nfc-w2-surface)}`.
  The actual v2.1 page stylesheet `console-v2-phase2.css` sets neutral
  `--v2-paper` for its own panel/card but had not overridden the inherited
  list token. CSS import order places page owner after v056.

## Scoped repair and regression safety

1. Add `--nfc-w2-surface:var(--v2-paper)` to the **existing**
   `.nfc-v2-shell .nfc-v2-plans-page` rule in
   `frontend/src/styles/console-v2-phase2.css`, not to global v056,
   `root`, another route, or Plan Detail.
2. In mounted read-only Chromium `/plans` at 360/390/430 and all four
   light/dark/system configurations, assert the **actual computed**
   opaque list paint equals `rgb(255,255,255)` in light and
   `rgb(36,36,34)` in dark, and that the card is either opaque neutral
   or transparent and composited over that verified neutral list.
   Fail closed on background images, absent/zero-size list/card, overflowing
   card geometry and missing nonzero solid card border. Record
   `planMobileNeutralPaint` in the per-case manifest.
3. Source regression tests pin CSS ownership, load order and the mounted
   paint guard. Do not change React business logic, NAS files, APIs or
   production environment. Recheck actual screenshots in the new
   exact-HEAD CI artifacts.

This is one real, measurable residual #70 visual defect. Successful
automated screenshots are **not** human #70/#71 signoff. Issue #347
remains **69/74 (93.2%)**, all #70–#74 human/NAS gates OPEN and
14 checkboxes unchecked. Do not merge before all exact HEAD checks and
workflows succeed, review/branch gates pass and the squash merge is
locked to the verified head SHA. Independent merged-main CI is required
after any merge. No production deployment or real NAS writes.
