# Stage #70 — Plan Detail legacy navy surfaces (2026-10-27)

## Confirmed evidence

Starting `main=061b61b462adcd19139e4a3c642cacccefac5aae`
(PR #353), reviewed the canonical
[800-case Chromium ZIP artifact 12709205993](https://github.com/JinHaocong/nas-file-center/actions/runs/40447335246/artifacts/12709205993).
Original actual `plan-detail-dark-light-390.png` and
`plan-detail-system-dark-390.png` contain **148,636 exact `#15191f`
pixels** each (of 390×2005). A lifecycle step interior at x=100/180,
y=350/430 paints `rgb(21,25,31)`, while v2.1 neutral dark paper should
be `rgb(36,36,34)`. At 360, 430, 768, 1024, 1280, 1440, 1920,
the dark screenshot respectively still had 59,923 / 73,153 /
49,568 / 77,771 / 55,510 / 65,113 / 94,742 exact navy pixels.
This persists in system-dark, but not light-mode. Those pixels are
**automated inspection evidence, not 800-case human signoff**.

Root cause: legacy `v056-right-workspace-v2.css` defines inherited
`--nfc-w2-surface:#15191f` and `--nfc-w2-surface-soft:#191e25`
in dark mode and paints the Plan Detail lifecycle strip
(`.nfc-plan-detail-page .nfc-lifecycle-strip`, with `!important`),
Plan action surface (`.nfc-plan-action-surface` with `!important`),
and mobile PlanItem ledger list/card. The separate native page owner
`console-v2-plan-detail.css` had Plan-specific text/panel tokens but
did not remap these two inherited v056 surfaces.

## Surgical fix and real-browser audit

- Add only `--nfc-w2-surface:var(--v2-paper)` and
  `--nfc-w2-surface-soft:var(--v2-sidebar-surface)` inside
  the existing `.nfc-plan-detail-page` local CSS owner, loaded after
  historical v056. Do not change v056 globally, other routes,
  lifecycle behavior, plan mutations or PlanItem data. No additional
  `!important` is introduced.
- In `browser-full-route-visual.mjs` validate **actual mounted
  computed paint** on each `/plans/:id` at all 8 widths and 4 theme
  configurations. The lifecycle strip must paint opaque light
  `rgb(255,255,255)` / dark `rgb(36,36,34)`. The action surface
  must paint neutral soft light `rgb(245,245,243)` / dark
  `rgb(43,43,40)`. No background images or missing/small geometry.
  At 360/390/430 require an opaque neutral mobile ledger list and
  a visible, contained PlanItem card, either opaque neutral or
  transparent over its already-verified neutral parent.
  Fail CI on any violation, with `planDetailNeutralPaint` in the
  visual manifest. Source tests pin CSS ownership and import order.
- Re-evaluate the **same actual pixel regions** from the new exact-head
  screenshots and confirm navy disappearance before any merge. The
  unmodified 800-case matrix and full-page interactive captures must
  still succeed.

**Acceptance limitations:** This is a confirmed residual Stage #70 CSS
defect, not #70/#71 owner approval. Issue #347 remains 69/74
(93.2%); 14 human signoff boxes unchecked and #70–#74 OPEN.
Never run real NAS test jobs, perform production deploys or record a
GO decision by extrapolating from browser CI. Any new merged PR
requires fresh exact-HEAD 800-case review evidence and independent
merged-main checks, with SHA-locked merge only after all gates pass.
