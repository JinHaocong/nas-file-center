# Stage #70 — Workflow list actual blue-navy surface in Pure White dark mode

## Reproduced from exact-HEAD browser evidence

At merged `main d404afaaff036929c96ce196b5e52c86a29555e0`, inspected actual
Chromium `workflows-dark-light-390.png` from the 800-case exact-HEAD
PR #348 visual pack (`human-visual-review-800-8fa68f79a5b069c787ca3e714d374279998754c8`).
The workflow list's mobile card is clearly **navy blue**, not the approved
Pure White v2.1 neutral charcoal / gray.

An independent pixel analysis of 25 real 390px dark-route baseline screenshots
showed **19.1%** blue-leaning dark pixels in Workflows, versus 0–1.3% for
the next routes (heuristic: dark pixels where B−R > 15, B−G > 6).
Representative original screenshot pixels:
- Card interior `(100, 440)` = `rgb(26,36,52)` (**#1a2434**);
- Parent behind card `(19,500)` = `rgb(21,25,31)` (also blue-leaning);
- Outside page `(5,350)` = `rgb(23,23,22)`, neutral as required.

This is a **confirmed painted color inconsistency** with
`docs/pure-white-v2-visual-contract.md`, not an inferred screenshot-depth
or synthetic API bug. The workflow list is a real mounted React page using
GET-only synthetic fixture data in CI.

## Source-level cause

`frontend/src/styles/console-v2-workflow-list.css` still assigned the
workflow card `--nfc-wfl-bg: #1a2434`, with matching blue-muted
`--nfc-wfl-soft: #222e41`, blue borders, text and blue focus accent.
Separately, historical v049 owns
`.nfc-workflows-page > .nfc-data-panel-dense { background:
var(--nfc-v49-surface) !important }`, with an inherited blue-black default.
Both classes occur on the same root WorkflowList element.

## Scoped fix and regression guard

Retain all selectors, DOM hierarchy, action handlers, routes, breakpoints and
security semantics. In the **existing workflow-list CSS owner only**, select
Pure White v2.1 local tokens:

| Token | Light | Dark |
| --- | --- | --- |
| background | `#ffffff` | `#242422` |
| soft background | `#f5f5f3` | `#2d2d2a` |
| text | `#20201f` | `#f5f5f2` |
| border | `#eaeae7` | `#383834` |
| focus/interactive accent | `#262625` | `#f5f5f2` |

Set `--nfc-v49-surface: var(--nfc-wfl-bg)` only on
`.nfc-v2-workflow-list-page` so the existing higher-specificity,
`!important` v049 data-panel winner resolves to the same neutral page
surface without changing global tokens or adding specificity escalation.

The existing **800-case actual mounted Chromium audit** now evaluates
`getComputedStyle(...).backgroundColor` for the Workflows panel plus
the mobile card or desktop table header across **8 viewports × 4 modes**.
It records `workflowListNeutralPaint` in per-case manifest and fails closed
on a mismatch. Existing frontend source regression enforces token scope,
CSS import ordering and browser audit registration.

If GitHub CI rejects computed paint, inspect its exact-HEAD manifest and
correct only actual owner conflicts. No false manual acceptance should be
claimed from automated screenshots or tests.

## Explicit remaining work

This repair addresses one actual Stage #70 color defect, **not** all
CSS selector intersections, pixel-level manual assessment, human screen
reader approval, isolated NAS acceptance, or deployment. #70–#74 remain
OPEN; formal status **69/74**. No backend or NAS operation is changed.

## First real Chromium run exposed a second inherited owner (do not suppress)

The first PR HEAD `378aa332d5b8bcc2e1d62729c243016d9be48c1b`
failed its new all-route Chromium gates as designed. The saved 360px
manifest demonstrated that the main Workflow card was **already repaired**:
`rgb(255,255,255)` light and `rgb(36,36,34)` dark. The outer DataPanel
had a **different, already neutral** skin: `rgb(251,251,250)` light and
`rgb(30,30,28)` dark. The initial guard incorrectly equated the outer
panel with the raised card. It was corrected to require these *distinct*
approved neutral surfaces, rather than weaken/remove painted-style checks.

Independent inspection of the first PR Chromium screenshot then showed
blue-black **behind** the neutralized mobile card. The culprit is an
additional later owner in `v056-right-workspace-v2.css`:

```css
.nfc-app-main .nfc-data-panel-body:not(:empty) {
  background: var(--nfc-w2-surface);
}
.nfc-app-main .nfc-mobile-record-list {
  background: var(--nfc-w2-surface);
}
```

These rules affect descendants even when the parent DataPanel and
raised mobile card are already neutral. The narrow correction therefore
also maps `--nfc-w2-surface: var(--nfc-wfl-soft)` **on the workflow-list
root only**, preserving historical v056 stylesheet rules and other routes.
The actual Chromium manifest now checks **four distinct computed fills**
where applicable: outer panel, inner body, mobile list backdrop, raised
record card / desktop header. All outputs must be opaque neutral and
match the documented Pure White values. A resumed CI can fail closed on
any additional cascade owner rather than invent an approval.

The first failed CI is intentionally preserved as causal evidence.
No global `--nfc-w2-*` token is changed, no blanket `!important`
override is introduced, and no production NAS file operation occurs.

### Second fail-closed test iteration: transparent structural wrapper

On intermediate HEAD `c1c42b722821beefac8dd94a58b942945ca6c9b8`,
[390px real Chromium](https://github.com/JinHaocong/nas-file-center/actions/runs/40308264744)
reported **all four effective themes** consistently:

| Paint element | Light | Dark |
| --- | --- | --- |
| Outer DataPanel | `rgb(251,251,250)` | `rgb(30,30,28)` |
| Structural `.nfc-data-panel-body` | `rgba(0,0,0,0)` | `rgba(0,0,0,0)` |
| Visible mobile list | `rgb(245,245,243)` | `rgb(45,45,42)` |
| Visible record card | `rgb(255,255,255)` | `rgb(36,36,34)` |

The new Workflow body guard mistakenly expected an opaque body fill.
That structural wrapper is **intentionally transparent**; the immediate
mobile list is responsible for visible painted content and is verified
separately. The fail-closed guard now requires body *transparency*
plus exact visible list/card/outer panel neutral fills. This keeps a
stronger actual-painted-surface contract without forcing an unnecessary
CSS property or hiding a failure.
