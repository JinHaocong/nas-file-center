/**
 * Pure White Stage 5D-A: actual React/Radix Quarantine Bulk Restore/Purge.
 * The ONLY POST accepted is /api/quarantine/bulk-preview, answered locally
 * with synthetic read-only data. Every other write is denied with HTTP 405.
 * All traffic is restricted to this localhost Vite preview. NEVER use a NAS.
 *
 * Run after npm run build and isolated playwright@1.56.1 installation.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';

const BASE_URL = 'http://127.0.0.1:4182';
const OUT = resolve(process.cwd(), 'artifacts/browser-quarantine-bulk');
const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
const THEMES = [
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
];
const entry = (id, state) => ({
  id, state, original_path: '/visual-fixture/document-' + id + '.txt',
  quarantine_path: '/visual-fixture/.nas-file-center-trash/' + id,
  size: 128, hash: null, mtime_ns: 0, device: 1, inode: id,
  task_id: null, plan_item_id: null, quarantined_at: null, expires_at: null,
  restored_at: null, purged_at: null, last_error: null, created_at: null, updated_at: null,
});
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
  '--port', '4182', '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });
let browser;
let completed = 0;

async function ready() {
  for (let i = 0; i < 100; i += 1) {
    if (server.exitCode !== null) throw Error('Vite preview exited');
    try { if ((await fetch(BASE_URL + '/login')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Vite preview did not become ready');
}

function getFixture(path) {
  if (path === '/api/auth/me') {
    return { id: 1, username: 'bulk-visual-admin', role: 'admin', is_admin: true };
  }
  if (path === '/api/settings') {
    return { allow_mutation: true, allow_delete: true, safe_mode: false };
  }
  if (path === '/api/quarantine') {
    return {
      items: [entry(42, 'active'), entry(43, 'active'), entry(44, 'restored')],
      page: 1, page_size: 20, total: 3,
    };
  }
  return { items: [], total: 0, page: 1, page_size: 20 };
}

function previewFixture(payload, ordinal) {
  assert.deepEqual(payload.entry_ids, [42, 43], 'Preview must use exact selected active IDs');
  assert.ok(payload.action === 'restore' || payload.action === 'purge');
  if (payload.action === 'restore') {
    assert.ok(['skip', 'rename'].includes(payload.conflict_policy));
  } else {
    assert.equal(payload.conflict_policy, undefined);
  }
  // Restore/skip is blocked; Restore/rename is eligible.
  // Purge's first Preview is eligible; its second Preview is blocked.
  const blocked = payload.action === 'restore'
    ? payload.conflict_policy === 'skip'
    : ordinal === 2;
  return {
    action: payload.action,
    entry_ids: [42, 43],
    eligible_count: blocked ? 1 : 2,
    blocked_count: blocked ? 1 : 0,
    preview_digest: 'bulk-visual-fixture-digest-' + payload.action + '-' + ordinal,
    items: [42, 43].map(id => ({
      entry_id: id, eligible: !blocked || id === 42,
      reason: blocked && id === 43 ? 'VISUAL_FIXTURE_BLOCKED' : null,
      conflict_policy: payload.action === 'restore' ? payload.conflict_policy : undefined,
      purge_semantics: payload.action === 'purge' ? 'unlink_v1' : undefined,
      mutation_blockers: blocked && id === 43 ? ['VISUAL_FIXTURE_BLOCKED'] : [],
      survivor_status: id === 42 ? 'found' : 'none',
      survivor_scope: 'indexed_roots_only',
      hardlink_survivor_paths: id === 42 ? ['/visual-fixture/survivor.txt'] : [],
      independent_copy_paths: id === 42 ? ['/visual-fixture/independent.txt'] : [],
    })),
  };
}

async function inspect(page, theme, width, selector) {
  return page.evaluate(({ theme, width, selector }) => {
    const dialog = document.querySelector(selector);
    const overlay = document.querySelector('.nfc-v2-confirm-overlay');
    if (!dialog || !overlay) throw Error('Missing actual bulk Radix Portal');
    const ds = getComputedStyle(dialog);
    const os = getComputedStyle(overlay);
    const rect = dialog.getBoundingClientRect();
    const expected = theme === 'dark' ? 'rgb(36, 36, 34)' : 'rgb(255, 255, 255)';
    const errors = [];
    const check = (ok, message) => { if (!ok) errors.push(message); };
    check(document.documentElement.dataset.theme === theme, 'Wrong effective theme');
    check(Number(os.zIndex) === 1300, 'Overlay z-index ' + os.zIndex);
    check(Number(ds.zIndex) === 1301, 'Dialog z-index ' + ds.zIndex);
    check(os.backdropFilter === 'none' &&
      (os.webkitBackdropFilter === undefined || os.webkitBackdropFilter === 'none'),
    'Scrim must not blur');
    check(ds.backgroundColor === expected, 'Dialog surface ' + ds.backgroundColor);
    check(rect.left >= -2 && rect.right <= width + 2,
      'Dialog horizontal overflow: ' + JSON.stringify(rect.toJSON()));
    check(rect.top >= -2 && rect.bottom <= innerHeight + 2,
      'Dialog vertical overflow: ' + JSON.stringify(rect.toJSON()));
    const x = Math.max(1, Math.min(width - 1, rect.left + rect.width / 2));
    const y = Math.max(1, Math.min(innerHeight - 1, rect.top + Math.min(rect.height / 2, 100)));
    check(Boolean(document.elementFromPoint(x, y)?.closest(selector)),
      'Scrim intercepts clicks on dialog');
    return errors;
  }, { theme, width, selector });
}

async function assertPurgeFooterAndScroll(page, width, state) {
  const failures = await page.evaluate(({ width, state }) => {
    const fail = [];
    const check = (condition, text) => { if (!condition) fail.push(text); };
    const modal = document.querySelector('.nfc-quarantine-bulk-purge-modal');
    const header = modal?.querySelector(':scope > .nfc-v2-dialog-heading');
    const body = modal?.querySelector(':scope > .nfc-v2-quarantine-bulk-body');
    const insetContent = body?.querySelector('.nfc-v2-quarantine-bulk-note');
    const footer = modal?.querySelector(':scope > .nfc-v2-confirm-actions');
    const token = body?.querySelector('.nfc-v2-quarantine-bulk-token input');
    const button = [...(footer?.querySelectorAll('button') || [])]
      .find(el => el.textContent?.includes('生成永久删除 Draft'));
    const modalBox = modal?.getBoundingClientRect();
    const headerBox = header?.getBoundingClientRect();
    const bodyBox = body?.getBoundingClientRect();
    const insetBox = insetContent?.getBoundingClientRect();
    const footerBox = footer?.getBoundingClientRect();
    const tokenBox = token?.getBoundingClientRect();
    const buttonBox = button?.getBoundingClientRect();
    const gutter = width < 768 ? 16 : 22;
    check(Boolean(modalBox && headerBox && bodyBox && footerBox && buttonBox),
      'Missing purge scroll layout/header/body/footer');
    if (modalBox && headerBox && bodyBox && footerBox && buttonBox) {
      check(footerBox.top >= bodyBox.bottom - 2 &&
        footerBox.bottom <= Math.min(modalBox.bottom, innerHeight) + 2,
        'Dangerous Draft action footer clipped below mobile viewport');
      check(buttonBox.top >= footerBox.top - 2 &&
        buttonBox.bottom <= Math.min(footerBox.bottom, innerHeight) + 2,
        'Purge Draft action is not visible in persistent footer');
      check(headerBox.bottom <= bodyBox.top + 2,
        'Fixed purge header overlaps diagnostics');
      check(Boolean(insetBox && insetBox.left >= modalBox.left + gutter &&
        insetBox.right <= modalBox.right - gutter),
        'Purge body contents must align with dialog heading gutters');
      if (width <= 390) {
        check(body.scrollHeight > body.clientHeight + 15,
          'Long mobile purge Preview must scroll within the body');
      }
      if (state === 'bottom') {
        check(Boolean(tokenBox && tokenBox.top >= bodyBox.top - 2 &&
          tokenBox.bottom <= bodyBox.bottom + 2),
          'Exact DELETE input cannot be reached inside body scroller');
        check(Boolean(token?.value === 'DELETE'), 'Exact confirmation token lost on scroll');
      }
    }
    return fail;
  }, { width, state });
  assert.deepEqual(failures, [], 'Purge ' + state + '-' + width + ': ' + failures.join('; '));
}

async function assertDialog(page, theme, width, selector, label) {
  const failures = await inspect(page, theme, width, selector);
  assert.deepEqual(failures, [], label + ': ' + failures.join('; '));
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
      const previewCalls = { restore: 0, purge: 0 };
      const forbidden = [];
      const external = [];
      // One universal guard: no requests to remote hosts, no unmocked API calls.
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
        if (request.method() === 'POST' && url.pathname === '/api/quarantine/bulk-preview') {
          try {
            const payload = request.postDataJSON();
            const ordinal = ++previewCalls[payload.action];
            const result = previewFixture(payload, ordinal);
            await route.fulfill({ status: 200, contentType: 'application/json',
              body: JSON.stringify(result) });
          } catch (error) {
            forbidden.push('Invalid synthetic preview: ' + String(error));
            await route.fulfill({ status: 422, contentType: 'application/json',
              body: JSON.stringify({ detail: 'INVALID_VISUAL_FIXTURE_PREVIEW' }) });
          }
          return;
        }
        forbidden.push(request.method() + ' ' + url.pathname);
        await route.fulfill({ status: 405, contentType: 'application/json',
          body: JSON.stringify({ detail: 'READ_ONLY_BROWSER_FIXTURE' }) });
      });

      const label = theme.mode + '-' + theme.system + '-' + width;
      const restoreSelector = '.nfc-quarantine-bulk-restore-modal';
      const purgeSelector = '.nfc-quarantine-bulk-purge-modal';
      try {
        await page.goto(BASE_URL + '/quarantine', { waitUntil: 'domcontentloaded' });
        const restoreAction = page.getByRole('button', { name: '批量恢复', exact: true });
        const purgeAction = page.getByRole('button', { name: '批量永久删除', exact: true });
        assert.equal(await restoreAction.isDisabled(), true, 'No selected entries: restore locked');
        assert.equal(await purgeAction.isDisabled(), true, 'No selected entries: purge locked');
        await page.getByRole('button', { name: '选择本页 active (2)' }).click();
        assert.equal(await restoreAction.isEnabled(), true);
        assert.equal(await purgeAction.isEnabled(), true);

        await restoreAction.click();
        const restore = page.locator(restoreSelector);
        await restore.waitFor({ state: 'visible' });
        await assertDialog(page, theme.effective, width, restoreSelector, 'Restore ' + label);
        const generateRestore = restore.getByRole('button', { name: '生成 Draft' });
        assert.equal(await generateRestore.isDisabled(), true, 'Restore requires fresh Preview');
        const policies = restore.locator('input[name="bulk-restore-policy"]');
        assert.equal(await policies.count(), 2, 'Only skip and rename allowed');
        assert.equal(await policies.nth(0).isChecked(), true, 'Skip must be default');
        await restore.getByRole('button', { name: '重新 Preview' }).click();
        await restore.getByText('Blocked 1').waitFor();
        assert.equal(await generateRestore.isDisabled(), true,
          'Any blocked restore member must prevent whole Draft');
        assert.ok((await restore.innerText()).includes('VISUAL_FIXTURE_BLOCKED'));
        await page.screenshot({ path: resolve(OUT, 'restore-blocked-' + label + '.png') });
        await policies.nth(1).check();
        assert.equal(await generateRestore.isDisabled(), true, 'Policy change invalidates Preview');
        await restore.getByRole('button', { name: '重新 Preview' }).click();
        await restore.getByText('Eligible 2').waitFor();
        assert.equal(await generateRestore.isEnabled(), true, 'Eligible rename Preview allows Draft UI');
        await assertDialog(page, theme.effective, width, restoreSelector, 'Restore ready ' + label);
        await page.screenshot({ path: resolve(OUT, 'restore-ready-' + label + '.png') });
        await page.keyboard.press('Escape');
        await restore.waitFor({ state: 'hidden' });
        assert.equal(await purgeAction.isEnabled(), true, 'Selection remains after cancelling');

        await purgeAction.click();
        const purge = page.locator(purgeSelector);
        await purge.waitFor({ state: 'visible' });
        await assertDialog(page, theme.effective, width, purgeSelector, 'Purge ' + label);
        const generatePurge = purge.getByRole('button', { name: '生成永久删除 Draft' });
        assert.equal(await generatePurge.isDisabled(), true, 'Purge requires Preview and DELETE');
        await purge.getByRole('button', { name: '重新 Preview' }).click();
        await purge.getByText('Eligible 2').waitFor();
        assert.ok((await purge.innerText()).includes('hard link'),
          'Hardlink survivor advisory must remain visible');
        assert.ok((await purge.innerText()).includes('独立副本'),
          'Independent same-content copy advisory must remain visible');
        const token = purge.getByPlaceholder('请输入 DELETE');
        for (const value of ['delete', 'DELETE ', ' Delete']) {
          await token.fill(value);
          assert.equal(await generatePurge.isDisabled(), true, 'Invalid DELETE token: ' + value);
        }
        await token.fill('DELETE');
        assert.equal(await generatePurge.isEnabled(), true,
          'Only exact uppercase DELETE unlocks Draft UI, never auto-submits');
        await assertDialog(page, theme.effective, width, purgeSelector, 'Purge ready ' + label);
        await assertPurgeFooterAndScroll(page, width, 'ready');
        await page.screenshot({ path: resolve(OUT, 'purge-ready-' + label + '.png') });
        // Read the exact DELETE gate inside the scrollable body without losing
        // the real footer, digest-bound Preview or any selected entry.
        await purge.locator('.nfc-v2-quarantine-bulk-body').evaluate(el => {
          el.scrollTop = el.scrollHeight;
        });
        await assertPurgeFooterAndScroll(page, width, 'bottom');
        await page.screenshot({ path: resolve(OUT, 'purge-review-bottom-' + label + '.png') });
        assert.equal(await generatePurge.isEnabled(), true,
          'Scrolling must not reset exact DELETE/Draft readiness');
        await purge.getByRole('button', { name: '重新 Preview' }).click();
        await purge.getByText('Blocked 1').waitFor();
        assert.equal(await generatePurge.isDisabled(), true,
          'Blocked second Preview must revoke both digest and DELETE');
        assert.ok((await purge.innerText()).includes('VISUAL_FIXTURE_BLOCKED'));
        await page.screenshot({ path: resolve(OUT, 'purge-blocked-' + label + '.png') });
        await page.keyboard.press('Escape');
        await purge.waitFor({ state: 'hidden' });

        assert.deepEqual(previewCalls, { restore: 2, purge: 2 });
        assert.deepEqual(forbidden, [], 'No mutating Plan/Execute/Delete requests allowed');
        assert.deepEqual(external, [], 'No request may leave localhost Vite');
        completed += 1;
        console.log('[BULK BROWSER PASS] ' + label);
      } catch (error) {
        console.error('[BULK BROWSER FAIL] ' + label, error);
        await page.screenshot({ path: resolve(OUT, 'failure-' + label + '.png') }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(completed, WIDTHS.length * THEMES.length);
  console.log('[BULK BROWSER] 32/32 viewport/theme cases; 160 screenshots; ' +
    'only synthetic Preview POST permitted, no Plan/Execute/Delete or NAS access.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
