# NAS File Center v0.4.6 — Glass Workspace System

**Status:** DESIGN / IMPLEMENTATION PLAN  
**Date:** 2026-09-19  
**Branch:** `ui/v0.4.6-glass-workspace-system`  
**Baseline:** `main@2ace0ca84f531ba539d57e6c1e7285aae09c83ef`

## 1. Goal

Refactor the entire right-side application workspace so every page, panel, toolbar, table, form, overlay, drawer and mobile surface follows one coherent visual system derived from the left navigation.

The new direction is **Frosted Control Plane**:

- keep the sidebar as the product identity anchor;
- introduce restrained glass / translucent surfaces on the right-side workspace;
- use depth, hierarchy and spacing instead of heavy borders;
- preserve high-density operational readability;
- unify desktop, tablet, mobile, light and dark themes;
- remove the current accumulation of version-specific CSS overrides in favor of reusable primitives.

This is not a decorative-only pass. Layout hierarchy, component density, spacing rhythm, responsive behavior, interactive feedback and CSS architecture are all in scope.

## 2. Current issues found on main

### 2.1 Styling is append-only and difficult to reason about

`frontend/src/index.css` has accumulated multiple version-specific passes. The same shell and component selectors are overridden repeatedly. For example the header has existed as:

- opaque surface;
- blurred surface;
- explicit “no glass” surface;
- translucent floating surface;
- v0.4.4 workspace surface.

This makes small changes risky and prevents one predictable design language.

### 2.2 Theme authority is split

`frontend/src/design/tokens.ts` and CSS variables both define palette/radius values, but they are not identical. Ant Design receives one token set while handcrafted CSS can receive another.

The refactor must establish one visual authority and expose it consistently to both Ant Design and CSS.

### 2.3 Right-side hierarchy is too uniform

Page headers, DataPanel, Ant Card, controls and embedded subpanels frequently use similar opaque surface/border treatment. The result is visually orderly but flat.

The glass pass should distinguish:

1. app canvas,
2. shell chrome,
3. primary workspace surface,
4. nested operational surface,
5. floating overlay.

### 2.4 Existing glass usage is inconsistent

Backdrop blur appears in earlier CSS passes and is explicitly disabled later. The result is not a controlled system.

Glass needs named tokens, explicit tiers and fallbacks rather than page-specific blur declarations.

### 2.5 Page-specific layouts have matured independently

Dashboard, Settings, Plan Detail, Scan Detail, Workflows, Organizer, Quarantine and tool pages each contain good local solutions, but spacing, panel hierarchy and action placement are not fully normalized.

The next pass should preserve domain-specific information architecture while normalizing the shared composition.

## 3. Visual direction

### 3.1 Product character

The visual target is:

- technical;
- calm;
- precise;
- premium without looking consumer-entertainment;
- transparent enough to create depth;
- opaque enough for long tables, logs and destructive workflows.

Avoid:

- excessive blur everywhere;
- neon glow;
- oversized rounded “bubble UI”;
- gradients behind every card;
- low-contrast glass over dense text;
- animations that make an operational console feel playful.

## 4. Surface hierarchy

Introduce named tiers instead of styling every container independently.

### G0 — Canvas

Application workspace background.

Light:
- cool neutral base;
- extremely subtle radial tint near the top/right so glass can visually separate.

Dark:
- graphite base;
- low-luminance blue/green neutral tint;
- never pure black.

No blur.

### G1 — Shell Glass

Used for:
- top Header;
- mobile dock;
- optional sticky page action rails.

Properties:
- translucent surface;
- 18–24px backdrop blur;
- moderate saturation;
- one-pixel soft hairline;
- controlled shadow;
- 16–20px radius.

### G2 — Workspace Glass

Used for:
- PageHeader;
- Dashboard metric cards;
- major DataPanel containers;
- tool workbenches;
- plan/workflow overview surfaces.

Properties:
- less transparent than shell;
- 14–18px blur;
- light internal highlight;
- minimal shadow;
- 16–20px radius.

### G3 — Dense Operational Surface

Used for:
- tables;
- logs;
- forms;
- settings controls;
- destructive review blocks;
- nested data descriptions.

Properties:
- near-opaque;
- no or very low blur;
- stronger contrast;
- 10–14px radius;
- thin separators.

Dense data must not sit directly on highly transparent glass.

### G4 — Floating Glass

Used for:
- Modal;
- Drawer;
- Dropdown;
- Popover;
- Select dropdown;
- command menus.

Properties:
- highest elevation;
- 22–30px blur;
- translucent but readable;
- stronger shadow than G1/G2;
- stronger outline in dark mode.

## 5. Token system

Replace ad-hoc surface styling with a consistent set of tokens.

Required token families:

- `--nfc-canvas-*`
- `--nfc-glass-shell-*`
- `--nfc-glass-workspace-*`
- `--nfc-dense-surface-*`
- `--nfc-overlay-*`
- `--nfc-border-*`
- `--nfc-shadow-*`
- `--nfc-radius-*`
- `--nfc-space-*`
- `--nfc-control-*`
- semantic success/warning/danger/info tokens.

Tokens must support light and dark themes.

Ant Design component tokens should be derived from the same palette used by CSS.

## 6. CSS architecture

Do not add another large override block to the end of `index.css`.

Target structure:

```
frontend/src/styles/
  tokens.css
  foundation.css
  shell.css
  primitives.css
  overlays.css
  responsive.css
  pages/
    dashboard.css
    operations.css
    settings.css
    tools.css
    workflows.css
```

`index.css` becomes an import entry point rather than an ever-growing override ledger.

Existing selectors can be migrated incrementally, but final-state rules should have one clear owner.

## 7. Shared primitive refactor

### PageHeader

New composition:

- compact eyebrow;
- stronger title/description hierarchy;
- optional contextual badge row;
- action cluster aligned to title zone;
- glass workspace surface;
- mobile action stack.

No page should invent a separate title/action shell.

### DataPanel

Add visual variants:

- `default` — workspace glass;
- `dense` — near-opaque data panel;
- `quiet` — low-emphasis nested panel;
- `danger` — destructive context without filling entire panel red;
- `floating` — elevated contextual panel.

Panel header/body/footer spacing must be tokenized.

### ActionBar

Standardize:
- primary action position;
- secondary action grouping;
- destructive action separation;
- compact toolbar mode;
- sticky mobile action mode where needed.

### MetricCard

Use G2 glass, subtle highlight and one controlled emphasis state. Avoid different decorative styles per metric.

### ResponsiveDataView / ResponsiveDescriptions

Desktop/tablet/mobile density and separators should share the same tokens.

### StatusBadge

Unify Tag/status semantics across:
- safe mode;
- worker state;
- plan status;
- task status;
- scan status;
- quarantine state.

Status color should communicate state, not become general decoration.

## 8. Ant Design global treatment

Normalize:

- Button
- Input
- InputNumber
- Select
- Switch
- Checkbox
- Radio
- Table
- Tabs
- Tag
- Alert
- Card
- Modal
- Drawer
- Dropdown
- Popover / Popconfirm
- Tooltip
- Pagination
- Empty
- Spin
- Form controls.

Inputs should look embedded in the workspace rather than like unrelated default Ant controls.

Primary buttons remain clear and limited. Destructive buttons retain high semantic contrast.

## 9. Shell redesign

### Sidebar

The current left navigation remains the reference language.

Only refine:
- collapsed spacing;
- selected indicator;
- group rhythm;
- brand block;
- scrollbar;
- dark/light parity.

Do not turn sidebar into glass; it remains the stable identity plane.

### Header

Refactor into one definitive G1 shell surface.

Desktop:
- floating inside workspace gutter;
- compact navigation toggle;
- workspace identity on left;
- safety/worker status in center-left;
- theme/user command cluster right.

Mobile:
- one-line command bar;
- overflow-safe status presentation;
- no duplicate product branding.

### Workspace canvas

Introduce subtle background depth so translucency is visible, while keeping the reading area neutral.

## 10. Page-by-page coverage

### Dashboard

- glass metric tiles;
- stronger metric typography;
- primary/secondary panel hierarchy;
- rail alignment;
- quick actions as compact actionable rows;
- remove any mixed-radius or joined-grid remnants.

### Indexes

- index summary and table become dense operational surfaces inside workspace glass;
- filters align to one toolbar rhythm;
- row actions become quieter until hover/focus.

### Scans

- scan list, scan detail and advanced dedupe share one data hierarchy;
- root lists, preview summary, identity safety and scorer editor normalized;
- advanced dedupe gets stronger section separation without extra card nesting.

### Path Match

- treat as tool workbench;
- parameters in a compact control deck;
- results on a dense surface;
- clearer empty/loading/result transition.

### Rename

- same workbench grammar as Path Match;
- preview/action boundary visually explicit;
- destructive/conflicting changes use semantic accents only.

### Batch

- operation cards normalized into shared tool tiles;
- remove isolated visual dialects;
- batch operation configuration gets consistent control layout.

### Organizer

- profile list, modal, preview and proposal cards unified;
- preview data stays dense;
- profile actions use shared ActionBar and overlay treatment.

### Workflows

- list, builder, step cards, editors and preview panels become one composition system;
- step cards use predictable selected/active/error states;
- editor controls avoid nested-card overload;
- revision drawer uses G4 overlay.

### Plans

- plan list and detail normalized;
- lifecycle strip becomes a compact timeline/step rail;
- validation/execution/destructive regions use strong semantic grouping;
- Operation Journal drawer stays highly legible and near-opaque inside floating glass frame.

### Quarantine

- list is dense and readable;
- bulk action rail visually distinct but not heavy;
- restore/purge modals use one overlay system;
- destructive permanent delete retains stronger danger affordance than general actions.

### Tasks

- worker card, task progress, action bar, log table and detail drawer normalized;
- live progress uses subtle motion only;
- log table stays opaque enough for long reading.

### Audit

- dense table-first composition;
- filters and time/context metadata compact;
- avoid decorative transparency under long audit rows.

### Settings

- retain the current corrected desktop topology;
- differentiate runtime, lifecycle, resource and sessions by hierarchy rather than different ad-hoc styles;
- control grids become consistent;
- destructive audit-cleanup subsection uses semantic border/header treatment;
- mobile collapses predictably to one-column.

### Login

- visually related to the product but simpler than the authenticated shell;
- one centered glass surface over restrained canvas depth;
- accessibility contrast preserved.

## 11. Overlay and transient surfaces

All of these must share G4:

- change password modal;
- directory picker modal;
- organizer import/profile modal;
- plan cleanup modal;
- task cleanup modal;
- quarantine restore/purge confirmations;
- dedupe plan modal;
- drawers;
- dropdown/select/popover surfaces.

Mask:
- subtle backdrop blur;
- avoid excessive darkening.

## 12. Mobile / tablet behavior

Glass effects must not compromise usability or GPU performance.

Rules:

- reduce blur strength on <= 767px;
- remove large shadows;
- prefer one-column panels;
- retain 44px minimum touch targets;
- use horizontal overflow only for toolbars that cannot stack safely;
- convert dense tables to existing mobile cards where applicable;
- keep bottom safe-area support;
- mobile dock can use G1 glass;
- no fixed-height content shells that fight browser viewport behavior.

## 13. Motion

Use motion only for hierarchy feedback:

- hover elevation: 1–2px maximum;
- surface transitions: 160–220ms;
- drawers/modals rely on Ant motion;
- progress/status animation subtle;
- fully honor `prefers-reduced-motion`.

No large entrance animation across every page.

## 14. Accessibility and readability

Acceptance requirements:

- text contrast must stay readable in light and dark mode;
- focus-visible state must be obvious;
- semantic warning/danger cannot rely on color alone;
- blur must have opaque fallback;
- dense code/path/log content uses mono type and stable line height;
- destructive dialogs retain explicit confirmation hierarchy.

## 15. Performance fallback

Use `@supports (backdrop-filter: blur(1px))`.

Fallback:
- replace glass with the corresponding opaque surface;
- maintain border/shadow/radius;
- no functional difference.

For low-width mobile surfaces, use reduced blur even when supported.

## 16. Implementation phases

### Phase A — Foundation

- consolidate theme tokens;
- create CSS module structure;
- implement G0–G4 surfaces;
- refactor shell/Header/PageHeader/DataPanel/ActionBar;
- migrate Ant global component treatment.

### Phase B — Core operational pages

- Dashboard;
- Indexes;
- Scans + advanced dedupe;
- Plans;
- Quarantine;
- Tasks;
- Audit.

### Phase C — Tool and automation pages

- Path Match;
- Rename;
- Batch;
- Organizer;
- Workflows.

### Phase D — Settings, Login and overlay sweep

- Settings;
- Login;
- every Modal/Drawer/Dropdown/Popover;
- DirectoryPicker;
- cleanup dialogs;
- status and utility components.

### Phase E — Responsive and final audit

- 320 / 375 / 768 / 1024 / 1200 / 1440+ widths;
- light/dark/system theme;
- keyboard focus;
- reduced motion;
- no horizontal body overflow;
- no clipped overlay/actions;
- no remaining one-off inline visual chrome.

## 17. Regression coverage

Add/update tests to assert:

- shared glass tokens exist;
- Header/PageHeader/DataPanel/overlay surfaces consume shared tokens;
- no legacy contradictory header glass/no-glass rules remain;
- page topology classes remain present;
- all major page roots participate in the new workspace system;
- responsive breakpoints include shell, surfaces and mobile dock;
- settings grid topology remains unchanged;
- destructive quarantine/plan/task actions retain semantic classes;
- frontend tests, typecheck and production build pass.

## 18. Definition of done

The pass is complete only when:

1. every routed page has been visually audited;
2. every shared component and overlay has been audited;
3. right-side surfaces use the same hierarchy and radius/spacing language;
4. glass is systematic rather than decorative;
5. dense operational content remains high contrast;
6. dark/light/mobile all have deliberate treatment;
7. old conflicting CSS overrides are removed rather than merely overridden again;
8. existing functional behavior and safety semantics are unchanged;
9. frontend test/typecheck/build are green.
