/** Protect all-route visual coverage without importing (and starting) Playwright. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { visualViewports, visualThemes } from './visual-fixtures.mjs';
import { requiresFullPageReview, FULL_PAGE_REVIEW_WIDTHS,
  requiresWorkspaceScrollReview, requiresExpandedInteractionFullPageReview } from './visual-screenshot-policy.mjs';
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
  assert.equal(declared.length, 25);
  assert.deepEqual(expected, declared);
  assert.equal(new Set(covered).size, 25);
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


test('Download Verification owns both stylesheets in deterministic main order, not route chunks', () => {
  const entry = readFileSync('src/main.tsx', 'utf8');
  const verify = readFileSync('src/pages/DownloadVerification/index.tsx', 'utf8');
  const sources = readFileSync('src/pages/DownloadVerification/SourcesPage.tsx', 'utf8');
  const base = "import './styles/console-v2-download-verify.css';";
  const mobile = "import './styles/console-v2-download-verification.css';";
  assert.equal(entry.split(base).length - 1, 1, 'Full feature owner imported exactly once');
  assert.equal(entry.split(mobile).length - 1, 1, 'Responsive repair imported exactly once');
  assert.ok(entry.indexOf(mobile) < entry.indexOf(base),
    'Responsive patch keeps its former earlier priority than late-loaded route CSS');
  for (const [name, page] of [['verify', verify], ['sources', sources]]) {
    assert.doesNotMatch(page, /import\s+['"]\.\.\/\.\.\/styles\/console-v2-download-verify\.css['"]/,
      name + ' must not load CSS from a lazy feature chunk');
  }
  const feature = readFileSync('src/styles/console-v2-download-verify.css', 'utf8');
  const responsive = readFileSync('src/styles/console-v2-download-verification.css', 'utf8');
  assert.match(feature, /\.nfc-download-verify\s*\{/);
  assert.match(feature, /\.nfc-dv-manager-grid/);
  assert.match(feature, /\.nfc-dv-table/);
  assert.match(responsive, /\.nfc-download-verify-page\s+\.nfc-form-grid/);
  assert.match(responsive, /@media \(max-width: 767px\)/);
  assert.ok(browser.includes("item.id === 'download-verification' || item.id === 'download-sources'"));
  assert.ok(browser.includes('audit.downloadVerificationCssOwner = owner'));
  assert.ok(browser.includes("owner.display !== 'grid'"));
  assert.ok(browser.includes('!owner.line || !owner.text || owner.width < 100'));
  assert.ok(browser.includes("path: '/download-sources', id: 'download-sources'"));
});

test('download source settings and modal browser remain covered by real route audit', () => {
  const settings = readFileSync('src/pages/DownloadVerification/SourcesPage.tsx', 'utf8');
  const verify = readFileSync('src/pages/DownloadVerification/index.tsx', 'utf8');
  const picker = readFileSync('src/pages/DownloadVerification/RemoteDirectoryPicker.tsx', 'utf8');
  assert.ok(browser.includes("path: '/download-sources', id: 'download-sources'"));
  assert.ok(settings.includes('ConsoleConfirmDialog'));
  assert.ok(verify.includes('RemoteDirectoryPicker'));
  assert.ok(verify.includes('ConsoleConfirmDialog'));
  assert.ok(verify.includes('removeReport'));
  assert.ok(verify.includes('aria-label="校验明细"'));
  assert.ok(picker.includes('nfc-v2-directory-dialog'));
  assert.ok(picker.includes('Dialog.Content'));
  assert.ok(picker.includes('!browse.isFetching'));
  assert.ok(browser.includes("name + '-remote-picker.png'"));
  assert.ok(browser.includes("name + '-source-editor.png'"));
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

test('768px recent-scans table has readable filenames and keyboard-native local scrolling', () => {
  const dash = readFileSync('src/pages/Dashboard/index.tsx', 'utf8');
  const css = readFileSync('src/styles/console-v2.css', 'utf8');
  for (const phrase of [
    'nfc-v2-recent-scans-scroll', 'nfc-v2-recent-scans-table',
    'role="region" aria-label="最近扫描表格，可横向滚动" tabIndex={0}',
  ]) assert.ok(dash.includes(phrase), 'Missing accessible recent scan region: ' + phrase);
  assert.match(css, /@media \(min-width: 768px\) and \(max-width: 899px\)/);
  assert.match(css, /\.nfc-v2-dashboard \.nfc-v2-recent-scans-table\s*\{\s*min-width:\s*860px/);
  assert.match(css, /\.nfc-v2-shell \.nfc-v2-recent-scans-scroll:focus-visible\s*\{\s*outline:\s*2px solid var\(--v2-indigo\) !important;/);
  assert.match(css, /\.nfc-v2-recent-scans-scroll:focus-visible\s*\{[^}]*transition:\s*none !important;/);
  for (const phrase of [
    "item.id === 'dashboard' && width === 768",
    'audit.recentScansGeometry = scans', 'scans.scrollContent < scans.scrollClient + 120',
    'scans.filenameWidth < 145', 'scans.filenameHeight > 72',
    "tab.locator('.nfc-v2-recent-scans-scroll')", "tab.keyboard.press('ArrowRight')",
    "tab.keyboard.press('Shift+Tab')", "element.matches(':focus-visible')",
    'audit.recentScansFocus = focus',
    'audit.recentScansKeyboardScrollLeft', 'if (scrollLeft < 3)',
  ]) assert.ok(browser.includes(phrase), 'Missing actual Chromium 768px scan table gate: ' + phrase);
});

test('shared native filter selects have real keyboard labels and opaque computed WCAG focus rings', () => {
  const css = readFileSync('src/styles/console-v2-tasks.css', 'utf8');
  const select = readFileSync('src/components/ui/ConsoleSelect.tsx', 'utf8');
  const tasks = readFileSync('src/pages/Tasks/index.tsx', 'utf8');
  const quarantine = readFileSync('src/pages/Quarantine/index.tsx', 'utf8');
  assert.match(css, /\.nfc-v2-shell \.nfc-console-select:focus-visible\s*\{[^}]*outline:\s*3px solid var\(--v2-indigo\)/s);
  assert.doesNotMatch(css, /\.nfc-console-select:focus-visible\s*\{[^}]*color-mix\(/s,
    'Focus ring must not reuse a 24%-opaque mixed color');
  for (const phrase of ['aria-label={label}', 'htmlFor={id}', '<select', 'onChange={event => {']) {
    assert.ok(select.includes(phrase), 'Missing native select semantics: ' + phrase);
  }
  for (const id of ['nfc-task-status-filter', 'nfc-task-type-filter'])
    assert.ok(tasks.includes('id="' + id + '"'), 'Missing task native filter ' + id);
  assert.ok(quarantine.includes('id="quarantine-state-filter"'));
  for (const phrase of [
    "item.id === 'tasks' || item.id === 'quarantine'",
    "tab.locator(selector)", "await tab.keyboard.press('Tab')",
    "await tab.keyboard.press('Shift+Tab')", "element.matches(':focus-visible')",
    "audit.nativeSelectFocus.push", "data.outlineWidth < 2",
    "computedContrastRatio(data.outlineColor, data.background)",
    "computedContrastRatio(data.color, data.background)",
    "focusContrast < 3 || textContrast < 4.5",
    "data.accessibleName !== accessibleName", "data.hasAssociatedLabel",
  ]) assert.ok(browser.includes(phrase), 'Missing real Chrome select focus check: ' + phrase);
});


test('dynamic scan detail waits for real route content without weakening the blank-page gate', () => {
  assert.ok(browser.includes("item.id === 'scan-detail'"));
  assert.match(browser, /tab\.waitForFunction\(\(\) => \{/);
  assert.match(browser, /\(main\?\.innerText \|\| ''\)\.trim\(\)\.length >= 25/);
  assert.match(browser, /\}, null, \{ timeout: 6000 \}\)/);
  assert.ok(browser.includes("audit.visibleChars < 25"),
    'Never remove the existing all-route empty-content rejection');
  assert.match(browser, /assert\.deepEqual\(failures, \[\]/);
  assert.ok(browser.includes("if (request.method() !== 'GET')"));
  assert.ok(browser.includes("url.origin !== BASE"));
});


test('all four theme modes capture full-page 390/1440 screenshots without clipping dark/system below the fold', () => {
  assert.deepEqual(FULL_PAGE_REVIEW_WIDTHS, [390, 1440]);
  for (const width of visualViewports) {
    for (const theme of visualThemes) {
      // Coverage depends on viewport size alone, never on explicit/system theme.
      assert.equal(requiresFullPageReview(width), [390, 1440].includes(width),
        width + ' ' + theme.mode + '-' + theme.system);
    }
  }
  assert.ok(browser.includes('audit.screenshotFullPage = requiresFullPageReview(width)'));
  assert.ok(browser.includes('fullPage: audit.screenshotFullPage'));
  for (const probe of [
    'baselinePng.readUInt32BE(16)', 'baselinePng.readUInt32BE(20)',
    'document.documentElement.scrollHeight',
    'audit.screenshotPixels = { width: pixelWidth, height: pixelHeight, documentHeight }',
    'pixelHeight < documentHeight - 2',
    'Baseline screenshot missing required viewport/full-page pixels:',
  ]) assert.ok(browser.includes(probe), 'Missing actual screenshot-depth check: ' + probe);
  assert.doesNotMatch(browser, /fullPage:\s*\([^\n]+\)\s*&&\s*theme\.mode\s*===\s*['"]light['"]/);
  assert.ok(browser.indexOf('audit.screenshotFullPage = requiresFullPageReview(width)') <
    browser.indexOf('await tab.screenshot({\n          path: resolve(OUT, name +'));
});


test('mobile advanced-dedupe disabled scorer cards pack by content, with live Chromium geometry gate', () => {
  const css = readFileSync('src/styles/console-v2-dedupe-scorer.css', 'utf8');
  const editor = readFileSync('src/components/dedupe/DedupeScorerConfigEditor.tsx', 'utf8');
  const entry = readFileSync('src/main.tsx', 'utf8');
  assert.ok(entry.includes("import './styles/console-v2-dedupe-scorer.css';"));
  const mobile = css.slice(css.indexOf('@media (max-width: 767px)'));
  assert.match(mobile, /\.nfc-v2-scorer-editor\s*\{\s*grid-auto-rows:\s*max-content;\s*align-content:\s*start;/);
  assert.match(mobile, /\.nfc-v2-scorer-card\s*\{\s*align-self:\s*start;/);
  assert.match(mobile, /\.nfc-v2-scorer-heading h3\s*\{\s*flex:\s*0 0 auto;/);
  assert.match(css, /\.nfc-v2-scorer-heading h3\s*\{\s*flex:\s*1 1 180px;/);
  assert.ok(editor.includes('nfc-dedupe-config-card nfc-v2-scorer-card'));
  assert.ok(editor.includes('nfc-v2-scorer-weight'));
  for (const phrase of [
    "item.id === 'scan-dedupe' && width <= 430",
    'audit.scorerMobileGeometry = geometry',
    "geometry.gridAutoRows !== 'max-content'",
    "geometry.alignContent !== 'start'",
    "card.height > 270 || card.gapToWeight > 90",
    'Mobile inactive dedupe scorer card has excessive whitespace:',
    'assert.deepEqual(failures, []',
  ]) assert.ok(browser.includes(phrase), 'Missing real mounted scorer geometry audit: ' + phrase);
});

test('1440px desktop full-page evidence also inspects real nested workspace scroll in all themes', () => {
  assert.equal(requiresWorkspaceScrollReview(1440, '/settings'), true);
  assert.equal(requiresWorkspaceScrollReview(1440, '/login'), false);
  for (const width of visualViewports) {
    for (const theme of visualThemes) {
      assert.equal(requiresWorkspaceScrollReview(width, '/dashboard'), width === 1440,
        width + ' ' + theme.mode + '-' + theme.system);
    }
  }
  for (const phrase of [
    'requiresWorkspaceScrollReview(width, item.path)',
    "document.querySelector('.nfc-app-main .nfc-page-content')",
    "['auto', 'scroll'].includes(computed.overflowY)",
    "pane.scrollTop = maxScroll",
    "name + '-workspace-bottom.png'",
    "fullPage: false, animations: 'disabled'",
    'item.id === \'settings\'',
    'audit.workspaceScroll = scroll ? { ...scroll, captured } : null',
    'if (pane) pane.scrollTop = 0',
    'assert.deepEqual(failures, []',
  ]) assert.ok(browser.includes(phrase), 'Missing real desktop scrolled-content evidence: ' + phrase);
});


test('real download-verification detail screenshots use equal full-page depth for all four themes', () => {
  for (const theme of visualThemes) {
    for (const viewport of visualViewports)
      assert.equal(requiresFullPageReview(viewport), [390, 1440].includes(viewport),
        viewport + ' ' + theme.mode + '-' + theme.system);
  }
  for (const phrase of [
    'const detailFullPage = requiresExpandedInteractionFullPageReview(width)',
    "name + '-selected-detail.png'",
    'fullPage: detailFullPage',
    'detailPng.readUInt32BE(16)',
    'detailPng.readUInt32BE(20)',
    'audit.detailScreenshotPixels = detailPixels',
    'detailPixels.height < detailPixels.documentHeight - 2',
    'Selected-detail screenshot missing required full-page pixels:',
  ]) assert.ok(browser.includes(phrase), 'Missing real selected-detail parity guard: ' + phrase);
  assert.doesNotMatch(browser,
    /fullPage:\s*width\s*===\s*390\s*&&\s*theme\.mode\s*===\s*['"]light['"]/);
});

test('all phone source-editor screenshots expose the full expanded form in all themes', () => {
  for (const theme of visualThemes)
    assert.equal(requiresFullPageReview(390), true, theme.mode + '-' + theme.system);
  for (const phrase of [
    'const editorFullPage = requiresExpandedInteractionFullPageReview(width)',
    "name + '-source-editor.png'",
    'fullPage: editorFullPage',
    'editorPng.readUInt32BE(16)',
    'editorPng.readUInt32BE(20)',
    'audit.sourceEditorScreenshotPixels = editorPixels',
    'editorPixels.height < editorPixels.documentHeight - 2',
    'width <= 430 && editorPixels.documentHeight <= 900',
    'Source editor screenshot missing below-the-fold form pixels:',
  ]) assert.ok(browser.includes(phrase),
    'Missing mounted source-editor full-page screenshot evidence: ' + phrase);
});

test('full-depth interactive mobile review policy is independent of visual theme', () => {
  for (const width of visualViewports) for (const theme of visualThemes) {
    assert.equal(requiresExpandedInteractionFullPageReview(width),
      [360, 390, 430, 1440].includes(width),
      width + ' ' + theme.mode + '-' + theme.system);
  }
  assert.ok(browser.includes('width <= 430 && detailPixels.documentHeight <= 900'));
  assert.ok(browser.includes('width <= 430 && editorPixels.documentHeight <= 900'));
  assert.doesNotMatch(browser, /fullPage:\s*width\s*===\s*390\s*&&\s*theme\.mode/);
});

test('Stage 70 workflow list neutralizes actual v049 panel owner and dark mobile cards', () => {
  const css = readFileSync('src/styles/console-v2-workflow-list.css', 'utf8');
  const v049 = readFileSync('src/styles/v049-workspace.css', 'utf8');
  const entry = readFileSync('src/main.tsx', 'utf8');
  const root = css.slice(css.indexOf('.nfc-v2-workflow-list-page {'),
    css.indexOf("[data-theme='dark'] .nfc-v2-workflow-list-page"));
  const dark = css.slice(css.indexOf("[data-theme='dark'] .nfc-v2-workflow-list-page"),
    css.indexOf('.nfc-v2-workflow-archive-filter'));
  for (const prop of [
    '--nfc-wfl-bg: #ffffff', '--nfc-wfl-soft: #f5f5f3',
    '--nfc-wfl-text: #20201f', '--nfc-wfl-line: #eaeae7',
    '--nfc-wfl-accent: #262625', '--nfc-v49-surface: var(--nfc-wfl-bg)',
    '--nfc-w2-surface: var(--nfc-wfl-soft)',
  ]) assert.ok(root.includes(prop), 'Missing light workflow-neutral owner: ' + prop);
  for (const prop of [
    '--nfc-wfl-bg: #242422', '--nfc-wfl-soft: #2d2d2a',
    '--nfc-wfl-text: #f5f5f2', '--nfc-wfl-line: #383834',
    '--nfc-wfl-accent: #f5f5f2',
  ]) assert.ok(dark.includes(prop), 'Missing dark workflow-neutral owner: ' + prop);
  assert.ok(v049.includes('.nfc-workflows-page > .nfc-data-panel-dense'));
  assert.ok(v049.includes('background: var(--nfc-v49-surface) !important'));
  assert.ok(entry.indexOf("import './styles/v049-workspace.css';") <
    entry.indexOf("import './styles/console-v2-workflow-list.css';"));
  assert.match(css, /\.nfc-v2-workflow-mobile-list \.nfc-workflow-mobile-card \{ background: var\(--nfc-wfl-bg\)/);
  assert.ok(browser.includes("if (item.id === 'workflows')"));
  assert.ok(browser.includes("paint.body.background !== 'rgba(0, 0, 0, 0)'"));
  assert.ok(browser.includes('paint.list.background !== headColor'));
  assert.ok(v049.includes('var(--nfc-v49-surface) !important'));
  const w2 = readFileSync('src/styles/v056-right-workspace-v2.css', 'utf8');
  assert.ok(w2.includes('.nfc-app-main .nfc-mobile-record-list'));
  assert.ok(w2.includes('background: var(--nfc-w2-surface)'));

  for (const phrase of [
    "document.querySelector('.nfc-v2-workflow-list-page')",
    "page?.querySelector('.nfc-data-panel-dense')",
    "panel?.querySelector('.nfc-data-panel-body')",
    "page?.querySelector('.nfc-v2-workflow-mobile-list')",
    "list?.querySelector('.nfc-workflow-mobile-card')",
    "page?.querySelector('.nfc-v2-workflow-table th')",
    'audit.workflowListNeutralPaint = { ...paint, mobile',
    'Workflow list inherited non-neutral rendered surface:',
  ]) assert.ok(browser.includes(phrase), 'Missing mounted-theme guard: ' + phrase);
});

test('Stage 70 Plan Detail lifecycle/action/mobile ledger use v2.1 neutral paint', () => {
  const css = readFileSync('src/styles/console-v2-plan-detail.css', 'utf8');
  const legacy = readFileSync('src/styles/v056-right-workspace-v2.css', 'utf8');
  const entry = readFileSync('src/main.tsx', 'utf8');
  const browser = readFileSync('scripts/browser-full-route-visual.mjs', 'utf8');
  const root = css.slice(css.indexOf('.nfc-plan-detail-page {'),
    css.indexOf('.nfc-v2-plan-load'));
  assert.ok(root.includes('--nfc-w2-surface:var(--v2-paper)'),
    'Plan Detail must locally override v056 paper');
  assert.ok(root.includes('--nfc-w2-surface-soft:var(--v2-sidebar-surface)'),
    'Plan Detail must locally override v056 blue soft surface');
  assert.ok(legacy.includes('.nfc-plan-detail-page .nfc-lifecycle-strip'));
  assert.ok(legacy.includes('.nfc-app-main .nfc-mobile-record-list'));
  assert.ok(legacy.includes('.nfc-app-main .nfc-plan-detail-page .nfc-plan-action-surface'));
  assert.ok(entry.indexOf("import './styles/v056-right-workspace-v2.css';") <
    entry.indexOf("import './styles/console-v2-plan-detail.css';"),
    'Plan Detail neutral owner must load after historical v056 stylesheet');
  for (const phrase of [
    "if (item.id === 'plan-detail')",
    "document.querySelector('.nfc-plan-detail-page')",
    "page?.querySelector('.nfc-lifecycle-strip')",
    "page?.querySelector('.nfc-plan-action-surface')",
    "page?.querySelector('.nfc-mobile-record-list')",
    "list?.querySelector('.nfc-plan-item-mobile-card')",
    "audit.planDetailNeutralPaint = {",
    "detailPaint.lifecycle.background !== paper",
    "detailPaint.actions.background !== soft",
    "detailPaint.list.background !== paper",
    "!cardNeutralComposite",
    "!detailPaint.cardContained",
    "detailPaint.card.borderWidth === '0px'",
    "Plan Detail legacy navy lifecycle/action/ledger paint:",
  ]) assert.ok(browser.includes(phrase), 'Missing mounted Plan Detail paint guard: ' + phrase);
});

test('Stage 70 Plans mobile list uses neutral v2 paper instead of legacy v056 navy', () => {
  const css = readFileSync('src/styles/console-v2-phase2.css', 'utf8');
  const legacy = readFileSync('src/styles/v056-right-workspace-v2.css', 'utf8');
  const entry = readFileSync('src/main.tsx', 'utf8');
  const owner = css.slice(css.indexOf('.nfc-v2-shell .nfc-v2-plans-page {'),
    css.indexOf('.nfc-v2-plans-page > .nfc-page-header'));
  assert.ok(owner.includes('--nfc-w2-surface: var(--v2-paper)'),
    'Plans must remap the inherited mobile list paint only inside its own page');
  assert.ok(css.includes('.nfc-v2-plans-page .nfc-mobile-record-list'));
  assert.ok(css.includes('.nfc-v2-plans-page .nfc-plan-mobile-card'));
  assert.ok(legacy.includes('.nfc-app-main .nfc-mobile-record-list'));
  assert.ok(legacy.includes('background: var(--nfc-w2-surface)'));
  assert.ok(entry.indexOf("import './styles/v056-right-workspace-v2.css';") <
    entry.indexOf("import './styles/console-v2-phase2.css';"),
    'Plans local paper must be loaded after historical v056 styles');
  for (const phrase of [
    "if (item.id === 'plans' && width <= 767)",
    "document.querySelector('.nfc-v2-plans-page')",
    "page?.querySelector('.nfc-mobile-record-list')",
    "list?.querySelector('.nfc-plan-mobile-card')",
    "audit.planMobileNeutralPaint = { ...planPaint, required, cardShowsNeutralPaper }",
    "planPaint.list.background !== required",
    "planPaint.card.background === 'rgba(0, 0, 0, 0)'",
    "!cardShowsNeutralPaper",
    "planPaint.list.backgroundImage !== 'none'",
    "planPaint.card.backgroundImage !== 'none'",
    "!planPaint.cardContained",
    "planPaint.card.borderStyle !== 'solid'",
    "planPaint.card.borderWidth === '0px'",
    "Plans mobile inherited non-neutral navy list/card:",
  ]) assert.ok(browser.includes(phrase), 'Missing real Plans browser paint guard: ' + phrase);
});

test('Stage 70 Scans mobile history paints neutral list and card in real Chromium', () => {
  const css = readFileSync('src/styles/console-v2-scans.css', 'utf8');
  const v054 = readFileSync('src/styles/v054-premium-system.css', 'utf8');
  const v056 = readFileSync('src/styles/v056-right-workspace-v2.css', 'utf8');
  const entry = readFileSync('src/main.tsx', 'utf8');
  const root = css.slice(css.indexOf('.nfc-v2-shell .nfc-v2-scans-page {'),
    css.indexOf('.nfc-v2-scans-page > .nfc-page-header'));
  assert.ok(root.includes('--nfc-w2-surface: var(--v2-paper)'),
    'Scans must override inherited v056 navy only inside the owned page');
  assert.ok(css.includes('.nfc-v2-scans-page .nfc-scan-mobile-card {'),
    'Existing Scans card background rule must remain page-owned');
  assert.ok(css.includes('background: var(--v2-paper)'),
    'Scans card owner must retain neutral paper token');
  assert.ok(v056.includes('.nfc-app-main .nfc-mobile-record-list'));
  assert.ok(v056.includes('background: var(--nfc-w2-surface)'));
  assert.ok(v054.includes('.nfc-app-main .nfc-scan-mobile-card'));
  assert.ok(entry.indexOf("import './styles/v056-right-workspace-v2.css';") <
    entry.indexOf("import './styles/console-v2-scans.css';"),
    'Scans CSS must stay deterministically after the v056 historical owner');
  for (const phrase of [
    "if (item.id === 'scans' && width <= 767)",
    "document.querySelector('.nfc-v2-scans-page')",
    "page?.querySelector('.nfc-mobile-record-list')",
    "list?.querySelector('.nfc-scan-mobile-card')",
    "audit.scanMobileNeutralPaint = { ...scanPaint, required, cardShowsNeutralPaper }",
    "scanPaint.list.background !== required",
    "scanPaint.card.background === 'rgba(0, 0, 0, 0)'",
    "!cardShowsNeutralPaper",
    "scanPaint.list.backgroundImage !== 'none'",
    "scanPaint.card.backgroundImage !== 'none'",
    "!scanPaint.cardContained",
    "scanPaint.card.borderStyle !== 'solid'",
    "scanPaint.card.borderWidth === '0px'",
    "Scans mobile inherited non-neutral navy list/card:",
  ]) assert.ok(browser.includes(phrase), 'Missing mounted Scans paint guard: ' + phrase);
});

test('Stage 70 Indexes mobile list neutralizes v056 inherited blue surface', () => {
  const css = readFileSync('src/styles/console-v2-indexes.css', 'utf8');
  const v056 = readFileSync('src/styles/v056-right-workspace-v2.css', 'utf8');
  const entry = readFileSync('src/main.tsx', 'utf8');
  const browser = readFileSync('scripts/browser-full-route-visual.mjs', 'utf8');
  const root = css.slice(css.indexOf('.nfc-v2-indexes-page {'),
    css.indexOf('.nfc-v2-indexes-page > .nfc-page-header'));
  assert.ok(root.includes('--nfc-w2-surface:var(--nfc-idx-bg)'),
    'Indexes must own v056 mobile paint via local paper token');
  assert.ok(v056.includes('.nfc-app-main .nfc-index-mobile-card'));
  assert.ok(v056.includes('.nfc-app-main .nfc-mobile-record-list'));
  assert.ok(v056.includes('background: var(--nfc-w2-surface)'));
  assert.ok(entry.indexOf("import './styles/v056-right-workspace-v2.css';") <
    entry.indexOf("import './styles/console-v2-indexes.css';"),
    'Indexes owner must load after inherited v056 rules');
  for (const phrase of [
    "if (item.id === 'indexes' && width <= 767)",
    "document.querySelector('.nfc-v2-indexes-page')",
    "page?.querySelector('.nfc-v2-indexes-mobile')",
    "list?.querySelector('.nfc-index-mobile-card')",
    'audit.indexMobileNeutralPaint = { ...indexPaint, required: paperColor,',
    'Indexes mobile card/list inherited non-neutral painted surface:',
    "indexPaint.list.backgroundImage !== 'none'",
    "indexPaint.card.background === 'rgba(0, 0, 0, 0)'",
    "indexPaint.card.backgroundImage !== 'none'",
    "!indexPaint.cardContained",
    "indexPaint.card.borderWidth === '0px'",
  ]) assert.ok(browser.includes(phrase), 'Missing computed paint guard: ' + phrase);
});

test('expanded interaction full-page capture retries a short image without relaxing height', () => {
  const start = browser.indexOf("const detailFullPage = requiresExpandedInteractionFullPageReview(width)");
  const end = browser.indexOf('audit.detailScreenshotPixels = detailPixels;', start);
  assert.ok(start > 0 && end > start);
  const excerpt = browser.slice(start, end);
  for (const phrase of [
    'captureAttempt <= 3',
    'requestAnimationFrame(() => requestAnimationFrame(resolve))',
    "detailPng.readUInt32BE(20)",
    "document.documentElement.scrollHeight",
    'detailPixels.height >= detailPixels.documentHeight - 2',
  ]) assert.ok(excerpt.includes(phrase), 'Missing fail-closed recapture: ' + phrase);
  assert.ok(browser.includes('detailPixels.height < detailPixels.documentHeight - 2'),
    'Final image must still fail when it truncates any page content');
});
