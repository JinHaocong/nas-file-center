/**
 * Stage 5E-AG/AI: real React/Chromium archive selection and 8-width regression.
 * Synthetic read-only GET fixtures only: never send a recovery check/start,
 * access a NAS, or treat these screenshots as NAS acceptance.
 * Run after npm run build with playwright@1.56.1 and Chromium installed.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';
import { visualAdminFixture, visualSafeSettingsFixture,
  visualArchiveDirectoryFixture, visualViewports, visualThemes } from './visual-fixtures.mjs';

const ROOT = process.cwd();
const PORT = 4198;
const BASE = 'http://127.0.0.1:' + PORT;
const OUTPUT = resolve(ROOT, 'artifacts/browser-archive-recovery-selection');
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview',
  '--host', '127.0.0.1', '--port', String(PORT), '--strictPort',
], { cwd: ROOT, stdio: 'ignore' });

let browser;
let passed = 0;

async function ready() {
  for (let i = 0; i < 100; i += 1) {
    if (server.exitCode !== null) throw new Error('Vite preview exited early');
    try {
      const response = await fetch(BASE + '/login');
      if (response.ok) return;
    } catch { /* startup */ }
    await sleep(200);
  }
  throw new Error('Vite preview did not become ready');
}

function fixture(url) {
  if (url.pathname === '/api/auth/me') {
    return visualAdminFixture('archive-selection-readonly-fixture');
  }
  if (url.pathname === '/api/settings') return visualSafeSettingsFixture();
  if (url.pathname === '/api/filesystem/list') {
    return visualArchiveDirectoryFixture(url.searchParams.get('path'), 'demo.zip');
  }
  if (url.pathname === '/api/filesystem/favorites' ||
      url.pathname === '/api/filesystem/recent') return { items: [] };
  return { ...visualSafeSettingsFixture(), items: [], total: 0, status: 'ok' };
}

try {
  await ready();
  mkdirSync(OUTPUT, { recursive: true });
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  // The consolidated visual acceptance baseline is 8 widths × 4 themes.
  for (const width of visualViewports) {
    for (const theme of visualThemes) {
      const context = await browser.newContext({
        viewport: { width, height: 900 },
        colorScheme: theme.system,
        reducedMotion: 'reduce',
      });
      await context.addInitScript(mode => {
        localStorage.setItem('nfc_theme_mode', mode);
      }, theme.mode);
      const page = await context.newPage();
      const blockedWrites = [];
      const outbound = [];
      await page.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin !== BASE) {
          outbound.push(request.url());
          await route.abort();
          return;
        }
        if (url.pathname.startsWith('/api/')) {
          if (request.method() !== 'GET') {
            blockedWrites.push(request.method() + ' ' + url.pathname);
            await route.fulfill({ status: 405, contentType: 'application/json',
              body: JSON.stringify({ error: 'READ_ONLY_BROWSER_FIXTURE' }) });
            return;
          }
          await route.fulfill({ status: 200, contentType: 'application/json',
            body: JSON.stringify(fixture(url)) });
          return;
        }
        await route.continue();
      });
      const label = (theme.mode === 'system' ? 'system-' + theme.effective : theme.mode) + '-' + width;
      try {
        await page.goto(BASE + '/archive-recovery', { waitUntil: 'domcontentloaded' });
        const file = page.locator('.nfc-archive-recovery-file').first();
        await file.waitFor({ state: 'visible', timeout: 20000 });
        await file.click();
        assert.equal(await page.locator('#recovery-source').inputValue(), '/data/demo.zip', label);
        await page.locator('#recovery-password').fill('synthetic-secret-never-sent');

        // Change the actual controlled DirectoryPicker, not internal React state.
        await page.getByRole('textbox', { name: '目录路径' }).fill('/data/other');
        assert.equal(await page.locator('#recovery-source').inputValue(), '', label);
        assert.equal(await page.locator('#recovery-password').inputValue(), '', label);
        assert.equal(await page.getByRole('button', { name: '开始恢复' }).isDisabled(), true, label);
        assert.equal(await page.locator('.nfc-archive-recovery-check-result').count(), 0, label);
        await page.screenshot({ path: resolve(OUTPUT, label + '.png') });
        assert.deepEqual(blockedWrites, [], label + ': blocked write requests');
        assert.deepEqual(outbound, [], label + ': off-origin requests');
        passed += 1;
        console.log('[ARCHIVE SELECTION PASS] ' + label);
      } catch (error) {
        await page.screenshot({ path: resolve(OUTPUT, label + '-failure.png') }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(passed, 32);
  console.log('[ARCHIVE SELECTION] 32/32 real Chromium cases; synthetic GET fixtures only.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
