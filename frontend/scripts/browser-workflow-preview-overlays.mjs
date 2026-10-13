/**
 * Pure White Stage 5D-C: real Workflow Preview -> Draft confirmation portals.
 * Playwright fulfills read-only /api/workflows/{id}/preview POST locally.
 * All other non-GET API requests are denied with 405 and treated as a failure.
 * Local Vite origin only. NEVER connects to NAS, never generates Drafts.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:4184';
const OUT = resolve(process.cwd(), 'artifacts/browser-workflow-preview');
const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
const THEMES = [
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
];
const SHA = 'b'.repeat(64);
const DIGEST = 'a'.repeat(64);
const MODE = { 41: 'file', 42: 'utility', 43: 'file' };
const archived = id => id === 43;
const definition = mode => ({
  schema_version: 1, mode,
  steps: mode === 'utility'
    ? [{ id: 'utility-1', type: 'single_child_wrapper_collapse', root_id: 1, subpath: '' }]
    : [{ id: 'scan-1', type: 'scan', root_ids: [1] }],
});
const workflow = id => ({
  id, name: 'Visual Workflow #' + id, description: 'Read-only workflow visual fixture',
  current_revision: 2, is_builtin: false, created_by_user_id: 1,
  archived_at: archived(id) ? '2026-10-12T09:00:00Z' : null,
  created_at: '2026-10-12T09:00:00Z', updated_at: '2026-10-12T09:00:00Z',
  definition: definition(MODE[id]), definition_sha256: SHA,
});
const candidates = [
  {
    candidate_id: 'ready-wrapper', state: 'READY', selectable: true, selected: true,
    wrapper_path: '/visual-fixture/A/B', child_path: '/visual-fixture/A/B/C',
    target_path: '/visual-fixture/A/C', child_object_type: 'directory',
  },
  {
    candidate_id: 'blocked-wrapper', state: 'BLOCKED', selectable: false, selected: true,
    wrapper_path: '/visual-fixture/X/B', child_path: '/visual-fixture/X/B/C',
    target_path: '/visual-fixture/X/C', capability_reason: 'BLOCKED_BY_SAFETY',
  },
];
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview',
  '--host', '127.0.0.1', '--port', '4184', '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });
let browser;
let completed = 0;

async function ready() {
  for (let i = 0; i < 100; i += 1) {
    if (server.exitCode !== null) throw Error('Vite preview exited');
    try { if ((await fetch(BASE_URL + '/login')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Vite preview not ready');
}

function readFixture(path) {
  if (path === '/api/auth/me') return { id: 1, username: 'workflow-visual-admin', role: 'admin' };
  if (path === '/api/settings') return { allow_mutation: true, allow_delete: false };
  if (path === '/api/indexes') return {
    items: [{ id: 1, root: '/visual-fixture', files: 2, folders: 3,
      created_at: '2026-10-12T09:00:00Z', last_indexed_at: null,
      exists: true, path_state: 'available', has_active_job: false,
      active_job_id: null, active_job_status: null, can_remove: false }],
    total: 1, page: 1, page_size: 100,
  };
  const m = /^\/api\/workflows\/(41|42|43)(?:\/revisions\/(\d+))?$/.exec(path);
  if (m) {
    const id = Number(m[1]);
    if (m[2]) return {
      revision: Number(m[2]), definition_sha256: SHA,
      definition: definition(MODE[id]), created_at: '2026-10-12T08:00:00Z',
      created_by_user_id: 1,
    };
    return workflow(id);
  }
  return { items: [], total: 0, page: 1, page_size: 20 };
}

function previewFixture(id, data) {
  assert.ok(MODE[id], 'Only fixture workflows may Preview');
  assert.equal(data.revision === 1 || data.revision === 2, true, 'Revision must be explicit');
  assert.equal(data.page, MODE[id] === 'utility' ? 1 : 1);
  assert.equal(data.page_size, MODE[id] === 'utility' ? 500 : 50);
  assert.equal(data.only_changed, false);
  if (MODE[id] === 'utility') {
    assert.equal(data.runtime_inputs, undefined, 'Utility must not inject runtime root override');
  } else {
    assert.ok(data.runtime_inputs === undefined ||
      JSON.stringify(data.runtime_inputs) === JSON.stringify({ root_ids: [1] }),
    'File runtime root identity must be exact');
  }
  return {
    workflow_id: id, revision: data.revision, workflow_revision: data.revision,
    definition_sha256: SHA, workflow_mode: MODE[id],
    preview_source: MODE[id] === 'utility' ? 'utility-live-readonly' : 'index',
    live_filesystem_verified: false, compile_digest: DIGEST,
    matched_count: 2, matched_bytes: 512, planned_operations_count: 1,
    page: 1, page_size: data.page_size, total_pages: 1,
    items: [{
      source_path: '/visual-fixture/original.txt',
      target_path: '/visual-fixture/target.txt',
      operation: 'rename', changed: true, metadata: {},
    }],
    utility_summary: MODE[id] === 'utility' ? {
      utility_action: 'single_child_wrapper_collapse', scope_path: '/visual-fixture',
      candidate_count: 2, ready_count: 1,
      candidates, selected_candidate_ids: ['ready-wrapper', 'blocked-wrapper'],
    } : undefined,
  };
}

async function assertPortal(page, effectiveTheme, width, label) {
  const problems = await page.evaluate(({ effectiveTheme, width }) => {
    const dialog = document.querySelector('.nfc-v2-confirm-dialog[data-state="open"]');
    const overlay = document.querySelector('.nfc-v2-confirm-overlay[data-state="open"]');
    if (!dialog || !overlay) throw Error('Missing real Radix Portal');
    const cs = getComputedStyle(dialog);
    const os = getComputedStyle(overlay);
    const rect = dialog.getBoundingClientRect();
    const errors = [];
    const check = (valid, why) => { if (!valid) errors.push(why); };
    check(document.documentElement.dataset.theme === effectiveTheme, 'Wrong effective theme');
    check(Number(os.zIndex) === 1300, 'Overlay z-index ' + os.zIndex);
    check(Number(cs.zIndex) === 1301, 'Dialog z-index ' + cs.zIndex);
    check(os.backdropFilter === 'none' &&
      (os.webkitBackdropFilter === undefined || os.webkitBackdropFilter === 'none'),
    'Scrim must not blur');
    check(cs.backgroundColor === (effectiveTheme === 'dark' ?
      'rgb(36, 36, 34)' : 'rgb(255, 255, 255)'), 'Dialog surface ' + cs.backgroundColor);
    check(rect.left >= -2 && rect.right <= width + 2, 'Horizontal viewport overflow');
    check(rect.top >= -2 && rect.bottom <= innerHeight + 2, 'Vertical viewport overflow');
    const x = Math.max(1, Math.min(width - 1, rect.left + rect.width / 2));
    const y = Math.max(1, Math.min(innerHeight - 1, rect.top + Math.min(rect.height / 2, 100)));
    check(Boolean(document.elementFromPoint(x, y)?.closest('.nfc-v2-confirm-dialog')),
      'Scrim intercepts confirmation pointer hits');
    return errors;
  }, { effectiveTheme, width });
  assert.deepEqual(problems, [], label + ': ' + problems.join('; '));
}

async function waitForEnabled(page, name) {
  await page.waitForFunction(label => [...document.querySelectorAll('button')].some(
    button => button.textContent?.trim() === label && !button.disabled
  ), name, { timeout: 10000 });
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
      await context.addInitScript(mode => localStorage.setItem('nfc_theme_mode', mode), theme.mode);
      const page = await context.newPage();
      const forbidden = [];
      const external = [];
      const acceptedPreviewRequests = [];
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
          await route.fulfill({ status: 200, contentType: 'application/json',
            body: JSON.stringify(readFixture(url.pathname)) });
          return;
        }
        const match = /^\/api\/workflows\/(41|42)\/preview$/.exec(url.pathname);
        if (request.method() === 'POST' && match) {
          try {
            const payload = request.postDataJSON();
            const result = previewFixture(Number(match[1]), payload);
            acceptedPreviewRequests.push({ id: Number(match[1]), revision: payload.revision });
            await route.fulfill({ status: 200, contentType: 'application/json',
              body: JSON.stringify(result) });
          } catch (error) {
            forbidden.push('Invalid read-only Preview: ' + String(error));
            await route.fulfill({ status: 422, contentType: 'application/json',
              body: JSON.stringify({ detail: 'INVALID_WORKFLOW_VISUAL_PREVIEW' }) });
          }
          return;
        }
        forbidden.push(request.method() + ' ' + url.pathname);
        await route.fulfill({ status: 405, contentType: 'application/json',
          body: JSON.stringify({ detail: 'READ_ONLY_WORKFLOW_BROWSER_FIXTURE' }) });
      });

      const label = theme.mode + '-' + theme.system + '-' + width;
      const confirm = page.locator('.nfc-v2-confirm-dialog');
      const goto = async url => {
        await page.goto(BASE_URL + url, { waitUntil: 'domcontentloaded' });
        await page.getByRole('heading', { name: /Visual Workflow #/ }).first().waitFor();
      };
      try {
        // Legacy File Preview: no Draft without authoritative saved Preview.
        await goto('/workflows/41');
        const legacy = page.locator('.nfc-v2-legacy-preview');
        const legacyDraft = legacy.getByRole('button', { name: '生成计划草稿' });
        assert.equal(await legacyDraft.isDisabled(), true, 'File Draft needs Preview');
        await legacy.getByRole('button', { name: '生成预览' }).click();
        await waitForEnabled(page, '生成计划草稿');
        await legacyDraft.click();
        await confirm.waitFor({ state: 'visible' });
        assert.ok((await confirm.innerText()).includes('compile digest'));
        await assertPortal(page, theme.effective, width, 'File Preview confirmation ' + label);
        assert.equal(await confirm.getByRole('button', { name: '生成草稿' }).isEnabled(), true,
          'Confirmation opens but must NEVER submit a Draft');
        await page.screenshot({ path: resolve(OUT, 'file-confirm-' + label + '.png') });
        await page.keyboard.press('Escape');
        await confirm.waitFor({ state: 'hidden' });

        // An Index Root override invalidates old Preview/digest until a fresh Preview.
        await legacy.getByRole('group', { name: '覆盖根目录，最多16个' })
          .getByRole('checkbox').first().check();
        assert.equal(await legacyDraft.isDisabled(), true, 'Root change must invalidate file Preview');
        await legacy.getByRole('button', { name: '生成预览' }).click();
        await waitForEnabled(page, '生成计划草稿');

        // Editing saved definition must disable Preview and Generate Draft; no Save click.
        await page.getByLabel('工作流名称').fill('Unsaved Visual Workflow');
        assert.equal(await legacy.getByRole('button', { name: '生成预览' }).isDisabled(), true,
          'Dirty file workflow must not Preview');
        assert.equal(await legacyDraft.isDisabled(), true, 'Dirty file workflow must not Draft');
        await page.screenshot({ path: resolve(OUT, 'file-dirty-' + label + '.png') });

        // Historical view is revision-bound and read-only, but can Preview.
        await goto('/workflows/41?revision=1');
        assert.equal(await page.getByLabel('工作流名称').isDisabled(), true,
          'Historical revision cannot edit');
        const historical = page.locator('.nfc-v2-legacy-preview');
        await historical.getByRole('button', { name: '生成预览' }).click();
        await waitForEnabled(page, '生成计划草稿');
        await historical.getByRole('button', { name: '生成计划草稿' }).click();
        await confirm.waitFor({ state: 'visible' });
        await assertPortal(page, theme.effective, width, 'Historical r1 Draft confirmation ' + label);
        await page.screenshot({ path: resolve(OUT, 'history-confirm-' + label + '.png') });
        await page.keyboard.press('Escape');
        await confirm.waitFor({ state: 'hidden' });

        // Utility: only READY explicitly selected candidates can enter a Draft.
        await goto('/workflows/42');
        const utility = page.locator('.nfc-v2-utility-preview');
        const utilityDraft = utility.getByRole('button', { name: '生成计划草稿' });
        assert.equal(await utilityDraft.isDisabled(), true, 'Utility must Preview first');
        await utility.getByRole('button', { name: '生成预览' }).click();
        await waitForEnabled(page, '生成计划草稿');
        const readyCandidate = utility.getByRole('checkbox', { name: '选择候选 ready-wrapper' });
        const blockedCandidate = utility.getByRole('checkbox', { name: '选择候选 blocked-wrapper' });
        assert.equal(await blockedCandidate.isDisabled(), true, 'Blocked candidate is never selectable');
        assert.equal(await blockedCandidate.isChecked(), false,
          'Server-proposed blocked member must be sanitized');
        assert.equal(await readyCandidate.isChecked(), true);
        await readyCandidate.uncheck();
        assert.equal(await utilityDraft.isDisabled(), true, 'Zero selected READY candidates block Draft');
        await readyCandidate.check();
        await waitForEnabled(page, '生成计划草稿');
        await utilityDraft.click();
        await confirm.waitFor({ state: 'visible' });
        assert.ok((await confirm.innerText()).includes('候选数：1'),
          'Confirmation must reflect exactly one READY candidate');
        await assertPortal(page, theme.effective, width, 'Utility Draft confirmation ' + label);
        await page.screenshot({ path: resolve(OUT, 'utility-confirm-' + label + '.png') });
        await page.keyboard.press('Escape');
        await confirm.waitFor({ state: 'hidden' });
        await page.getByLabel('工作流名称').fill('Dirty Utility Visual');
        assert.equal(await utility.getByRole('button', { name: '生成预览' }).isDisabled(), true,
          'Dirty Utility workflow must not Preview');
        assert.equal(await utilityDraft.isDisabled(), true, 'Dirty Utility workflow must not Draft');

        // Archived definitions remain strictly read-only.
        await goto('/workflows/43');
        const locked = page.locator('.nfc-v2-legacy-preview');
        assert.equal(await page.getByLabel('工作流名称').isDisabled(), true);
        assert.equal(await locked.getByRole('button', { name: '生成预览' }).isDisabled(), true);
        assert.equal(await locked.getByRole('button', { name: '生成计划草稿' }).isDisabled(), true);
        assert.ok((await page.innerText('body')).includes('已归档'));
        assert.deepEqual(acceptedPreviewRequests, [
          { id: 41, revision: 2 }, { id: 41, revision: 2 },
          { id: 41, revision: 1 }, { id: 42, revision: 2 },
        ], 'Preview calls must be revision-pinned and immutable');
        assert.deepEqual(forbidden, [], 'No Generate/Save/Rollback/mutation requests');
        assert.deepEqual(external, [], 'No external network or NAS');
        completed += 1;
        console.log('[WORKFLOW PREVIEW BROWSER PASS] ' + label);
      } catch (error) {
        console.error('[WORKFLOW PREVIEW BROWSER FAIL] ' + label, error);
        await page.screenshot({ path: resolve(OUT, 'failure-' + label + '.png') }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(completed, WIDTHS.length * THEMES.length);
  console.log('[WORKFLOW PREVIEW BROWSER] 32/32 cases; 128 screenshots; ' +
    'Preview-only synthetic API, no Draft/Save/Execute/NAS access.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
