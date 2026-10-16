/**
 * Final acceptance: actual React app on EVERY declared route, not a component mock.
 * 8 CI jobs × 4 effective theme modes × 24 routes = 768 real Chromium visits.
 * GET APIs are 100% synthetic; any outbound or mutating request fails closed.
 * Captures screenshot, route, page heading, render/runtime errors and viewport overflow.
 * Screenshot collection is evidence to REVIEW; it does not automatically approve UI.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';
import { visualThemes, visualViewports, visualAdminFixture, visualSafeSettingsFixture } from './visual-fixtures.mjs';

const routes = Object.freeze([
  { path: '/login', id: 'login', public: true },
  { path: '/dashboard', id: 'dashboard' },
  { path: '/indexes', id: 'indexes' },
  { path: '/media', id: 'media' },
  { path: '/archive-recovery', id: 'archive-recovery' },
  { path: '/scans', id: 'scans' },
  { path: '/scans/1', id: 'scan-detail', template: 'scans/:id' },
  { path: '/scans/1/dedupe', id: 'scan-dedupe', template: 'scans/:id/dedupe' },
  { path: '/path-match', id: 'path-match' },
  { path: '/directory-diff', id: 'directory-diff' },
  { path: '/download-verification', id: 'download-verification' },
  { path: '/filename-audit', id: 'filename-audit' },
  { path: '/rename', id: 'rename' },
  { path: '/batch', id: 'batch' },
  { path: '/organizer', id: 'organizer' },
  { path: '/workflows', id: 'workflows' },
  { path: '/workflows/1', id: 'workflow-detail', template: 'workflows/:id' },
  { path: '/schedules', id: 'schedules' },
  { path: '/plans', id: 'plans' },
  { path: '/plans/1', id: 'plan-detail', template: 'plans/:id' },
  { path: '/quarantine', id: 'quarantine' },
  { path: '/tasks', id: 'tasks' },
  { path: '/audit', id: 'audit' },
  { path: '/settings', id: 'settings' },
]);

// Ensure the inventory changes when a new React route is introduced.
const router = readFileSync('src/router/index.tsx', 'utf8');
const declared = [...router.matchAll(/<Route\s+path="([^"]+)"/g)]
  .map(m => m[1].replace(/^\/+/, '')).filter(path => path !== '*' && path !== '');
const tested = routes.map(r => r.template || r.path.slice(1));
assert.equal(new Set(tested).size, tested.length, 'Duplicate visual route case');
assert.deepEqual([...tested].sort(), [...declared].sort(),
  'Visual matrix must include every router path, including dynamic details');
assert.equal(routes.length, 24);

const width = Number(process.env.NFC_VISUAL_WIDTH);
assert.ok(visualViewports.includes(width), 'Set NFC_VISUAL_WIDTH to one of the eight required widths');
const PORT = 4196;
const BASE = 'http://127.0.0.1:' + PORT;
const OUT = resolve('artifacts/full-route-visual', String(width));
mkdirSync(OUT, { recursive: true });
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
  '--port', String(PORT), '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });

async function ready() {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw Error('Vite preview exited before startup');
    try { if ((await fetch(BASE + '/login')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Vite preview failed to start');
}
const TS = '2026-10-16T08:00:00Z';
const fixtureScan = {
  id: 1, name: 'Mock 完整扫描 / 图片视频资料归档', status: 'completed',
  created_at: TS, started_at: TS, finished_at: TS, root_paths: ['/mock/library'],
  roots: ['/mock/library'], total_files: 12500, total_size: 8712312000,
  duplicate_groups: 2, duplicate_group_count: 2, duplicate_files: 5,
  reclaimable_bytes: 1350000000, error: null,
};
const fixturePlan = {
  id: 1, name: 'Mock 精确去重审查计划', kind: 'dedupe', status: 'draft',
  created_at: TS, updated_at: TS, expected_changes: 2,
  expected_reclaim_bytes: 1350000000, items: [], total: 0,
  preview_digest: 'synthetic-read-only', can_execute: false,
};
const fixtureWorkflow = {
  id: 1, name: 'Mock 文件巡检工作流', description: '浏览器截图专用模拟数据',
  steps: [], current_revision: 1, revision: 1, is_archived: false,
  created_at: TS, updated_at: TS,
};
const downloadRun = {
  id: 7, work_job_id: 16, remote_root: 'PikPak/Movies', local_root: '/mock/library/movies',
  result: 'DIFFERENT', job_status: 'completed', checked: 8, total: 9,
  bytes_checked: 9443284231, error_code: null, created_at: TS, finished_at: TS,
};
const page = items => ({ items, total: items.length, page: 1, page_size: 50 });
function fixture(path) {
  if (path === '/api/auth/me') return visualAdminFixture('full-site-visual-mock');
  if (path === '/api/settings') return visualSafeSettingsFixture();
  if (path === '/api/dashboard/summary') return {
    indexed_files: 123456, indexed_folders: 5100, queued_or_running_jobs: 0,
    plan_count: 12, latest_scan_id: 1, duplicate_group_count: 2,
    latest_reclaimable_bytes: 1350000000,
  };
  if (path === '/api/media/summary') return {
    total: 3, image: 2, video: 1, healthy: 2, corrupt: 1, unknown: 0,
    verification_unverified: 1, verification_baseline: 0, verification_verified: 1,
    verification_changed: 1, verification_unknown: 0,
  };
  if (path === '/api/scans/1') return fixtureScan;
  if (path === '/api/scans/1/groups') return page([]);
  if (path === '/api/scans') return page([fixtureScan]);
  if (path === '/api/plans/1/items' || path === '/api/plans/1/operation-journal') return page([]);
  if (path === '/api/plans/1') return fixturePlan;
  if (path === '/api/plans') return page([fixturePlan]);
  if (path === '/api/workflows/1') return fixtureWorkflow;
  if (path === '/api/workflows') return page([fixtureWorkflow]);
  if (path === '/api/download-verifications/configuration') return {
    configured: false, endpoint: '', mode: 'strict', read_only: true,
  };
  if (path === '/api/download-verifications') return page([downloadRun]);
  if (path === '/api/download-verifications/7/items') return page([
    { relative_path: 'movies/Archive.Movie.2026.mkv', kind: 'file',
      status: 'HASH_MISMATCH', remote_size: 500000, local_size: 500000,
      remote_sha256: 'f'.repeat(64), local_sha256: '0'.repeat(64), reason_code: 'HASH_MISMATCH' },
    { relative_path: 'movies/Only-on-NAS.mkv', kind: 'file',
      status: 'ONLY_LOCAL', remote_size: null, local_size: 800000,
      remote_sha256: null, local_sha256: null, reason_code: 'ONLY_LOCAL' },
  ]);
  if (path === '/api/indexes') return page([
    { id: 1, root: '/mock/library', files: 12500, folders: 500,
      path_state: 'available', exists: true, can_remove: false, has_active_job: false,
      created_at: TS, last_indexed_at: TS },
  ]);
  if (path === '/api/tasks') return page([]);
  if (path === '/api/media') return page([]);
  if (path === '/api/quarantine') return page([]);
  if (path === '/api/audit') return page([]);
  if (path === '/api/filesystem/list') return {
    path: '/mock/library', parent: null, allowed_roots: ['/mock'],
    items: [{name:'Movies', path:'/mock/library/Movies', type:'directory', is_dir:true}],
    total: 1, page: 1, page_size: 50,
  };
  if (path === '/api/filesystem/favorites' || path === '/api/filesystem/recent') return page([]);
  return page([]);
}

let browser;
const report = [];
const failures = [];
try {
  await ready();
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  for (const theme of visualThemes) {
    const context = await browser.newContext({
      viewport: { width, height: 900 }, colorScheme: theme.system,
      reducedMotion: 'reduce',
    });
    const writes = [], outbound = [], pageErrors = [];
    await context.addInitScript(mode => localStorage.setItem('nfc_theme_mode', mode), theme.mode);
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== BASE) {
        outbound.push(request.method() + ' ' + url.href);
        await route.abort('blockedbyclient');
      } else if (url.pathname.startsWith('/api/')) {
        if (request.method() !== 'GET') {
          writes.push(request.method() + ' ' + url.pathname);
          await route.fulfill({ status: 405, contentType: 'application/json',
            body: JSON.stringify({ error: 'READ_ONLY_VISUAL_AUDIT' }) });
        } else {
          await route.fulfill({ status: 200, contentType: 'application/json',
            body: JSON.stringify(fixture(url.pathname)) });
        }
      } else {
        await route.continue();
      }
    });
    const tab = await context.newPage();
    tab.on('pageerror', err => pageErrors.push(err.message));
    const themeLabel = theme.mode + '-' + theme.system;
    for (const item of routes) {
      const beforeErrors = pageErrors.length;
      const problems = [];
      try {
        await tab.goto(BASE + item.path, { waitUntil: 'domcontentloaded' });
        if (item.public) await tab.locator('#nfc-login-theme-select').waitFor();
        else await tab.locator('#main-content').waitFor();
        await tab.waitForTimeout(160);
        const audit = await tab.evaluate(() => {
          const main = document.querySelector('main') || document.querySelector('#root');
          const shell = document.querySelector('.nfc-v2-shell');
          const visible = main?.innerText?.trim() || '';
          const heading = [...document.querySelectorAll('h1,h2')].map(x =>
            x.innerText.trim()).filter(Boolean).slice(0, 4);
          const area = main?.getBoundingClientRect();
          return {
            pathname: location.pathname,
            effectiveTheme: document.documentElement.dataset.theme,
            title: document.title,
            heading,
            visibleChars: visible.length,
            horizontalOverflow: document.documentElement.scrollWidth - window.innerWidth,
            mainRight: area?.right ?? null,
            hasShell: Boolean(shell),
            busy: Boolean(main?.querySelector('.nfc-session-loading')),
          };
        });
        if (audit.pathname !== item.path) problems.push('Route redirected: ' + audit.pathname);
        if (audit.effectiveTheme !== theme.effective) problems.push('Theme mismatch');
        if (!item.public && !audit.hasShell) problems.push('Missing authenticated React shell');
        if (audit.visibleChars < 25) problems.push('Empty/near-empty rendered page');
        if (audit.busy) problems.push('Still showing session loading');
        if (audit.horizontalOverflow > 3) problems.push(
          'Document horizontal overflow: ' + audit.horizontalOverflow + 'px');
        if (pageErrors.length > beforeErrors) problems.push(
          'Uncaught React errors: ' + pageErrors.slice(beforeErrors).join('; '));
        const name = item.id + '-' + themeLabel + '-' + width;
        await tab.screenshot({
          path: resolve(OUT, name + '.png'),
          fullPage: (width === 390 || width === 1440) && theme.mode === 'light',
          animations: 'disabled',
        });
        report.push({ route: item.path, width, theme: themeLabel, ...audit, problems });
        if (problems.length) failures.push({ route: item.path, theme: themeLabel, problems });
      } catch (err) {
        const message = String(err?.message || err);
        failures.push({ route: item.path, theme: themeLabel, problems: [message] });
        report.push({ route: item.path, width, theme: themeLabel, problems: [message] });
        await tab.screenshot({
          path: resolve(OUT, item.id + '-' + themeLabel + '-' + width + '-failed.png'),
          animations: 'disabled',
        }).catch(() => {});
      }
    }
    if (writes.length) failures.push({ theme: themeLabel, problems: ['Mutating API: ' + writes.join(', ')] });
    if (outbound.length) failures.push({ theme: themeLabel, problems: ['External requests: ' + outbound.join(', ')] });
    await context.close();
  }
  writeFileSync(resolve(OUT, 'manifest.json'),
    JSON.stringify({ width, routes: routes.length, themes: visualThemes.length,
      captured: report.length, failures, report }, null, 2));
  console.log('[FULL ROUTE AUDIT] width=' + width + ', routes=' + routes.length +
    ', themes=' + visualThemes.length + ', captures=' + report.length +
    ', failures=' + failures.length + '; screenshot manifest saved.');
  assert.deepEqual(failures, [], 'All-route mock visual audit detected failures; see manifest.json');
  assert.equal(report.length, 24 * 4);
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
