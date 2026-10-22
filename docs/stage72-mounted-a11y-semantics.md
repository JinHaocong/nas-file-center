# Stage #72 — mounted all-route accessibility semantics audit

## Evidence scope

The existing UI Validation `full-route-visual-audit` job exercises the actual
compiled React app at **25 routes × 8 widths × 4 theme configurations**
(800 mounted page visits). This Stage #72 tranche adds a read-only,
fail-closed semantic audit to every such visit, before the ordinary screenshots:

- Visible native buttons, links, inputs, selects and textareas plus ARIA button,
  link, tab, menuitem, checkbox, radio and switch roles must have a nonblank
  computed programmatic name (explicit aria-label/labelledby, native labels,
  element text, image alternative or applicable native action default).
- Mounted `aria-labelledby` and `aria-describedby` references on those controls
  must resolve to exactly one live ID. Missing and ambiguous references fail.
- Visible non-decorative image elements require an explicit `alt` attribute.
  `alt=""` correctly remains valid for decorative images.
- Positive tabindex on visible elements fails to prevent bypassing native Tab order.
- Hidden or inert elements are excluded from the *initial route baseline*, but
  disabled controls are included because they must still be understandable.

Each viewport's `manifest.json` now records `accessibility.inspectedControls`,
`inspectedImages`, `checkedAriaReferences`, `positiveTabstops`, and `issues`
for each route/theme. Any finding enters `problems` and fails the existing
full-route job, blocking downstream unified review bundling and PR merge.
These new tests use the same GET-only synthetic API and explicitly block
mutating and off-origin requests. They do not change runtime React or CSS.

## Confirmed defect and repair

On the first exact-HEAD Chromium run, the new audit rejected the visible
`/audit` search field in light/dark/system configurations at several widths:
`input#audit-search-input[type=search]` had only a search icon and placeholder,
neither providing a reliable programmatic control name. This PR adds
`aria-label="搜索审计事件（操作或路径）"` to the actual Audit search input
and registers a dedicated regression assertion. This is an accessibility
bug fix, not a cosmetic stylesheet change or a human signoff.
## Limitations / remaining human work

**No owner/manual checkboxes have been closed.** This audit does not certify
the complete Accessible Name and Description Computation algorithm,
screen-reader announcements, dynamic modal state, keyboard traversal through
every interaction, motion-trigger effects, touch target usability, complete
contrast, or real NAS accessibility. Existing focused Chromium keyboard/overlay
checks remain in place. Reviewers must still conduct manual keyboard and
screen-reader spot checks (at least Windows NVDA / macOS VoiceOver where
available), validate interactive overlays and confirm actual UI presentation
before signing off global #72. Stage #70, #71, #73 and #74 remain open.

## Troubleshooting

If a viewport fails, inspect its `artifacts/full-route-visual/<width>/manifest.json`,
find the route/theme `accessibility.issues`, and fix the corresponding actual
component or intentional semantics. Do not bypass a missing name by treating
placeholder text as a native label, suppress a failing route, or accept a
missing artifact. Build/run again on the exact newest candidate HEAD.
