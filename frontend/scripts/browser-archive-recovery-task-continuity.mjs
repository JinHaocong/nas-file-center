/**
 * Stage 5E-AH: real built React/Chromium WorkJob monitor continuity.
 * All task detail/report data are synthetic GET responses on localhost.
 * Never POST a check, start, cancel, or any other mutation to a NAS.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';
import { visualAdminFixture, visualSafeSettingsFixture } from './visual-fixtures.mjs';

const ROOT = process.cwd();
const PORT = 4199;
const BASE = 'http://127.0.0.1:' + PORT;
const OUTPUT = resolve(ROOT, 'artifacts/browser-archive-recovery-task-continuity');
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

function fixture(url, status) {
  if (url.pathname === '/api/auth/me') return visualAdminFixture('recovery-task-readonly');
  if (url.pathname === '/api/settings') return visualSafeSettingsFixture();
  if (url.pathname === '/api/filesystem/list') {
    const path = url.searchParams.get('path');
    const items = path === '/data'
      ? [{ name: 'fixture.zip', path: '/data/fixture.zip',
          type: 'file', is_dir: false, size: 123 }]
      : [];
    return { path, parent: null, allowed_roots: ['/data'], items,
      total: items.length, page: 1, page_size: 100, has_more: false };
  }
  if (url.pathname === '/api/filesystem/favorites' ||
      url.pathname === '/api/filesystem/recent') return { items: [] };
  if (url.pathname === '/api/tasks/777' || url.pathname === '/api/tasks/778') {
    const unrelated = url.pathname.endsWith('/778');
    return { id: unrelated ? 778 : 777,
      job_type: unrelated ? 'fclones-scan' : 'archive-recovery',
      status: unrelated ? 'completed' : status,
      capabilities: { supports_cancel: false, supports_pause: false,
        supports_resume: false, supports_retry: false },
      progress: { current: 1, total: 3, percent: 33, message: 'Synthetic Worker' },
      created_at: null, started_at: null, finished_at: null,
      heartbeat_at: null, error: null, error_code: null, retry_of: null,
      payload: {}, checkpoint: {} };
  }
  if (url.pathname === '/api/archive-recovery/777/report') {
    return { source: '/data/fixture.zip', output: '/data/fixture.zip_恢复结果_fixture',
      format: 'ZIP', recovery_status: 'complete', known_total: 1,
      items: [{ name: 'sample.txt', status: 'integrity_passed', bytes: 3 }],
      stats: { integrity_passed: 1, format_validated: 0, unverified: 0,
        incomplete: 0, unrecovered: 0 }, warnings: [] };
  }
  return { ...visualSafeSettingsFixture(), items: [], total: 0, status: 'ok' };
}

try {
  await ready();
  mkdirSync(OUTPUT, { recursive: true });
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  for (const width of [390, 1280]) {
    for (const theme of ['light', 'dark', 'system-light', 'system-dark']) {
      const context = await browser.newContext({
        viewport: { width, height: 900 },
        colorScheme: theme.endsWith('dark') ? 'dark' : 'light',
        reducedMotion: 'reduce',
      });
      await context.addInitScript(mode => {
        localStorage.setItem('nfc_theme_mode', mode.split('-')[0]);
      }, theme);
      const page = await context.newPage();
      const blockedWrites = [];
      const outbound = [];
      const taskReads = [];
      let status = 'running';
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
          if (url.pathname === '/api/tasks/777') taskReads.push(status);
          await route.fulfill({ status: 200, contentType: 'application/json',
            body: JSON.stringify(fixture(url, status)) });
          return;
        }
        await route.continue();
      });
      const label = theme + '-' + width;
      try {
        await page.goto(BASE + '/archive-recovery?task=777', {
          waitUntil: 'domcontentloaded',
        });
        const monitor = page.locator('.nfc-archive-recovery-task-panel');
        // The panel mounts before the asynchronous Task detail GET resolves.
        // Wait for actual server-fixture data, not only for the shell to render.
        await monitor.getByText(/Synthetic Worker/).waitFor({ state: 'visible' });
        assert.match(await monitor.innerText(), /任务 #777/, label);
        assert.equal(await page.getByRole('button', {
          name: '开始下一次恢复',
        }).count(), 0, label + ' no premature task dismissal');
        assert.equal(await page.getByRole('button', {
          name: '开始恢复',
        }).isDisabled(), true, label);

        // Re-selecting an archive, editing the source and changing folders
        // must never silently detach a still-active WorkJob.
        await page.locator('.nfc-archive-recovery-file').first().click();
        await page.locator('#recovery-password').fill('synthetic-secret-never-sent');
        await page.locator('#recovery-source').fill('/data/different.zip');
        assert.equal(await page.locator('#recovery-password').inputValue(), '', label);
        assert.match(await monitor.innerText(), /任务 #777/, label);
        await page.getByRole('textbox', { name: '目录路径' }).fill('/data/other');
        assert.match(await monitor.innerText(), /任务 #777/, label);
        assert.equal(new URL(page.url()).searchParams.get('task'), '777', label);
        await page.screenshot({ path: resolve(OUTPUT, label + '-running.png') });

        await page.reload({ waitUntil: 'domcontentloaded' });
        // The panel mounts before the asynchronous Task detail GET resolves.
        // Wait for actual server-fixture data, not only for the shell to render.
        await monitor.getByText(/Synthetic Worker/).waitFor({ state: 'visible' });
        assert.match(await monitor.innerText(), /任务 #777/, label);
        assert.equal(new URL(page.url()).searchParams.get('task'), '777', label);

        // Synthetic terminal WorkJob, retrieved only through GET.
        status = 'completed';
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.getByRole('button', {
          name: '开始下一次恢复',
        }).waitFor({ state: 'visible' });
        assert.match(await monitor.innerText(), /任务 #777/, label);
        assert.ok((await page.locator('.nfc-archive-recovery-results').innerText())
          .includes('sample.txt'), label);
        await page.screenshot({ path: resolve(OUTPUT, label + '-completed.png') });

        // Explicit acknowledgement only; no cancel/start/plan/execute POST.
        await page.locator('#recovery-source').fill('/data/other.zip');
        await page.getByRole('button', { name: '开始下一次恢复' }).click();
        await monitor.waitFor({ state: 'detached' });
        assert.equal(await monitor.count(), 0, label + ' monitor dismissed');
        assert.equal(new URL(page.url()).searchParams.has('task'), false, label);
        assert.equal(await page.locator('#recovery-source').inputValue(), '', label);
        assert.equal(await page.getByRole('button', { name: '开始恢复' }).isDisabled(),
          true, label);
        // A manually supplied ID for a different WorkJob kind must not
        // expose cancellation, recovery reports, or terminal acknowledgement.
        await page.goto(BASE + '/archive-recovery?task=778', {
          waitUntil: 'domcontentloaded',
        });
        await page.getByText('任务编号对应的不是压缩包恢复任务。', {
          exact: false,
        }).waitFor({ state: 'visible' });
        assert.equal(await page.getByRole('button', {
          name: '取消任务',
        }).isDisabled(), true, label);
        assert.equal(await page.getByRole('button', {
          name: '开始下一次恢复',
        }).count(), 0, label);
        assert.equal(await page.locator('.nfc-archive-recovery-results').count(),
          0, label);
        await page.screenshot({ path: resolve(OUTPUT, label + '-unrelated.png') });

        assert.ok(taskReads.includes('running') && taskReads.includes('completed'),
          label + ' observed readonly task lifecycle');
        assert.deepEqual(blockedWrites, [], label + ': blocked write requests');
        assert.deepEqual(outbound, [], label + ': off-origin requests');
        passed += 1;
        console.log('[ARCHIVE TASK CONTINUITY PASS] ' + label);
      } catch (error) {
        await page.screenshot({
          path: resolve(OUTPUT, label + '-failure.png'),
        }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(passed, 8);
  console.log('[ARCHIVE TASK CONTINUITY] 8/8 GET-only WorkJob cases.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
