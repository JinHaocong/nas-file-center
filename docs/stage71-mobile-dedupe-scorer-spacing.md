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

## Root cause proved by real Chromium

The first CSS grid-row packing hypothesis was **insufficient**. Its
GET-only Chromium run deliberately failed at 360px in all four themes,
reporting the Path Priority card at **403px** and Preferred Extension
at **420px**, even though the content after the heading is compact
(`gapToWeight: 16px`). Instrumented computed geometry confirmed
`headingHeight: 244px` with card `minHeight: auto` and weight block
heights of only 104px and 121px.

Root cause: the desktop rule `.nfc-v2-scorer-heading h3 { flex: 1 1 180px }`
specifies a horizontal heading flex-basis. The historical 767px mobile
rule changes `.nfc-dedupe-config-heading` to a **column** flex direction,
turning that width basis into **180px of vertical height** in the title.
Both light and dark modes inherit this same layout bug.

## Narrow CSS fix

At <=767px, reset only the scorer title flex item to
`flex: 0 0 auto`. Also use `grid-auto-rows: max-content`,
`align-content: start` and `align-self: start` on the scorer grid/cards
to keep unused parent height from being distributed into inactive factors.
No factor configurations, controls, handler logic, keyboard focus, theme
tokens or backend behavior are changed; desktop remains unchanged.

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
