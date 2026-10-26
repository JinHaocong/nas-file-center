# Stage #70/#71 visual final-review tranche: source-editor evidence

## Source and scope

Started final-review triage on the latest merged `main`
`1bccedc775e8a44e2a51f271cf9420d8e5afe61a`, using the exact-HEAD
PR #346 `human-visual-review-800-885a1be2332cbf2c91ae7d9115ce1cce878b9b1d`
ZIP from UI Validation run `40275697744`. Provenance: 800 baseline
images, 36 desktop workspace-bottom images, 136 interactive-state images,
no browser manifest failures and **zero human approvals**.

The `/download-sources` -> **新增来源** inline form is opened by real
GET-only Chromium. In the 390px supplemental images all four themes
(`light-dark`, `dark-light`, `system-light`, `system-dark`) were
**390×900**, ending at the 服务类型 field / fixed bottom nav. The form
continues below the first viewport, so its service URL, optional credentials,
submit/cancel controls and spacing cannot be inspected from the provided
interaction screenshot alone. This is a documented **review evidence gap**,
not a proven malfunction of the form.

## Narrow repair

- Use the same existing `requiresFullPageReview(width)` screenshot
  policy already enforced for the 800 baseline and download-verification
  selected detail screenshots, regardless of light/dark/system theme.
- Persist actual Chromium editor PNG dimensions and actual
  `document.documentElement.scrollHeight` in the per-case manifest;
  fail if the 390px form cannot demonstrate below-first-fold content
  and if a mandatory full-page screenshot truncates the document.
- Require matching metrics in the exact-HEAD unified offline reviewer-pack
  builder, with rejection tests for missing, wrong-theme and cropped
  source editor evidence.
- Keep all 800 human worklist entries UNREVIEWED; keep supplementary
  screenshot counts unchanged, no runtime CSS change or backend change.

## Remaining signoff

This targeted capture repair does NOT approve #70/#71. The human owner
must still review all 800 cases and supplemental images, and consider CSS
cascade/specificity risks, keyboard interaction, actual devices and remaining
states. Stages #70–#74 stay OPEN, **69/74** formal progress. No real NAS,
production data mutation, or deployment.
