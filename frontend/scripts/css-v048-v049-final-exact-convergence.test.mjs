import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
const layers=['v048.css','v048-detail.css','v049-workspace.css','v050-layout.css',
 'v051-product-polish.css','v052-final-audit.css','v054-premium-system.css',
 'v055-workspace-breathing.css','v056-right-workspace-v2.css'];
const cases=[
  [
    "v048.css",
    "",
    ".nfc-app-main::before",
    "content",
    "v049-workspace.css",
    "''"
  ],
  [
    "v048.css",
    "",
    ".nfc-app-main::before",
    "position",
    "v049-workspace.css",
    "fixed"
  ],
  [
    "v048.css",
    "",
    ".nfc-app-main::before",
    "height",
    "v049-workspace.css",
    "190px"
  ],
  [
    "v048.css",
    "",
    ".nfc-app-main::before",
    "pointer-events",
    "v049-workspace.css",
    "none"
  ],
  [
    "v048.css",
    "",
    ".nfc-app-main::before",
    "background",
    "v049-workspace.css",
    "radial-gradient(circle at 76% -20%, color-mix(in srgb, var(--nfc-v49-accent) 5%, transparent), transparent 46%),\n    linear-gradient(180deg, color-mix(in srgb, var(--nfc-v49-surface) 54%, transparent), transparent 84%)"
  ],
  [
    "v048.css",
    "",
    ".nfc-app-main::before",
    "opacity",
    "v049-workspace.css",
    "0.82"
  ],
  [
    "v048.css",
    "",
    ".nfc-data-panel-quiet",
    "border-color",
    "v049-workspace.css",
    "var(--nfc-border-soft) !important"
  ],
  [
    "v048.css",
    "",
    ".nfc-data-panel-quiet",
    "background",
    "v049-workspace.css",
    "var(--nfc-ui-panel-bg-soft) !important"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-data-panel-header",
    "background",
    "v056-right-workspace-v2.css",
    "transparent"
  ],
  [
    "v048.css",
    "",
    ".nfc-metric-card:hover",
    "box-shadow",
    "v049-workspace.css",
    "0 1px 1px color-mix(in srgb, var(--nfc-text) 3%, transparent),\n    0 14px 34px color-mix(in srgb, var(--nfc-text) 7%, transparent)"
  ],
  [
    "v048.css",
    "",
    ".nfc-filter-bar, .nfc-bulk-action-bar",
    "min-height",
    "v049-workspace.css",
    "56px"
  ],
  [
    "v048.css",
    "",
    ".nfc-filter-bar, .nfc-bulk-action-bar",
    "padding",
    "v049-workspace.css",
    "9px 12px"
  ],
  [
    "v048.css",
    "",
    ".nfc-filter-bar, .nfc-bulk-action-bar",
    "border-color",
    "v049-workspace.css",
    "var(--nfc-border-soft) !important"
  ],
  [
    "v048.css",
    "",
    ".nfc-filter-bar, .nfc-bulk-action-bar",
    "background",
    "v049-workspace.css",
    "var(--nfc-ui-panel-bg-soft) !important"
  ],
  [
    "v048.css",
    "",
    ".nfc-filter-bar, .nfc-bulk-action-bar",
    "box-shadow",
    "v049-workspace.css",
    "none !important"
  ],
  [
    "v048.css",
    "",
    ".nfc-kind-badge, .nfc-operation-badge",
    "background",
    "v048-detail.css",
    "var(--nfc-detail-soft-fill)"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-app-main::before",
    "display",
    "v049-workspace.css",
    "none"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-header.nfc-header",
    "min-height",
    "v056-right-workspace-v2.css",
    "52px"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-header.nfc-header",
    "min-height",
    "v056-right-workspace-v2.css",
    "52px"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-header.nfc-header",
    "margin-inline",
    "v049-workspace.css",
    "10px"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-header.nfc-header",
    "padding-block",
    "v049-workspace.css",
    "5px"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-header-workspace",
    "display",
    "v049-workspace.css",
    "none"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-page-header",
    "min-height",
    "v049-workspace.css",
    "auto"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-page-title",
    "font-size",
    "v056-right-workspace-v2.css",
    "26px"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-page-title",
    "font-size",
    "v056-right-workspace-v2.css",
    "26px"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-metric-grid",
    "grid-template-columns",
    "v049-workspace.css",
    "repeat(2, minmax(0, 1fr))"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-metric-card",
    "min-height",
    "v056-right-workspace-v2.css",
    "96px"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-metric-card",
    "min-height",
    "v056-right-workspace-v2.css",
    "96px"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-metric-card",
    "padding",
    "v056-right-workspace-v2.css",
    "13px"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-metric-card",
    "padding",
    "v056-right-workspace-v2.css",
    "13px"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-data-panel-header",
    "min-height",
    "v049-workspace.css",
    "56px"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-data-panel-header",
    "padding",
    "v049-workspace.css",
    "12px 14px"
  ],
  [
    "v048.css",
    "@media (max-width: 767px)",
    ".nfc-data-panel-description",
    "display",
    "v056-right-workspace-v2.css",
    "block"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-data-panel-description",
    "display",
    "v056-right-workspace-v2.css",
    "block"
  ],
  [
    "v048.css",
    "@media (prefers-reduced-motion: reduce)",
    ".nfc-app-shell *, .nfc-app-shell *::before, .nfc-app-shell *::after",
    "transition-duration",
    "v049-workspace.css",
    "0.01ms !important"
  ],
  [
    "v048.css",
    "@media (prefers-reduced-motion: reduce)",
    ".nfc-app-shell *, .nfc-app-shell *::before, .nfc-app-shell *::after",
    "animation-duration",
    "v049-workspace.css",
    "0.01ms !important"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header.nfc-header",
    "position",
    "v056-right-workspace-v2.css",
    "sticky"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header.nfc-header",
    "z-index",
    "v056-right-workspace-v2.css",
    "30"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header-status",
    "gap",
    "v056-right-workspace-v2.css",
    "5px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header-status",
    "padding",
    "v056-right-workspace-v2.css",
    "0"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header-status",
    "border",
    "v056-right-workspace-v2.css",
    "0"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-header",
    "border-bottom",
    "v056-right-workspace-v2.css",
    "1px solid var(--nfc-w2-hairline)"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-data-panel",
    "border-radius",
    "v056-right-workspace-v2.css",
    "0 !important"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-row-actions:focus-within",
    "opacity",
    "v056-right-workspace-v2.css",
    "1"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-file-tool-result-panel",
    "margin-top",
    "v051-product-polish.css",
    "18px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-advanced-dedupe-page .nfc-dedupe-stage-stack",
    "gap",
    "v050-layout.css",
    "18px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-advanced-dedupe-page .nfc-dedupe-plan-surface",
    "padding",
    "v050-layout.css",
    "14px 16px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-advanced-dedupe-page .nfc-dedupe-plan-surface",
    "border-radius",
    "v050-layout.css",
    "14px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-plan-detail-page .nfc-plan-action-surface",
    "margin-bottom",
    "v050-layout.css",
    "14px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-plan-detail-page .nfc-plan-action-surface",
    "padding",
    "v050-layout.css",
    "10px 12px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-plan-detail-page .nfc-plan-action-surface",
    "border-radius",
    "v050-layout.css",
    "14px !important"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-plan-detail-page .nfc-plan-action-surface",
    "background",
    "v050-layout.css",
    "var(--nfc-ui-panel-bg-soft) !important"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-plan-detail-page .nfc-plan-action-surface",
    "box-shadow",
    "v050-layout.css",
    "none !important"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-organizer-page .nfc-organizer-profile-toolbar, .nfc-organizer-preview-page .nfc-organizer-preview-filter",
    "padding",
    "v051-product-polish.css",
    "10px 12px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-organizer-preview-page .nfc-organizer-metric-grid",
    "margin-bottom",
    "v051-product-polish.css",
    "16px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-system-controls-page .nfc-settings-subpanel",
    "border",
    "v050-layout.css",
    "1px solid var(--nfc-border-soft) !important"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-system-controls-page .nfc-settings-subpanel",
    "background",
    "v050-layout.css",
    "var(--nfc-ui-panel-bg-soft) !important"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-system-controls-page .nfc-settings-subpanel-header, .nfc-system-controls-page .nfc-settings-window-header",
    "min-height",
    "v052-final-audit.css",
    "50px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-system-controls-page .nfc-settings-subpanel-header, .nfc-system-controls-page .nfc-settings-window-header",
    "padding",
    "v050-layout.css",
    "11px 12px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-system-controls-page .nfc-settings-control-grid",
    "padding",
    "v050-layout.css",
    "12px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-system-controls-page .nfc-settings-control-grid",
    "gap",
    "v052-final-audit.css",
    "10px 12px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-overlay-stack",
    "gap",
    "v054-premium-system.css",
    "14px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-directory-list-viewport",
    "max-height",
    "v052-final-audit.css",
    "min(52dvh, 520px)"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 1199px)",
    ".nfc-page-header-copy",
    "max-width",
    "v056-right-workspace-v2.css",
    "min(860px, 68vw)"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 1199px)",
    ".nfc-dashboard-page .nfc-dashboard-layout",
    "grid-template-columns",
    "v056-right-workspace-v2.css",
    "1fr"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 1199px)",
    ".nfc-dashboard-page .nfc-dashboard-rail",
    "position",
    "v056-right-workspace-v2.css",
    "static"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 1199px)",
    ".nfc-dashboard-page .nfc-dashboard-rail",
    "grid-template-columns",
    "v056-right-workspace-v2.css",
    "repeat(2, minmax(0, 1fr))"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-page-content",
    "padding",
    "v056-right-workspace-v2.css",
    "18px 14px max(34px, env(safe-area-inset-bottom))"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-filter-bar, .nfc-bulk-action-bar",
    "padding",
    "v056-right-workspace-v2.css",
    "10px"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-dashboard-page .nfc-dashboard-rail",
    "grid-template-columns",
    "v056-right-workspace-v2.css",
    "1fr"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-system-controls-page .nfc-settings-grid",
    "gap",
    "v050-layout.css",
    "12px"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-row-actions",
    "opacity",
    "v051-product-polish.css",
    "1"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-login-shell",
    "padding",
    "v052-final-audit.css",
    "14px"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 420px)",
    ".nfc-page-title",
    "font-size",
    "v052-final-audit.css",
    "21px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header.nfc-header",
    "top",
    "v056-right-workspace-v2.css",
    "12px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header.nfc-header",
    "min-height",
    "v056-right-workspace-v2.css",
    "68px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header.nfc-header",
    "margin",
    "v056-right-workspace-v2.css",
    "12px 12px 0"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header.nfc-header",
    "padding",
    "v056-right-workspace-v2.css",
    "8px 12px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header.nfc-header",
    "border-radius",
    "v056-right-workspace-v2.css",
    "var(--nfc-radius-shell)"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header.nfc-header",
    "box-shadow",
    "v056-right-workspace-v2.css",
    "0 10px 34px color-mix(in srgb, var(--nfc-text) 7%, transparent)"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header.nfc-header",
    "backdrop-filter",
    "v056-right-workspace-v2.css",
    "blur(22px) saturate(120%)"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header.nfc-header",
    "-webkit-backdrop-filter",
    "v056-right-workspace-v2.css",
    "blur(22px) saturate(120%)"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-header-status",
    "background",
    "v056-right-workspace-v2.css",
    "transparent"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-header",
    "min-height",
    "v056-right-workspace-v2.css",
    "0"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-header",
    "margin",
    "v056-right-workspace-v2.css",
    "0 0 32px !important"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-header",
    "padding",
    "v056-right-workspace-v2.css",
    "0 0 24px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-header",
    "align-items",
    "v056-right-workspace-v2.css",
    "flex-end"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-header",
    "gap",
    "v056-right-workspace-v2.css",
    "28px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-header",
    "border",
    "v056-right-workspace-v2.css",
    "0"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-header",
    "background",
    "v056-right-workspace-v2.css",
    "transparent"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-header",
    "box-shadow",
    "v056-right-workspace-v2.css",
    "none"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-header-copy",
    "max-width",
    "v056-right-workspace-v2.css",
    "min(980px, 74vw)"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-title",
    "font-size",
    "v056-right-workspace-v2.css",
    "clamp(27px, 1.45vw, 31px)"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-title",
    "font-weight",
    "v056-right-workspace-v2.css",
    "620"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-description",
    "margin-top",
    "v056-right-workspace-v2.css",
    "8px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-description",
    "font-size",
    "v056-right-workspace-v2.css",
    "13px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-description",
    "line-height",
    "v056-right-workspace-v2.css",
    "1.58"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-page-actions",
    "padding-bottom",
    "v056-right-workspace-v2.css",
    "1px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-data-panel",
    "overflow",
    "v056-right-workspace-v2.css",
    "visible"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-data-panel-header",
    "min-height",
    "v056-right-workspace-v2.css",
    "0"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-data-panel-header",
    "padding",
    "v056-right-workspace-v2.css",
    "var(--nfc-w2-panel-header-top) var(--nfc-w2-panel-header-x) var(--nfc-w2-panel-header-bottom)"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-data-panel-title",
    "font-size",
    "v056-right-workspace-v2.css",
    "14px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-data-panel-title",
    "font-weight",
    "v056-right-workspace-v2.css",
    "620"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-data-panel-description",
    "margin-top",
    "v056-right-workspace-v2.css",
    "5px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-data-panel-description",
    "font-size",
    "v056-right-workspace-v2.css",
    "11.5px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-data-panel-description",
    "line-height",
    "v056-right-workspace-v2.css",
    "1.52"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-metric-card",
    "border",
    "v056-right-workspace-v2.css",
    "1px solid var(--nfc-w2-hairline)"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-metric-value",
    "margin-top",
    "v056-right-workspace-v2.css",
    "12px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-directory-browser-toolbar",
    "border-radius",
    "v052-final-audit.css",
    "12px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-system-controls-page .nfc-settings-grid",
    "gap",
    "v050-layout.css",
    "18px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-system-controls-page .nfc-settings-grid > .nfc-data-panel > .nfc-data-panel-header",
    "min-height",
    "v052-final-audit.css",
    "62px"
  ],
  [
    "v049-workspace.css",
    "",
    ".nfc-system-controls-page .nfc-settings-subpanel",
    "border-radius",
    "v052-final-audit.css",
    "12px !important"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-header.nfc-header",
    "top",
    "v056-right-workspace-v2.css",
    "0"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-header.nfc-header",
    "margin",
    "v056-right-workspace-v2.css",
    "0"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-header.nfc-header",
    "padding",
    "v056-right-workspace-v2.css",
    "5px 8px"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-header.nfc-header",
    "border-radius",
    "v056-right-workspace-v2.css",
    "0"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-header.nfc-header",
    "box-shadow",
    "v056-right-workspace-v2.css",
    "none"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-page-header",
    "margin-bottom",
    "v056-right-workspace-v2.css",
    "22px !important"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-page-header",
    "align-items",
    "v056-right-workspace-v2.css",
    "stretch"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-page-header",
    "gap",
    "v056-right-workspace-v2.css",
    "15px"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-page-header-copy",
    "max-width",
    "v056-right-workspace-v2.css",
    "none"
  ],
  [
    "v049-workspace.css",
    "@media (max-width: 767px)",
    ".nfc-page-description",
    "font-size",
    "v056-right-workspace-v2.css",
    "12.75px"
  ]
];
const read=f=>readFileSync(resolve(process.cwd(),'src/styles',f),'utf8');
function leaf(css) {
 const rows=[],stack=[];let start=0,comment=false,quote=null,escaped=false;
 for(let i=0;i<css.length;i++){
  const c=css[i],n=css[i+1];
  if(comment){if(c==='*'&&n==='/'){comment=false;i++}continue}
  if(quote){if(escaped){escaped=false;continue}if(c==='\\'){escaped=true;continue}if(c===quote)quote=null;continue}
  if(c==='/'&&n==='*'){comment=true;i++;continue}
  if(c==='"'||c==="'"){quote=c;continue}
  if(c==='{'){const sel=css.slice(start,i).replace(/\/\*[\s\S]*?\*\//g,'').trim().replace(/\s+/g,' ');
   stack.push({sel,ctx:stack.filter(x=>x.sel.startsWith('@')).map(x=>x.sel).join(' > '),from:i+1});start=i+1;
  }else if(c==='}'){
   const e=stack.pop();assert.ok(e,'Unexpected CSS brace');const body=css.slice(e.from,i),props=new Map();
   if(!e.sel.startsWith('@')&&!body.includes('{')){
    for(const field of body.replace(/\/\*[\s\S]*?\*\//g,'').split(';')){
     const j=field.indexOf(':');if(j>0)props.set(field.slice(0,j).trim(),field.slice(j+1).trim());
    }
    rows.push({sel:e.sel,ctx:e.ctx,props});
   }start=i+1;
  }else if(c===';'&&!stack.length)start=i+1;
 }
 assert.equal(stack.length,0,'Unbalanced CSS');return rows;
}
const sheets=Object.fromEntries(layers.map(x=>[x,leaf(read(x))]));
const matching=(f,ctx,sel)=>sheets[f].filter(r=>r.ctx===ctx&&r.sel===sel);
const key=(ctx,sel,p)=>[ctx,sel,p].join(' | ');
test('122 early CSS properties stay retired with exact owner declarations pinned',()=>{
 assert.equal(cases.length,122);
 assert.equal(new Set(cases.map(x=>x.slice(0,4).join(' | '))).size,122);
 for(const [old,ctx,sel,p,later,value] of cases){
  assert.ok(matching(old,ctx,sel).every(r=>!r.props.has(p)),
   'Old property reintroduced '+old+' '+key(ctx,sel,p));
  const winners=matching(later,ctx,sel).filter(r=>r.props.has(p));
  assert.ok(winners.length,'No final CSS owner '+later+' '+key(ctx,sel,p));
  assert.equal(winners.at(-1).props.get(p),value,
   'Final authored CSS value drift '+later+' '+key(ctx,sel,p));
 }
});
test('only six explicit protected important-priority overlaps survive',()=>{
 const byKey=new Map();
 for(const f of layers)for(const r of sheets[f])for(const [p,v] of r.props){
  const k=key(r.ctx,r.sel,p),a=byKey.get(k)||[];a.push({file:f,value:v});byKey.set(k,a);
 }
 const overlaps=[...byKey].filter(([,a])=>new Set(a.map(x=>x.file)).size>1);
 const expected=[
  key('','.nfc-data-panel-header','background'),
  key('','.nfc-header.nfc-header','border'),
  key('','.nfc-header.nfc-header','background'),
  key('','.nfc-overlay-section','border-radius'),
  key('','.nfc-overlay-section','background'),
  key('@media (max-width: 767px)','.nfc-header.nfc-header','border'),
 ];
 assert.equal(overlaps.length,6);
 assert.deepEqual(overlaps.map(([k])=>k).sort(),expected.sort());
 for(const [k,a] of overlaps){
  assert.ok(a.slice(0,-1).some(x=>/!important\s*$/i.test(x.value)),'Missing protected important '+k);
  assert.ok(!/!important\s*$/i.test(a.at(-1).value),'Unexpected unprotected shadow '+k);
 }
});
test('native import, reduced-motion, and read-only computed browser contract preserved',()=>{
 const m=readFileSync(resolve('src/main.tsx'),'utf8');let last=-1;
 for(const f of layers){const i=m.indexOf("import './styles/"+f+"';");assert.ok(i>last,f+' import order changed');last=i}
 assert.ok(last<m.indexOf("import './styles/console-v2.css';"));
 for(const f of ['v048.css','v049-workspace.css']){
  assert.match(read(f),/@media \(max-width: 767px\)/);
  assert.match(read(f),/@media \(prefers-reduced-motion: reduce\)/);
 }
 // A retired multiline selector group must not leave a dangling comma
 // that silently joins the following independent responsive rule.
 assert.ok(matching('v049-workspace.css','@media (max-width: 767px)',
   '.nfc-metric-card:nth-child(2n)').some(r=>r.props.get('border-right')==='0'),
   'Independent even-card phone border must not become grouped with retired action selector');
 assert.match(read('v048.css'),/\.nfc-data-panel-header\s*\{[^}]*background:\s*transparent !important/);
 assert.match(read('v049-workspace.css'),/\.nfc-overlay-section\s*\{[^}]*background:\s*var\(--nfc-ui-panel-bg-strong\) !important/);
 const ci=readFileSync(resolve('../.github/workflows/ui-v044-validation.yml'),'utf8');
 for(const name of ['browser-workspace-cascade.mjs','browser-overlay-smoke.mjs','browser-full-route-visual.mjs'])
  assert.ok(ci.includes(name),'Browser CI missing '+name);
});
