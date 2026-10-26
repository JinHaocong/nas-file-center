# Stage #71 — interaction screenshot theme-depth parity and review visibility

## Confirmed gap from the **actual** PR #345 ZIP

Artifact `human-visual-review-800-6601e4efbd44271b16599f3c4304ccb695654bc3`
(UI Validation run `40264960404`) has zero **baseline** failures, but its
`/download-verification` selected-detail **interaction** screenshots at
390px differ dramatically by theme:

| Screenshot | Actual PNG |
|---|---|
| `download-verification-light-dark-390-selected-detail.png` | **390×1999** |
| `download-verification-dark-light-390-selected-detail.png` | **390×900** |
| `download-verification-system-light-390-selected-detail.png` | **390×900** |
| `download-verification-system-dark-390-selected-detail.png` | **390×900** |

The real Chromium runner gated `fullPage` with
`width === 390 && theme.mode === 'light'` **only in the interaction
capture**, even after PR #343 corrected the baseline screenshot policy.
This hides the lower selected-detail table under dark/system themes.
The issue is missing acceptance evidence, not proof the app has clipped
or malfunctioning content.

## Change and safety boundaries

- Reuse the **exact same `requiresFullPageReview(width)` policy** for
  the interactive selected-detail PNG in every theme. At 390px, all
  four effective-theme modes now capture the full document; at 1440px
  `fullPage` still only covers the outer document (inner workspace
  scroll is handled separately by PR #345).
- Record the real selected-detail PNG width, height and document height
  in the per-case Chromium manifest. Fail closed when a required
  full-page image is shorter than the actual document, or viewport
  dimensions disagree.
- The offline human gallery now *also displays* supplemental evidence
  next to its matching baseline case: remote directory picker,
  selected-detail table, source editor modal, Scheduler 503 alert and
  keyboard-focused Retry. **136 interaction screenshots** in total,
  included in the *same* 800 manual review decisions; no extra statuses.
- The exact-HEAD pack assembler checks that all expected interaction
  screenshots exist and rejects missing/forged selected-detail manifest
  metadata. Unit regressions cover absent files and all four themes.
- All browser network fixtures remain synthetic GET-only; external
  requests and mutations fail closed. No production NAS or real writes.

Manual reviewers still need to inspect overlays, nested scroll areas,
actual keyboard navigation, full image pixels and responsive layouts.
**Zero screenshots are auto-approved**. Stage #70–#74 remain OPEN and
formal progress stays **69/74** until actual human signoff.
