/** Protect all-route visual coverage without importing (and starting) Playwright. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { visualViewports, visualThemes } from './visual-fixtures.mjs';
import { computedContrastRatio } from './computed-contrast.mjs';

const browser = readFileSync('scripts/browser-full-route-visual.mjs', 'utf8');
const routes = readFileSync('src/router/index.tsx', 'utf8');
const workflow = readFileSync('../.github/workflows/ui-v044-validation.yml', 'utf8');

test('all declared React routes, including every parameterized detail page, have a named visual case', () => {
  const declared = [...routes.matchAll(/<Route\s+path="([^"]+)"/g)]
    .map(x => x[1].replace(/^\/+/, '')).filter(x => x && x !== '*').sort();
  const cases = browser.split('// Ensure the inventory')[0];
  const covered = [...cases.matchAll(/path: '\/([^']+)'/g)]
    .map(x => x[1]).sort();
  const expected = covered.map(x => x.replace(/\/1(?=\/|$)/g, '/:id')).sort();
  assert.equal(declared.length, 24);
  assert.deepEqual(expected, declared);
  assert.equal(new Set(covered).size, 24);
});

test('8x4 safe Chrome visual suite has protected exact-head screenshot upload jobs', () => {
  const job = workflow.slice(workflow.indexOf('  full-route-visual-audit:'));
  assert.ok(job.startsWith('  full-route-visual-audit:\n'));
  assert.match(job, /width: \[360, 390, 430, 768, 1024, 1280, 1440, 1920\]/);
  assert.equal(visualViewports.length, 8);
  assert.equal(visualThemes.length, 4);
  for (const phrase of [
    'Checkout exact candidate HEAD', 'Verify candidate identity',
    'Install isolated Chromium test runner',
    'Build actual production frontend',
    'fonts-noto-cjk', 'node scripts/browser-full-route-visual.mjs',
    'if: always()', 'manifest.json', 'name: full-route-visual-', 'fail-fast: false',
  ]) assert.ok((job + browser).includes(phrase), 'missing audit gate: ' + phrase);
});

test('real browser checks do not mutate or read from NAS and fail on layout/render errors', () => {
  for (const phrase of [
    "if (request.method() !== 'GET')",
    "url.origin !== BASE", "await route.abort('blockedbyclient')",
    "status: 405", "pageErrors", "horizontalOverflow", "tab.screenshot",
    "assert.deepEqual(failures, []", "writeFileSync(resolve(OUT, 'manifest.json')",
  ]) assert.ok(browser.includes(phrase), 'unsafe or missing visual gate ' + phrase);
  assert.doesNotMatch(browser, /await fetch\(['"]https?:\/\/|https:\/\/.*nas/i);
});


test('download verification actual 390px form/table defect has owned responsive UI guards', () => {
  const page = readFileSync('src/pages/DownloadVerification/index.tsx', 'utf8');
  const css = readFileSync('src/styles/console-v2-download-verification.css', 'utf8');
  const entry = readFileSync('src/main.tsx', 'utf8');
  for (const phrase of [
    'nfc-download-verify-page',
    'nfc-download-verify-field',
    'nfc-download-verify-table-scroll',
    'aria-label="校验历史"',
    'aria-label="校验明细"',
  ]) assert.ok(page.includes(phrase), 'missing actual Download Verification UI hook ' + phrase);
  assert.match(css, /grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(css, /@media \(max-width: 767px\)/);
  assert.match(css, /grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.match(css, /min-width:\s*720px/);
  assert.match(css, /overflow-x:\s*auto/);
  assert.ok(entry.includes("import './styles/console-v2-download-verification.css';"));
  assert.ok(browser.includes("item.id === 'download-verification'"));
  assert.ok(browser.includes("field?.querySelector('label')"));
  assert.ok(browser.includes("Download verification remote folder field is missing"));
  assert.ok(browser.includes("'-selected-detail.png'"));
  assert.ok(browser.includes("'Mobile six-column history should scroll within its panel'"));
  assert.ok(browser.includes("path === '/api/plans/legacy/summary'"));
});


test('real 360px visual regression keeps mobile route title on one line without hiding status badges', () => {
  const css = readFileSync('src/styles/console-v2-mobile-header.css', 'utf8');
  const entry = readFileSync('src/main.tsx', 'utf8');
  const header = readFileSync('src/components/Header.tsx', 'utf8');
  assert.ok(entry.includes("import './styles/console-v2-mobile-header.css';"));
  assert.match(css, /@media \(max-width: 767px\)/);
  assert.match(css, /\.nfc-v2-header \.nfc-v2-breadcrumb > strong/);
  assert.match(css, /white-space:\s*nowrap/);
  assert.match(css, /text-overflow:\s*ellipsis/);
  assert.match(css, /@media \(max-width: 380px\)/);
  assert.doesNotMatch(css, /nfc-header-status\s*\{[^}]*display:\s*none/s,
    'Mobile repair may not hide the authoritative Safe Mode / Worker status');
  assert.ok(header.includes('navLabel(location.pathname)'));
  for (const phrase of [
    "width <= 768 && !item.public",
    "h.identityWrap !== 'nowrap'",
    "h.leftRight > h.commandsLeft + 2",
    "h.commandsRight > width + 2",
    "h.parentCrumbDisplay !== 'none'",
  ]) assert.ok(browser.includes(phrase), 'Missing real Chromium header regression: ' + phrase);
});


test('every authenticated route has a real first-Tab bypass with visible light/dark focus and reduced motion', () => {
  const layout = readFileSync('src/layouts/MainLayout.tsx', 'utf8');
  const css = readFileSync('src/styles/console-v2-keyboard-navigation.css', 'utf8');
  const entry = readFileSync('src/main.tsx', 'utf8');
  const oldImport = "import './styles/console-v2-mobile-header.css';";
  const newImport = "import './styles/console-v2-keyboard-navigation.css';";
  assert.ok(entry.includes(newImport) && entry.indexOf(newImport) > entry.indexOf(oldImport),
    'Keyboard skip-link styles must be imported after existing mobile and theme layers');
  assert.match(layout, /className="nfc-v2-skip-link" href="#main-content">跳转到主要内容/);
  assert.ok(layout.indexOf('nfc-v2-skip-link') < layout.indexOf('<ResponsiveNav'),
    'Skip link must be before the sidebar/header in the actual Tab order');
  assert.match(layout, /id="main-content" tabIndex=\{-1\}/);
  assert.match(css, /\.nfc-v2-skip-link:focus-visible/);
  assert.match(css, /outline:\s*3px solid var\(--nfc-text\)/);
  assert.match(css, /min-height:\s*44px/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  for (const phrase of [
    "await tab.keyboard.press('Tab')",
    "await tab.keyboard.press('Enter')",
    "document.activeElement === skip",
    "document.activeElement?.id === 'main-content'",
    "focusAudit.reducedMotion",
    "focusAudit.skipVisible",
    "focusAudit.focusOutline",
    "navTransitionSeconds",
    "locationHash",
  ]) assert.ok(browser.includes(phrase), 'Missing executable Chromium a11y regression: ' + phrase);
});

test('computed focus contrast tests Chromium colors rather than CSS tokens', () => {
  assert.equal(computedContrastRatio('rgb(0, 0, 0)', 'rgb(255, 255, 255)'), 21);
  assert.equal(computedContrastRatio('rgb(32, 32, 31)', 'rgb(32, 32, 31)'), 1);
  assert.ok(computedContrastRatio('rgb(160, 160, 160)', 'rgb(255, 255, 255)') < 4.5);
  assert.throws(() => computedContrastRatio('rgba(0, 0, 0, 0.5)', 'rgb(255, 255, 255)'),
    /opaque computed RGB/);
  assert.throws(() => computedContrastRatio('rgb(999, 0, 0)', 'rgb(255, 255, 255)'),
    /exceeds 255/);
  for (const phrase of [
    "computedContrastRatio(\n            focusAudit.focusColor, focusAudit.focusBackground)",
    "focusAudit.focusOutlineColor, focusAudit.focusBackground",
    "focusTextContrast < 4.5",
    "focusOutlineContrast < 3",
    "audit.skipFocusContrast",
    "rect.width >= 80 && rect.height >= 44",
    "focusAudit.skipTransitionSeconds, focusAudit.skipAnimationSeconds",
  ]) assert.ok(browser.includes(phrase), 'Missing computed Chromium focus assertion: ' + phrase);
});

test('tablet 768px keeps first-party header identity single-line and safety controls reachable', () => {
  const css = readFileSync('src/styles/console-v2-mobile-header.css', 'utf8');
  assert.match(css, /@media \(min-width: 768px\) and \(max-width: 899px\)/);
  const tablet = css.slice(css.indexOf('@media (min-width: 768px)'));
  for (const phrase of [
    '.nfc-v2-header .nfc-v2-breadcrumb > span,',
    '.nfc-v2-header .nfc-v2-breadcrumb > strong',
    'white-space: nowrap',
    'text-overflow: ellipsis',
    '.nfc-v2-header .nfc-v2-user-button > strong',
  ]) assert.ok(tablet.includes(phrase), 'Missing 768px header repair: ' + phrase);
  assert.doesNotMatch(tablet, /\.nfc-header-status\s*\{[^}]*display:\s*none/s,
    'Tablet must not hide Safe Mode or Worker status badges');
  assert.doesNotMatch(tablet, /\.nfc-v2-user-button\s*\{[^}]*display:\s*none/s,
    'Tablet must not hide the admin menu trigger');
  for (const phrase of [
    'width <= 768 && !item.public',
    "h.identityWrap !== 'nowrap'",
    'h.leftRight > h.commandsLeft + 2',
    'h.commandsRight > width + 2',
    "h.parentCrumbDisplay !== 'none'",
  ]) assert.ok(browser.includes(phrase), 'Missing 768px real Chromium geometry: ' + phrase);
});

test('tablet Dashboard column header cancels the inherited historical 620px flex-basis', () => {
  const css = readFileSync('src/styles/console-v2.css', 'utf8');
  const legacy = readFileSync('src/styles/v056-right-workspace-v2.css', 'utf8');
  assert.match(legacy, /\.nfc-app-main \.nfc-page-header-copy\s*\{\s*flex:\s*1 1 620px/);
  assert.match(css, /@media \(min-width: 768px\) and \(max-width: 1199px\)/);
  assert.match(css, /\.nfc-v2-shell \.nfc-v2-dashboard-hero \.nfc-page-header-copy\s*\{\s*flex:\s*0 1 auto/);
  for (const phrase of [
    "if (item.id === 'dashboard')", 'const style = getComputedStyle(copy)',
    'audit.dashboardGeometry = geom', 'width >= 768 && width <= 1024',
    "geom.copyFlexBasis !== 'auto'", "geom.copyFlexGrow !== '0'",
    'geom.heroHeight > 300', 'geom.actionGap > 96', 'geom.metricGap > 90',
  ]) assert.ok(browser.includes(phrase), 'Missing actual Chromium Dashboard geometry regression: ' + phrase);
});
