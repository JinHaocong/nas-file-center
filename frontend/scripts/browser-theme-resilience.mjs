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

  await runCase('canonical shared text contrast: 8 widths × 4 light/dark/system themes', async () => {
    const widths = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
    const themes = [
      { mode: 'light', system: 'dark', effective: 'light' },
      { mode: 'dark', system: 'light', effective: 'dark' },
      { mode: 'system', system: 'light', effective: 'light' },
      { mode: 'system', system: 'dark', effective: 'dark' },
    ];
    const luminance = hex => {
      const channels = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
        .map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
      return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
    };
    const contrast = (a, b) => {
      const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
      return (high + 0.05) / (low + 0.05);
    };
    let validated = 0;
    for (const width of widths) for (const theme of themes) {
      const context = await browser.newContext({
        viewport: { width, height: 900 },
        colorScheme: theme.system, reducedMotion: 'reduce',
      });
      const external = [];
      try {
        await context.route('**/*', async route => {
          if (new URL(route.request().url()).origin !== BASE) {
            external.push(route.request().url());
            await route.abort();
          } else {
            await route.continue();
          }
        });
        await fixture(context);
        await context.addInitScript(mode => localStorage.setItem('nfc_theme_mode', mode),
          theme.mode);
        const page = await context.newPage();
        await visit(page);
        await expectTheme(page, theme.mode, theme.effective);
        const colors = await page.evaluate(() => {
          const style = getComputedStyle(document.documentElement);
          const names = ['--nfc-canvas', '--nfc-surface-1', '--nfc-surface-2',
            '--nfc-surface-raised', '--nfc-nav-surface', '--nfc-accent-soft'];
          const values = Object.fromEntries(names.map(name =>
            [name, style.getPropertyValue(name).trim().toLowerCase()]));
          const probe = document.createElement('span');
          probe.className = 'nfc-page-eyebrow';
          probe.textContent = 'Read-only native control contrast fixture';
          document.body.appendChild(probe);
          const probeColor = getComputedStyle(probe).color;
          probe.remove();
          return { subtle: style.getPropertyValue('--nfc-text-subtle').trim().toLowerCase(),
            values, probeColor };
        });
        assert.match(colors.subtle, /^#[0-9a-f]{6}$/,
          theme.mode + '/' + width + ' must expose a concrete theme token');
        const rgb = colors.probeColor.match(/^rgb\\((\\d+), (\\d+), (\\d+)\\)$/);
        assert.ok(rgb, theme.mode + '/' + width + ' native label color not solid RGB');
        const computedHex = '#' + rgb.slice(1).map(v => Number(v).toString(16).padStart(2, '0')).join('');
        assert.equal(computedHex, colors.subtle,
          theme.mode + '/' + width + ' native page eyebrow uses canonical subtle token');
        for (const [name, background] of Object.entries(colors.values)) {
          assert.match(background, /^#[0-9a-f]{6}$/);
          const actual = contrast(colors.subtle, background);
          assert.ok(actual >= 4.5,
            theme.mode + '/' + theme.effective + '/' + width + ' ' + name +
            ' actual computed contrast ' + actual.toFixed(2) + ':1 < 4.5:1');
        }
        assert.deepEqual(external, [], 'No cross-origin requests permitted in contrast fixture');
        validated += 1;
      } finally {
        await context.close();
      }
    }
    assert.equal(validated, 32);
    console.log('[THEME CONTRAST] 32/32 computed CSS, 6 surfaces each, 0 external requests.');
  });

  assert.deepEqual(rejectedWrites, [], 'Browser fixture must not make any mutating API calls');
  assert.equal(completed, 4);
  console.log('[THEME BROWSER] 4/4 real Chromium groups passed; read-only synthetic APIs.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
