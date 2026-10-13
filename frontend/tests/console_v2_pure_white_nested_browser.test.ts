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
      "await page.goto(URL + '/scans'",
      "await page.route('**/api/**'",
      "request.method() !== 'GET'",
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
