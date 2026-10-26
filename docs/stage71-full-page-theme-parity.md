# Stage #71 — full-page theme parity from real screenshot review

## Confirmed evidence gap

Visual review of the **actual** PR #342 800-case ZIP (UI Validation run
`39763312219`, exact PR head `c863ccac7961b577fc2e446089b2731cfc0bbd9f`)
found a screenshot-depth disparity, **not a proven runtime UI defect**:

- At 390px, `settings-light-dark-390.png` is **390 × 5151**, showing the
  entire Settings page, while `settings-dark-light-390.png` and both
  `settings-system-*-390.png` are only **390 × 900** (the initial viewport).
- The original runner explicitly gated `fullPage` on
  `theme.mode === 'light'`; this impacts all 390px and 1440px cases.
- This prevents equivalent below-the-fold evidence for dark/system colors,
  cross-layer CSS overrides, lengthy forms and mobile fixed navigation.
  It does not establish that the application itself is clipped or defective.

## Narrow repair and fail-closed evidence contract

- Full-page baseline screenshots are now captured at **390px and 1440px
  for every theme mode**: explicit light, explicit dark, system-light and
  system-dark. All other six widths retain their viewport snapshots.
- The existing 25 × 8 × 4 matrix stays **800** baseline images;
  **200 full-page cases and 600 viewport cases** are identified separately
  in `visual-review-pack/evidence.json`, offline gallery and review CSV.
- Each actual React Chromium route result includes `screenshotFullPage`.
  The runner also decodes the real PNG header and checks image width and
  height against the page's actual scroll height. An incorrectly clipped
  full-page capture fails the viewport's CI job immediately.
  Pack generation rejects missing/incorrect screenshot-depth metadata for any
  viewport/theme/route, and rejects all prior manifest failures as before.
- Regression tests pin the theme-independent policy, exact cases, CSV and
  failure on missing or falsely downgraded dark-mode evidence.
- CI continues using synthetic GET-only fixtures with off-origin and mutation
  requests blocked; screenshots cannot approve a case or operate on real NAS.

## Review boundaries

A fresh **exact-HEAD** artifact is required after this PR's successful UI
Validation. Do not mix previous PR #342 partial-depth screenshots into the
new review. The 800 review decisions remain initially `UNREVIEWED`;
full-page screenshots require human interpretation. Viewport captures at
360, 430, 768, 1024, 1280 and 1920 still require manual below-the-fold
inspection as necessary. All Stage #70–#74 owner, accessibility, isolated
real-NAS and deployment signoffs remain OPEN: **69/74 unchanged**.
