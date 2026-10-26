# Stage #71 final visual review — complete mobile interaction states

## Actual last-main artifact finding (2026-10-26)

Reviewed original PNG bytes from latest merged `main`
`a29feec573cec96167cc28130a85e667f1ed2f53`,
PR #348 exact-HEAD UI Validation artifact
`human-visual-review-800-8fa68f79a5b069c787ca3e714d374279998754c8`
(run `40294627204`, unified artifact `12639248195`).

- All **800** mounted route/theme/width cases report zero browser failures.
  The ZIP has 800 baseline PNG, 36 desktop scroll-bottom PNG and 136
  interactive screenshots, none marked human approved.
- The 390px `download-sources-*-source-editor.png` screenshots do correctly
  span **390×1309** in each of four theme modes after PR #348.
- At **360px and 430px**, however, all `source-editor` and
  `download-verification-*-selected-detail` supplemental images are still
  only **900px high**. Inspection of the actual 360px expanded source-editor
  image shows the bottom edge at the service-type field and fixed nav,
  without the subsequent account/password/save controls, so it is
  **insufficient evidence for checking the full mobile interaction state**.
  This is an evidence gap, not proof the live form malfunctions.

## Narrow fix

The 800 baseline policy is intentionally preserved: only 390px and 1440px
baseline screenshots are fullPage; 200 full-page cases, 600 viewport cases.

For the **two expanded interactive states only**, capture full-page screenshots
at **360px, 390px, 430px, 1440px**, regardless of effective light/dark/system.
At 360/390/430, require actual document height > 900 and PNG dimensions
covering the real DOM document height. Retain the existing at-1440 behavior
(no claim that outer-document fullPage includes separately scrollable
inner workspace).

Route manifests record the actual PNG and DOM heights. The unified offline
review builder now fails closed on cropped or missing source-editor /
selected-detail evidence at each mobile width. Tests cover both 360 and 430,
all four theme policies, and keep 800 human decisions UNREVIEWED.

No runtime UI/CSS change, no backend change, no NAS connection, no writes,
no deployment. #70–#74 remain OPEN; formal project count **69/74**.
