# Stage #70 — Scans mobile history navy surface (2026-10-27)

## Exact source and actual rendered evidence

Candidate baseline: `main=6d75644a6f792ec5b8fd02479e197437d9eefe3c`,
merged PR #351. Review the **actual Chromium screenshots** from
[UI Validation run 40428740174](https://github.com/JinHaocong/nas-file-center/actions/runs/40428740174),
[exact-HEAD 390px artifact 12701273450](https://github.com/JinHaocong/nas-file-center/actions/runs/40428740174/artifacts/12701273450):

- `scans-dark-light-390.png`: a large blue-black list/card surface is
  visible below the “扫描历史” header, unlike Pure White v2.1's neutral page.
- In the actual screenshot, list background at (14,350), (190,350),
  (14,600), (360,600) = `rgb(21,25,31)`, or `#15191f` (navy).
  The surrounding panel footer (190,755) is neutral `rgb(36,36,34)`.
- Source: `frontend/src/styles/v056-right-workspace-v2.css` defines
  dark `--nfc-w2-surface:#15191f` globally and paints
  `.nfc-app-main .nfc-mobile-record-list` with this token.
  The `/scans` route uses that shared record-list class.
  Existing `console-v2-scans.css` owns Pure White v2.1
  `--v2-paper` for panel and scan card but did not remap the inherited v056
  **list** token. The desktop scan table is separate and unaffected.

## Local fix and fail-closed QA gate

1. In the Scans page-only owner `console-v2-scans.css`, map
   `--nfc-w2-surface:var(--v2-paper)`, **only within**
   `.nfc-v2-shell .nfc-v2-scans-page`. This leaves v056's global tokens
   and other routes untouched.
2. **First exact-HEAD Chromium CI failure, corrected without forcing a
   repaint:** [UI Validation run 40434503721](https://github.com/JinHaocong/nas-file-center/actions/runs/40434503721)
   at 360/430 measured the **list** as successfully fixed, exact neutral
   `rgb(255,255,255)` light / `rgb(36,36,34)` dark. The bordered
   `nfc-scan-mobile-card` itself computed to `rgba(0,0,0,0)`
   in all four themes; it is intentionally a transparent child over the
   now opaque neutral list. Its background is **visibly neutral** through
   ordinary alpha compositing. The first guard incorrectly demanded opaque
   direct card paint and failed closed as designed. A temporarily proposed
   higher-specificity card background was ineffectual, so it was reverted;
   the existing route card CSS and shared v054 rules remain intact.
3. The revised mounted Chromium audit at 360/390/430 × four themes now
   strictly requires an **opaque exact-neutral list**, no background image
   on list/card, and a card that is either exact-neutral itself **or**
   transparent over that verified parent. It also requires real card
   containment, positive list/card geometry, and a positive-width
   solid card border. No test bypass or unexplained transparent ancestor
   is accepted; the before/after actual screenshot still has to be reviewed.
   A mismatch is recorded in the screenshot manifest and fails CI.
4. Source regression tests pin the owning selector and CSS import ordering,
   and the mounted-browser guard. Do not simulate human approval.

This is a confirmed visual defect with a targeted prospective repair.
Only exact-HEAD passing browser CI and a new fresh human-review ZIP may replace
the #351 candidate after a permitted SHA-locked squash merge. Keep #70–#74,
14 manual Issue #347 checkboxes and formal 69/74 **OPEN**. No real NAS
filesystem writes, real credentials, production deployment or accessibility
signoff are authorized by this change.
