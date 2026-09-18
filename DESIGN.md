# NAS File Center Design System

> Status: v0.4.0 C0 FROZEN
> Baseline: `main@08ce4046a556e7f3dec1d2de1a7d4ea37c610f7f`
> Reference corpus pin: `VoltAgent/awesome-design-md@8147538b4226ae41e2487a9179e3bcc1f68e8554`
> Runtime dependency: none
> Implementation layer: React 18 + TypeScript + Vite + Ant Design 5

## Product character

NAS File Center is a technical, data-dense NAS operations console. It must feel calm, precise, safe and fast to scan.

Reference synthesis:
- Linear: restrained technical chrome, hairline hierarchy, quiet surfaces.
- Supabase: clean developer-tool character, near-monochrome product surfaces, strong information hierarchy.
- IBM / Carbon: data-density discipline, semantic state clarity, 4px-grid rigor and accessibility-oriented interaction.

Do not copy any reference product 1:1. Do not build a marketing landing page, AI-purple gradient UI, glassmorphism dashboard, decorative animation surface, or card-inside-card showcase.

## Non-negotiable semantics

Preserve:
- all existing routes,
- auth/session behavior,
- API contracts unless separately approved,
- Plan and Task lifecycles,
- Quarantine / Restore meaning,
- Preview → Draft → Freeze → Validate → Execute,
- danger confirmation semantics,
- Safe Mode / mutation / delete visibility,
- Worker state visibility,
- no-clobber behavior,
- PathGuard / symlink / stale validation authority.

UI work must not redesign executor, Worker ownership, fs_ops or Quarantine transaction authority.

## Layout and density

Base spacing grid: 4px.

Spacing:
- 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48px.

Page gutters:
- mobile 12px,
- tablet 20px,
- desktop 24px,
- large desktop 32px when useful.

Operational pages stay compact-but-readable. Prefer hairlines and surface changes over heavy shadow. No oversized hero typography.

## Responsive contract

Breakpoints:
- mobile: `< 768px`
- tablet: `768px–1199px`
- desktop: `>= 1200px`

Acceptance widths:
`360 / 390 / 430 / 768 / 820 / 1024 / 1280 / 1440 / 1920`

Rules:
- primary touch target >= 44px,
- no accidental viewport-wide horizontal overflow,
- no hover-only functionality,
- desktop action groups collapse to primary + overflow on mobile,
- filters move to Drawer/sheet when needed,
- forms collapse to one column on mobile,
- long paths wrap or truncate with copy affordance,
- desktop table → tablet priority columns → mobile card/list,
- controlled horizontal scroll is reserved for raw technical evidence where preserving columns is the task.

## Shape, border and elevation

Radius:
- xs 4px,
- sm 6px,
- md 8px,
- lg 10px,
- pill only for compact status tags.

Do not use arbitrary per-page radii.

Borders:
- 1px hairlines are the default hierarchy mechanism,
- stronger borders only for focus, selected state, warning/danger emphasis.

Elevation:
- page canvas,
- hairline panel/card,
- transient overlay Drawer/Modal.
Avoid persistent dramatic shadows.

## Color roles

Use semantic roles, never page-local decorative hex values.

Core:
- canvas
- surface-1
- surface-2
- surface-raised
- hairline
- hairline-strong
- text
- text-muted
- text-subtle
- accent
- focus

Semantic:
- success
- info
- attention
- warning
- danger
- irreversible

Color is never the only signal. Status uses text label + semantic color + icon where helpful.

## Light / dark / system

Support Light, Dark and System with equivalent information hierarchy.

Validate:
- surface separation,
- hairlines,
- table rows,
- selected state,
- focus,
- disabled,
- warning/danger,
- code/path surfaces,
- charts,
- Drawer/Modal.

Ant Design algorithms are a base, not the finished design.

## Typography

System UI stack:
`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", sans-serif`

Mono:
`ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace`

Hierarchy:
- Page title 20–24px / 600
- Section title 16–18px / 600
- Body 14px / 400
- Dense table 13–14px
- Caption/meta 12px
- Code/path 12–13px mono

## App Shell

Desktop:
- persistent compact sidebar,
- sticky utility header,
- page header with context/actions,
- safety + worker state always visible.

Tablet:
- collapsible navigation,
- reduced gutters,
- action wrapping,
- column priority starts applying.

Mobile:
- remove desktop sidebar from layout,
- hamburger opens full-height navigation Drawer,
- compact top bar,
- page title/actions stack,
- secondary actions move to overflow,
- sticky bottom action area only where it improves reachability.

Do not use a 13-item bottom navigation.

Navigation domains:
- Overview
- Data & Scan
- File Tools
- Automation
- Safety & Operations
- System

## Shared product primitives

Converge on:
- AppShell
- ResponsiveNav
- PageHeader
- PageSection
- MetricCard
- DataPanel
- ResponsiveDataView
- StatusBadge
- SafetyBadge
- DangerLevel
- ActionBar
- MobileActionSheet
- FilterBar
- SearchField
- EmptyState
- LoadingState
- ErrorState
- ConfirmAction
- ResponsiveForm
- ResponsiveDescriptions
- CodePath

Pages must not independently invent spacing, status colors, danger hierarchy or mobile behavior.

## Status and safety language

Lifecycle states:
read-only, draft, frozen, validating, ready, stale, expired, blocked, queued, running, paused, completed, partial, failed, cancelled, conflict.

Risk levels:
Neutral → Informational → Attention → Warning → Danger → Irreversible.

Preview/Draft/Freeze/Validate/Execute must remain visually distinct without implying Preview or Draft mutated the filesystem.

Safe mode:
- read-only = calm safe state,
- mutation-enabled = attention/warning,
- permanent-delete-enabled = persistent high-risk.

## Data-heavy views

`ResponsiveDataView` is mandatory for primary business tables.

Desktop:
- dense table,
- sortable/filterable where supported,
- explicit bulk selection where already supported.

Tablet:
- hide low-priority columns,
- preserve identity/state/actions,
- compact action column.

Mobile:
- card/list row,
- identifier first,
- status visible,
- key label/value pairs,
- one primary action visible,
- secondary actions in overflow,
- explicit bulk selection if supported.

Never squeeze a full desktop table into 360px.

## Forms, dialogs and destructive actions

Forms:
- labels visible,
- mobile one-column,
- helper text near field,
- technical/path inputs may use mono.

Dialogs:
- desktop Modal where suitable,
- mobile full-width/full-screen dialog or Drawer for complex content.

Danger:
- irreversible actions use explicit wording,
- destructive primary button remains danger,
- explanation names object and consequence,
- typed confirmation remains where current safety contract requires it,
- never hide destructive actions in unlabeled icon-only controls.

## Charts

Charts are secondary to operational data:
- simplify labels before shrinking,
- light/dark parity,
- semantic palette,
- no decorative 3D/gradients,
- critical values also have numeric/table context.

## Motion

Functional motion only:
- 120–180ms small state changes,
- 180–240ms Drawer/Modal transitions,
- respect `prefers-reduced-motion`,
- no decorative looping except genuine progress indicators.

## Accessibility

Required:
- keyboard reachable actions,
- visible focus,
- semantic buttons/links,
- status not color-only,
- meaningful icon labels/tooltips,
- >=44px touch targets on touch layouts,
- sufficient contrast,
- no hover-only actions,
- reduced-motion support.

## Migration order

1. Foundation: tokens, theme, AppShell, responsive nav, PageHeader.
2. Shared primitives: states, actions, responsive data/form/description.
3. Representative pages: Dashboard, Task Center, Plans / Plan Detail.
4. Core data/safety: Scans, Dedupe, Quarantine, Audit, Indexes.
5. Complex workflows/tools: Workflows, Organizer, Batch, Path Match, Rename.
6. Remaining: Settings, Login, DirectoryPicker, dialogs/drawers.
7. Closure: visual consistency, responsive acceptance, a11y, dependency security, Docker/NAS browser smoke.

## Do / Don't

Do:
- make operational state easy to scan,
- keep safety context persistent,
- use quiet near-monochrome surfaces,
- use one restrained accent,
- prefer hairlines over heavy shadows,
- keep dense data readable,
- give mobile its own layout,
- reuse shared primitives.

Don't:
- add decorative gradients,
- use random page-local colors/radii,
- stack Cards inside Cards without information need,
- use giant headings,
- hide destructive state for visual cleanliness,
- rely on horizontal scrolling for every mobile table,
- change backend/filesystem semantics as part of visual refactoring.


## v0.4.1 Premium Visual Pass

This amendment refines the frozen v0.4.0 system without changing product, API, Worker, Plan, Quarantine or filesystem semantics.

Visual target:
- Linear-level restraint with stronger depth hierarchy,
- Vercel-level typography and control precision,
- Supabase-level developer-tool density,
- Raycast-like interaction polish without decorative spectacle.

Ant Design is infrastructure, not visual identity. Shared NFC tokens and chrome must make buttons, inputs, selects, tables and overlays read as one product rather than stock Ant Design.

### Surface hierarchy

Persistent surfaces may use subtle elevation in addition to hairlines:
- xs: static control / compact floating affordance,
- sm: interactive panel hover and dropdown,
- md: Modal / Drawer / elevated transient surface.

Shadow must remain low-opacity and theme-aware. Depth is supporting hierarchy, not a decorative card effect.

### Motion hierarchy

Motion is functional and spatial:
- 120–180ms: hover, pressed, focus and selection response,
- 180–260ms: page/panel entrance and local state transition,
- 220–320ms: Drawer / Modal / major navigation transition,
- live operational states may use a restrained status-dot pulse,
- no decorative infinite motion outside genuine live/progress state,
- transforms stay within 1–4px and must not move layout,
- prefers-reduced-motion disables entrance, pulse and transform effects.

Representative acceptance surfaces for this pass:
Dashboard, Plans, Workflows, shared shell, shared DataPanel/MetricCard, Ant Design control chrome, Modal/Drawer.


### v0.4.1 Premium Visual Pass closure — 2026-09-18

Automated acceptance:
- RED: Actions `35309248747` — 7 / 7 premium visual contract assertions failed as expected.
- Foundation GREEN: Actions `35309382366` — frontend regression, typecheck and production build PASS.
- Representative-page RED: Actions `35309466791` — premium representative-surface polish assertion failed as expected.
- Final GREEN: Actions `35309541463` — 446 / 446 frontend tests PASS, typecheck PASS, production build PASS.

Implemented:
- theme-aware xs/sm/md depth hierarchy,
- shared motion curves and page/surface entrance,
- Sidebar selected-state motion,
- DataPanel / MetricCard / quick-action interaction depth,
- live-state pulse for running / executing / validating only,
- refined Button / Input / Select / Table / Modal / Drawer / Dropdown chrome,
- staggered Dashboard / mobile record entrance,
- refined Switch / Checkbox / Tabs / Pagination / tooltip / scrollbar behavior,
- complete prefers-reduced-motion fallback.

Not changed:
- routes,
- backend APIs,
- Worker ownership,
- Plan / Task lifecycle semantics,
- Quarantine authority,
- filesystem mutation / validation behavior.

Manual browser visual review remains separate from automated acceptance.
