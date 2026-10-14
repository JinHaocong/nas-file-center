/**
 * Real Chromium validation: Tasks drawer -> nested delete confirmation, and
 * terminal-status history cleanup. All API requests are mocked READ ONLY.
 * No request can reach a NAS; writes are rejected even inside the fixture.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:4180';
const OUT = resolve(process.cwd(), 'artifacts/browser-task-overlay');
const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
const THEMES = [
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
];
const task = {
  id: 42, job_type: 'fclones-scan', status: 'completed',
  capabilities: { supports_pause: false, supports_resume: false,
    supports_cancel: false, supports_retry: false },
  progress: { current: 12, total: 12, percent: 100, message: null },
  created_at: '2026-10-12T09:00:00+08:00',
  started_at: '2026-10-12T09:01:00+08:00',
  finished_at: '2026-10-12T09:03:00+08:00',
  heartbeat_at: '2026-10-12T09:02:00+08:00',
  error: null, error_code: null, retry_of: null,
  checkpoint: {}, payload: {},
};
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js',
  'preview', '--host', '127.0.0.1', '--port', '4180', '--strictPort'],
{ cwd: process.cwd(), stdio: 'ignore' });
let browser;
let completed = 0;

async function ready() {
  for (let i = 0; i < 100; i += 1) {
    if (server.exitCode !== null) throw Error('Vite preview exited');
    try { if ((await fetch(BASE_URL + '/tasks')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Vite preview was not ready');
}
function fixture(url) {
  const path = new URL(url).pathname;
  if (path === '/api/auth/me') {
    return { id: 1, username: 'visual-read-only-admin', role: 'admin', is_admin: true };
  }
  if (path === '/api/tasks') return { items: [task], total: 1, page: 1, page_size: 50 };
  if (path === '/api/tasks/42') return task;
  if (path === '/api/tasks/42/logs') return { items: [], total: 0, page: 1, page_size: 50 };
  if (path === '/api/tasks/worker') return {
    status: 'offline', worker_id: null, started_at: null,
    heartbeat_at: null, heartbeat_age_seconds: null,
  };
  return { items: [], total: 0, safe_mode: true };
}
async function inspect(page, theme, width, mode) {
  return page.evaluate(({ theme, width, mode }) => {
    const read = selector => {
      const node = document.querySelector(selector);
      if (!node) throw Error('Missing actual Radix DOM element: ' + selector);
      const style = getComputedStyle(node);
      const b = node.getBoundingClientRect();
      return {
        z: Number(style.zIndex), background: style.backgroundColor,
        filter: style.backdropFilter, webkitFilter: style.webkitBackdropFilter,
        rect: { left: b.left, right: b.right, top: b.top, bottom: b.bottom },
      };
    };
    const expected = theme === 'dark' ? 'rgb(36, 36, 34)' : 'rgb(255, 255, 255)';
    const rows = mode === 'nested' ? [
      ['sheet overlay', '.nfc-v2-sheet-overlay', 1100, false],
      ['sheet dialog', '.nfc-v2-sheet.nfc-overlay-drawer', 1101, true],
      ['confirm overlay', '.nfc-v2-confirm-overlay', 1300, false],
      ['confirm dialog', '.nfc-v2-confirm-dialog', 1301, true],
    ] : [
      ['history overlay', '.nfc-v2-dialog-overlay', 1100, false],
      ['history dialog', '.nfc-v2-history-dialog', 1101, true],
    ];
    const errors = [];
    const check = (valid, why) => { if (!valid) errors.push(why); };
    check(document.documentElement.dataset.theme === theme, 'Wrong effective theme');
    for (const [name, selector, z, content] of rows) {
      const x = read(selector);
      check(x.z === z, name + ' z-index ' + x.z + ' expected ' + z);
      if (content) {
        check(x.background === expected, name + ' surface ' + x.background);
        check(x.rect.left >= -2 && x.rect.right <= width + 2,
          name + ' horizontal overflow ' + JSON.stringify(x.rect));
        check(x.rect.top >= -2 && x.rect.bottom <= innerHeight + 2,
          name + ' vertical overflow ' + JSON.stringify(x.rect));
      } else {
        check(x.filter === 'none' &&
          (x.webkitFilter === undefined || x.webkitFilter === 'none'),
          name + ' backdrop is not dim-only');
      }
    }
    const element = document.elementFromPoint(width / 2, innerHeight / 2);
    const target = mode === 'nested' ? '.nfc-v2-confirm-dialog' : '.nfc-v2-history-dialog';
    check(Boolean(element?.closest(target)), 'Top-most dialog does not receive pointer hit');
    return errors;
  }, { theme, width, mode });
}

try {
  await ready();
  mkdirSync(OUT, { recursive: true });
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  for (const width of WIDTHS) {
    for (const theme of THEMES) {
      const context = await browser.newContext({
        viewport: { width, height: 900 }, colorScheme: theme.system,
        reducedMotion: 'reduce',
      });
      await context.addInitScript(mode => {
        localStorage.setItem('nfc_theme_mode', mode);
      }, theme.mode);
      const page = await context.newPage();
      const writes = [];
      await page.route('**/api/**', async route => {
        const request = route.request();
        if (request.method() !== 'GET') {
          writes.push(request.method() + ' ' + request.url());
          await route.fulfill({ status: 405, contentType: 'application/json',
            body: JSON.stringify({ detail: 'READ_ONLY_VISUAL_FIXTURE' }) });
          return;
        }
        await route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify(fixture(request.url())) });
      });
      const label = theme.mode + '-' + theme.system + '-' + width;
      try {
        await page.goto(BASE_URL + '/tasks', { waitUntil: 'domcontentloaded' });
        await page.getByRole('button', { name: '详情' }).first().click({ timeout: 15000 });
        const sheet = page.locator('.nfc-v2-sheet.nfc-overlay-drawer');
        await sheet.waitFor({ state: 'visible' });
        const deleteLauncher = sheet.getByRole('button', { name: '删除任务 #42' });
        await deleteLauncher.click();
        const confirm = page.locator('.nfc-v2-confirm-dialog');
        await confirm.waitFor({ state: 'visible' });
        const nestedErrors = await inspect(page, theme.effective, width, 'nested');
        assert.deepEqual(nestedErrors, [], 'Nested ' + label + ': ' + nestedErrors.join(', '));
        await page.screenshot({ path: resolve(OUT, 'nested-' + label + '.png') });
        await page.keyboard.press('Escape');
        await confirm.waitFor({ state: 'hidden' });
        await sheet.waitFor({ state: 'visible' });
        const launcherFocused = () => document.activeElement?.getAttribute('aria-label') ===
          '删除任务 #42' && Boolean(document.activeElement.closest('.nfc-v2-sheet'));
        await page.waitForFunction(launcherFocused);
        // A restored keyboard target must reopen the same nested confirmation.
        await page.keyboard.press('Enter');
        await confirm.waitFor({ state: 'visible' });
        await confirm.getByRole('button', { name: '取消' }).click();
        await confirm.waitFor({ state: 'hidden' });
        await page.waitForFunction(launcherFocused);
        await page.getByRole('button', { name: '关闭详情抽屉' }).click();
        await sheet.waitFor({ state: 'hidden' });
        console.log('[TASK BROWSER NESTED PASS] ' + label);

        await page.getByRole('button', { name: '清理历史' }).click();
        const history = page.locator('.nfc-v2-history-dialog');
        await history.waitFor({ state: 'visible' });
        const historyErrors = await inspect(page, theme.effective, width, 'history');
        assert.deepEqual(historyErrors, [], 'History ' + label + ': ' + historyErrors.join(', '));
        const choices = history.locator('.nfc-v2-history-statuses input[type="checkbox"]');
        assert.equal(await choices.count(), 3, 'Only three terminal statuses are selectable');
        for (let i = 0; i < 3; i += 1) await choices.nth(i).uncheck();
        const destructive = history.getByRole('button', { name: '确认清理' });
        assert.equal(await destructive.isDisabled(), true, 'No selection must disable deletion');
        await choices.first().check();
        assert.equal(await destructive.isEnabled(), true);
        await page.screenshot({ path: resolve(OUT, 'history-' + label + '.png') });
        await page.keyboard.press('Escape');
        await history.waitFor({ state: 'hidden' });
        assert.deepEqual(writes, [], 'Browser must not submit any mutating API request');
        completed += 1;
        console.log('[TASK BROWSER HISTORY PASS] ' + label);
      } catch (error) {
        console.error('[TASK BROWSER FAIL] ' + label, error);
        await page.screenshot({ path: resolve(OUT, 'failure-' + label + '.png') }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(completed, 32);
  console.log('[TASK BROWSER] 32/32 theme-viewport cases, 64 actual dialog screenshots; read-only synthetic APIs.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
