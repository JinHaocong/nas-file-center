/**
 * Pure White Stage 5E-G: real Media search/filter/pagination, queue dialogs,
 * selection reset and recoverable GET failure in Chromium.
 * Only localhost Vite; synthetic GET fixtures; deny mutations with HTTP 405.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';
import { computedContrastRatio } from './computed-contrast.mjs';
import { parseComputedPaintColor, contrastRatioForOpaqueChannels } from './computed-paint-color.mjs';
import { visualAdminFixture, visualSafeSettingsFixture } from './visual-fixtures.mjs';

const BASE = 'http://127.0.0.1:4189';
const OUT = resolve(process.cwd(), 'artifacts/browser-media-ledger-states');
const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
const THEMES = [
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
];
const ROOT = '/synthetic-media-test/Camera-Archive/' +
  'VeryLongUnbrokenCameraArchiveFolder'.repeat(5);
const BLOCKED = ROOT + '/blocked-root';
const stamp = '2026-10-12T08:30:00Z';
const assets = Array.from({ length: 51 }, (_, i) => {
  const id = 901 + i;
  const video = i === 1;
  const corrupt = i === 1;
  const unknown = i === 2;
  return {
    id, indexed_path_id: 5000 + id, root_key: ROOT,
    path: ROOT + '/2026/Original/' + 'LosslessMasterFilename'.repeat(6) +
      '-' + id + (video ? '.mp4' : '.raw'),
    relative_path: '2026/Original/' + id, basename: 'Master-' + id,
    size: 7785234567, mtime_ns: 1700000000000000000,
    media_kind: video ? 'video' : 'image',
    width: video ? 3840 : 8192, height: video ? 2160 : 5464,
    format: video ? 'MP4' : 'RAW',
    date_taken: '2026-10-12', camera: 'Synthetic Test Device',
    orientation: 1, duration_seconds: video ? 420.5 : null,
    codec: video ? 'HEVC' : null, bitrate: video ? 24000000 : null,
    fps: video ? 59.94 : null, audio_codec: video ? 'AAC' : null,
    integrity_status: corrupt ? 'corrupt' : unknown ? 'unknown' : 'healthy',
    integrity_reason_code: corrupt ? 'FROZEN_SHA256_CONFLICT' : null,
    integrity_detail: null,
    verification_status: corrupt ? 'changed' : unknown ? 'unverified' : 'verified',
    verification_reason_code: null, verification_detail: null,
    verification_checked_at: stamp, can_direct_delete: corrupt,
    probed_at: stamp,
  };
});
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
  '--port', '4189', '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });
let browser;
let passed = 0;
const mediaErrorPaintCases = [];

async function ready() {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw Error('Vite preview exited');
    try { if ((await fetch(BASE + '/media')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Local Vite preview unavailable');
}
function fixture(url) {
  if (url.pathname === '/api/auth/me') return visualAdminFixture('media-readonly-visual-fixture');
  if (url.pathname === '/api/settings') return visualSafeSettingsFixture();
  if (url.pathname === '/api/indexes') return {
    items: [
      { id: 701, root: ROOT, path_state: 'available', files: 5000, folders: 20,
        has_active_job: false, can_remove: true },
      { id: 702, root: BLOCKED, path_state: 'blocked', files: 10, folders: 2,
        has_active_job: false, can_remove: false },
    ], total: 2, page: 1, page_size: 500,
  };
  if (url.pathname === '/api/media/summary') return {
    total: assets.length, image: 50, video: 1,
    healthy: 49, corrupt: 1, unknown: 1,
    verification_unverified: 1, verification_baseline: 0,
    verification_verified: 49, verification_changed: 1, verification_unknown: 0,
  };
  if (url.pathname === '/api/media') {
    const p = url.searchParams;
    const page = Number(p.get('page') || 1), size = Number(p.get('page_size') || 50);
    const matches = assets.filter(item =>
      (!p.get('root_key') || item.root_key === p.get('root_key')) &&
      (!p.get('media_kind') || item.media_kind === p.get('media_kind')) &&
      (!p.get('integrity_status') || item.integrity_status === p.get('integrity_status')) &&
      (!p.get('verification_status') || item.verification_status === p.get('verification_status')) &&
      (!p.get('search') || item.path.includes(p.get('search'))));
    return { items: matches.slice((page - 1) * size, page * size),
      total: matches.length, page, page_size: size };
  }
  return { items: [], total: 0, page: 1, page_size: 50 };
}
async function inspect(page, theme, width, state) {
  const failures = await page.evaluate(({ theme, width, state }) => {
    const errors = [];
    const check = (ok, reason) => { if (!ok) errors.push(reason); };
    const inside = node => {
      if (!node) return false;
      const r = node.getBoundingClientRect();
      return r.width > 0 && r.left >= -2 && r.right <= width + 2;
    };
    check(document.documentElement.dataset.theme === theme, 'Wrong effective theme');
    check(inside(document.querySelector('.nfc-page-content')), 'Media workspace overflow');
    check(inside(document.querySelector('.nfc-v2-media-page')), 'Media page overflow');
    check(inside(document.querySelector('.nfc-v2-media-filters')), 'Media filter bar overflow');
    check(inside(document.querySelector('.nfc-v2-media-search')), 'Media search overflow');
    if (state === 'analyze' || state === 'verify' || state === 'analyze-expanded') {
      const dialog = document.querySelector('.nfc-v2-media-queue-dialog');
      const overlay = document.querySelector('.nfc-v2-confirm-overlay');
      check(inside(dialog), state + ' media queue dialog overflow');
      const rect = dialog?.getBoundingClientRect();
      check(Boolean(rect && rect.top >= -2 && rect.bottom <= innerHeight + 2),
        state + ' media queue vertical overflow');
      check(getComputedStyle(overlay).backdropFilter === 'none',
        state + ' overlay must remain dim-only');
      check(Number(getComputedStyle(overlay).zIndex) === 1300,
        state + ' media overlay z-index');
      check(Number(getComputedStyle(dialog).zIndex) === 1301,
        state + ' media dialog z-index');
      const centerHit = document.elementFromPoint(width / 2, innerHeight / 2);
      check(Boolean(centerHit?.closest('.nfc-v2-media-queue-dialog')),
        state + ' dialog pointer hit');
      const body = dialog?.querySelector('.nfc-v2-media-queue-body');
      const note = body?.querySelector('.nfc-form-note');
      const fieldset = body?.querySelector('.nfc-v2-media-root-options');
      const gutter = width < 768 ? 16 : 22;
      for (const [name, node] of [['help copy', note], ['root fieldset', fieldset]]) {
        const box = node?.getBoundingClientRect();
        check(Boolean(box && rect && box.left >= rect.left + gutter &&
          box.right <= rect.right - gutter), state + ' ' + name + ' content gutter');
      }
      for (const row of document.querySelectorAll('.nfc-v2-media-root-options label'))
        check(inside(row), state + ' long root option overflow');
      const optionRows = [...(dialog?.querySelectorAll('.nfc-v2-media-root-option') || [])];
      check(optionRows.length === 2, state + ' expected two read-only roots');
      for (const row of optionRows) {
        const preview = row.querySelector('.nfc-v2-media-root-path');
        const disclosure = row.querySelector('.nfc-v2-media-root-reveal');
        const bounds = row.getBoundingClientRect();
        check(inside(row), state + ' root container overflows viewport');
        check(Boolean(preview && disclosure), state + ' full-path disclosure missing');
        const css = preview && getComputedStyle(preview);
        check(Boolean(css && css.webkitLineClamp === '2'), state + ' long path lacks two-line limit');
        if (state !== 'analyze-expanded') {
          check(Boolean(disclosure && !disclosure.open && bounds.height <= 110),
            state + ' collapsed root consumes excessive vertical space');
        }
      }
      if (state === 'analyze-expanded') {
        const first = optionRows[0];
        const full = first?.querySelector('.nfc-v2-media-root-reveal[open] p');
        const preview = first?.querySelector('.nfc-v2-media-root-path');
        check(Boolean(full && full.textContent === preview?.textContent),
          'Expanded Media root path must preserve exact original text');
        check(Boolean(first?.querySelector('input')?.checked),
          'Disclosure keyboard interaction unexpectedly changed root selection');
        check(Boolean(optionRows[1]?.querySelector('input')?.disabled),
          'Blocked root must remain disabled in expanded state');
      }
    } else if (state === 'failure') {
      check(inside(document.querySelector('.nfc-v2-media-loading[role="alert"]')),
        'Media GET 503 error alert overflow');
    } else {
      if (state !== 'empty') {
        check(inside(document.querySelector('.nfc-console-pagination')),
          'Media pagination overflow');
        if (width < 768) {
          for (const card of document.querySelectorAll('.nfc-v2-media-mobile .nfc-index-mobile-card'))
            check(inside(card), 'Media long-path card overflow');
        } else {
          const scroller = document.querySelector('.nfc-v2-media-table-scroll');
          check(inside(scroller), 'Media desktop scrollport overflow');
          check(['auto', 'scroll'].includes(getComputedStyle(scroller).overflowX),
            'Media table must own horizontal overflow');
        }
      }
    }
    return errors;
  }, { theme, width, state });
  assert.deepEqual(failures, [], state + '-' + width + ': ' + failures.join('; '));
}

/**
 * Actual React Media GET-503 error message is a direct flex text node.
 * Verify its inherited computed ink and the keyboard-visible Retry control
 * over fail-closed, alpha-composited, opaque ancestor backgrounds.
 */
async function inspectMediaListErrorPaint(page, theme, width) {
  const snapshot = await page.evaluate(() => {
    const alert = document.querySelector('.nfc-v2-media-loading[role="alert"]');
    const retry = alert?.querySelector('button');
    const label = retry?.querySelector('span');
    // The real Media message is a direct text child of the flex alert;
    // the computed ink is inherited from the alert, not the button.
    const message = [...(alert?.childNodes || [])]
      .filter(node => node.nodeType === Node.TEXT_NODE)
      .map(node => node.textContent || '').join(' ').trim();
    if (!alert || !message.includes('媒体列表读取失败') ||
        !message.includes('Synthetic media listing failure') ||
        !retry || !label?.textContent?.includes('重试'))
      throw Error('Missing mounted real Media 503 message/Retry label');
    if (document.activeElement !== retry || !retry.matches(':focus-visible') ||
        retry.disabled)
      throw Error('Media list Retry must have actual keyboard-visible enabled focus');
    const retryBox = retry.getBoundingClientRect();
    if (!retryBox.width || !retryBox.height || retryBox.left < -2 ||
        retryBox.right > innerWidth + 2 || retryBox.top < -2 ||
        retryBox.bottom > innerHeight + 2)
      throw Error('Media list Retry escapes the visible viewport');
    const ring = getComputedStyle(retry);
    const ringWidth = Number.parseFloat(ring.outlineWidth);
    const ringOffset = Number.parseFloat(ring.outlineOffset);
    if (ring.outlineStyle !== 'solid' || !Number.isFinite(ringWidth) ||
        !Number.isFinite(ringOffset) || ringWidth < 2 || ringOffset < 1)
      throw Error('Media list Retry keyboard focus indicator is not solid/visible');
    const flat = element => {
      const ancestors = [];
      for (let node = element; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.backgroundImage !== 'none' || Number(style.opacity) !== 1 ||
            style.filter !== 'none' || style.backdropFilter !== 'none' ||
            (style.webkitBackdropFilter && style.webkitBackdropFilter !== 'none'))
          throw Error('Unsupported Media alert paint ancestor: ' + node.tagName);
        ancestors.push({ tag: node.tagName, color: style.backgroundColor });
      }
      return { foreground: getComputedStyle(element).color, ancestors };
    };
    return {
      texts: [
        { name: 'error-message', ...flat(alert) },
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
      throw Error('Media list ' + name + ' lacks opaque painted ancestor');
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
      throw Error('Translucent Media list ink or ring needs rendered-pixel audit');
    const integer = channels => 'rgb(' + channels.map(Math.round).join(', ') + ')';
    return Math.min(
      contrastRatioForOpaqueChannels(foreground.channels, background),
      computedContrastRatio(integer(foreground.channels), integer(background)),
    );
  };
  const pairs = snapshot.texts.map(pair => {
    const paint = compose(pair, pair.name);
    const contrast = wcag(pair.foreground, paint.background);
    assert.ok(contrast >= 4.5, 'Media list failure/Retry text below 4.5:1: ' +
      JSON.stringify({ width, theme, pair, contrast, paint }));
    return { name: pair.name, foreground: pair.foreground,
      contrast: Number(contrast.toFixed(3)), ...paint };
  });
  const alert = compose(snapshot.alertPaint, 'error-banner');
  const button = compose(snapshot.buttonPaint, 'retry-button');
  const focusPairs = [['error-banner', alert], ['retry-button', button]].map(
    ([name, paint]) => {
      const contrast = wcag(snapshot.focus.foreground, paint.background);
      assert.ok(contrast >= 3, 'Media list Retry outline below 3:1: ' +
        JSON.stringify({ width, theme, name, contrast, paint, focus: snapshot.focus }));
      return { name, contrast: Number(contrast.toFixed(3)), ...paint };
    });
  mediaErrorPaintCases.push({ width, mode: theme.mode, system: theme.system,
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
      await context.addInitScript(mode =>
        localStorage.setItem('nfc_theme_mode', mode), theme.mode);
      const page = await context.newPage();
      const writes = [], outbound = [], listQueries = [];
      let failList = false;
      await page.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url());
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
            body: JSON.stringify({ detail: 'READ_ONLY_MEDIA_FIXTURE' }) });
          return;
        }
        if (url.pathname === '/api/media') listQueries.push(url.search);
        const fail = failList && url.pathname === '/api/media';
        await route.fulfill({ status: fail ? 503 : 200,
          contentType: 'application/json',
          body: JSON.stringify(fail
            ? { detail: 'Synthetic media listing failure' } : fixture(url)) });
      });
      const label = theme.mode + '-' + theme.system + '-' + width;
      const record = width < 768
        ? '.nfc-v2-media-mobile .nfc-index-mobile-card'
        : '.nfc-v2-media-table tbody tr';
      const destructive = page.getByRole('button', { name: /永久删除损坏文件/ });
      const filter = index => page.locator('.nfc-v2-media-filters > label').nth(index).locator('select');
      try {
        await page.goto(BASE + '/media', { waitUntil: 'domcontentloaded' });
        await page.locator(record).first().waitFor({ state: 'visible' });
        assert.equal(await page.locator(record).count(), 50, 'Page one must show 50 media records');
        const checkbox = id => page.getByRole('checkbox', {
          name: '选择可永久删除损坏媒体 #' + id,
        });
        assert.equal(await checkbox(901).isDisabled(), true,
          'Healthy media must not be selectable');
        assert.equal(await checkbox(902).isEnabled(), true,
          'Corrupt media with frozen evidence may be selected');
        assert.equal(await checkbox(903).isDisabled(), true,
          'Unknown media must never be selectable');
        await checkbox(902).check();
        assert.match(await destructive.innerText(), /\(1\)/);
        await inspect(page, theme.effective, width, 'dense');
        await page.screenshot({ path: resolve(OUT, 'dense-media-' + label + '.png') });

        await page.getByRole('button', { name: '下一页' }).click();
        await page.waitForFunction(selector =>
          document.querySelectorAll(selector).length === 1, record);
        assert.equal(await page.locator(record).count(), 1);
        assert.match(await destructive.innerText(), /\(0\)/);
        assert.ok(listQueries.some(q => new URLSearchParams(q).get('page') === '2'),
          'Media page 2 must request the server');
        await inspect(page, theme.effective, width, 'page2');
        await page.screenshot({ path: resolve(OUT, 'media-page-two-' + label + '.png') });

        await filter(1).selectOption('video');
        await page.waitForFunction(selector =>
          document.querySelectorAll(selector).length === 1, record);
        await filter(2).selectOption('corrupt');
        await filter(3).selectOption('changed');
        await page.waitForFunction(selector => {
          const rows = document.querySelectorAll(selector);
          return rows.length === 1 && rows[0].textContent?.includes('902');
        }, record);
        assert.equal(await page.locator(record).count(), 1);
        assert.ok((await page.locator(record).first().innerText()).includes('902'),
          'Compound filters should show only frozen-evidence corrupt video');
        assert.match(await destructive.innerText(), /\(0\)/);
        assert.ok(listQueries.some(q => {
          const p = new URLSearchParams(q);
          return p.get('page') === '1' && p.get('media_kind') === 'video' &&
            p.get('integrity_status') === 'corrupt' &&
            p.get('verification_status') === 'changed';
        }), 'Compound Media filters must reset to page=1');
        await inspect(page, theme.effective, width, 'filtered');
        await page.screenshot({ path: resolve(OUT, 'media-compound-filters-' + label + '.png') });

        const search = page.getByRole('searchbox', { name: '搜索路径' });
        await search.fill('NeverExistsMediaFixtureToken');
        await page.getByRole('button', { name: '搜索', exact: true }).click();
        await page.getByText('暂无媒体分析结果', { exact: true })
          .waitFor({ state: 'visible' });
        assert.ok(listQueries.some(q => new URLSearchParams(q).get('search') ===
          'NeverExistsMediaFixtureToken'), 'Applied search must be server-driven');
        assert.match(await destructive.innerText(), /\(0\)/);
        await inspect(page, theme.effective, width, 'empty');
        await page.screenshot({ path: resolve(OUT, 'media-empty-search-' + label + '.png') });

        await page.getByRole('button', { name: '分析媒体', exact: true }).click();
        const dialog = page.locator('.nfc-v2-media-queue-dialog');
        await dialog.waitFor({ state: 'visible' });
        const queue = dialog.getByRole('button', { name: '加入分析队列' });
        assert.equal(await queue.isDisabled(), true, 'No root selected must block media queue');
        const options = dialog.locator('.nfc-v2-media-root-options input');
        assert.equal(await options.count(), 2);
        assert.equal(await options.nth(1).isDisabled(), true, 'Blocked root must remain disabled');
        await options.nth(0).check();
        assert.equal(await queue.isEnabled(), true, 'Available root selection should enable queue');
        await inspect(page, theme.effective, width, 'analyze');
        await page.screenshot({ path: resolve(OUT, 'media-analyze-dialog-' + label + '.png') });
        // Native disclosure is not nested inside the checkbox label: Enter
        // expands the full path but may never change authorized root selection.
        const fullPath = dialog.locator('.nfc-v2-media-root-reveal').first();
        await fullPath.locator('summary').focus();
        await page.keyboard.press('Enter');
        await page.waitForFunction(() => Boolean(document.querySelector(
          '.nfc-v2-media-queue-dialog .nfc-v2-media-root-reveal[open]')));
        assert.equal(await fullPath.locator('p').innerText(), ROOT);
        assert.equal(await options.nth(0).isChecked(), true);
        assert.equal(await options.nth(1).isDisabled(), true);
        await inspect(page, theme.effective, width, 'analyze-expanded');
        await page.screenshot({ path: resolve(OUT, 'media-expanded-root-' + label + '.png') });
        await page.keyboard.press('Enter');
        await page.waitForFunction(() => !document.querySelector(
          '.nfc-v2-media-queue-dialog .nfc-v2-media-root-reveal[open]'));
        await inspect(page, theme.effective, width, 'analyze');
        await page.keyboard.press('Escape');
        await dialog.waitFor({ state: 'hidden' });

        await page.getByRole('button', { name: 'SHA256 校验', exact: true }).click();
        await dialog.waitFor({ state: 'visible' });
        assert.equal(await dialog.getByRole('button', { name: '加入校验队列' }).isDisabled(),
          true, 'New verify dialog must not inherit analyze selection');
        await options.nth(0).check();
        assert.equal(await dialog.getByRole('button', { name: '加入校验队列' }).isEnabled(),
          true, 'Available root should enable verify queue');
        await inspect(page, theme.effective, width, 'verify');
        await page.screenshot({ path: resolve(OUT, 'media-verify-dialog-' + label + '.png') });
        await page.keyboard.press('Escape');
        await dialog.waitFor({ state: 'hidden' });

        await search.fill('');
        await page.getByRole('button', { name: '搜索', exact: true }).click();
        await filter(1).selectOption('');
        await filter(2).selectOption('');
        await filter(3).selectOption('');
        await page.locator(record).first().waitFor({ state: 'visible' });
        failList = true;
        await page.getByRole('button', { name: '刷新', exact: true }).click();
        await page.getByText(/媒体列表读取失败/).waitFor({ state: 'visible' });
        await inspect(page, theme.effective, width, 'failure');
        await page.screenshot({ path: resolve(OUT, 'media-list-503-' + label + '.png') });
        // Keep the existing 503 screenshot unchanged; drive real keyboard
        // modality before inspecting the actual mounted Retry paint.
        const retry = page.locator('.nfc-v2-media-loading[role="alert"]')
          .getByRole('button', { name: '重试', exact: true });
        await retry.focus();
        await page.keyboard.press('Tab');
        await page.keyboard.press('Shift+Tab');
        await inspectMediaListErrorPaint(page, theme, width);
        if ([390, 1440].includes(width))
          await page.screenshot({ path: resolve(OUT, 'media-list-503-keyboard-' + label + '.png') });
        failList = false;
        await page.getByRole('button', { name: '重试', exact: true }).click();
        await page.locator(record).first().waitFor({ state: 'visible' });
        assert.equal(await page.locator(record).count(), 50,
          'Media list must restore on explicit GET retry');
        assert.deepEqual(writes, [], 'No mutating API request may be sent');
        assert.deepEqual(outbound, [], 'No off-origin or NAS request permitted');
        passed++;
        console.log('[MEDIA LEDGER STATES PASS] ' + label);
      } catch (err) {
        console.error('[MEDIA LEDGER STATES FAIL] ' + label, err);
        await page.screenshot({ path: resolve(OUT, 'failure-' + label + '.png') })
          .catch(() => {});
        throw err;
      } finally { await context.close(); }
    }
  }
  assert.equal(passed, WIDTHS.length * THEMES.length);
  assert.equal(mediaErrorPaintCases.length, WIDTHS.length * THEMES.length,
    'All 32 actual Media 503 alerts require painted focus measurements');
  assert.ok(mediaErrorPaintCases.every(entry =>
    entry.texts.length === 2 && entry.texts.every(pair => pair.contrast >= 4.5) &&
    entry.focus.keyboard && entry.focus.width >= 2 && entry.focus.offset >= 1 &&
    entry.focusPairs.length === 2 &&
    entry.focusPairs.every(pair => pair.contrast >= 3)),
    'Media 503 message/Retry text and keyboard outline must pass AA');
  writeFileSync(resolve(OUT, 'media-list-error-retry-paint-audit.json'),
    JSON.stringify({ total: mediaErrorPaintCases.length,
      paintedTextPairs: mediaErrorPaintCases.length * 2,
      paintedFocusPairs: mediaErrorPaintCases.length * 2,
      scope: 'actual-React-media-503-direct-text-keyboard-focus-flat-computed-paint-not-pixel-or-human',
      cases: mediaErrorPaintCases }, null, 2));
  console.log('[MEDIA LIST ERROR PAINT] 32/32 real alerts, 64 text >=4.5:1, ' +
    '64 keyboard focus/background >=3:1.');
  console.log('[MEDIA LEDGER STATES] 32/32 cases, 256 screenshots; ' +
    'long media paths, page 2, compound filters, queue dialogs and GET 503 recovery; zero NAS traffic');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
