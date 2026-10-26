# Stage #71 — 390px Advanced Dedupe mobile scorer spacing

## Evidence

The downloaded, **successful** PR #343 visual review artifact
(`human-visual-review-800-2426d62e9ada6f268c8cfa6e707ed65c12a407e3`,
GitHub Actions run `40252243734`) contains 390px full-document screenshots
`scan-dedupe-light-dark-390.png` and
`scan-dedupe-dark-light-390.png`, both **390 × 2856**.
Actual examination of both images exposed extremely tall, mostly empty
**Path Priority** and **Preferred Extension** configuration cards while
both scorer factors are disabled. The labels, toggle, weight and explanatory
text are spread out across the empty cards, creating unnecessary scrolling.
This is a visible layout/spacing defect; it is not a deduplication logic issue.

## Narrow CSS fix

The reusable scorer `.nfc-v2-scorer-editor` uses a CSS grid. At mobile
widths (up to 767px), make implicit tracks `max-content` and pin
`align-content: start`, plus `align-self: start` for its scorer cards.
This prevents spare panel height from being distributed into disabled
configuration cards. Keep existing labels, controls, factor defaults,
disabled states, keyboard focus styles, theme tokens and backend behavior
unchanged. Desktop layout is not changed.

## Acceptance evidence

The existing **real React + GET-only synthetic Chromium** 25-route ×
8-width × 4-theme suite now additionally checks mounted `/scans/1/dedupe`
geometry at 360, 390 and 430px. It records the real CSS computed grid row
setting and the inactive Path Priority / Preferred Extension card heights
and heading-to-weight gaps. Absent elements, wrong CSS or oversized empty
cards fail the job instead of accepting a static-only CSS edit. The normal
screenshot manifest and exact-HEAD human ZIP remain the source of review
evidence. New snapshots require manual review against original screenshots.

**Stage #71 is NOT signed off.** This corrects one observed mobile
visual defect, not all visual states, CSS ownership, screen-reader review,
isolated real-NAS verification or deployment approval. The official tally
stays **69/74** until human acceptance is actually completed.
