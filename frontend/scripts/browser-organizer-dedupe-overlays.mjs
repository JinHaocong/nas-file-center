/**
 * Pure White Stage 5D-D: actual Organizer Advanced and Dedupe Workflow Preview.
 * All GET endpoints are local synthetic read-only fixtures. Only the exact
 * workflow and direct-dedupe read-only Preview POST routes are locally fulfilled.
 * Every Draft/Generate/Execute/write is denied and asserted absent. No NAS access.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:4185';
const OUT = resolve(process.cwd(), 'artifacts/browser-organizer-dedupe');
const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
const THEMES = [
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
];
const SHA = 'b'.repeat(64);
const COMPILE = 'a'.repeat(64);
const ORGANIZER_DIGEST = 'c'.repeat(64);
const DEDUPE_DIGEST = 'd'.repeat(64);
const ROOT = '/visual-fixture/root';
const modeOf = id => id === 51 ? 'organizer' : 'dedupe';
const definition = id => ({
  schema_version: 1, mode: modeOf(id),
  steps: id === 51
    ? [{ id: 'scan-fixture', type: 'scan', root_ids: [1] },
      { id: 'organizer-fixture', type: 'organize', profile_snapshot: {
        name: 'Visual Fixture Profile', root: ROOT, recursive: true,
        image_extensions: ['jpg'], video_extensions: ['mp4'],
        rename_template: '{name}', statistics_template: '{images}',
        advanced_rules: { version: 1, directory_depth: { enabled: true, rename_from_depth: 2 },
          file_numbering: { enabled: false, start: 1, padding: 2, sort: 'natural_name',
            extension_mode: 'preserve' },
          latest_child_prefix: { enabled: false, prefix: 'New ', timestamp: 'mtime_ns' },
          single_child_wrapper_collapse: { enabled: true, wrapper_depth: 2, child_type: 'directory' } },
      } }]
    : [{ id: 'dedupe-fixture', type: 'dedupe', scorer_config: {
      schema_version: 1, selection_mode: 'weighted',
      factors: {
        path_priority: { enabled: false, weight: 0, rules: [] },
        preferred_extension: { enabled: false, weight: 0, extensions: [] },
        mtime: { mode: 'none', weight: 0 },
      },
    } }],
});
const scan = (id, status) => ({
  id, name: 'Synthetic Scan #' + id, mode: 'dedupe',
  roots: [ROOT], status,
  total_groups: 1, total_files_in_groups: 2, reclaimable_bytes: 256,
  created_at: '2026-10-13T08:00:00Z',
  finished_at: status === 'completed' ? '2026-10-13T08:05:00Z' : null,
});
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
  '--port', '4185', '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });
let browser;
let completed = 0;

async function ready() {
  for (let i = 0; i < 100; i += 1) {
    if (server.exitCode !== null) throw Error('Vite preview exited');
    try { if ((await fetch(BASE_URL + '/login')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Local Vite preview not ready');
}

function getFixture(path) {
  if (path === '/api/auth/me') {
    return { id: 1, username: 'visual-organizer-dedupe', role: 'admin', is_admin: true };
  }
  if (path === '/api/settings') {
    return { allow_mutation: true, allow_delete: false, safe_mode: false };
  }
  if (path === '/api/indexes') {
    return { items: [{ id: 1, root: ROOT }], page: 1, page_size: 100, total: 1 };
  }
  if (path === '/api/scans') {
    return { items: [scan(501, 'completed'), scan(502, 'completed'),
      scan(503, 'running')], page: 1, page_size: 500, total: 3 };
  }
  if (path === '/api/scans/501') return scan(501, 'completed');
  const m = /^\/api\/workflows\/(51|52)$/.exec(path);
  if (m) {
    const id = Number(m[1]);
    return {
      id, name: 'Visual Workflow #' + id,
      description: 'Local read-only Organizer/Dedupe fixture',
      current_revision: 2, is_builtin: false, created_by_user_id: 1,
      created_at: '2026-10-13T08:00:00Z', updated_at: '2026-10-13T08:00:00Z',
      archived_at: null, definition: definition(id), definition_sha256: SHA,
    };
  }
  return { items: [], total: 0, page: 1, page_size: 20 };
}

function directDedupePreviewFixture(payload) {
  assert.equal(payload.scorer_config?.schema_version, 1);
  assert.equal(payload.storage_action, 'quarantine');
  assert.equal(payload.page, 1);
  assert.equal(payload.page_size, 50);
  const summary = {
    scan_job_id: 501, scan_roots: [ROOT], selection_mode: 'weighted',
    group_count: 1, candidate_member_count: 2, actionable_group_count: 1,
    skipped_group_count: 0, planned_quarantine_count: 1, planned_action_count: 1,
    storage_blocked_count: 0, expected_reclaim_bytes: 256,
    released_bytes_by_scan_root: { 0: 256 }, storage_action: 'quarantine',
    effective_safety_policy: { protect_last_file: true, allowed_roots: [ROOT] },
  };
  return {
    ...summary, summary, scan_roots: [ROOT],
    page: 1, page_size: 50, total_pages: 1, total_rows: 0, rows: [],
    preview_digest: DEDUPE_DIGEST,
    scorer_config_digest: 'e'.repeat(64),
    source_snapshot_digest: 'f'.repeat(64),
    decision_digest: '1'.repeat(64),
    dedupe_engine_version: 2, preview_source: 'synthetic-scan-readonly',
    live_filesystem_verified: false,
  };
}

function previewFixture(id, req, ordinal) {
  assert.equal(req.revision, 2, 'Preview must pin saved revision 2');
  assert.equal(req.page, 1);
  assert.equal(req.page_size, 50);
  assert.equal(req.only_changed, false);
  const organizer = id === 51;
  if (organizer) {
    assert.equal(req.runtime_inputs, undefined, 'Organizer initial Preview uses step scope');
    assert.ok(ordinal <= 4, 'Unexpected Organizer Preview count');
  } else {
    assert.deepEqual(req.runtime_inputs, { scan_job_id: 501 },
      'Dedupe must bind exactly the verified completed Scan #501');
    assert.ok(ordinal <= 2, 'Unexpected Dedupe Preview count');
  }
  const structural = organizer && ordinal === 2;
  const conflict = organizer && ordinal === 1;
  const missingDigest = organizer && ordinal === 3;
  const missingDedupeSummary = !organizer && ordinal === 1;
  return {
    workflow_id: id, revision: 2, workflow_revision: 2,
    definition_sha256: SHA, workflow_mode: modeOf(id),
    preview_source: organizer ? 'organizer-live-readonly' : 'completed-scan-readonly-safety',
    live_filesystem_verified: false, compile_digest: COMPILE,
    matched_count: 2, matched_bytes: 512, planned_operations_count: 1,
    page: 1, page_size: 50, total_pages: 1,
    items: organizer ? [{
      source_path: ROOT + '/A/B', target_path: ROOT + '/A/C',
      changed: true, operation: structural ? 'move' : 'rename',
      metadata: { proposal_type: structural ? 'wrapper_collapse' : 'directory_rename',
        conflict },
    }] : [],
    organizer_summary: organizer ? {
      advanced_enabled: true,
      structural_required: structural,
      preview_digest: missingDigest ? null : ORGANIZER_DIGEST,
      summary: { conflicts: conflict ? 1 : 0, structural_required: structural,
        total_directories: 2, advanced_changes: 1 },
    } : undefined,
    dedupe_summary: missingDedupeSummary ? undefined : organizer ? undefined : {
      scan_job_id: 501, scan_roots: [ROOT], selection_mode: 'weighted',
      group_count: 1, candidate_member_count: 2,
      actionable_group_count: 1, skipped_group_count: 0,
      planned_quarantine_count: 1, expected_reclaim_bytes: 256,
      preview_digest: DEDUPE_DIGEST, scorer_config_digest: 'e'.repeat(64),
      source_snapshot_digest: 'f'.repeat(64), decision_digest: '1'.repeat(64),
      dedupe_engine_version: 3,
      effective_safety_policy: { protect_last_file: true,
        allowed_roots: [ROOT], quarantine_root: ROOT + '/.trash' },
    },
  };
}

async function assertConfirm(page, effectiveTheme, width, label) {
  // Radix can report its portal visible before Chromium has updated pointer
  // hit testing for the newly opened modal. Wait only for that paint boundary,
  // never for a fixed sleep: a genuinely occluded dialog must still fail CI
  // after this bounded two-second readiness check.
  await page.waitForFunction(() => {
    const dialog = document.querySelector('.nfc-v2-confirm-dialog[data-state="open"]');
    if (!dialog) return false;
    const rect = dialog.getBoundingClientRect();
    const x = Math.max(1, Math.min(innerWidth - 1, rect.left + rect.width / 2));
    const y = Math.max(1, Math.min(innerHeight - 1, rect.top + Math.min(rect.height / 2, 100)));
    return Boolean(document.elementFromPoint(x, y)?.closest('.nfc-v2-confirm-dialog'));
  }, undefined, { polling: 'raf', timeout: 2000 });
  const problems = await page.evaluate(({ effectiveTheme, width }) => {
    const dialog = document.querySelector('.nfc-v2-confirm-dialog[data-state="open"]');
    const mask = document.querySelector('.nfc-v2-confirm-overlay[data-state="open"]');
    if (!dialog || !mask) throw Error('Real Radix confirmation portal missing');
    const cs = getComputedStyle(dialog);
    const ms = getComputedStyle(mask);
    const rect = dialog.getBoundingClientRect();
    const bad = [];
    const check = (valid, message) => { if (!valid) bad.push(message); };
    check(document.documentElement.dataset.theme === effectiveTheme, 'Theme mismatch');
    check(Number(ms.zIndex) === 1300, 'Scrim z-index ' + ms.zIndex);
    check(Number(cs.zIndex) === 1301, 'Dialog z-index ' + cs.zIndex);
    check(ms.backdropFilter === 'none' &&
      (ms.webkitBackdropFilter === undefined || ms.webkitBackdropFilter === 'none'),
    'Scrim applies blur');
    check(cs.backgroundColor === (effectiveTheme === 'dark' ?
      'rgb(36, 36, 34)' : 'rgb(255, 255, 255)'), 'Dialog surface ' + cs.backgroundColor);
    check(rect.left >= -2 && rect.right <= width + 2, 'Horizontal overflow');
    check(rect.top >= -2 && rect.bottom <= innerHeight + 2, 'Vertical overflow');
    const x = Math.max(1, Math.min(width - 1, rect.left + rect.width / 2));
    const y = Math.max(1, Math.min(innerHeight - 1, rect.top + Math.min(rect.height / 2, 100)));
    check(Boolean(document.elementFromPoint(x, y)?.closest('.nfc-v2-confirm-dialog')),
      'Scrim intercepts dialog pointer hits');
    return bad;
  }, { effectiveTheme, width });
  assert.deepEqual(problems, [], label + ' ' + problems.join('; '));
}

async function waitEnabled(page, label) {
  await page.waitForFunction(text => Array.from(document.querySelectorAll('button')).some(
    b => b.textContent?.trim() === text && !b.disabled,
  ), label, { timeout: 12000 });
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
      const counters = { 51: 0, 52: 0 };
      const acceptedPreviews = [];
      const directDedupePreviews = [];
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
            body: JSON.stringify(getFixture(url.pathname)) });
          return;
        }
        const previewMatch = /^\/api\/workflows\/(51|52)\/preview$/.exec(url.pathname);
        if (request.method() === 'POST' && previewMatch) {
          try {
            const id = Number(previewMatch[1]);
            const body = request.postDataJSON();
            const next = counters[id] + 1;
            const response = previewFixture(id, body, next);
            counters[id] = next;
            acceptedPreviews.push({ id, revision: body.revision,
              scanJobId: body.runtime_inputs?.scan_job_id ?? null });
            await route.fulfill({ status: 200, contentType: 'application/json',
              body: JSON.stringify(response) });
          } catch (error) {
            forbidden.push('Invalid Preview payload: ' + String(error));
            await route.fulfill({ status: 422, contentType: 'application/json',
              body: JSON.stringify({ detail: 'INVALID_READ_ONLY_PREVIEW_FIXTURE' }) });
          }
          return;
        }
        if (request.method() === 'POST' && url.pathname === '/api/scans/501/dedupe-preview') {
          try {
            const body = request.postDataJSON();
            const response = directDedupePreviewFixture(body);
            directDedupePreviews.push({ scanId: 501, preview: 'read-only' });
            await route.fulfill({ status: 200, contentType: 'application/json',
              body: JSON.stringify(response) });
          } catch (error) {
            forbidden.push('Invalid direct Dedupe Preview: ' + String(error));
            await route.fulfill({ status: 422, contentType: 'application/json',
              body: JSON.stringify({ detail: 'INVALID_READ_ONLY_DEDUPE_PREVIEW' }) });
          }
          return;
        }
        forbidden.push(request.method() + ' ' + url.pathname);
        await route.fulfill({ status: 405, contentType: 'application/json',
          body: JSON.stringify({ detail: 'READ_ONLY_BROWSER_FIXTURE' }) });
      });
      const label = theme.mode + '-' + theme.system + '-' + width;
      const confirm = page.locator('.nfc-v2-confirm-dialog');
      const go = async id => {
        await page.goto(BASE_URL + '/workflows/' + id, { waitUntil: 'domcontentloaded' });
        await page.getByRole('heading', { name: 'Visual Workflow #' + id }).first().waitFor();
      };
      try {
        // Organizer Advanced Preview: a conflict must lock Draft.
        await go(51);
        const organizer = page.locator('.nfc-v2-legacy-preview');
        assert.equal(await organizer.getByRole('button', { name: '生成计划草稿' }).isDisabled(),
          true, 'Organizer must Preview before Draft');
        await organizer.getByRole('button', { name: '生成预览' }).click();
        await organizer.getByText('Organizer Preview 存在 1 个 blocking conflict').waitFor();
        assert.equal(await organizer.getByRole('button', { name: '生成 Stage B 重命名草稿' }).isDisabled(),
          true, 'Conflicts must block Stage B Draft');
        await page.screenshot({ path: resolve(OUT, 'organizer-conflict-' + label + '.png') });

        // Stage A structural operations are isolated; Stage B must not bypass them.
        await organizer.getByRole('button', { name: '刷新预览' }).click();
        await waitEnabled(page, '生成 Stage A 结构草稿');
        assert.ok((await organizer.innerText()).includes('Stage B rename/file/prefix 已锁定'),
          'Structural Stage A must visibly lock Stage B work');
        await organizer.getByRole('button', { name: '生成 Stage A 结构草稿' }).click();
        await confirm.waitFor({ state: 'visible' });
        assert.ok((await confirm.innerText()).includes('Stage A 执行完成后必须重新 Preview'));
        await assertConfirm(page, theme.effective, width, 'Organizer Stage A ' + label);
        await page.screenshot({ path: resolve(OUT, 'organizer-stage-a-' + label + '.png') });
        await page.keyboard.press('Escape');
        await confirm.waitFor({ state: 'hidden' });

        // Missing Organizer digest must invalidate the Draft even if compile digest exists.
        await organizer.getByRole('button', { name: '刷新预览' }).click();
        await organizer.getByText('(缺失，请重新 Preview)').waitFor();
        assert.equal(await organizer.getByRole('button', { name: '生成 Stage B 重命名草稿' }).isDisabled(),
          true, 'Missing preview_digest must block Stage B Draft');

        await organizer.getByRole('button', { name: '刷新预览' }).click();
        await waitEnabled(page, '生成 Stage B 重命名草稿');
        await organizer.getByRole('button', { name: '生成 Stage B 重命名草稿' }).click();
        await confirm.waitFor({ state: 'visible' });
        assert.ok((await confirm.innerText()).includes('revision、compile digest'));
        await assertConfirm(page, theme.effective, width, 'Organizer Stage B ' + label);
        await page.screenshot({ path: resolve(OUT, 'organizer-stage-b-' + label + '.png') });
        await page.keyboard.press('Escape');
        await confirm.waitFor({ state: 'hidden' });

        // Dedupe only accepts completed authority Scan, no unverified scan override.
        await go(52);
        const dedupe = page.locator('.nfc-v2-legacy-preview');
        const draft = dedupe.getByRole('button', { name: '生成计划草稿' });
        assert.equal(await dedupe.getByRole('button', { name: '生成预览' }).isDisabled(),
          true, 'No completed Scan selected => Preview disabled');
        assert.equal(await draft.isDisabled(), true);
        const picker = page.getByLabel('选择已完成的扫描任务');
        await picker.locator('option[value="501"]').waitFor({ state: 'attached' });
        assert.equal(await picker.locator('option[value="503"]').count(), 0,
          'Running Scan must be absent from completed picker');
        await picker.selectOption('501');
        await dedupe.getByRole('button', { name: '生成预览' }).click();
        await dedupe.getByText('缺少去重权威摘要 (dedupe_summary)').waitFor();
        assert.equal(await draft.isDisabled(), true, 'Missing dedupe_summary blocks Draft');

        await dedupe.getByRole('button', { name: '刷新预览' }).click();
        await waitEnabled(page, '生成计划草稿');
        const identity = dedupe.getByRole('region', { name: '身份凭证与安全摘要' });
        await identity.waitFor();
        const line = await identity.innerText();
        assert.ok(line.includes('Scan #501') && line.includes('第 r2 版'));
        assert.ok(line.includes('已启用 (true)') && line.includes('未验证 (false)'),
          'Dedupe safety identity must disclose Protect Last File and Pre-Freeze status');
        await draft.click();
        await confirm.waitFor({ state: 'visible' });
        assert.ok((await confirm.innerText()).includes('compile digest'));
        await assertConfirm(page, theme.effective, width, 'Dedupe Draft ' + label);
        await page.screenshot({ path: resolve(OUT, 'dedupe-authority-' + label + '.png') });
        await page.keyboard.press('Escape');
        await confirm.waitFor({ state: 'hidden' });

        await picker.selectOption('502');
        assert.equal(await draft.isDisabled(), true,
          'Changing completed Scan identity revokes old Preview/Draft');
        assert.equal(await identity.count(), 0, 'Old Scan authority must disappear');
        assert.deepEqual(counters, { 51: 4, 52: 2 });
        assert.deepEqual(acceptedPreviews, [
          { id: 51, revision: 2, scanJobId: null },
          { id: 51, revision: 2, scanJobId: null },
          { id: 51, revision: 2, scanJobId: null },
          { id: 51, revision: 2, scanJobId: null },
          { id: 52, revision: 2, scanJobId: 501 },
          { id: 52, revision: 2, scanJobId: 501 },
        ], 'All Preview responses must pin exact Workflow revision and Scan authority');
        // Stage 5E-Y: this is the *direct* advanced Dedupe controlled dialog,
        // separate from the legacy Workflow Dedupe confirmation above.
        // One isolated read-only Preview POST enables the generate launcher;
        // no Draft/Generate POST is made, even in the browser fixture.
        await page.goto(BASE_URL + '/scans/501/dedupe', { waitUntil: 'domcontentloaded' });
        await page.getByRole('heading', { name: '高级精确去重' }).first().waitFor();
        await page.getByRole('button', { name: '运行高级预览 (Preview)' }).click();
        const generateLauncher = page.getByRole('button', { name: '生成执行计划草案' });
        await generateLauncher.waitFor({ state: 'visible' });
        await waitEnabled(page, '生成执行计划草案');
        const generateOpener = await generateLauncher.elementHandle();
        assert.ok(generateOpener, 'Actual direct Dedupe launcher must exist');
        await generateLauncher.click();
        const directDialog = page.locator('.nfc-v2-advanced-dedupe-dialog');
        await directDialog.waitFor({ state: 'visible' });
        assert.ok((await directDialog.innerText()).includes('仅创建 Draft 状态计划'));
        await directDialog.getByRole('button', { name: '取消' }).click();
        await directDialog.waitFor({ state: 'hidden' });
        await page.waitForFunction(opener => document.activeElement === opener, generateOpener);
        await page.keyboard.press('Enter');
        await directDialog.waitFor({ state: 'visible' });
        await page.keyboard.press('Escape');
        await directDialog.waitFor({ state: 'hidden' });
        await page.waitForFunction(opener => document.activeElement === opener, generateOpener);
        assert.deepEqual(directDedupePreviews, [{ scanId: 501, preview: 'read-only' }]);
        assert.deepEqual(forbidden, [], 'No Draft/Generate/Execute/Save/Delete API allowed');
        assert.deepEqual(external, [], 'No external network or NAS access');
        completed += 1;
        console.log('[ORG DEDUPE BROWSER PASS] ' + label);
      } catch (error) {
        console.error('[ORG DEDUPE BROWSER FAIL] ' + label, error);
        await page.screenshot({ path: resolve(OUT, 'failure-' + label + '.png') }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(completed, WIDTHS.length * THEMES.length);
  console.log('[ORG DEDUPE BROWSER] 32/32 cases, 128 screenshots; ' +
    'read-only local Preview POST, no Draft/Generate/Execute/NAS access.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
