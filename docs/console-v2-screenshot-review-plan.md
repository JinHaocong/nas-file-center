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

## CJK screenshot fidelity finding (same Stage 5E-AB)

- The latest Stage 5E-AA Actions artifact was actually downloaded and its Indexes create-dialog PNGs inspected at **1280 and 390, light and dark**. The Linux Chromium screenshots display Chinese UI labels as **tofu squares**. This is a fixture environment defect, not a product copy change. Without a real CJK font, screenshot-based Chinese typography/line wrapping cannot be meaningfully reviewed.
- Stage 5E-AB adds Noto CJK installation + `fc-match :lang=zh-cn` verification in the **browser-overlay-smoke CI job before rendering screenshots**. It does not add a CDN, web font bundle, runtime dependency or production typography override. Re-check the new exact-HEAD artifact visually before treating any Chinese screenshots as useful design evidence; OS font rendering will still differ somewhat from macOS PingFang.

## Stage 5E-AC — screenshot-driven Tasks visual fix, incremental shared fixture

- Source evidence: exact Stage 5E-AB CI artifact `pure-white-overlays-7795ed067da1b7c8aa0ec9849516a438e6f722e1`. Screened **42 representative 1280px screenshots** and **16 mobile 390px screenshots** in contact sheets, then opened native-resolution Task Inspector long-error screenshots at 390px and 1280px. Screening **does not** imply complete 1,568-image or all-component manual sign-off.
- Reproducer: `/tasks` → failed task #601 → Inspector. At 390px an extremely long synthetic `FAIL_CLOSED_PATH_IDENTITY` path consumes ~380px and pushes the more actionable Execution summary down despite the old overflow gate passing.
- Fix: for long errors (>240 characters) show a compact three-line preview with keyboard-accessible native `details` control, retaining **the complete unchanged original diagnostic** when expanded. Short errors, error codes, task states and all mutation permissions are untouched.
- Expand the existing 8 widths × 4 themes read-only Chromium Task suite with compact height <=210px, Execution ordering, keyboard Enter expansion/collapse, exact expanded error text and an extra expanded-state screenshot per case. Task screenshots expected **160 instead of 128**; global synthetic snapshot target **1,600 instead of 1,568**, pending exact-HEAD CI verification.
- First shared `frontend/scripts/visual-fixtures.mjs`: deterministic synthetic admin, locked safe-mode settings, eight viewport sizes and four themes. **Only Task ledger, Indexes ledger and Workspace cascade** migrated at this stage. All other routes, data densities and components remain OPEN for future incremental fixture consolidation and real screenshot inspection.
- Product owner consolidated visual sign-off, Organizer C5 and Scheduler S5 real-NAS acceptance and production deployment approval remain OPEN. No backend, RBAC, database, NAS operation or real-file access is changed.


## Stage 5E-AD — Media queue modal gutters and compact root paths

- Screenshot evidence: native 390px CJK-enabled Stage 5E-AC artifact `media-analyze-dialog-light-dark-390.png` shows Media queue instructions/fieldset nearly flush against the dialog edges, while two unbroken synthetic NAS root paths occupy several lines each. Existing Chromium only asserted viewport containment, so the visual density issue was missed. This is a *targeted* screenshot issue, not a whole-site acceptance claim.
- Scope: `/media` → `分析媒体` and `SHA256 校验` modal. The Media-specific body now owns **24px desktop / 18px mobile** horizontal gutters, aligned with title and footer. Paths over 96 characters use two-line visual previews with a separate native, keyboard-operable `details` control revealing their **exact original full path**. The disclosure is outside the checkbox label so Enter does not select a root. All short roots and existing root values/availability/security checks remain unchanged; blocked roots remain disabled.
- Extend existing 8-width × 4-theme read-only Media Chromium suite with actual heading/body gutter geometry, option height, keyboard Enter expanded path, exact full-root text, selected/blocked checkbox invariants, and one expanded screenshot per case. Expected Media 256 vs 224 images, overall **1,632 vs 1,600** synthetic screenshots, pending exact-HEAD CI and targeted visual review.
- Reuse `visualAdminFixture` and `visualSafeSettingsFixture` for the Media suite, bringing the initial shared defaults from three to **four** scripts. This is **not** a fully centralized visual mock catalogue. Full page-by-page/component inspection, Organizer C5/Scheduler S5 real NAS acceptance, owner sign-off and production approval remain **OPEN**.


## Stage 5E-AE — mobile Quarantine Bulk Purge footer visibility

- Reproducer from the **actual Stage 5E-AD exact-HEAD Chromium artifact**: `browser-quarantine-bulk/purge-ready-light-dark-390.png`. At 390 × 900, the long two-entry hard-link/independent-copy advisory fills the modal. The crucial exact `DELETE` confirmation and the button row fall below the initial viewport; even though the dialog rectangle itself stays within the viewport, the danger action was not *visibly usable*. Compare `restore-ready-light-dark-390.png` (shorter, visible actions) and `purge-ready-light-dark-1280.png` (temporary Preview toast can additionally overlap the action).
- Change is **owned only by** `.nfc-quarantine-bulk-purge-modal`: use a flex-column dialog with scrollable, gutter-aligned **diagnostic body** and non-scrolling header/footer. This preserves the full advisory paragraphs, both eligible item cards and exact DELETE token, rather than truncating warnings. Keep Restore and unrelated Radix dialogs unchanged.
- Expand existing 8-width × 4-theme *real React/Chromium* Quarantine Bulk matrix with visible footer/button geometry, body inset, narrow body scroll verification, bottom-reached exact DELETE input and still-enabled Draft-only action. Add one `purge-review-bottom` screenshot per case: expected Quarantine Bulk 160 instead of 128, total screenshot target **1,664 instead of 1,632**. Pending exact-HEAD CI and targeted screenshot inspection; all screenshots are synthetic, not real NAS or human full-route sign-off.
- Existing test authorizes **only** local synthetic read-only `POST /api/quarantine/bulk-preview`; all other POST/Plan/Execute/Delete are denied, outbound traffic blocked. Preserve digest, admin/safety switches, exact uppercase DELETE, single-flight, Freeze → Validate → Execute. Owner full visual audit, real-NAS C5/S5, deployment approval remain OPEN.

- Extra native screenshot inspection of Stage 5E-AE's first 390px/1280px light/dark captures identified a **second visibility defect**: a duplicate green eligible-Preview toast overlays the now-reachable exact `DELETE` input and occasionally the footer. For successful Purge Preview only, keep the same metrics/digest visible in the dialog with `role=status` and `aria-live=polite`, but omit the duplicate floating success toast. Do **not** suppress blocked, error, or Draft-created messages. The Chromium geometry suite additionally checks `elementFromPoint` on the exact confirmation input after body scrolling. New exact-HEAD CI and screenshots are required before claiming success.

- Stage 5E-AE *second exact-SHA artifact* (9702860a) was downloaded and **opened at full 390px**. Green toast text was identified as the **earlier Restore eligible-Preview success**, persisting for 6s after switching modals; removing the Purge success toast alone was insufficient. Fix keeps eligible Restore/Purge Preview announcements in their respective inline `role=status` metric rows, and dismisses any prior blocked/success transient toast on eligible Preview. Blocked Preview, errors and Draft-created success messages continue using the existing feedback paths. The Chromium suite explicitly asserts the Restore→Purge sequence has no floating toast and hit-tests 20%, 50% and 80% of the exact DELETE field after scrolling. Screenshots and latest HEAD CI must be reverified again.


## Stage 5E-AG — Archive Recovery selection/preflight consistency

- Source audit found a reproducible state-invalidation gap: on `/archive-recovery`, choosing a different directory previously updated `folder` without clearing `selected` and its positive check. The screen could retain a previous file/path while showing a new directory. The client now clears selection, password and stale mutations when the directory changes (but does not detach an already tracked running task); the Start button additionally requires the server's check `source` to equal the current selection. This is UI fail-closed consistency, **not** a fix for the NAS shared tmpfs mount.
- Executable unit/source assertions and an independent genuine React/Chromium selection-flow smoke are added. The browser smoke uses synthetic **GET-only** localhost fixtures, blocks all POST/PUT/PATCH/DELETE and outbound requests, and captures 390/1280 × light/dark/system-light/system-dark (8 PNGs). It never calls archive check/start or reads NAS data. Source-bound positive preflight behavior is separately asserted in the frontend regression.
- Stage 5E-AF's API-side `password_channel_available` and mandatory shared API/Worker tmpfs remain unchanged. Real 7z password restore and actual NAS mount verification, the complete visual matrix, Organizer C5/Scheduler S5 NAS acceptance, product-owner sign-off and production deployment approval remain open.

## Stage 5E-AH — Archive Recovery running WorkJob monitor continuity

- Source audit: on `/archive-recovery`, file-row clicks and manual path edits previously invoked `setTaskId(null)`, instantly losing a running/queued archive recovery monitor. Folder switches preserved it, producing inconsistent task tracking and making an in-flight recovery harder to find.
- Fix: preserve the WorkJob independently of editable archive selections; clear selection-bound password and check/start preflight on source switches. After a successful Start the non-secret WorkJob ID is mirrored in the validated `?task=` URL; reload resumes authorized read-only Task API polling. Do not put a password or one-time token in URL or disk.
- A visible “开始下一次恢复” action is available **only after** terminal status; it explicitly clears the monitor and stale preflight and never cancels, deletes, or starts tasks. A running task cannot be dismissed just by selecting another archive.
- New source regression and a real React/Chromium 390/1280 × 4-theme matrix cover running/terminal GET fixture, file/manual-path/folder changes, hard reload, report evidence, and terminal acknowledgement. Exactly eight cases and 24 running/completed/unrelated-job PNGs are captured, pending CI; all other HTTP verbs to `/api/**` are blocked and all off-origin traffic aborted.
- This is synthetic application evidence, not production NAS verification, owner visual acceptance, shared tmpfs deployment, nor Organizer C5/Scheduler S5 real-NAS closure.
