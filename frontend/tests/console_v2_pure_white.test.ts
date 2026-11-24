import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const shell = read('src/styles/console-v2.css');
const tokens = read('src/styles/tokens.css');
const phase2 = read('src/styles/console-v2-phase2.css');
const overlays = read('src/styles/console-v2-task-overlays.css');

describe('Console surfaces, navigation materials and controls', () => {
  test('content retains solid white surfaces and readable neutral text', () => {
    assert.match(tokens, /--nfc-accent:\s*#252525;/);
    assert.match(tokens, /--nfc-canvas:\s*#ffffff;/);
    assert.match(tokens, /--nfc-nav-surface:\s*#fbfbfa;/);
    assert.match(tokens, /--nfc-hairline:\s*#eaeae7;/);
    assert.match(shell, /--v2-canvas:\s*#ffffff;/);
    assert.match(shell, /--v2-sidebar:\s*#fbfbfa;/);
    assert.doesNotMatch(tokens, /#1769e0|#64a7ff|#e9f1ff/);
  });

  test('dark mode supplies a separate material and active navigation palette', () => {
    assert.match(tokens, /\[data-theme='dark'\]\s*\{[^}]*--nfc-canvas:\s*#171716;/);
    assert.match(tokens, /\[data-theme='dark'\]\s*\{[^}]*--nfc-accent:\s*#e9e9e6;/);
    assert.match(shell, /\[data-theme='dark'\] \.nfc-v2-shell\s*\{[^}]*--v2-sidebar:\s*#1e1e1c;/);
    assert.match(tokens, /\[data-theme='dark'\]\s*\{[^}]*--nfc-material-bg:[^;]+;[^}]*--nfc-material-shadow:/);
    assert.match(shell, /\.nfc-v2-nav-item\.is-active\s*\{[^}]*background:\s*var\(--nfc-tint-soft\);[^}]*color:\s*var\(--nfc-tint\);/);
  });

  test('sidebar uses an inset navigation surface and retains current-page semantics', () => {
    assert.match(shell, /\.nfc-v2-shell \.nfc-v2-sidebar\s*\{[^}]*position:\s*sticky;[^}]*background:\s*var\(--nfc-material-bg\);[^}]*border-radius:\s*var\(--nfc-overlay-radius\);/);
    assert.match(shell, /\.nfc-v2-brand-icon\s*\{[^}]*background:\s*var\(--nfc-tint-fill\);/);
    assert.match(shell, /\.nfc-v2-nav-item\.is-active::before\s*\{[^}]*width:\s*2px;[^}]*height:\s*18px;/);
    assert.doesNotMatch(shell, /linear-gradient\(100deg,\s*#1c4c91/);
    const sidebar = read('src/components/Sidebar.tsx');
    assert.match(sidebar, /aria-current=\{selectedKey === item\.path \? 'page' : undefined\}/);
    const productVersion = JSON.parse(read('package.json')).version as string;
    assert.ok(sidebar.includes(`className="nfc-v2-release-version">v${productVersion}</small>`));
    assert.doesNotMatch(sidebar, /SECURE FILE OPERATIONS · v[0-9]/);
  });

  test('header uses a consistent material with a divider and visible focus', () => {
    assert.match(shell, /\.nfc-v2-shell \.nfc-v2-header\.nfc-header\s*\{[^}]*border-bottom:\s*1px solid var\(--v2-line\) !important;[^}]*background:\s*var\(--nfc-material-bg\) !important;[^}]*backdrop-filter:\s*var\(--nfc-material-filter\);/);
    assert.match(shell, /\.nfc-v2-shell button:focus-visible,\s*\.nfc-v2-shell summary:focus-visible\s*\{\s*outline:\s*2px solid var\(--nfc-tint\);/);
    assert.match(shell, /\.nfc-v2-avatar\s*\{[^}]*background:\s*var\(--nfc-tint-soft\);/);
  });

  test('Dashboard keeps live data and separates product art from text', () => {
    assert.match(shell, /\.nfc-v2-dashboard-hero\s*\{[^}]*background:\s*var\(--nfc-hero-from\);/);
    assert.match(shell, /\.nfc-v2-hero-illustration\s*\{[^}]*object-fit:\s*contain;/);
    assert.match(shell, /\.nfc-v2-dashboard \.nfc-metric-card\s*\{[^}]*border-radius:\s*var\(--nfc-panel-radius\) !important;[^}]*box-shadow:\s*var\(--v2-shadow\) !important;/);
    assert.match(shell, /\.nfc-v2-data-table tbody tr:hover,\s*\.nfc-v2-data-table tbody tr:focus-within\s*\{\s*background:\s*var\(--v2-indigo-soft\);/);
    const dashboard = read('src/pages/Dashboard/index.tsx');
    assert.ok(dashboard.includes('dashboardApi'));
    assert.ok(dashboard.includes('scansApi'));
    assert.ok(dashboard.includes('tasksApi'));
    assert.ok(dashboard.includes('<MetricCard'));
    assert.ok(dashboard.includes('<DataPanel'));
  });

  test('primary controls share the theme tint while dangerous actions keep red semantics', () => {
    assert.match(phase2, /\.nfc-v2-shell \.nfc-console-button-primary\s*\{[^}]*color:\s*var\(--nfc-tint-on-fill\);[^}]*background:\s*var\(--nfc-tint-fill\);[^}]*border-color:\s*var\(--nfc-tint-fill\);/);
    assert.match(overlays, /\.nfc-v2-history-dialog \.nfc-console-button-primary\s*\{[^}]*color:\s*var\(--nfc-tint-on-fill\);[^}]*background:\s*var\(--nfc-tint-fill\);/);
    assert.ok(phase2.includes('.nfc-v2-shell .nfc-console-button-danger'));
    assert.match(overlays, /\.nfc-v2-history-dialog \.nfc-console-button-danger\s*\{[^}]*background:\s*#b9344f;/);
  });

  test('native portal dialogs and sheets match the shell in both themes', () => {
    assert.match(tokens, /--v2-paper:\s*var\(--nfc-surface-1\);/);
    assert.match(overlays, /\.nfc-v2-sheet, \.nfc-v2-confirm-dialog, \.nfc-v2-history-dialog\s*\{[^}]*--v2-indigo:\s*#252525;/);
    assert.match(overlays, /\[data-theme='dark'\] \.nfc-v2-sheet,[\s\S]*?\.nfc-v2-history-dialog\s*\{[^}]*--v2-indigo:\s*#e9e9e6;/);
    assert.match(shell, /\.nfc-v2-dialog:focus-visible\s*\{\s*outline:\s*3px solid var\(--nfc-tint\);/);
    assert.match(shell, /\.nfc-v2-dialog \.nfc-console-button-primary\s*\{[^}]*background:\s*var\(--nfc-tint-fill\);/);
    assert.doesNotMatch(overlays, /#2878ef|#2875e9/);
  });

  test('mobile menu uses solid paper above the floating dock', () => {
    assert.match(shell, /\.nfc-v2-mobile-nav-dialog\s*\{[^}]*background:\s*var\(--v2-paper\);/);
    assert.match(shell, /\.nfc-v2-mobile-nav-close\s*\{[^}]*width:\s*44px;[^}]*height:\s*44px;/);
    assert.match(shell, /\.nfc-v2-mobile-dock \.nfc-mobile-dock-surface\s*\{[^}]*background:\s*var\(--nfc-material-bg\) !important;/);
    assert.match(shell, /\.nfc-mobile-dock-surface::before\s*\{[^}]*pointer-events:\s*none;/);
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
