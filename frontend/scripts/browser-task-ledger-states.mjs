/**
 * Pure White Stage 5E-E: real Tasks ledger, filter/pagination, long errors and
 * recoverable list failure. The only server is localhost Vite; API GETs are
 * synthetic and every mutation or off-origin request is rejected.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';
import { computedContrastRatio } from './computed-contrast.mjs';
import { visualAdminFixture, visualSafeSettingsFixture,
  visualViewports, visualThemes } from './visual-fixtures.mjs';

const BASE = 'http://127.0.0.1:4187';
const OUT = resolve(process.cwd(), 'artifacts/browser-task-ledger-states');
const WIDTHS = visualViewports; // 360, 390, 430, 768, 1024, 1280, 1440, 1920
const THEMES = visualThemes; // mode: 'system', system: 'dark', effective: 'dark'
const LONG_ERROR = 'FAIL_CLOSED_PATH_IDENTITY: ' +
  '/synthetic-nas/2026/Archived-Camera-Exports-Only/' +
  'ExtremelyLongFilenameWithoutNaturalBreaks'.repeat(18) +
  '/frozen-source-replaced-after-read; operator-review-required';
const timestamp = '2026-10-12T08:30:00Z';
function task(id) {
  const failed = id === 601;
  return {
    id, job_type: failed ? 'fclones-scan' : 'index-root',
    status: failed ? 'failed' : 'completed',
    created_at: timestamp, started_at: timestamp, finished_at: timestamp,
    heartbeat_at: timestamp, retry_of: null,
    capabilities: { supports_pause: false, supports_resume: false,
      supports_cancel: false, supports_retry: false },
    progress: { current: 100, total: 100, percent: 100, message: null },
    error_code: failed ? 'SOURCE_IDENTITY_CONFLICT' : null,
    error: failed ? LONG_ERROR : null,
    checkpoint: {}, payload: {},
  };
}
const all = Array.from({ length: 51 }, (_, i) => task(i + 601));
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js',
  'preview', '--host', '127.0.0.1', '--port', '4187', '--strictPort'],
{ cwd: process.cwd(), stdio: 'ignore' });
let browser;
let passed = 0;
const errorPaintCases = [];

async function ready() {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw Error('Vite preview exited');
    try { if ((await fetch(BASE + '/tasks')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Local Vite preview unavailable');
}
function fixture(url) {
  const path = url.pathname;
  if (path === '/api/auth/me') return visualAdminFixture('task-state-visual-fixture');
  if (path === '/api/tasks/worker') return {
    status: 'offline', worker_id: null, started_at: null,
    heartbeat_at: null, heartbeat_age_seconds: null,
  };
  if (path === '/api/settings') return visualSafeSettingsFixture();
  if (path === '/api/tasks/601') return all[0];
  if (path === '/api/tasks/601/logs') return {
    items: [], total: 0, page: 1, page_size: 50,
  };
  if (path === '/api/tasks') {
    const page = Number(url.searchParams.get('page') || 1);
    const size = Number(url.searchParams.get('page_size') || 50);
    const status = url.searchParams.get('status');
    const type = url.searchParams.get('job_type');
    const filtered = all.filter(item =>
      (!status || item.status === status) &&
      (!type || item.job_type === type));
    return { items: filtered.slice((page - 1) * size, page * size),
      total: filtered.length, page, page_size: size };
  }
  return { items: [], total: 0, page: 1, page_size: 50 };
}

async function assertBounds(page, theme, width, mode) {
  const violations = await page.evaluate(({ theme, width, mode }) => {
    const errors = [];
    const check = (ok, name) => { if (!ok) errors.push(name); };
    const inside = node => {
      if (!node) return false;
      const r = node.getBoundingClientRect();
      return r.width > 0 && r.left >= -2 && r.right <= width + 2;
    };
    check(document.documentElement.dataset.theme === theme, 'Wrong effective theme');
    check(inside(document.querySelector('.nfc-page-content')), 'Workspace overflow');
    check(inside(document.querySelector('.nfc-tasks-page')), 'Tasks root overflow');
    check(inside(document.querySelector('.nfc-v2-task-filter-bar')), 'Filter bar overflow');
    if (mode === 'drawer' || mode === 'drawer-expanded') {
      const overlay = document.querySelector('.nfc-v2-sheet-overlay');
      const sheet = document.querySelector('.nfc-task-detail-drawer');
      const error = sheet?.querySelector('.nfc-prewrap-error');
      check(Boolean(error?.textContent?.includes('FAIL_CLOSED_PATH_IDENTITY')),
        'Long error detail missing');
      check(inside(sheet), 'Task inspector exceeds viewport');
      check(inside(error), 'Long error exceeds viewport');
      const disclosure = sheet?.querySelector('.nfc-v2-task-error-details');
      const preview = sheet?.querySelector('.nfc-v2-task-error-preview');
      const alert = sheet?.querySelector('.nfc-v2-task-inline-alert[role="alert"]');
      const execution = sheet?.querySelector('.nfc-overlay-section');
      const alertRect = alert?.getBoundingClientRect();
      const executionRect = execution?.getBoundingClientRect();
      check(Boolean(disclosure && preview && alertRect && executionRect),
        'Error disclosure / execution section missing');
      check(Boolean(preview?.textContent?.includes('FAIL_CLOSED_PATH_IDENTITY')),
        'Diagnostic prefix missing from collapsed preview');
      if (mode === 'drawer') {
        check(Boolean(!disclosure?.open && alertRect && executionRect &&
          alertRect.height <= 210 && alertRect.bottom <= executionRect.top),
          'Compact error must leave Execution visible');
      } else {
        check(Boolean(disclosure?.open && disclosure.querySelector('p')?.textContent?.includes(
          'operator-review-required')), 'Full expanded diagnostic unavailable');
      }
      check(Number(getComputedStyle(overlay).zIndex) === 1100, 'Sheet overlay z-index');
      check(Number(getComputedStyle(sheet).zIndex) === 1101, 'Sheet content z-index');
      check(getComputedStyle(overlay).backdropFilter === 'none', 'Unexpected sheet blur');
      const r = sheet?.getBoundingClientRect();
      check(Boolean(r && r.top >= -2 && r.bottom <= innerHeight + 2),
        'Sheet vertical bounds');
    }
    if (mode === 'pagination') {
      const nav = document.querySelector('.nfc-console-pagination');
      check(inside(nav), 'Pagination horizontal overflow');
      check(Boolean(nav?.textContent?.includes('第 2 / 2 页')),
        'Second page label missing');
    }
    if (mode === 'empty') {
      check(inside(document.querySelector('.nfc-v2-task-filter-bar')),
        'Empty filter toolbar overflow');
    }
    if (mode === 'failure') {
      check(inside(document.querySelector('.nfc-v2-task-alert')),
        'List error alert overflows');
      check(Boolean(document.querySelector('.nfc-v2-task-alert [role="alert"]') ||
        document.querySelector('.nfc-v2-task-alert[role="alert"]')),
      'Error alert semantics lost');
    }
    if (width < 768) {
      for (const card of document.querySelectorAll('.nfc-task-mobile-card'))
        check(inside(card), 'Mobile task card overflows viewport');
    } else {
      const scroll = document.querySelector('.nfc-v2-task-table-scroll');
      if (scroll) {
        check(inside(scroll), 'Desktop table scrollport overflows');
        check(['auto', 'scroll'].includes(getComputedStyle(scroll).overflowX),
          'Desktop table must own horizontal scrolling');
      }
    }
    return errors;
  }, { theme, width, mode });
  assert.deepEqual(violations, [], mode + ' ' + width + ': ' + violations.join('; '));
}


// Painted desktop Tasks row error: the table's normal/hover backgrounds come
// from different historical CSS layers. Audit actual Chromium winners, with
// real alpha composition back to a verified opaque ancestor (not palette tokens).
async function inspectTableErrorPaint(page, theme, width, state) {
  const snapshot = await page.evaluate(expectedState => {
    const row = document.querySelector('.nfc-v2-task-table tbody tr');
    const text = row?.querySelector('.nfc-v2-task-error');
    if (!row || !text || !text.textContent?.includes('SOURCE_IDENTITY_CONFLICT'))
      throw Error('Missing mounted failed Tasks row diagnostic');
    if (row.matches(':hover') !== (expectedState === 'hover'))
      throw Error('Real Tasks row pointer hover does not match requested state');
    const parse = value => {
      const rgb = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(\d*\.?\d+))?\s*\)$/.exec(value);
      const srgb = /^color\(srgb\s+(\d*\.?\d+)\s+(\d*\.?\d+)\s+(\d*\.?\d+)(?:\s*\/\s*(\d*\.?\d+))?\s*\)$/.exec(value);
      if (!rgb && !srgb) throw Error('Unsupported computed Tasks error color: ' + value);
      const found = rgb || srgb;
      const channels = found.slice(1, 4).map(Number);
      const alpha = found[4] === undefined ? 1 : Number(found[4]);
      if (srgb) for (let i = 0; i < 3; i++) channels[i] *= 255;
      if (channels.some(n => !Number.isFinite(n) || n < 0 || n > 255) ||
          !Number.isFinite(alpha) || alpha < 0 || alpha > 1)
        throw Error('Out-of-range computed Tasks error color: ' + value);
      return { channels, alpha };
    };
    const rgb = channels => 'rgb(' + channels.map(Math.round).join(', ') + ')';
    const foreground = parse(getComputedStyle(text).color);
    if (foreground.alpha !== 1)
      throw Error('Translucent Tasks error ink needs pixel-level evidence');
    const layers = [];
    for (let node = text; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.backgroundImage !== 'none' || Number(style.opacity) !== 1 ||
          style.filter !== 'none' || style.backdropFilter !== 'none' ||
          (style.webkitBackdropFilter && style.webkitBackdropFilter !== 'none'))
        throw Error('Unsupported Tasks error painted ancestor: ' + node.className);
      const layer = parse(style.backgroundColor);
      if (layer.alpha > 0) layers.push({
        node: node.tagName + (node.className && typeof node.className === 'string' ?
          '.' + node.className.trim().replace(/\s+/g, '.') : ''),
        color: style.backgroundColor, ...layer,
      });
      if (layer.alpha === 1) break;
    }
    if (!layers.length || layers.at(-1).alpha !== 1)
      throw Error('No opaque ancestor behind Tasks error ink');
    let painted = [0, 0, 0];
    for (const layer of [...layers].reverse()) {
      painted = painted.map((value, i) =>
        layer.channels[i] * layer.alpha + value * (1 - layer.alpha));
    }
    return { state: expectedState, hovered: row.matches(':hover'),
      foreground: rgb(foreground.channels), background: rgb(painted),
      layers: layers.map(({ node, color, alpha }) => ({ node, color, alpha })) };
  }, state);
  const ratio = computedContrastRatio(snapshot.foreground, snapshot.background);
  snapshot.contrast = Number(ratio.toFixed(3));
  assert.ok(ratio >= 4.5,
    'Actual Tasks table short error text below AA 4.5:1: ' +
    JSON.stringify({ width, theme, ...snapshot }));
  errorPaintCases.push({ width, mode: theme.mode, system: theme.system,
    effective: theme.effective, ...snapshot });
}

try {
  await ready();
  mkdirSync(OUT, { recursive: true });
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  for (const width of WIDTHS) {
    for (const theme of THEMES) {
      const context = await browser.newContext({
        viewport: { width, height: 900 },
        colorScheme: theme.system, reducedMotion: 'reduce',
      });
      await context.addInitScript(mode =>
        localStorage.setItem('nfc_theme_mode', mode), theme.mode);
      const page = await context.newPage();
      const writes = [], outbound = [], listRequests = [];
      let failList = false;
      await page.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin !== BASE) {
          outbound.push(url.href);
          await route.abort('blockedbyclient');
          return;
        }
        if (!url.pathname.startsWith('/api/')) {
          await route.continue();
          return;
        }
        if (request.method() !== 'GET') {
          writes.push(request.method() + ' ' + url.pathname);
          await route.fulfill({ status: 405, contentType: 'application/json',
            body: JSON.stringify({ detail: 'READ_ONLY_TASK_STATE_FIXTURE' }) });
          return;
        }
        if (url.pathname === '/api/tasks') listRequests.push(url.search);
        const fail = failList && url.pathname === '/api/tasks';
        await route.fulfill({ status: fail ? 503 : 200,
          contentType: 'application/json',
          body: JSON.stringify(fail
            ? { detail: 'Synthetic read-only task listing failure' } : fixture(url)) });
      });
      const label = theme.mode + '-' + theme.system + '-' + width;
      try {
        await page.goto(BASE + '/tasks', { waitUntil: 'domcontentloaded' });
        const cards = width < 768;
        const row = cards ? '.nfc-task-mobile-card' : '.nfc-v2-task-table tbody tr';
        await page.locator(row).first().waitFor({ state: 'visible' });
        assert.equal(await page.locator(row).count(), 50, 'First page must contain 50 records');
        if (cards) await page.locator(row).first()
          .getByRole('button', { name: '查看详情' }).click();
        else await page.locator(row).first().getByRole('button', { name: '详情' }).click();
        const sheet = page.locator('.nfc-task-detail-drawer');
        await sheet.waitFor({ state: 'visible' });
        await sheet.locator('.nfc-v2-task-error-preview').waitFor({ state: 'visible' });
        await assertBounds(page, theme.effective, width, 'drawer');
        await page.screenshot({ path: resolve(OUT, 'long-error-' + label + '.png') });
        const disclosure = sheet.locator('.nfc-v2-task-error-details');
        await disclosure.locator('summary').focus();
        await page.keyboard.press('Enter');
        await page.waitForFunction(() => Boolean(document.querySelector(
          '.nfc-task-detail-drawer .nfc-v2-task-error-details[open]')));
        assert.equal(await disclosure.locator('.nfc-prewrap-error').innerText(), LONG_ERROR);
        await assertBounds(page, theme.effective, width, 'drawer-expanded');
        await page.screenshot({ path: resolve(OUT, 'expanded-error-' + label + '.png') });
        await page.keyboard.press('Enter');
        await page.waitForFunction(() => !document.querySelector(
          '.nfc-task-detail-drawer .nfc-v2-task-error-details[open]'));
        await assertBounds(page, theme.effective, width, 'drawer');
        await page.keyboard.press('Escape');
        await sheet.waitFor({ state: 'hidden' });

        if (width >= 768) {
          // Existing screenshots stay unchanged; inspect table after drawer
          // closes and before pagination changes its first failed row.
          await page.mouse.move(0, 0);
          await inspectTableErrorPaint(page, theme, width, 'normal');
          await page.locator('.nfc-v2-task-table tbody tr .nfc-v2-task-error').first().hover();
          await inspectTableErrorPaint(page, theme, width, 'hover');
          await page.mouse.move(0, 0);
        }

        await page.getByRole('button', { name: '下一页' }).click();
        await page.getByRole('button', { name: '#651', exact: true }).waitFor({ state: 'visible' });
        assert.equal(await page.locator(row).count(), 1);
        assert.equal(await page.getByRole('button', { name: '上一页' }).isEnabled(), true);
        await assertBounds(page, theme.effective, width, 'pagination');
        await page.screenshot({ path: resolve(OUT, 'page-two-' + label + '.png') });
        assert.ok(listRequests.some(q => new URLSearchParams(q).get('page') === '2'),
          'Pagination must query server page 2');

        await page.locator('#nfc-task-status-filter').selectOption('failed');
        await page.locator('#nfc-task-type-filter').selectOption('media-analysis');
        await page.getByText('没有匹配的任务').waitFor({ state: 'visible' });
        assert.ok(listRequests.some(q => {
          const params = new URLSearchParams(q);
          return params.get('page') === '1' &&
            params.get('status') === 'failed' &&
            params.get('job_type') === 'media-analysis';
        }), 'Filter changes must reset page and use server-side query params');
        await assertBounds(page, theme.effective, width, 'empty');
        await page.screenshot({ path: resolve(OUT, 'filtered-empty-' + label + '.png') });

        failList = true;
        await page.locator('#nfc-task-status-filter').selectOption('running');
        await page.getByText('任务列表加载失败').waitFor({ state: 'visible', timeout: 25000 });
        await assertBounds(page, theme.effective, width, 'failure');
        await page.screenshot({ path: resolve(OUT, 'list-error-' + label + '.png') });
        failList = false;
        await page.getByRole('button', { name: '重试', exact: true }).click();
        await page.getByText('没有匹配的任务').waitFor({ state: 'visible' });
        assert.deepEqual(writes, [], 'No backend write is permitted');
        assert.deepEqual(outbound, [], 'No external or NAS request is permitted');
        passed++;
        console.log('[TASK LEDGER STATES PASS] ' + label);
      } catch (error) {
        console.error('[TASK LEDGER STATES FAIL] ' + label, error);
        await page.screenshot({ path: resolve(OUT, 'failure-' + label + '.png') }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(passed, WIDTHS.length * THEMES.length);
  assert.equal(errorPaintCases.length,
    WIDTHS.filter(width => width >= 768).length * THEMES.length * 2,
    'Five desktop widths, four themes and actual normal/hover Tasks error states required');
  writeFileSync(resolve(OUT, 'task-table-error-paint-contrast-audit.json'),
    JSON.stringify({ total: errorPaintCases.length, cases: errorPaintCases,
      minimumContrast: 4.5, method: 'actual-Chromium-normal-hover-opaque-ancestor-composition' }, null, 2));
  console.log('[TASK ERROR PAINT] 40/40 actual desktop normal/hover error text pairs >= 4.5:1.');
  console.log('[TASK LEDGER STATES] 32/32 cases, 160 screenshots; ' +
    'long failure, server pagination, compound filters, error/retry; synthetic GET only.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
