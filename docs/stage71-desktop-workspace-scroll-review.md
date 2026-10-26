# Stage #71 — desktop inner scroll visual evidence

## Verified blind spot (real PR #344 artifact)

The successful exact-HEAD **PR #344** 800-case artifact
(`human-visual-review-800-edf41b7d990bc57f4f13c0ca11483986508f90fc`,
UI Validation run `40258104051`) includes desktop 1440px baseline
screenshots with `screenshotFullPage: true`. The Settings PNG remains
**1440×900** although the Settings page contains much more content.

This is not proof of a runtime layout defect. In the actual desktop CSS
(`frontend/src/styles/v056-right-workspace-v2.css`) the app shell is
`height:100dvh; overflow:hidden`, and the main workspace
`.nfc-app-main .nfc-page-content` is independently
`overflow-y:auto`. Chromium `fullPage` saves only the outer document,
not the *bottom of the independent workspace*. The original human review
pack therefore lacked evidence of the lower desktop settings panels and
other long workspaces.

## Implementation

- At **1440px** for all 24 authenticated routes, inspect the mounted
  `.nfc-app-main .nfc-page-content` CSS, client height, maximum scroll,
  and whether the scroll bottom was actually reachable.
- When it scrolls by more than 48px, take a **supplemental**
  `<route>-<theme>-1440-workspace-bottom.png` screenshot with the
  inner pane actually scrolled to bottom; immediately restore it.
  Do not click, submit, mutate APIs, or navigate to any external origin.
- Settings **must** have a reachable scroll bottom of at least 100px.
  Missing workspace, unreachable bottom, wrong screenshot dimensions or
  missing screenshot produce a CI failure.
- The review-pack builder validates the exact matching manifest metadata
  and supplemental file for each qualifying route/theme. The offline
  gallery shows the baseline and matching bottom-of-workspace image
  together, while preserving the **same 800 UNREVIEWED decisions**.
- Other independently scrolling *tables, drawers and modals* are not
  automatically covered. The operator still needs to review those states.

This change is a visual **evidence capture enhancement**, not a human
visual pass or CSS closure. Stages #70–#74 remain OPEN, project formal
count stays **69/74**. No production NAS writes, live NAS, or deployment.
