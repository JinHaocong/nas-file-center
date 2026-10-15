# Console v2 / Pure White v2.1 — rendered-screenshot inspection register

Status: **OPEN / progressive**. Updated 2026-10-15, Stage 5E-AB.

## Why this exists

The Index create dialog looked viewport-safe in the existing Chromium run but visually failed: content had approximately **zero** horizontal inset while its header was inset. Browser overflow checks alone were insufficient. The product owner requested a **shared global synthetic fixture** and a systematic, page-by-page, component-by-component review of **real React/Chromium screenshots**, with direct CSS/layout corrections when justified.

This document records review coverage and missing work; **CI PASS does not mean screenshots have been manually reviewed**, real-NAS approved, or production deployed.

## Safety / accuracy contract

- Render the **actual built React app in a localhost Vite preview**, not a handcrafted screenshot, static mockup or remote production NAS.
- Use deterministic synthetic GET fixtures. Only a script-authorized, locally fulfilled read-only Preview POST may be permitted in a specific legacy script. All mutation endpoints (Generate/Draft/Freeze/Validate/Execute/Purge/Delete etc.) are forbidden; assert zero unexpected requests and zero external origins.
- Introduce a central `visual-fixtures` catalogue incrementally, keeping the existing per-flow mocks executable during migration. Representative states: empty, dense, long/Unicode paths, loading, error, pagination, role/safe-mode, stale/conflict, and nested overlays. No fabricated runtime values presented as production evidence.
- Review 360 / 390 / 430 / 768 / 1024 / 1280 / 1440 / 1920 CSS widths and light, dark, system-light, system-dark. Inspect real screenshots (not merely counts), comparing vertical rhythm, space utilization, column/label alignment, dialog gutters, focus, clipping, contrast, error copy and dangerous-action distinction.
- Each reported visual issue needs a screenshot/route/state/width/theme reproducer, a single owned CSS or component fix, new computed-geometry or interaction assertions where applicable, and an exact-HEAD CI screenshot artifact. Keep user approval consolidated at the end.
- Never claim real NAS verification from synthetic Chromium fixtures or silently change backend safety semantics.

## Screenshot route coverage inventory

| Page / component surface | Existing executable screenshot source | Visual review |
|---|---|---|
| Dashboard | `browser-workspace-cascade.mjs` | Open |
| Indexes ledger and Create/DirectoryPicker | `browser-indexes-ledger-states.mjs`, `browser-workspace-cascade.mjs` | **Stage 5E-AB gutter/focus fix; full visual review open** |
| Scan list, detail, create modal | `browser-overlay-smoke.mjs`; dedicated scan browsers | Open |
| Tasks, detail Sheet, cleanup | `browser-task-overlays.mjs`, `browser-task-ledger-states.mjs` | Open |
| Plans, detail, audit, cleanup | `browser-plan-lifecycle-overlays.mjs`, `browser-workspace-cascade.mjs` | Open |
| Quarantine ledger, single and bulk operations | `browser-quarantine-plan-overlays.mjs`, `browser-quarantine-bulk-overlays.mjs` | Open |
| Media ledger and verification | `browser-media-ledger-states.mjs`, `browser-workspace-cascade.mjs` | Open |
| Workflow list, builder, preview and revisions | `browser-workflow-preview-overlays.mjs`; route/state audit pending | Open |
| Organizer profiles, previews, actions | `browser-organizer-dedupe-overlays.mjs`; route/state audit pending | Open |
| Advanced Dedupe | `browser-organizer-dedupe-overlays.mjs` | Open |
| Scheduler | Route/state screenshot audit pending | Open |
| Settings and Audit | Route/state screenshot audit pending | Open |
| Directory Diff, Filename Audit, Path Match | Route/state screenshot audit pending | Open |
| Batch, Rename, Archive Recovery | Route/state screenshot audit pending | Open |
| Login, navigation and responsive shell | Existing overlay/workspace scripts; expanded audit pending | Open |
| Shared form elements / select / checkbox / confirmation / sheet | Existing overlay scripts; cross-page visual inventory pending | Open |

The current CI generates real screenshots in its artifact (e.g. `pure-white-overlays-<exact-HEAD>`); however, the existing per-flow fixtures are **not yet one unified global fixture dataset**, and all routes/states have not been visually inspected. Do not mark any row accepted without actually inspecting the rendered evidence.

## Inspection checklist per screen

1. **Page frame:** navigational spacing, content width, vertical rhythm, no redundant scrolling.
2. **Typography:** heading/content hierarchy, readable Chinese and English labels, clipping/wrapping.
3. **Grids/tables:** row density, minimum useful information width, sticky/overflow behavior, narrow viewport cards.
4. **Forms:** header/body/footer alignment, 16–24px appropriate gutters, field label proximity, nested form controls and error spacing.
5. **Dialogs/Sheets/Pickers:** focus return, nested layer order, containment, Escape/Cancel/X, background masking, safe/disabled/busy behaviors.
6. **Modes:** light/dark/system, contrast, keyboard visible focus, reduced motion, mobile touch targets.
7. **Dangerous actions:** clear scope and irreversible consequences, no accidental submit or simulated NAS file modification.

### Stage 5E-AB identified case

- Route: `/indexes`; control: `加入索引队列` → `创建增量文件索引`.
- Owner evidence: screenshot captured 2026-10-15, label/picker/note nearly flush with content rim.
- Fix: `console-v2-indexes.css` form-owned gutters and footer alignment.
- Verification: `browser-indexes-ledger-states.mjs` 32 combinations × actual create-dialog screenshots and computed left/right gutter checks.
- State: **await exact-HEAD CI**, **pending full owner visual sign-off**.

## Remaining work order

After the Index dialog, audit shared controlled Dialog/Sheet/DirectoryPicker surfaces first, then iterate across ledger pages and complex forms. Expand deterministic mocks and screenshot coverage in small reversible PRs. Each PR should report exact tested screens, evidence, unreviewed screens and outstanding real-NAS/owner gates; no wholesale restyling based solely on theoretical CSS matches.
