/**
 * Chromium smoke checks for the real React/Radix ScanCreate -> DirectoryPicker stack.
 * API requests are intercepted with read-only synthetic data: NEVER contact a NAS.
 * This is computed-style evidence, not production NAS / complete visual acceptance.
 *
 * Run after npm run build:
 *   npm install --no-save --package-lock=false playwright@1.56.1
 *   npx playwright install chromium
 *   node scripts/browser-overlay-smoke.mjs
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const ROOT = process.cwd();
const PORT = 4179;
const URL = 'http://127.0.0.1:' + PORT;
const OUTPUT = resolve(ROOT, 'artifacts/browser-overlay');
const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
const MODES = [
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
];
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview',
  '--host', '127.0.0.1', '--port', String(PORT), '--strictPort',
], { cwd: ROOT, stdio: 'ignore' });

let browser;
let completed = 0;

async function ready() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null) throw new Error('Vite preview exited early');
    try {
      const response = await fetch(URL + '/login');
      if (response.ok) return;
    } catch { /* startup */ }
    await sleep(200);
  }
  throw new Error('Vite preview did not become ready');
}

function mockResponse(url) {
  const pathname = new URL(url).pathname;
  if (pathname === '/api/auth/me') {
    return { id: 1, username: 'visual-fixture-admin', role: 'admin', is_admin: true };
  }
  if (pathname === '/api/filesystem/list') {
    return {
      path: '/visual-fixture', parent: null, allowed_roots: ['/visual-fixture'],
      items: [{ name: 'Long-Test-Folder', path: '/visual-fixture/Long-Test-Folder',
        is_dir: true, is_directory: true }], total: 1, page: 1, page_size: 100,
    };
  }
  if (pathname === '/api/filesystem/favorites' || pathname === '/api/filesystem/recent') {
    return { items: [] };
  }
  if (pathname === '/api/scans') return { items: [], total: 0, page: 1, page_size: 20 };
  return { items: [], total: 0, status: 'ok', safe_mode: true };
}

async function inspect(page, theme, width) {
  return page.evaluate(({ theme, width }) => {
    const css = selector => {
      const element = document.querySelector(selector);
      if (!element) throw new Error('Missing actual React/Radix DOM: ' + selector);
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      return {
        z: Number(style.zIndex), filter: style.backdropFilter,
        webkitFilter: style.webkitBackdropFilter,
        background: style.backgroundColor, color: style.color,
        rect: { left: box.left, right: box.right, top: box.top, bottom: box.bottom },
      };
    };
    const scan = css('.nfc-v2-scan-create-modal');
    const directory = css('.nfc-v2-directory-dialog');
    const scanOverlay = css('.nfc-v2-scan-create-overlay');
    const dirOverlay = css('.nfc-v2-directory-overlay');
    const primary = css('.nfc-v2-directory-dialog .nfc-console-button-primary');
    const expected = theme === 'dark' ? 'rgb(36, 36, 34)' : 'rgb(255, 255, 255)';
    const expectedButtonText = theme === 'dark' ? 'rgb(32, 32, 31)' : 'rgb(255, 255, 255)';
    const errors = [];
    const check = (pass, message) => { if (!pass) errors.push(message); };
    check(document.documentElement.dataset.theme === theme,
      'document theme disagrees with system/theme choice');
    for (const [name, overlay] of [['scan', scanOverlay], ['directory', dirOverlay]]) {
      check(overlay.filter === 'none' && overlay.webkitFilter === 'none',
        name + ' scrim has blur/filter: ' + overlay.filter + ' / ' + overlay.webkitFilter);
    }
    check(scan.background === expected, 'Scan modal background: ' + scan.background);
    check(directory.background === expected, 'Directory modal background: ' + directory.background);
    check(primary.color === expectedButtonText, 'Directory primary text: ' + primary.color);
    check(scanOverlay.z === 1190 && scan.z === 1191,
      'Scan overlay/dialog z pair: ' + scanOverlay.z + '/' + scan.z);
    check(dirOverlay.z === 1200 && directory.z === 1201,
      'Directory overlay/dialog z pair: ' + dirOverlay.z + '/' + directory.z);
    check(directory.z > scan.z && dirOverlay.z > scan.z,
      'nested DirectoryPicker must be above parent content');
    for (const [name, box] of [['scan', scan.rect], ['directory', directory.rect]]) {
      check(box.left >= -2 && box.right <= width + 2,
        name + ' dialog horizontal overflow: ' + JSON.stringify(box));
      check(box.top >= -2 && box.bottom <= innerHeight + 2,
        name + ' dialog vertical overflow: ' + JSON.stringify(box));
    }
    const center = document.elementFromPoint(width / 2, innerHeight / 2);
    check(Boolean(center?.closest('.nfc-v2-directory-dialog')),
      'DirectoryPicker should receive pointer hits above both scrims');
    return { errors, scan, directory, scanOverlay, dirOverlay, primary };
  }, { theme, width });
}

try {
  await ready();
  mkdirSync(OUTPUT, { recursive: true });
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });

  for (const width of WIDTHS) {
    for (const visual of MODES) {
      const context = await browser.newContext({
        viewport: { width, height: 900 },
        colorScheme: visual.system,
        reducedMotion: 'reduce',
      });
      await context.addInitScript(mode => {
        localStorage.setItem('nfc_theme_mode', mode);
      }, visual.mode);
      const page = await context.newPage();
      const deniedMethods = [];
      await page.route('**/api/**', async route => {
        const request = route.request();
        if (request.method() !== 'GET') {
          deniedMethods.push(request.method() + ' ' + request.url());
          await route.fulfill({ status: 405, contentType: 'application/json',
            body: JSON.stringify({ error: 'READ_ONLY_BROWSER_FIXTURE' }) });
          return;
        }
        await route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify(mockResponse(request.url())) });
      });
      const label = visual.mode + '-' + visual.system + '-' + width;
      try {
        await page.goto(URL + '/scans', { waitUntil: 'domcontentloaded' });
        await page.getByRole('button', { name: '新建扫描' }).first().click({ timeout: 15000 });
        await page.locator('.nfc-v2-scan-create-modal').waitFor({ state: 'visible' });
        await page.locator('.nfc-v2-scan-create-modal')
          .getByRole('button', { name: '选择目录' }).first().click();
        await page.locator('.nfc-v2-directory-dialog').waitFor({ state: 'visible' });
        const state = await inspect(page, visual.effective, width);
        assert.deepEqual(state.errors, [], label + '\n' + state.errors.join('\n'));
        await page.screenshot({ path: resolve(OUTPUT, label + '.png') });
        await page.keyboard.press('Escape');
        await page.locator('.nfc-v2-directory-dialog').waitFor({ state: 'hidden' });
        await page.locator('.nfc-v2-scan-create-modal').waitFor({ state: 'visible' });
        assert.deepEqual(deniedMethods, [], 'Browser fixture must not make mutating API requests');
        completed += 1;
        console.log('[BROWSER OVERLAY PASS] ' + label);
      } catch (error) {
        console.error('[BROWSER OVERLAY FAIL] ' + label, error);
        await page.screenshot({ path: resolve(OUTPUT, label + '-failure.png') }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(completed, WIDTHS.length * MODES.length);
  console.log('[BROWSER OVERLAY] ' + completed + '/' + (WIDTHS.length * MODES.length) +
    ' real Chromium cases passed; mocked read-only APIs, no NAS access.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
