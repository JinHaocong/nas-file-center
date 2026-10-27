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
2. Give its existing mobile scan card a page-owned, higher-specificity
   `background:var(--v2-paper)` (no new `!important`).
   Shared v054 structural rules, borders, action layout and React remain.
3. For every mounted `/scans` route at 360/390/430 pixels and all four
   light/dark/system effective themes, the browser audit asserts
   **actual** computed list **and** card background equal to
   `rgb(255,255,255)` light / `rgb(36,36,34)` dark. No background images,
   missing geometry or card spill outside the list are permitted. An error
   is recorded in the screenshot manifest and fails CI.
4. Source regression tests pin the owning selector and CSS import ordering,
   and the mounted-browser guard. Do not simulate human approval.

This is a confirmed visual defect with a targeted prospective repair.
Only exact-HEAD passing browser CI and a new fresh human-review ZIP may replace
the #351 candidate after a permitted SHA-locked squash merge. Keep #70–#74,
14 manual Issue #347 checkboxes and formal 69/74 **OPEN**. No real NAS
filesystem writes, real credentials, production deployment or accessibility
signoff are authorized by this change.
