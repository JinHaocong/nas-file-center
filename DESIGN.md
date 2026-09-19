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


## v0.4.2 Taste-Skill Redesign

This pass is based on the audit-first `redesign-existing-projects` guidance from `Leonxlnx/taste-skill`. The default taste skill is not treated as the primary authority for this product because it explicitly excludes dashboards, data tables and multi-step product UI.

Design read:
- technical NAS operations console for an experienced administrator,
- restrained developer-tool language rather than a marketing surface,
- Graphite + Jade identity,
- Ant Design remains infrastructure, not visual identity.

Taste dials:
- DESIGN_VARIANCE: 5
- MOTION_INTENSITY: 4
- VISUAL_DENSITY: 7

### Audit findings

The v0.4.1 pass improved polish but still retained recognizable generic SaaS / Ant Design signals:
- default system-font hierarchy without a deliberate display/data treatment,
- generic bright SaaS blue as the product accent,
- four equal metric cards on Dashboard,
- persistent border + shadow card chrome across shared panels,
- navigation/header chrome that still reads as a conventional Ant Design application shell,
- all-caps Dashboard eyebrow treatment.

### v0.4.2 direction

The redesign must:
- use a graphite neutral family with one restrained jade accent,
- use tabular numerics and stronger optical hierarchy for operational data,
- reduce generic card chrome and use separators / negative space where elevation is not meaningful,
- make Dashboard metrics asymmetric on desktop while preserving responsive collapse,
- make Sidebar and Header feel like one deliberate workspace chrome system,
- keep semantic success / warning / danger colors functional and separate from the product accent,
- retain purposeful motion only and continue honoring `prefers-reduced-motion`,
- preserve all API, Worker, Plan, Quarantine, filesystem and destructive-action semantics.

No framework migration is authorized. React 18, TypeScript, Vite and Ant Design 5 remain the implementation stack.


### Feihong Console Quality Gate

This quality gate adapts the Console/Admin discipline from `ifeihong/feihong-design-system` without importing Feihong's personal-brand skin.

Adopted principles:
- function before decoration,
- navigation carries product identity while the work canvas stays neutral,
- operational controls expose hover / active / focus / disabled states,
- dense data surfaces use a stable scan rhythm,
- data and identifiers use tabular / mono treatment where appropriate,
- motion must be purposeful, restrained and reduced-motion safe,
- desktop, tablet and mobile remain first-class layouts.

NAS-specific adaptation:
- the existing Graphite + Jade identity remains authoritative instead of Feihong Royal Blue / Gold / Burgundy,
- semantic colors remain authoritative: success stays green, warning stays amber, danger / irreversible stays red,
- no Feihong wax-seal, fleuron, editorial ornament, luxury serif branding or decorative gold is imported,
- terminal green remains reserved for genuine terminal/code semantics if introduced later,
- Header chrome is crisp rather than glassmorphic so safety and Worker state remain immediately legible.

Console rhythm:
- primary operational table rows target 46px on desktop,
- nested decorative entrance animations are removed from dense data regions,
- one page-level entrance plus genuine live/progress motion is the default ceiling,
- the shared easing reference is `cubic-bezier(0.16, 1, 0.3, 1)`, without bounce or overshoot.

The source design system is guidance, not runtime dependency. React 18 + TypeScript + Vite + Ant Design 5 remain unchanged.


### v0.4.2 closure

Manual acceptance:
- User explicitly approved merge on 2026-09-18 after the Taste × Feihong Console redesign pass.
- Real-browser visual acceptance is treated as user-owned approval; automated tests remain evidence for structural UI contracts only.

Verification evidence:
- Taste RED: Actions `35311300882`
- Taste GREEN: Actions `35311577378`
- Taste final refactor validation: Actions `35311699878`
- Feihong Console Quality Gate RED: Actions `35312162194`
- Combined GREEN: Actions `35312349148`
- Final combined automated result: 463 / 463 frontend tests PASS, TypeScript PASS, production build PASS.

Release boundary:
- v0.4.2 remains UI / design-system / visual-regression scope only.
- No backend, API, Worker, executor, fs_ops, Quarantine, Plan lifecycle, PathGuard, RBAC or destructive-confirmation semantics were intentionally changed.
- The temporary v0.4.2 PR-only TDD workflow is removed at closure; the regression contracts remain in the frontend test runner.


## v0.4.3 Modern Console Reset

The v0.4.3 visual reset supersedes the v0.4.2 Graphite + Jade **brand skin** while preserving its product-safety and anti-slop lessons.

Research references:
- Vercel Geist: high-contrast neutral foundations, developer-tool typography, grid discipline, compact functional surfaces.
- Raycast: fast tool ergonomics, command-oriented chrome, restrained high-signal interaction.
- Ant Design remains infrastructure for accessible controls, tables, overlays and responsive primitives; it is not the visual identity.
- Feihong Console guidance remains useful for function before decoration, explicit states and density, but its brand palette is not used.

### New product direction

- Neutral Graphite canvas + Electric Blue product accent.
- Light floating workspace rail on desktop instead of a permanent dark navigation slab.
- Compact command-bar Header with low chrome and clear system-state grouping.
- Rounded premium operational surfaces use whitespace, hairlines and subtle elevation instead of heavy gray table chrome.
- Table headers are transparent and scanning hierarchy comes from typography and rhythm.
- Worker status is a compact status strip rather than a traditional four-column admin card.
- Mobile is a distinct interaction model, not a scaled-down desktop.
- Primary mobile navigation uses a persistent mobile bottom dock for Overview / Scans / Plans / Tasks, with More opening the full navigation drawer.
- Mobile content reserves safe-area space for the dock; task rows become touch-friendly cards with separate action regions.

### Safety and behavior boundaries

This reset is presentation-only:
- API contracts unchanged.
- Worker / executor / fs_ops ownership unchanged.
- Quarantine and destructive confirmations unchanged.
- Preview → Draft → Freeze → Validate → Execute unchanged.
- PathGuard / symlink / no-clobber / stale checks unchanged.
- RBAC unchanged.

The earlier v0.4.2 Graphite + Jade assertions are historical design evidence, not a permanent palette lock. The v0.4.3 Electric Blue identity intentionally supersedes that palette while retaining semantic success / warning / danger colors.


## v0.4.4 Page Detail Pass

The Modern Console shell is retained. This pass refines only the right-side product surfaces and desktop scroll behavior.

### Shell behavior

- Desktop uses a fixed 100dvh application shell.
- The right application pane is the primary vertical scroll container.
- The left workspace rail stays bound to the viewport and only its own menu scrolls when navigation content exceeds available height.
- Mobile keeps native document scrolling and the existing Bottom Dock safe-area model.

### Page-specific detail language

- Indexes: operational root registry with compact status hierarchy.
- Scans: scan history emphasizes snapshot scale and reclaimable capacity.
- Path Match: rule-building workbench separated from Preview results.
- Rename: transformation workbench separated from conflict/result review.
- Batch: operation selection reads as a tool palette rather than a generic radio form.
- Organizer: reusable profiles remain automation-oriented with lighter tab hierarchy.
- Workflows: versioned definitions emphasize mode/revision/state rather than generic table chrome.
- Plans: lifecycle and expected-change information remain primary.
- Quarantine: destructive/bulk actions are visually distinct from ordinary controls.
- Tasks: Worker state, filters and execution rows remain an operations surface.
- Audit: event browsing uses a more forensic / monospace treatment.
- Settings: ordinary controls and destructive policy actions are visually separated.

The left navigation rail and top command bar are intentionally unchanged because that shell direction is already accepted.

### Safety boundaries

This pass is presentation-only. It does not change API contracts, RBAC, destructive confirmations, Worker/executor/fs_ops ownership, Quarantine semantics, or Preview → Draft → Freeze → Validate → Execute.


## v0.4.4 Detail Pass 2 — Deep Component & Mobile Contract

This pass keeps the accepted floating left workspace rail and top command bar. It focuses on the right-side product surface and treats every detail route and overlay as part of the product, not as secondary Ant Design chrome.

### Coverage

Primary pages:
- Dashboard
- Indexes
- Scans
- Path Match
- Rename
- Batch
- Organizer
- Workflows
- Plans
- Quarantine
- Tasks
- Audit
- Settings

Detail / builder routes:
- Scan Detail
- Advanced Dedupe
- Plan Detail
- Workflow Builder
- Organizer Preview

Embedded product components:
- Task Detail + Task Logs
- Operation Journal
- Stale Plan Rebuild
- Workflow Revision History
- Workflow Step Composer and step editors
- Organizer Profile editor
- Directory Picker
- Quarantine restore / purge / bulk dialogs
- Audit detail
- Index / Scan creation dialogs
- Settings destructive confirmation

### Mobile contract

Mobile is not allowed to be a shrunk desktop layout.

- Shared Drawer overlays become full viewport width.
- Shared Modal overlays use near-fullscreen width and safe-area-aware footers.
- Task logs, operation journals, workflow revisions and stale-plan previews use mobile cards/lists instead of desktop tables.
- Touch targets are at least 44px for page controls.
- Forms collapse to one column.
- Page actions may scroll horizontally when the action set cannot safely wrap.
- Tables that already have page-level mobile card implementations continue to use those implementations.
- Bottom Dock safe-area spacing remains authoritative.
- Long paths, hashes and JSON evidence must wrap/scroll within their own surface rather than expanding the viewport.

### Visual contract

- Data density remains high, but hierarchy comes from typography, spacing, hairlines and semantic surfaces rather than gray card stacking.
- Detail drawers use sectioned evidence surfaces.
- Code/JSON evidence uses a shared mono code block.
- Workflow editing uses a consistent step-composer model.
- Quarantine destructive dialogs use semantic danger borders/controls without tinting the entire application red.
- Settings destructive actions are visually isolated from normal configuration controls.
- Inline one-off visual chrome should be replaced by reusable semantic classes when a component is revisited.

No API, RBAC, filesystem, Worker, Plan lifecycle or destructive-operation semantics are changed by this pass.

## v0.4.6 Frosted Control Plane

This pass supersedes the v0.4.4 right-side workspace skin while preserving its accepted information architecture, mobile behavior and safety boundaries.

### Product direction

- Sidebar remains the stable opaque product identity plane.
- Header, PageHeader, major workspace panels and floating overlays use restrained frosted translucency.
- Dense operational content — tables, logs, forms, journal evidence, destructive review and settings controls — remains near-opaque for sustained readability.
- Electric Blue remains the product accent; semantic success / warning / danger colors remain independent.
- Visual hierarchy is expressed through named surface tiers, spacing, hairlines and optical depth rather than page-specific card decoration.
- Glass is a material system, not a decoration applied everywhere.

### Surface tiers

- G0 Canvas: neutral operational background with subtle depth tint.
- G1 Shell Glass: Header and Mobile Dock.
- G2 Workspace Glass: PageHeader, metric tiles, primary DataPanels and tool workbenches.
- G3 Dense Surface: tables, logs, forms, settings, journals and destructive review.
- G4 Floating Glass: Modal, Drawer, Dropdown, Select, Popover, Message and Notification.

All tiers have light/dark variants, reduced-transparency behavior and opaque fallback when backdrop filters are unavailable.

### Architecture

The accepted style ownership is now:

```
src/styles/
  tokens.css
  foundation.css
  shell.css
  primitives.css
  overlays.css
  components.css
  responsive.css
  pages/
    dashboard.css
    operations.css
    details.css
    tools.css
    organizer.css
    workflows.css
    settings.css
    login.css
```

`index.css` remains a legacy compatibility substrate while selectors are migrated. New release-specific UI work must not append another global override ledger to its end.

The superseded terminal v0.4.4 Workspace Cohesion, Sidebar Parity, shared substrate and Settings topology override blocks were removed. Their still-valid contracts now live with the v0.4.6 style owners.

### Coverage

Every routed surface participates in the system:

- Dashboard
- Indexes
- Scans / Scan Detail / Advanced Dedupe
- Path Match
- Rename
- Batch
- Organizer / Organizer Preview
- Workflows / Workflow Builder / Revision and Definition inspectors
- Plans / Plan Detail / Operation Journal / Stale Rebuild
- Quarantine / Restore / Purge / Bulk Purge
- Tasks / Worker status / Task Detail / Task Logs
- Audit
- Settings
- Login
- Directory Picker and shared transient overlays

### Responsive and accessibility

- 320px and 375px compact mobile layouts are first-class.
- Tablet and desktop maintain dense operational information without horizontal body overflow.
- Blur and large shadows are reduced on mobile.
- `prefers-reduced-motion` and `prefers-reduced-transparency` are honored.
- Focus-visible treatment remains explicit.
- Unsupported backdrop-filter environments fall back to opaque surfaces without functional change.

### Safety boundary

This release is UI / design-system scope only.

It does not intentionally change:
- API contracts,
- RBAC,
- Worker / executor ownership,
- filesystem mutation semantics,
- Quarantine authority,
- permanent-delete authority,
- Plan lifecycle,
- Preview → Draft → Freeze → Validate → Execute,
- PathGuard / symlink / stale identity checks.

Destructive workflows retain stronger semantic hierarchy, but their authorization and execution semantics are unchanged.

## v0.4.7 Control Plane Redesign

v0.4.7 supersedes the v0.4.6 right-workspace skin. The v0.4.6 information architecture and safety boundaries remain valid, but ordinary workspace content is no longer required to look frosted, floating or card-based.

### Open-source research synthesis

The direction was rebuilt from production-grade open-source interfaces rather than a single visual reference:

- Supabase Studio: explicit page/container/section ownership, dense developer tooling, restrained section hierarchy.
- Twenty: sidebar-first workspace, view/table-centric primary content, command surfaces and side-panel inspection.
- Plane: compact operational hierarchy and low-chrome work-item surfaces.
- Immich: application-shell discipline and high information density for self-hosted media operations.
- Open WebUI: desktop-like navigation, settings navigation and focused workspace composition.
- CasaOS / Runtipi / Homarr: self-hosted/NAS status context and approachable operational navigation.
- Portainer: infrastructure-console vocabulary, status/action separation and table-first operations.

No one project is treated as a template. NAS File Center combines these patterns around its own safety-heavy file-operation lifecycle.

### Current visual hierarchy

- Sidebar is the stable identity/elevation anchor.
- Header is an integrated sticky command rail, not a floating rounded card.
- PageHeader is an unboxed title/action band separated by a hairline.
- Tables and workbenches are allowed to become the primary page surface.
- Metrics form joined instrument strips where possible instead of decks of small cards.
- Default and dense DataPanel surfaces are opaque and restrained.
- Glass/blur is reserved for shell chrome and transient overlays.
- Shadows communicate actual elevation; they are not default decoration.
- Radius is smaller and less frequent in normal workspace content.
- Settings reads like system preferences with ruled sections and isolated destructive controls.
- Workflow/Dedupe tools read as editors and analysis workbenches rather than generic admin cards.
- Mobile keeps route-specific card/list views where useful, but title/actions and metrics are recomposed rather than blindly stacked.

### CSS ownership

`src/styles/v047.css` is the active release entry. Existing page/component style owners remain split under `src/styles/`.

The terminal v0.4.4 audit/override ledger has been removed from `index.css`; migrated selectors now live under their semantic owners. New UI work must continue this ownership model instead of reintroducing a release-specific override tail.

### Safety boundary

This redesign does not change filesystem, Plan, Worker, Quarantine, purge, RBAC or API semantics. Preview → Draft → Freeze → Validate → Execute and all fail-closed identity protections remain authoritative.

