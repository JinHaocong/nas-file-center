/**
 * Stage 5C: real Chromium Portal acceptance for Quarantine Restore, Purge
 * and Plan History. Only synthetic GET fixtures; all writes are rejected.
 * Run after Vite build + isolated playwright@1.56.1 install.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';
import { computedContrastRatio } from './computed-contrast.mjs';
import { parseComputedPaintColor, contrastRatioForOpaqueChannels } from './computed-paint-color.mjs';

const BASE_URL = 'http://127.0.0.1:4181';
const OUT = resolve(process.cwd(), 'artifacts/browser-quarantine-plan');
const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
const THEMES = [
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
];
const entry = {
  id: 42, state: 'active',
  original_path: '/visual-fixture/long-named-document.txt',
  quarantine_path: '/visual-fixture/.nas-file-center-trash/42',
  size: 128, hash: null, mtime_ns: 0, device: 1, inode: 2,
  task_id: null, plan_item_id: null,
  quarantined_at: null, expires_at: null, restored_at: null,
  purged_at: null, last_error: null, created_at: null, updated_at: null,
};
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
  '--port', '4181', '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });
let browser;
let completed = 0;
const quarantineErrorPaintCases = [];

async function ready() {
  for (let i = 0; i < 100; i += 1) {
    if (server.exitCode !== null) throw Error('Vite preview exited unexpectedly');
    try { if ((await fetch(BASE_URL + '/login')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Vite preview not ready');
}
function fixture(url) {
  const path = new URL(url).pathname;
  if (path === '/api/auth/me') {
    return { id: 1, username: 'visual-fixture-admin', role: 'admin', is_admin: true };
  }
  if (path === '/api/settings') {
    return { allow_mutation: true, allow_delete: true,
      quarantine_retention_days: 30, safe_mode: false };
  }
  if (path === '/api/quarantine') {
    return { items: [entry], page: 1, page_size: 20, total: 1 };
  }
  if (path === '/api/plans') {
    return { items: [], page: 1, page_size: 20, total: 0 };
  }
  return { items: [], page: 1, page_size: 20, total: 0 };
}

async function inspect(page, theme, width, selector) {
  return page.evaluate(({ theme, width, selector }) => {
    const dialog = document.querySelector(selector);
    const overlay = document.querySelector('.nfc-v2-confirm-overlay');
    if (!dialog || !overlay) throw Error('Radix portal or overlay not rendered');
    const contentStyle = getComputedStyle(dialog);
    const overlayStyle = getComputedStyle(overlay);
    const box = dialog.getBoundingClientRect();
    const failures = [];
    const check = (ok, reason) => { if (!ok) failures.push(reason); };
    check(document.documentElement.dataset.theme === theme, 'Wrong effective theme');
    check(Number(overlayStyle.zIndex) === 1300, 'Scrim z-index ' + overlayStyle.zIndex);
    check(Number(contentStyle.zIndex) === 1301, 'Dialog z-index ' + contentStyle.zIndex);
    check(overlayStyle.backdropFilter === 'none' &&
      (overlayStyle.webkitBackdropFilter === undefined ||
        overlayStyle.webkitBackdropFilter === 'none'), 'Scrim must not blur');
    check(box.left >= -2 && box.right <= width + 2, 'Dialog horizontal overflow');
    check(box.top >= -2 && box.bottom <= innerHeight + 2, 'Dialog vertical overflow');
    check(contentStyle.backgroundColor !== 'rgba(0, 0, 0, 0)',
      'Transparent dialog background');
    // A real dialog must receive pointer hits above its own mask, even on mobile.
    const x = Math.max(1, Math.min(width - 1, box.left + box.width / 2));
    const y = Math.max(1, Math.min(innerHeight - 1, box.top + Math.min(box.height / 2, 100)));
    const hit = document.elementFromPoint(x, y);
    check(Boolean(hit?.closest(selector)), 'Scrim intercepts pointer hits');
    return failures;
  }, { theme, width, selector });
}

/**
 * Real Quarantine GET-503 alert/Retry keyboard audit. Browser computed colors
 * are decoded with the independently tested strict RGB/sRGB/Oklab parser.
 */
async function inspectQuarantineListErrorPaint(page, theme, width) {
  const snapshot = await page.evaluate(() => {
    const alert = document.querySelector('.nfc-v2-quarantine-ledger .nfc-v2-quarantine-error[role="alert"]');
    const retry = alert?.querySelector('button');
    const title = alert?.querySelector('strong');
    const detail = alert?.querySelector('p');
    const label = retry?.querySelector('span');
    if (!alert || !title?.textContent?.includes('获取隔离区列表失败') ||
        !detail?.textContent?.trim() ||
        !retry || !label?.textContent?.includes('重试'))
      throw Error('Missing mounted real Quarantine list failure alert/Retry labels');
    if (document.activeElement !== retry || !retry.matches(':focus-visible') ||
        retry.disabled)
      throw Error('Quarantine list Retry must have actual keyboard-visible enabled focus');
    const alertBox = alert.getBoundingClientRect();
    if (!alertBox.width || !alertBox.height || alertBox.left < -2 ||
        alertBox.right > innerWidth + 2 || alertBox.top < -2 ||
        alertBox.bottom > innerHeight + 2)
      throw Error('Quarantine 503 alert overflows viewport');
    const retryBox = retry.getBoundingClientRect();
    if (!retryBox.width || !retryBox.height || retryBox.left < -2 ||
        retryBox.right > innerWidth + 2 || retryBox.top < -2 ||
        retryBox.bottom > innerHeight + 2)
      throw Error('Quarantine list Retry escapes the visible viewport');
    const ring = getComputedStyle(retry);
    const ringWidth = Number.parseFloat(ring.outlineWidth);
    const ringOffset = Number.parseFloat(ring.outlineOffset);
    if (ring.outlineStyle !== 'solid' || !Number.isFinite(ringWidth) ||
        !Number.isFinite(ringOffset) || ringWidth < 2 || ringOffset < 1)
      throw Error('Quarantine list Retry keyboard focus indicator is not solid/visible');
    const flat = element => {
      const ancestors = [];
      for (let node = element; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.backgroundImage !== 'none' || Number(style.opacity) !== 1 ||
            style.filter !== 'none' || style.backdropFilter !== 'none' ||
            (style.webkitBackdropFilter && style.webkitBackdropFilter !== 'none'))
          throw Error('Unsupported Quarantine alert paint ancestor: ' + node.tagName);
        ancestors.push({ tag: node.tagName, color: style.backgroundColor });
      }
      return { foreground: getComputedStyle(element).color, ancestors };
    };
    return {
      texts: [
        { name: 'error-title', ...flat(title) },
        { name: 'error-detail', ...flat(detail) },
        { name: 'retry-label', ...flat(label) },
      ],
      alertPaint: flat(alert),
      buttonPaint: flat(retry),
      focus: { foreground: ring.outlineColor, width: ringWidth,
        offset: ringOffset, keyboard: true },
    };
  });
  const compose = (paint, name) => {
    const layers = [];
    for (const layer of paint.ancestors) {
      const decoded = parseComputedPaintColor(layer.color);
      if (decoded.alpha > 0) layers.push({ ...layer, ...decoded });
      if (decoded.alpha === 1) break;
    }
    if (!layers.length || layers.at(-1).alpha !== 1)
      throw Error('Quarantine list ' + name + ' lacks opaque painted ancestor');
    let background = [0, 0, 0];
    for (const layer of [...layers].reverse()) {
      background = background.map((value, i) =>
        layer.channels[i] * layer.alpha + value * (1 - layer.alpha));
    }
    return { background, layers: layers.map(({ tag, color, alpha }) => ({ tag, color, alpha })) };
  };
  const wcag = (ink, background) => {
    const foreground = parseComputedPaintColor(ink);
    if (foreground.alpha !== 1)
      throw Error('Translucent Quarantine list ink or ring needs rendered-pixel audit');
    const integer = channels => 'rgb(' + channels.map(Math.round).join(', ') + ')';
    return Math.min(
      contrastRatioForOpaqueChannels(foreground.channels, background),
      computedContrastRatio(integer(foreground.channels), integer(background)),
    );
  };
  const pairs = snapshot.texts.map(pair => {
    const paint = compose(pair, pair.name);
    const contrast = wcag(pair.foreground, paint.background);
    assert.ok(contrast >= 4.5, 'Quarantine list failure/Retry text below 4.5:1: ' +
      JSON.stringify({ width, theme, pair, contrast, paint }));
    return { name: pair.name, foreground: pair.foreground,
      contrast: Number(contrast.toFixed(3)), ...paint };
  });
  const alert = compose(snapshot.alertPaint, 'error-banner');
  const button = compose(snapshot.buttonPaint, 'retry-button');
  const focusPairs = [['error-banner', alert], ['retry-button', button]].map(
    ([name, paint]) => {
      const contrast = wcag(snapshot.focus.foreground, paint.background);
      assert.ok(contrast >= 3, 'Quarantine list Retry outline below 3:1: ' +
        JSON.stringify({ width, theme, name, contrast, paint, focus: snapshot.focus }));
      return { name, contrast: Number(contrast.toFixed(3)), ...paint };
    });
  quarantineErrorPaintCases.push({ width, mode: theme.mode, system: theme.system,
    effective: theme.effective, texts: pairs, focus: snapshot.focus,
    focusPairs });
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
      await context.addInitScript(mode => {
        localStorage.setItem('nfc_theme_mode', mode);
      }, theme.mode);
      const page = await context.newPage();
      const writes = [], outbound = [];
      let failList = false;
      await page.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin !== BASE_URL) {
          outbound.push(url.href);
          await route.abort('blockedbyclient');
          return;
        }
        if (!url.pathname.startsWith('/api/')) {
          await route.continue();
          return;
        }
        if (request.method() !== 'GET') {
          writes.push(request.method() + ' ' + request.url());
          await route.fulfill({ status: 405, contentType: 'application/json',
            body: JSON.stringify({ detail: 'READ_ONLY_VISUAL_FIXTURE' }) });
          return;
        }
        const fail = failList && url.pathname === '/api/quarantine';
        await route.fulfill({ status: fail ? 503 : 200, contentType: 'application/json',
          body: JSON.stringify(fail
            ? { detail: 'Synthetic read-only quarantine listing failure' }
            : fixture(request.url())) });
      });
      const label = theme.mode + '-' + theme.system + '-' + width;
      try {
        await page.goto(BASE_URL + '/quarantine', { waitUntil: 'domcontentloaded' });
        await page.getByRole('button', { name: '恢复', exact: true }).first().click({ timeout: 15000 });
        const restore = page.locator('.nfc-v2-quarantine-dialog');
        await restore.waitFor({ state: 'visible' });
        let errors = await inspect(page, theme.effective, width, '.nfc-v2-quarantine-dialog');
        assert.deepEqual(errors, [], 'Restore ' + label + ': ' + errors.join('; '));
        const choices = restore.locator('input[name="restore-conflict-policy"]');
        assert.equal(await choices.count(), 3, 'Only skip/rename/manual recovery strategies');
        await choices.first().check();
        await page.screenshot({ path: resolve(OUT, 'restore-' + label + '.png') });
        await page.keyboard.press('Escape');
        await restore.waitFor({ state: 'hidden' });
        console.log('[QPLAN BROWSER RESTORE PASS] ' + label);

        await page.getByRole('button', { name: '清除', exact: true }).first().click();
        const purge = page.locator('.nfc-v2-quarantine-dialog');
        await purge.waitFor({ state: 'visible' });
        errors = await inspect(page, theme.effective, width, '.nfc-v2-quarantine-dialog');
        assert.deepEqual(errors, [], 'Purge ' + label + ': ' + errors.join('; '));
        const purgeButton = purge.getByRole('button', { name: '永久清除 (unlink)' });
        assert.equal(await purgeButton.isDisabled(), true, 'Empty DELETE confirmation must fail closed');
        const token = purge.getByPlaceholder('请输入 DELETE');
        await token.fill('delete');
        assert.equal(await purgeButton.isDisabled(), true, 'Lowercase delete must be rejected');
        await token.fill('DELETE');
        assert.equal(await purgeButton.isEnabled(), true, 'Uppercase DELETE enables only the UI button');
        await page.screenshot({ path: resolve(OUT, 'purge-' + label + '.png') });
        await page.keyboard.press('Escape');
        await purge.waitFor({ state: 'hidden' });
        console.log('[QPLAN BROWSER PURGE PASS] ' + label);

        failList = true;
        await page.getByRole('button', { name: '刷新', exact: true }).click();
        await page.getByText('获取隔离区列表失败', { exact: true })
          .waitFor({ state: 'visible', timeout: 30000 });
        await page.screenshot({ path: resolve(OUT, 'quarantine-list-503-' + label + '.png') });
        const retry = page.locator('.nfc-v2-quarantine-ledger .nfc-v2-quarantine-error[role="alert"]')
          .getByRole('button', { name: '重试', exact: true });
        await retry.focus();
        await page.keyboard.press('Tab');
        await page.keyboard.press('Shift+Tab');
        await inspectQuarantineListErrorPaint(page, theme, width);
        if ([390, 1440].includes(width))
          await page.screenshot({ path: resolve(OUT, 'quarantine-list-503-keyboard-' + label + '.png') });
        failList = false;
        await retry.click();
        await page.getByRole('button', { name: '恢复', exact: true })
          .first().waitFor({ state: 'visible' });
        console.log('[QPLAN BROWSER 503 RECOVERY PASS] ' + label);

        await page.goto(BASE_URL + '/plans', { waitUntil: 'domcontentloaded' });
        await page.getByRole('button', { name: '清理计划历史' }).click({ timeout: 15000 });
        const plan = page.locator('.nfc-v2-plan-history-dialog');
        await plan.waitFor({ state: 'visible' });
        errors = await inspect(page, theme.effective, width, '.nfc-v2-plan-history-dialog');
        assert.deepEqual(errors, [], 'Plan cleanup ' + label + ': ' + errors.join('; '));
        const planChoices = plan.locator('input[type="checkbox"]');
        assert.equal(await planChoices.count(), 2, 'Plan cleanup terminal statuses only');
        for (let i = 0; i < 2; i += 1) await planChoices.nth(i).uncheck();
        assert.equal(await plan.getByRole('button', { name: '确认清理' }).isDisabled(), true,
          'No plan statuses selected must disable destructive confirmation');
        await page.screenshot({ path: resolve(OUT, 'plan-history-' + label + '.png') });
        await page.keyboard.press('Escape');
        await plan.waitFor({ state: 'hidden' });
        assert.deepEqual(writes, [], 'Fixture must issue zero mutating requests');
        assert.deepEqual(outbound, [], 'Fixture must never issue outbound or NAS requests');
        completed += 1;
        console.log('[QPLAN BROWSER PLAN PASS] ' + label);
      } catch (error) {
        console.error('[QPLAN BROWSER FAIL] ' + label, error);
        await page.screenshot({ path: resolve(OUT, 'failure-' + label + '.png') }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(completed, 32);
  assert.equal(quarantineErrorPaintCases.length, WIDTHS.length * THEMES.length,
    'All 32 actual Quarantine list failures must have real keyboard focus and painted AA');
  assert.ok(quarantineErrorPaintCases.every(entry =>
    entry.texts.length === 3 && entry.texts.every(pair => pair.contrast >= 4.5) &&
    entry.focus.keyboard && entry.focus.width >= 2 && entry.focus.offset >= 1 &&
    entry.focusPairs.length === 2 &&
    entry.focusPairs.every(pair => pair.contrast >= 3)),
    'Quarantine 503 text and Retry ring must meet both contrast thresholds');
  writeFileSync(resolve(OUT, 'quarantine-list-error-retry-paint-audit.json'),
    JSON.stringify({ total: quarantineErrorPaintCases.length,
      paintedTextPairs: quarantineErrorPaintCases.length * 3,
      paintedFocusPairs: quarantineErrorPaintCases.length * 2,
      scope: 'actual-React-quarantine-503-keyboard-focus-flat-computed-paint-not-pixel-or-human',
      cases: quarantineErrorPaintCases }, null, 2));
  console.log('[QUARANTINE LIST ERROR PAINT] 32/32 alerts, 96 text >=4.5:1, ' +
    '64 keyboard focus/background >=3:1.');
  console.log('[QPLAN BROWSER] 32/32 cases; original 96 screenshots plus 32 list 503 and 8 focus images; read-only, no NAS access.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
