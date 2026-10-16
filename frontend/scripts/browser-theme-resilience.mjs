/**
 * Stage 5E-AR — read-only real Chromium verification of Pure White ThemeProvider.
 * Only visits /login. Every /api/ request is intercepted; no NAS/production I/O.
 * Run after npm run build and playwright Chromium installation.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const ROOT = process.cwd();
const PORT = 4192;
const BASE = 'http://127.0.0.1:' + PORT;
const OUTPUT = resolve(ROOT, 'artifacts/browser-theme-resilience');
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview',
  '--host', '127.0.0.1', '--port', String(PORT), '--strictPort',
], { cwd: ROOT, stdio: 'ignore' });

let browser;
let completed = 0;
const rejectedWrites = [];

async function ready() {
  for (let i = 0; i < 100; i += 1) {
    if (server.exitCode !== null) throw Error('Vite preview exited before startup');
    try {
      const response = await fetch(BASE + '/login');
      if (response.ok) return;
    } catch { /* starting */ }
    await sleep(200);
  }
  throw Error('Vite preview did not become ready');
}

async function fixture(context) {
  await context.route('**/api/**', async route => {
    const req = route.request();
    if (req.method() !== 'GET') {
      rejectedWrites.push(req.method() + ' ' + req.url());
      await route.fulfill({ status: 405, contentType: 'application/json',
        body: JSON.stringify({ error: 'READ_ONLY_BROWSER_FIXTURE' }) });
      return;
    }
    // Keep the actual unauthenticated login interface visible. No real NAS.
    await route.fulfill({ status: 401, contentType: 'application/json',
      body: JSON.stringify({ message: 'synthetic unauthenticated fixture' }) });
  });
}

async function visit(page) {
  await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' });
  await page.locator('#nfc-login-theme-select').waitFor({ state: 'visible' });
}

async function expectTheme(page, mode, effective) {
  await page.waitForFunction(
    ({ mode, effective }) => {
      const select = document.querySelector('#nfc-login-theme-select');
      return select?.value === mode &&
        document.documentElement.dataset.theme === effective &&
        document.documentElement.style.colorScheme === effective;
    },
    { mode, effective },
    { timeout: 10000 },
  );
  assert.equal(await page.locator('#nfc-login-theme-select').inputValue(), mode);
  assert.equal(await page.locator('html').getAttribute('data-theme'), effective);
}

async function runCase(name, run) {
  try {
    await run();
    completed += 1;
    console.log('[THEME BROWSER PASS] ' + name);
  } catch (error) {
    console.error('[THEME BROWSER FAIL] ' + name, error);
    throw error;
  }
}

try {
  await ready();
  mkdirSync(OUTPUT, { recursive: true });
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });

  await runCase('cross-tab light/dark/system and OS scheme', async () => {
    const context = await browser.newContext({
      viewport: { width: 430, height: 900 }, colorScheme: 'light', reducedMotion: 'reduce',
    });
    try {
      await fixture(context);
      await context.addInitScript(() => localStorage.setItem('nfc_theme_mode', 'light'));
      const first = await context.newPage();
      const second = await context.newPage();
      await visit(first);
      await visit(second);
      await expectTheme(first, 'light', 'light');
      await expectTheme(second, 'light', 'light');

      await first.locator('#nfc-login-theme-select').selectOption('dark');
      await expectTheme(first, 'dark', 'dark');
      await expectTheme(second, 'dark', 'dark');

      await first.locator('#nfc-login-theme-select').selectOption('system');
      await expectTheme(first, 'system', 'light');
      await expectTheme(second, 'system', 'light');
      await first.emulateMedia({ colorScheme: 'dark' });
      await second.emulateMedia({ colorScheme: 'dark' });
      await expectTheme(first, 'system', 'dark');
      await expectTheme(second, 'system', 'dark');
      await first.emulateMedia({ colorScheme: 'light' });
      await second.emulateMedia({ colorScheme: 'light' });
      await expectTheme(first, 'system', 'light');
      await expectTheme(second, 'system', 'light');
    } finally {
      await context.close();
    }
  });

  await runCase('blocked matchMedia still permits explicit theme change', async () => {
    const context = await browser.newContext({
      viewport: { width: 390, height: 900 }, colorScheme: 'dark',
    });
    try {
      await fixture(context);
      await context.addInitScript(() => {
        Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => {
          throw new DOMException('system media query denied', 'SecurityError');
        } });
      });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await visit(page);
      await expectTheme(page, 'light', 'light');
      await page.locator('#nfc-login-theme-select').selectOption('dark');
      await expectTheme(page, 'dark', 'dark');
      assert.deepEqual(errors, [], 'matchMedia exceptions must not crash React');
    } finally {
      await context.close();
    }
  });

  await runCase('blocked localStorage still permits in-session theme changes', async () => {
    const context = await browser.newContext({
      viewport: { width: 360, height: 900 }, colorScheme: 'light',
    });
    try {
      await fixture(context);
      await context.addInitScript(() => {
        Object.defineProperty(window, 'localStorage', { configurable: true, get() {
          throw new DOMException('storage access denied', 'SecurityError');
        } });
      });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await visit(page);
      await expectTheme(page, 'light', 'light');
      await page.locator('#nfc-login-theme-select').selectOption('dark');
      await expectTheme(page, 'dark', 'dark');
      assert.deepEqual(errors, [], 'blocked localStorage must not crash React');
    } finally {
      await context.close();
    }
  });

  assert.deepEqual(rejectedWrites, [], 'Browser fixture must not make any mutating API calls');
  assert.equal(completed, 3);
  console.log('[THEME BROWSER] 3/3 real Chromium cases passed; read-only synthetic APIs.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
