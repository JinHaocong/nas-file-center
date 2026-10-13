/**
 * Stage 5E-A: actual Dashboard, Plans, Tasks workspace cascade in Chromium.
 * Playwright serves synthetic local GET fixtures and denies all writes/outbound.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const BASE = 'http://127.0.0.1:4186';
const OUT = resolve(process.cwd(), 'artifacts/browser-workspace-cascade');
const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
const THEMES = [
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
];
const PAGES = [
  { path: '/dashboard', id: 'dashboard', heading: 'NAS File Center', selector: '.nfc-dashboard-page' },
  { path: '/plans', id: 'plans', heading: '执行计划', selector: '.nfc-plans-page' },
  { path: '/tasks', id: 'tasks', heading: '任务中心', selector: '.nfc-tasks-page' },
  { path: '/indexes', id: 'indexes', heading: '文件索引', selector: '.nfc-indexes-page' },
  { path: '/media', id: 'media', heading: '媒体完整性', selector: '.nfc-media-page' },
  { path: '/quarantine', id: 'quarantine', heading: '文件隔离区', selector: '.nfc-quarantine-page' },
];
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
  '--port', '4186', '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });
let browser;
let passed = 0;

async function ready() {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw Error('Vite preview exited');
    try { if ((await fetch(BASE + '/login')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Local Vite preview unavailable');
}

const DENSE_ROOT = '/visual-fixture/NAS/Very-Long-Archive-Name/Photography-2026/Original-Camera-Exports-and-Unsorted-Video-Files';
const DENSE_PAGES = [
  { path: '/plans', id: 'plans', row: '.nfc-v2-plan-table tbody tr',
    card: '.nfc-plan-mobile-card', scroll: '.nfc-v2-plan-table-scroll' },
  { path: '/tasks', id: 'tasks', row: '.nfc-v2-task-table tbody tr',
    card: '.nfc-task-mobile-card', scroll: '.nfc-v2-task-table-scroll' },
  { path: '/indexes', id: 'indexes', row: '.nfc-v2-indexes-table tbody tr',
    card: '.nfc-index-mobile-card', scroll: '.nfc-v2-indexes-table-scroll' },
];
function denseFixture(path) {
  const timestamp = '2026-10-12T08:30:00Z';
  if (path === '/api/plans') return {
    items: [
      { id: 301, name: 'Visual Fixture — Deep Archive Photo and Video Deduplication Plan 2026',
        kind: 'dedupe', status: 'ready', expected_changes: 136,
        expected_reclaim_bytes: 9865489321, created_at: timestamp },
      { id: 302, name: 'Second confirmed retention plan', kind: 'organizer',
        status: 'completed', expected_changes: 24,
        expected_reclaim_bytes: 10240, created_at: timestamp },
    ], total: 2, page: 1, page_size: 20,
  };
  if (path === '/api/tasks') return {
    items: [
      { id: 501, job_type: 'scan_and_verify_deep_archive_long_history',
        status: 'failed', created_at: timestamp, started_at: timestamp,
        finished_at: timestamp, heartbeat_at: timestamp, retry_of: null,
        progress: { current: 124, total: 500, percent: 24.8, message: 'Checking deep NAS paths' },
        capabilities: { supports_pause: false, supports_resume: false,
          supports_cancel: false, supports_retry: false },
        error_code: 'VALIDATION_PATH_IDENTITY_CHANGED',
        error: 'Read-only fixture: root identity changed under the archived path' },
      { id: 502, job_type: 'index', status: 'completed',
        created_at: timestamp, started_at: timestamp, finished_at: timestamp,
        heartbeat_at: timestamp, retry_of: null, error: null, error_code: null,
        progress: { current: 500, total: 500, percent: 100, message: null },
        capabilities: { supports_pause: false, supports_resume: false,
          supports_cancel: false, supports_retry: false } },
    ], total: 2, page: 1, page_size: 50,
  };
  if (path === '/api/indexes') return {
    items: [
      { id: 701, root: DENSE_ROOT, files: 12455678, folders: 98340,
        path_state: 'available', exists: true, can_remove: false,
        has_active_job: true, active_job_id: 777, active_job_status: 'running',
        created_at: timestamp, last_indexed_at: timestamp },
      { id: 702, root: DENSE_ROOT + '/Unavailable-Recovery-Snapshot',
        files: 1474, folders: 52, path_state: 'missing', exists: false,
        can_remove: false, has_active_job: false, active_job_id: null,
        active_job_status: null, created_at: timestamp, last_indexed_at: null },
    ], total: 2, page: 1, page_size: 20,
  };
  return null;
}
function fixture(path, dense = false) {
  if (path === '/api/auth/me') return {
    id: 1, username: 'css-visual-fixture', role: 'admin', is_admin: true,
  };
  if (path === '/api/dashboard/summary') return {
    indexed_files: 100000, indexed_folders: 2000, queued_or_running_jobs: 0,
    plan_count: 5, latest_scan_id: null, duplicate_group_count: 0,
    latest_reclaimable_bytes: 0,
  };
  if (path === '/api/settings') return {
    allow_mutation: false, allow_delete: false, safe_mode: true,
  };
  if (dense) {
    const populated = denseFixture(path);
    if (populated) return populated;
  }
  return { items: [], total: 0, page: 1, page_size: 50 };
}

async function inspect(page, theme, width, item) {
  const violations = await page.evaluate(({ theme, width, item }) => {
    const get = selector => {
      const el = document.querySelector(selector);
      if (!el) throw Error('Missing actual React CSS target: ' + selector);
      return el;
    };
    const failures = [];
    const check = (ok, message) => { if (!ok) failures.push(message); };
    const workspace = get('.nfc-app-main');
    const pageContent = get('.nfc-app-main .nfc-page-content');
    const screen = get(item.selector);
    const inside = el => {
      const r = el.getBoundingClientRect();
      return r.left >= -2 && r.right <= width + 2;
    };
    check(document.documentElement.dataset.theme === theme, 'Wrong effective theme');
    check(inside(pageContent), 'Workspace overflow');
    check(inside(screen), 'Page root overflow');
    if (width >= 768) {
      check(getComputedStyle(workspace).overflowY === 'hidden',
        'Desktop outer workspace unexpectedly scrolls');
      check(getComputedStyle(pageContent).overflowY === 'auto',
        'Desktop page must own single scrolling region');
      check(getComputedStyle(get('.nfc-app-shell')).overflowY === 'hidden',
        'Desktop shell adds a second scroller');
    } else {
      check(getComputedStyle(workspace).overflowY === 'visible',
        'Mobile must keep normal document scrolling');
    }
    if (item.id === 'dashboard') {
      const metrics = get('.nfc-v2-dashboard-metrics .nfc-metric-grid');
      const content = get('.nfc-v2-dashboard-content');
      check(inside(metrics), 'Dashboard metrics overflow');
      check(inside(content), 'Dashboard columns overflow');
      check(getComputedStyle(metrics).display === 'grid', 'Metric layout lost grid');
    } else {
      if (item.id === 'media') {
        const mediaMetrics = get('.nfc-media-page > .nfc-metric-grid');
        check(inside(mediaMetrics), 'Media metrics overflow viewport');
        check(getComputedStyle(mediaMetrics).display === 'grid',
          'Media metrics lost their responsive grid');
      }
      const head = get(item.selector + ' > .nfc-page-header');
      const panel = get(item.selector + ' > .nfc-data-panel');
      const mb = getComputedStyle(head).marginBottom;
      check(mb === '0px', 'Ledger duplicate heading margin: ' + mb);
      check(inside(head), 'Ledger header overflow');
      check(inside(panel), 'Ledger panel overflow');
      check(parseFloat(getComputedStyle(screen).rowGap) >= 10,
        'Ledger page gap must own vertical rhythm');
    }
    return failures;
  }, { theme, width, item });
  assert.deepEqual(violations, [], item.id + ' ' + width + ': ' + violations.join('; '));
}

async function inspectDense(page, item, width) {
  await page.waitForFunction(({ row, card }) =>
    Boolean(document.querySelector(row) || document.querySelector(card)),
  { row: item.row, card: item.card }, { timeout: 10000 });
  const failures = await page.evaluate(({ item, width }) => {
    const errors = [];
    const isMobile = width < 768;
    const selectors = isMobile ? item.card : item.row;
    const rows = [...document.querySelectorAll(selectors)];
    if (rows.length !== 2) errors.push('Expected two dense records, got ' + rows.length);
    const container = document.querySelector('.nfc-page-content');
    const outer = container?.getBoundingClientRect();
    for (const row of rows) {
      const rect = row.getBoundingClientRect();
      if (!Number.isFinite(rect.width) || rect.width <= 0) errors.push('Zero-width dense row/card');
      if (isMobile && (rect.left < -2 || rect.right > width + 2))
        errors.push('Mobile dense card exceeds viewport bounds');
    }
    if (!isMobile) {
      const scroll = document.querySelector(item.scroll);
      if (!scroll) errors.push('Desktop wide-table scroller missing');
      else {
        const r = scroll.getBoundingClientRect();
        if (r.left < -2 || r.right > width + 2)
          errors.push('Wide-table scrollport exceeds viewport');
        if (!['auto', 'scroll'].includes(getComputedStyle(scroll).overflowX))
          errors.push('Wide table must own horizontal overflow');
      }
    }
    if (!outer || outer.left < -2 || outer.right > width + 2)
      errors.push('Dense data caused workspace viewport overflow');
    return errors;
  }, { item, width });
  assert.deepEqual(failures, [], item.id + ' dense ' + width + ': ' + failures.join('; '));
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
      const outbound = [], writes = [];
      let denseMode = false;
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
            body: JSON.stringify({ detail: 'READ_ONLY_WORKSPACE_FIXTURE' }) });
          return;
        }
        await route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify(fixture(url.pathname, denseMode)) });
      });
      const label = theme.mode + '-' + theme.system + '-' + width;
      try {
        for (const item of PAGES) {
          await page.goto(BASE + item.path, { waitUntil: 'domcontentloaded' });
          await page.getByRole('heading', { name: item.heading, exact: true }).waitFor();
          await inspect(page, theme.effective, width, item);
          await page.screenshot({
            path: resolve(OUT, item.id + '-' + label + '.png'),
            fullPage: false,
          });
        }
        // A second pass mounts populated realistic ledgers without any backend writes.
        // Preserve the existing six empty-state screenshots and add three dense views.
        denseMode = true;
        for (const item of DENSE_PAGES) {
          await page.goto(BASE + item.path, { waitUntil: 'domcontentloaded' });
          await inspectDense(page, item, width);
          await page.screenshot({
            path: resolve(OUT, item.id + '-dense-' + label + '.png'),
            fullPage: false,
          });
        }
        denseMode = false;
        assert.deepEqual(writes, [], 'No write or Generate action may reach backend');
        assert.deepEqual(outbound, [], 'No outbound or real NAS traffic');
        passed++;
        console.log('[WORKSPACE CASCADE PASS] ' + label);
      } catch (err) {
        console.error('[WORKSPACE CASCADE FAIL] ' + label, err);
        await page.screenshot({ path: resolve(OUT, 'failure-' + label + '.png') })
          .catch(() => {});
        throw err;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(passed, WIDTHS.length * THEMES.length);
  console.log('[WORKSPACE CASCADE] 32/32 cases, 288 screenshots; ' +
    'real six-page empty + three-page dense CSS, synthetic GET only; no NAS or file access.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
