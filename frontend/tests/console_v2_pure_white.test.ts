import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const shell = read('src/styles/console-v2.css');
const tokens = read('src/styles/tokens.css');
const phase2 = read('src/styles/console-v2-phase2.css');
const overlays = read('src/styles/console-v2-task-overlays.css');

describe('Pure White v2.1 visual foundation and details', () => {
  test('canonical light palette uses white, charcoal and neutral hairlines', () => {
    assert.match(tokens, /--nfc-accent:\s*#252525;/);
    assert.match(tokens, /--nfc-canvas:\s*#ffffff;/);
    assert.match(tokens, /--nfc-nav-surface:\s*#fbfbfa;/);
    assert.match(tokens, /--nfc-hairline:\s*#eaeae7;/);
    assert.match(shell, /--v2-canvas:\s*#ffffff;/);
    assert.match(shell, /--v2-sidebar:\s*#fbfbfa;/);
    assert.doesNotMatch(tokens, /#1769e0|#64a7ff|#e9f1ff/);
  });

  test('dark mode is separately tuned with legible neutral foreground and active navigation', () => {
    assert.match(tokens, /\[data-theme='dark'\]\s*\{[^}]*--nfc-canvas:\s*#171716;/);
    assert.match(tokens, /\[data-theme='dark'\]\s*\{[^}]*--nfc-accent:\s*#e9e9e6;/);
    assert.match(shell, /\[data-theme='dark'\] \.nfc-v2-shell\s*\{[^}]*--v2-sidebar:\s*#1e1e1c;/);
    assert.match(shell, /\[data-theme='dark'\] \.nfc-v2-nav-item\.is-active\s*\{\s*background:\s*#343431;\s*color:\s*#f5f5f2;/);
    assert.match(shell, /\[data-theme='dark'\] \.nfc-v2-nav-item\.is-active::before\s*\{\s*background:\s*#f5f5f2;/);
  });

  test('sidebar has a 248px white workspace, quiet active state and no gradients', () => {
    assert.match(shell, /\.nfc-v2-shell \.nfc-v2-sidebar\s*\{[^}]*width:\s*248px;[^}]*background:\s*var\(--v2-sidebar\);/);
    assert.match(shell, /\.nfc-v2-brand-icon\s*\{[^}]*background:\s*#262625;/);
    assert.match(shell, /\.nfc-v2-nav-item\.is-active\s*\{[^}]*background:\s*#eeefed;[^}]*box-shadow:\s*none;/);
    assert.match(shell, /\.nfc-v2-nav-item\.is-active::before\s*\{[^}]*width:\s*2px;[^}]*height:\s*18px;/);
    assert.doesNotMatch(shell, /linear-gradient\(100deg,\s*#1c4c91/);
    const sidebar = read('src/components/Sidebar.tsx');
    assert.match(sidebar, /aria-current=\{selectedKey === item\.path \? 'page' : undefined\}/);
    assert.ok(sidebar.includes('PRIVATE FILE WORKSPACE'));
    assert.doesNotMatch(sidebar, /SECURE FILE OPERATIONS · v0\.4\.7/);
  });

  test('header is truly white with one-pixel divider and accessible focus', () => {
    assert.match(shell, /\.nfc-v2-shell \.nfc-v2-header\.nfc-header\s*\{[^}]*border-bottom:\s*1px solid var\(--v2-line\) !important;[^}]*background:\s*var\(--v2-paper\) !important;/);
    assert.match(shell, /\.nfc-v2-shell button:focus-visible,\s*\.nfc-v2-shell summary:focus-visible\s*\{\s*outline:\s*2px solid #777771;/);
    assert.match(shell, /\[data-theme='dark'\] \.nfc-v2-shell button:focus-visible,[^}]*outline-color:\s*#e9e9e6;/);
    assert.match(shell, /\.nfc-v2-avatar\s*\{[^}]*background:\s*#292928;/);
  });

  test('Dashboard favors actual live data over decorative hardware artwork', () => {
    assert.match(shell, /\.nfc-v2-dashboard-hero\s*\{[^}]*min-height:\s*0;[^}]*border:\s*0;[^}]*background:\s*transparent;/);
    assert.match(shell, /\.nfc-v2-hero-illustration\s*\{\s*display:\s*none;/);
    assert.match(shell, /\.nfc-v2-dashboard \.nfc-metric-card\s*\{[^}]*border-radius:\s*12px !important;[^}]*box-shadow:\s*var\(--v2-shadow\) !important;/);
    assert.match(shell, /\.nfc-v2-data-table tbody tr:hover\s*\{\s*background:\s*var\(--v2-indigo-soft\);/);
    const dashboard = read('src/pages/Dashboard/index.tsx');
    assert.ok(dashboard.includes('dashboardApi'));
    assert.ok(dashboard.includes('scansApi'));
    assert.ok(dashboard.includes('tasksApi'));
    assert.ok(dashboard.includes('<MetricCard'));
    assert.ok(dashboard.includes('<DataPanel'));
  });

  test('primary controls use charcoal while dangerous actions keep red semantics', () => {
    assert.match(phase2, /\.nfc-v2-shell \.nfc-console-button-primary\s*\{[^}]*background:\s*#262625;[^}]*border-color:\s*#262625;/);
    assert.match(phase2, /\[data-theme='dark'\] \.nfc-v2-shell \.nfc-console-button-primary\s*\{[^}]*background:\s*#e9e9e6;[^}]*color:\s*#20201f;/);
    assert.ok(phase2.includes('.nfc-v2-shell .nfc-console-button-danger'));
    assert.doesNotMatch(phase2, /#2878ef|#236bda/);
  });

  test('native portal dialogs and sheets match the shell in both themes', () => {
    assert.match(tokens, /--v2-paper:\s*var\(--nfc-surface-1\);/);
    assert.match(overlays, /\.nfc-v2-sheet, \.nfc-v2-confirm-dialog, \.nfc-v2-history-dialog\s*\{[^}]*--v2-indigo:\s*#252525;/);
    assert.match(overlays, /\[data-theme='dark'\] \.nfc-v2-sheet,[\s\S]*?\.nfc-v2-history-dialog\s*\{[^}]*--v2-indigo:\s*#e9e9e6;/);
    assert.match(shell, /\.nfc-v2-dialog:focus-visible\s*\{\s*outline:\s*3px solid #858580;/);
    assert.match(shell, /\.nfc-v2-dialog \.nfc-console-button-primary\s*\{[^}]*background:\s*var\(--v2-indigo, #262625\);/);
    assert.doesNotMatch(overlays, /#2878ef|#2875e9/);
  });

  test('mobile drawer and dock are white instead of deep-blue', () => {
    assert.match(shell, /\.nfc-v2-mobile-nav-dialog\s*\{[^}]*background:\s*var\(--v2-sidebar\);/);
    assert.match(shell, /\.nfc-v2-mobile-nav-close\s*\{[^}]*background:\s*var\(--v2-indigo-soft\);/);
    assert.match(shell, /\.nfc-v2-mobile-dock \.nfc-mobile-dock-surface\s*\{[^}]*background:\s*var\(--v2-paper\) !important;/);
    assert.match(shell, /\.nfc-v2-mobile-dock \.nfc-mobile-dock-item\.is-active\s*\{[^}]*background:\s*var\(--v2-indigo-soft\);/);
    assert.doesNotMatch(shell, /#121f31|#293e59/);
  });

  test('responsive, keyboard and reduced-motion contracts remain unchanged', () => {
    for (const rule of [
      '@media (max-width: 1199px)',
      '@media (max-width: 767px)',
      '@media (max-width: 380px)',
      '@media (prefers-reduced-motion: reduce)',
      '.nfc-v2-shell button:focus-visible',
      '.nfc-v2-dialog:focus-visible',
    ]) assert.ok(shell.includes(rule), rule);
    assert.ok(phase2.includes('@media (prefers-reduced-motion: reduce)'));
    assert.ok(overlays.includes('@media (prefers-reduced-motion: reduce)'));
  });

  test('existing CSS cascade, no new override layer and full CI registration', () => {
    const entry = read('src/main.tsx');
    const root = entry.indexOf("import './index.css';");
    const tokensLayer = entry.indexOf("import './styles/v047.css';");
    const shellLayer = entry.indexOf("import './styles/console-v2.css';");
    const phaseLayer = entry.indexOf("import './styles/console-v2-phase2.css';");
    assert.ok(root < tokensLayer && tokensLayer < shellLayer && shellLayer < phaseLayer);
    assert.doesNotMatch(entry, /v057|pure-white\.css/);
    const audit = read('scripts/check-console-css-ownership.mjs');
    assert.ok(audit.includes("Incomplete CSS inventory coverage"));
    const runner = read('scripts/run-tests.mjs');
    assert.ok(runner.includes('tests/console_v2_pure_white.test.ts'));
    assert.ok(runner.includes('dist-test/tests/console_v2_pure_white.test.js'));
  });
});
