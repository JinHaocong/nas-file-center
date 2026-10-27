# Stage #70 — Tasks filter inherits legacy navy (2026-10-27)

## Exact screenshot evidence from green merged main

Base `main=02c9af66ebf38a30943961f567bfb3ed2351e503`
([PR #354](https://github.com/JinHaocong/nas-file-center/pull/354),
independent merged-main 3/3 workflows and 4/4 Checks SUCCESS).

Downloaded and inspected the complete latest
[800-case review ZIP artifact 12711499282](https://github.com/JinHaocong/nas-file-center/actions/runs/40454685357/artifacts/12711499282).
In the actual `full-route-visual/390/tasks-dark-light-390.png`
(390×1146), a broad continuous **navy `#15191f` rectangle** behind
the status/type filter controls spans approximately x=15..374,
y=615..802. **36,713 exact `rgb(21,25,31)` pixels** occur there,
including (80,650), (190,700) and (360,770).
At 1440px `tasks-dark-light-1440.png`, the same navy occurs
**87,600 exact pixels**, x=287..1380, y=433..528.
System-dark also reproduces it. Under the approved v2.1 Pure White
palette, dark paper is `#242422`, light paper is `#ffffff`.

Actual root cause in the historical
`frontend/src/styles/v056-right-workspace-v2.css`:
`.nfc-filter-bar` receives
`background:var(--nfc-opl-surface,var(--nfc-w2-surface)) !important`.
The inherited W2 dark surface is `#15191f`; it overrides the newer
`frontend/src/styles/console-v2-tasks.css` page-owned
`.nfc-v2-task-filter-bar {background:var(--v2-paper)}`
because that newer declaration is not important. Populated
`.nfc-mobile-record-list` also receives the W2 inherited paint.

## Scoped repair / real Chromium regression

- Only in the existing `.nfc-v2-shell .nfc-v2-tasks-page` rule set
  `--nfc-w2-surface:var(--v2-paper)`. The inherited CSS variable
  handles legacy `!important` paint without global selector changes,
  new `!important` barriers, or changing task functionality.
- Audit real mounted `/tasks` screenshots at all eight widths
  (360,390,430,768,1024,1280,1440,1920) × all four themes
  (light/dark/system-light/system-dark): actual computed
  `.nfc-v2-task-filter-bar` must be opaque neutral
  `rgb(255,255,255)` or `rgb(36,36,34)`, have no background image,
  and occupy positive nontrivial bounds. Record
  `tasksFilterNeutralPaint` in the per-case manifest.
- The read-only Tasks fixture currently contains zero jobs, so the
  valid empty-state `ConsoleEmpty` is not a card defect. If mounted
  data provides an actual mobile `.nfc-mobile-record-list`, audit
  that list's exact neutral paint and the composed bounded card,
  including solid border. Never invent task rows to satisfy tests.
- Source tests pin the Task CSS owner, historical v056 `!important`
  cause, import order and real-browser checks. Compare latest-head
  screenshots at the exact pixel locations above. A changed HEAD
  must rerun all CI; merge only after 17/17 Checks and 4/4 Workflows
  pass and SHA/review/branch preflights are verified. Then independently
  validate merged-main and rotate the full 800-case review artifact.

**No change to human signoff:** Issue #347 is 69/74 (93.2%),
#70–#74 OPEN, 14 unchecked human boxes. CI/fixture findings do not
replace human visual/accessibility approval, isolated NAS acceptance
or owner's explicit GO/NO-GO and deployment instruction.
