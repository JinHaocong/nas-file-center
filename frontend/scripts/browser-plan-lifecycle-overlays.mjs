/**
 * Stage 5D-B: actual Plan Detail lifecycle portals in the built React/Radix app.
 * Synthetic GET fixtures and ONLY a locally fulfilled read-only rebuild-preview.
 * Every other non-GET request returns 405 and is counted as a failure.
 * No backend, NAS, Worker, Plan Freeze/Validate/Execute/Undo or file mutation.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:4183';
const OUT = resolve(process.cwd(), 'artifacts/browser-plan-lifecycle');
const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
const THEMES = [
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
];
const CASES = {
  101: { status: 'draft' },
  102: { status: 'frozen' },
  103: { status: 'ready' },
  104: { status: 'stale', workflow: true },
  105: { status: 'ready', readOnly: true },
  106: { status: 'ready', activeJob: 700 },
  107: { status: 'completed' },
  108: { status: 'stale', dedupe: true },
};
const DIGEST = 'a'.repeat(64);
const SHA = 'b'.repeat(64);
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
  '--port', '4183', '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });
let browser;
let completed = 0;

async function ready() {
  for (let n = 0; n < 100; n += 1) {
    if (server.exitCode !== null) throw Error('Vite preview exited');
    try { if ((await fetch(BASE_URL + '/login')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Vite preview unavailable');
}

function plan(id) {
  const info = CASES[id];
  assert.ok(info, 'Unexpected fixture plan ID ' + id);
  return {
    id, name: 'Visual Fixture Plan #' + id, kind: info.dedupe ? 'dedupe' : 'workflow',
    status: info.status, expected_changes: 1, expected_reclaim_bytes: 256,
    created_at: '2026-10-12T09:00:00+08:00', frozen_at: id === 101 ? null : '2026-10-12T09:01:00+08:00',
    total_items: 1, page: 1, page_size: 50,
    active_work_job_id: info.activeJob || null,
    active_work_job_status: info.activeJob ? 'running' : null,
    metadata: info.workflow || info.dedupe
      ? { source: 'workflow', workflow_id: 42, workflow_revision: 2,
        workflow_mode: info.dedupe ? 'dedupe' : 'file',
        scan_job_id: info.dedupe ? 99 : undefined,
        definition_sha256: SHA, compile_digest: DIGEST,
        runtime_inputs: info.dedupe ? { scan_job_id: 99 } : { root_ids: [1] } }
      : {},
    items: [{
      id: id * 10, sequence: 1, operation: 'quarantine',
      source: '/visual-fixture/file-' + id + '.txt',
      target: '/visual-fixture/.nas-file-center-trash/file-' + id + '.txt',
      expected_size: 256, state: 'planned', reason: null,
    }],
  };
}

function journalRecord(planId) {
  return {
    id: 1, sequence: 1, plan_id: planId, plan_item_id: planId * 10,
    task_id: 11, user_id: 1, operation: 'quarantine',
    before: { path: '/visual-fixture/file-' + planId + '.txt', size: 256 },
    after: { path: '/visual-fixture/.nas-file-center-trash/file-' + planId + '.txt', size: 256 },
    metadata_before: { inode: 10 }, metadata_after: { inode: 10 },
    created_at: '2026-10-12T09:03:00+08:00',
  };
}

function getFixture(url) {
  const path = url.pathname;
  if (path === '/api/auth/me') {
    return { id: 1, username: 'plan-lifecycle-visual-admin', role: 'admin', is_admin: true };
  }
  if (path === '/api/settings') {
    const id = Number(url.searchParams.get('visual_plan_id') || '103');
    return { allow_mutation: id !== 105, allow_delete: false, safe_mode: id === 105 };
  }
  const match = /^\/api\/plans\/(\d+)(?:\/(operation-journal))?$/.exec(path);
  if (match) {
    const id = Number(match[1]);
    if (match[2]) {
      // Completed Plan has journal authority; others expose one read-only sample.
      return { items: [journalRecord(id)], total: 1, page: 1, page_size: Number(url.searchParams.get('page_size') || 20) };
    }
    return plan(id);
  }
  return { items: [], total: 0, page: 1, page_size: 20 };
}

function rebuildPreviewFixture(body) {
  assert.equal(body.page, 1);
  assert.equal(body.page_size, 50);
  return {
    workflow_id: 42, workflow_revision: 2,
    planned_operations_count: 1, matched_count: 1,
    compile_digest: DIGEST, definition_sha256: SHA,
    items: [{
      operation: 'quarantine', changed: true,
      source_path: '/visual-fixture/old-source.txt',
      target_path: '/visual-fixture/new-quarantine.txt',
    }],
  };
}

async function inspect(page, effectiveTheme, width, kind, selector) {
  return page.evaluate(({ effectiveTheme, width, kind, selector }) => {
    const content = document.querySelector(selector);
    const mask = document.querySelector(kind === 'confirm' ?
      '.nfc-v2-confirm-overlay' : '.nfc-v2-sheet-overlay');
    if (!content || !mask) throw Error('Actual Radix Plan Portal not found');
    const cs = getComputedStyle(content);
    const ms = getComputedStyle(mask);
    const r = content.getBoundingClientRect();
    const expectSurface = effectiveTheme === 'dark' ? 'rgb(36, 36, 34)' : 'rgb(255, 255, 255)';
    const problems = [];
    const check = (valid, reason) => { if (!valid) problems.push(reason); };
    const expectedOverlay = kind === 'confirm' ? 1300 : 1100;
    check(document.documentElement.dataset.theme === effectiveTheme, 'Wrong effective theme');
    check(Number(ms.zIndex) === expectedOverlay, 'Mask z ' + ms.zIndex);
    check(Number(cs.zIndex) === expectedOverlay + 1, 'Content z ' + cs.zIndex);
    check(ms.backdropFilter === 'none' &&
      (ms.webkitBackdropFilter === undefined || ms.webkitBackdropFilter === 'none'),
    'Blurred overlay');
    check(cs.backgroundColor === expectSurface, 'Surface ' + cs.backgroundColor);
    check(r.left >= -2 && r.right <= width + 2, 'Horizontal overflow');
    check(r.top >= -2 && r.bottom <= innerHeight + 2, 'Vertical overflow');
    const x = Math.max(1, Math.min(width - 1, r.left + r.width / 2));
    const y = Math.max(1, Math.min(innerHeight - 1, r.top + Math.min(r.height / 2, 100)));
    check(Boolean(document.elementFromPoint(x, y)?.closest(selector)),
      'Overlay intercepts dialog pointer hits');
    return problems;
  }, { effectiveTheme, width, kind, selector });
}

async function assertPortal(page, theme, width, kind, selector, label) {
  const errors = await inspect(page, theme, width, kind, selector);
  assert.deepEqual(errors, [], label + ': ' + errors.join('; '));
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
      await context.addInitScript(mode => localStorage.setItem('nfc_theme_mode', mode),
        theme.mode);
      const page = await context.newPage();
      const forbidden = [];
      const external = [];
      let rebuildPreviews = 0;
      // This is an isolated localhost-only simulation; even the nominally POST
      // rebuild-preview is answered by Playwright without reaching an app backend.
      await page.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin !== BASE_URL) {
          external.push(request.url());
          await route.abort('blockedbyclient');
          return;
        }
        if (!url.pathname.startsWith('/api/')) {
          await route.continue();
          return;
        }
        if (request.method() === 'GET') {
          // Settings must simulate per-plan safe mode without changing the
          // production component or calling an unmocked endpoint.
          const activeId = Number(new URL(page.url()).pathname.split('/').pop());
          if (url.pathname === '/api/settings') {
            await route.fulfill({ status: 200, contentType: 'application/json',
              body: JSON.stringify({ allow_mutation: activeId !== 105, allow_delete: false,
                safe_mode: activeId === 105 }) });
          } else {
            await route.fulfill({ status: 200, contentType: 'application/json',
              body: JSON.stringify(getFixture(url)) });
          }
          return;
        }
        if (request.method() === 'POST' && url.pathname === '/api/plans/104/rebuild-preview') {
          try {
            const result = rebuildPreviewFixture(request.postDataJSON());
            rebuildPreviews += 1;
            await route.fulfill({ status: 200, contentType: 'application/json',
              body: JSON.stringify(result) });
          } catch (error) {
            forbidden.push('Invalid rebuild Preview payload: ' + String(error));
            await route.fulfill({ status: 422, contentType: 'application/json',
              body: JSON.stringify({ detail: 'INVALID_VISUAL_PREVIEW' }) });
          }
          return;
        }
        forbidden.push(request.method() + ' ' + url.pathname);
        await route.fulfill({ status: 405, contentType: 'application/json',
          body: JSON.stringify({ detail: 'READ_ONLY_VISUAL_FIXTURE' }) });
      });
      const label = theme.mode + '-' + theme.system + '-' + width;
      const confirm = page.locator('.nfc-v2-confirm-dialog');
      const journal = page.locator('.nfc-v2-operation-journal.nfc-v2-sheet');
      const rebuild = page.locator('.nfc-v2-stale-rebuild.nfc-v2-sheet');
      const goto = async id => {
        await page.goto(BASE_URL + '/plans/' + id, { waitUntil: 'domcontentloaded' });
        await page.getByRole('heading', { name: 'Visual Fixture Plan #' + id }).waitFor();
      };
      try {
        await goto(101);
        assert.equal(await page.getByRole('button', { name: '冻结计划 (Freeze)' }).isEnabled(), true,
          'Draft may Freeze but is never executed by browser');
        assert.equal(await page.getByRole('button', { name: '执行计划 (Execute)' }).count(), 0,
          'Draft cannot expose Execute');
        await goto(102);
        assert.equal(await page.getByRole('button', { name: 'SHA256 实时校验 (Validate)' }).isEnabled(),
          true, 'Frozen Plan may Validate; browser will not click');
        assert.equal(await page.getByRole('button', { name: '执行计划 (Execute)' }).count(), 0);

        await goto(103);
        await page.getByRole('button', { name: '执行计划 (Execute)' }).click();
        await confirm.waitFor({ state: 'visible' });
        await assertPortal(page, theme.effective, width, 'confirm',
          '.nfc-v2-confirm-dialog', 'Execute confirmation ' + label);
        assert.ok((await confirm.innerText()).includes('Worker'));
        assert.equal(await confirm.getByRole('button', { name: '确认执行' }).isEnabled(), true,
          'Confirm UI enabled but NEVER clicked');
        await page.screenshot({ path: resolve(OUT, 'ready-execute-' + label + '.png') });
        await page.keyboard.press('Escape');
        await confirm.waitFor({ state: 'hidden' });

        await page.getByRole('button', { name: /操作日志/ }).click();
        await journal.waitFor({ state: 'visible' });
        await assertPortal(page, theme.effective, width, 'sheet',
          '.nfc-v2-operation-journal.nfc-v2-sheet', 'Journal ' + label);
        await journal.getByText('查看原始审计数据').first().click();
        assert.ok((await journal.innerText()).includes('Metadata Before'),
          'Journal must reveal original read-only evidence');
        await page.screenshot({ path: resolve(OUT, 'journal-' + label + '.png') });
        await page.keyboard.press('Escape');
        await journal.waitFor({ state: 'hidden' });

        await goto(105);
        const safeExecute = page.getByRole('button', { name: '执行计划 (Execute)' });
        assert.equal(await safeExecute.isDisabled(), true,
          'ALLOW_MUTATION=false must block Execute even when Ready');
        assert.equal(await confirm.count(), 0, 'Safe mode cannot open Execute confirmation');
        await goto(106);
        assert.equal(await page.getByRole('button', { name: 'SHA256 实时校验 (Validate)' }).isDisabled(),
          true, 'Active worker blocks Validate');
        assert.equal(await page.getByRole('button', { name: '执行计划 (Execute)' }).isDisabled(),
          true, 'Active worker blocks Execute');

        await goto(104);
        assert.equal(await page.getByRole('button', { name: '执行计划 (Execute)' }).count(), 0,
          'Stale Plan must never expose Execute');
        await page.getByRole('button', { name: '重建工作流计划 (Rebuild Plan)' }).click();
        await rebuild.waitFor({ state: 'visible' });
        await rebuild.getByText('Compile Digest').waitFor();
        await assertPortal(page, theme.effective, width, 'sheet',
          '.nfc-v2-stale-rebuild.nfc-v2-sheet', 'Stale Workflow rebuild ' + label);
        assert.equal(await rebuild.getByRole('button', { name: '生成草稿' }).isEnabled(), true,
          'Fresh preview can show Draft button; NEVER click it');
        await page.screenshot({ path: resolve(OUT, 'stale-rebuild-' + label + '.png') });
        await page.keyboard.press('Escape');
        await rebuild.waitFor({ state: 'hidden' });

        await goto(108);
        assert.equal(await page.getByRole('button', { name: '重建工作流计划 (Rebuild Plan)' }).count(), 0,
          'Stale Dedupe requires rescan, not Workflow rebuild');
        assert.ok((await page.innerText('body')).includes('PLAN_STALE'));

        await goto(107);
        await page.getByRole('button', { name: '生成撤销计划 (Undo)' }).click();
        await confirm.waitFor({ state: 'visible' });
        await assertPortal(page, theme.effective, width, 'confirm',
          '.nfc-v2-confirm-dialog', 'Undo confirmation ' + label);
        assert.ok((await confirm.innerText()).includes('新的 Undo Draft'));
        await page.screenshot({ path: resolve(OUT, 'completed-undo-' + label + '.png') });
        await page.keyboard.press('Escape');
        await confirm.waitFor({ state: 'hidden' });
        // Stage 5E-Z: the Plans ledger owns a controlled cleanup dialog with
        // no Dialog.Trigger. Verify exact launcher focus return on three
        // cancellation paths, without ever issuing a metadata cleanup POST.
        await page.goto(BASE_URL + '/plans', { waitUntil: 'domcontentloaded' });
        await page.getByRole('heading', { name: '执行计划' }).first().waitFor();
        const historyLauncher = page.getByRole('button', { name: '清理计划历史' }).first();
        const historyOpener = await historyLauncher.elementHandle();
        assert.ok(historyOpener, 'Plan History launcher must exist');
        const historyDialog = page.locator('.nfc-v2-plan-history-dialog');
        await historyLauncher.click();
        await historyDialog.waitFor({ state: 'visible' });
        assert.ok((await historyDialog.innerText()).includes('Delete ≠ Undo'));
        await historyDialog.getByRole('button', { name: '取消' }).click();
        await historyDialog.waitFor({ state: 'hidden' });
        await page.waitForFunction(opener => document.activeElement === opener, historyOpener);
        await page.keyboard.press('Enter');
        await historyDialog.waitFor({ state: 'visible' });
        await page.keyboard.press('Escape');
        await historyDialog.waitFor({ state: 'hidden' });
        await page.waitForFunction(opener => document.activeElement === opener, historyOpener);
        await page.keyboard.press('Enter');
        await historyDialog.waitFor({ state: 'visible' });
        await historyDialog.getByRole('button', { name: '关闭清理窗口' }).click();
        await historyDialog.waitFor({ state: 'hidden' });
        await page.waitForFunction(opener => document.activeElement === opener, historyOpener);
        assert.equal(rebuildPreviews, 1, 'Only one mock rebuild Preview, zero Draft requests');
        assert.deepEqual(forbidden, [], 'No Plan or History cleanup mutations allowed');
        assert.deepEqual(external, [], 'No outbound NAS/network requests allowed');
        completed += 1;
        console.log('[PLAN LIFECYCLE BROWSER PASS] ' + label);
      } catch (error) {
        console.error('[PLAN LIFECYCLE BROWSER FAIL] ' + label, error);
        await page.screenshot({ path: resolve(OUT, 'failure-' + label + '.png') }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(completed, WIDTHS.length * THEMES.length);
  console.log('[PLAN LIFECYCLE BROWSER] 32/32 cases, 128 screenshots; ' +
    'read-only mock rebuild-preview; no Draft/Freeze/Validate/Execute/Undo/NAS access.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
