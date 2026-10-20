import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const scan = read('src/styles/console-v2-scan-create.css');
const directory = read('src/styles/console-v2-directory-modal.css');
const shell = read('src/styles/console-v2.css');
const browser = read('scripts/browser-overlay-smoke.mjs');

describe('Pure White Stage 5A — actual browser portal acceptance contracts', () => {
  test('ScanCreate Portal owns neutral light/dark colors and legible primary action', () => {
    for (const marker of [
      '--nfc-form-paper: #ffffff', '--nfc-form-paper: #242422',
      '--nfc-form-accent: #252525', '--nfc-form-accent: #e9e9e6',
      '--nfc-form-primary-text: #ffffff', '--nfc-form-primary-text: #20201f',
      'color: var(--nfc-form-primary-text)',
      'accent-color: var(--nfc-form-accent)',
      'nfc-v2-scan-create-overlay { z-index: 1190',
      'z-index: 1191',
      'max-height: calc(100dvh - 16px)',
    ]) assert.ok(scan.includes(marker), marker);
    assert.doesNotMatch(scan, /#2878ef|#83b5ff|#1a2434|#18263a|rgba\(4,24,50/);
    assert.ok(scan.includes('.nfc-v2-scan-create-error'));
    assert.ok(scan.includes('.nfc-v2-scan-create-note svg'));
  });

  test('nested DirectoryPicker Portal stays above Scan and has contrasting dark primary', () => {
    for (const marker of [
      '--nfc-dialog-paper: #ffffff', '--nfc-dialog-paper: #242422',
      '--nfc-dialog-accent: #252525', '--nfc-dialog-accent: #e9e9e6',
      '--nfc-dialog-primary-text: #ffffff', '--nfc-dialog-primary-text: #20201f',
      'color: var(--nfc-dialog-primary-text)',
      '.nfc-v2-directory-overlay { z-index: 1200',
      'z-index: 1201',
      '.nfc-v2-directory-close:focus-visible',
      'min-width: 44px; min-height: 44px',
    ]) assert.ok(directory.includes(marker), marker);
    assert.doesNotMatch(directory, /#2878ef|#83b5ff|#1a2434|#18263a|#e0e7f0/);
    assert.ok(directory.includes('.nfc-v2-directory-error'));
    assert.ok(directory.includes('.nfc-console-button-danger'));
  });

  test('shared scrim has no blur in either theme, including CSS prefixed property', () => {
    assert.match(shell, /\.nfc-v2-dialog-overlay\s*\{[^}]*backdrop-filter:\s*none;[^}]*-webkit-backdrop-filter:\s*none;/);
    assert.match(shell, /\[data-theme='dark'\] \.nfc-v2-dialog-overlay\s*\{[^}]*background:\s*rgba\(0,\s*0,\s*0,\s*\.64\)/);
    assert.match(shell, /\.nfc-v2-dialog::backdrop\s*\{[^}]*backdrop-filter:\s*none;/);
    const scanSource = read('src/components/scans/ScanCreateModal.tsx');
    const picker = read('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    for (const src of [scanSource, picker]) {
      assert.ok(src.includes('<Dialog.Portal>'));
      assert.ok(src.includes('<Dialog.Overlay'));
      assert.ok(src.includes('<Dialog.Content'));
      assert.ok(src.includes('onEscapeKeyDown'));
      assert.ok(src.includes('onPointerDownOutside'));
    }
  });

  test('Chromium smoke tests actual Vite/React output, not a static HTML imitation', () => {
    for (const marker of [
      "import { chromium } from 'playwright'",
      "await page.goto(BASE_URL + '/scans'",
      "await page.route('**/*'",
      "request.method() !== 'GET'",
      "url.origin !== BASE_URL",
      "await route.abort('blockedbyclient')",
      "assert.deepEqual(outbound, []",
      "await page.locator('.nfc-v2-directory-dialog').waitFor",
      "await page.keyboard.press('Escape')",
      "await page.screenshot",
      "WIDTHS.length * MODES.length",
      "'--no-sandbox'",
    ]) assert.ok(browser.includes(marker), marker);
    assert.ok(browser.includes('360, 390, 430, 768, 1024, 1280, 1440, 1920'));
    assert.ok(browser.includes("mode: 'system', system: 'dark'"));
    assert.ok(browser.includes("mode: 'system', system: 'light'"));
    assert.doesNotMatch(browser, /https:\/\/[^'\s]*nas|POST.*\/api\/scans/);
  });

  test('selected DirectoryPicker checkbox keyboard ring is composited against real tinted row', () => {
    // Keep the original 32-case/192-text evidence and add independent
    // keyboard-visible focus checks, not a theme-token-only approximation.
    assert.ok(directory.includes('.nfc-v2-directory-dialog input:focus-visible {'));
    assert.ok(directory.includes('outline: 2px solid var(--nfc-dialog-accent); outline-offset: 2px;'));
    for (const phrase of [
      "const checkbox = row.getByRole('checkbox', { name: '选择目录 Long-Test-Folder' })",
      "await page.keyboard.press('Tab')",
      "document.activeElement !== checkbox",
      "checkbox.matches(':focus-visible')",
      "focusStyle.outlineWidth",
      "focusStyle.outlineOffset",
      "layersFor(checkbox.parentElement)",
      "computedContrastRatio(snapshot.focus.foreground, snapshot.focus.background)",
      "focusRatio >= 3",
      "c.focus.contrast >= 3",
      "'directory-selected-focus-' + label + '.png'",
      "keyboardFocusPairs: compositedPaintCases.length",
    ]) assert.ok(browser.includes(phrase), 'Missing real keyboard/paint guard: ' + phrase);
    assert.ok(browser.includes('c.pairs.length === 6 && c.pairs.every(pair => pair.contrast >= 4.5)'));
    assert.ok(browser.includes("url.origin !== BASE_URL"));
    assert.ok(browser.includes("request.method() !== 'GET'"));
  });

  test('live directory GET error, retry and keyboard focus are contrast-checked in Chromium', () => {
    const picker = read('src/components/DirectoryPicker/DirectoryPickerModal.tsx');
    const api = read('src/api/filesystem.ts');
    for (const marker of [
      "className=\\\"nfc-v2-directory-error\\\" role=\\\"alert\\\"",
      'void refetchDir();',
      "type=\\\"search\\\" aria-label=\\\"搜索子目录\\\"",
    ]) assert.ok(picker.includes(marker), 'Lost actual error/retry semantics: ' + marker);
    assert.ok(api.includes('/api/filesystem/list?'));
    assert.ok(directory.includes('.nfc-v2-directory-dialog .nfc-v2-directory-error {'));
    assert.ok(directory.includes("[data-theme='dark'] .nfc-v2-directory-dialog .nfc-v2-directory-error {"));
    for (const marker of [
      'const directoryErrorCases = []',
      "simulateDirectoryFailure && url.pathname === '/api/filesystem/list'",
      "status: 503",
      "if ([390, 1440].includes(width))",
      "await alert.waitFor({ state: 'visible', timeout: 20000 })",
      "await page.keyboard.press('Tab')",
      "node === document.activeElement",
      "retryStyle.outlineWidth < 2",
      "retryStyle.outlineOffset < 1",
      "computedContrastRatio(style.ink, style.paper)",
      "computedContrastRatio(details.retry.outline, surface)",
      "await retry.click()",
      "await alert.waitFor({ state: 'hidden', timeout: 10000 })",
      "await checkbox.isChecked()",
      "directory-error-retry-contrast-audit.json",
      "directoryErrorCases.length, 2 * MODES.length",
    ]) assert.ok(browser.includes(marker), 'Missing executable error/retry gate: ' + marker);
    assert.ok(browser.includes("request.method() !== 'GET'"));
    assert.ok(browser.includes("url.origin !== BASE_URL"));
    assert.ok(browser.includes("assert.deepEqual(deniedMethods, []"));
    assert.ok(browser.includes("assert.deepEqual(outbound, []"));
  });

  test('CI checks the exact candidate and uploads screenshot evidence without touching NAS', () => {
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    for (const marker of [
      'browser-overlay-smoke:', 'Checkout exact candidate HEAD',
      'Verify candidate identity',
      'playwright@1.56.1', 'npx playwright install chromium',
      'Run read-only Chromium overlay matrix', 'Upload visual evidence',
      'frontend/artifacts/browser-overlay/*.png',
    ]) assert.ok(workflow.includes(marker), marker);
    const entry = read('src/main.tsx');
    for (const marker of [
      "import './styles/console-v2-scan-create.css'",
      "import './styles/console-v2-directory-modal.css'",
    ]) assert.ok(entry.includes(marker), marker);
  });
});
