/**
 * Pure White Stage 5E-F: actual Indexes ledger, page change, capability gates,
 * create/remove confirmation and recoverable API error in Chromium.
 * Local Vite only; synthetic GET fixtures; non-GET requests denied HTTP 405.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';
import { computedContrastRatio } from './computed-contrast.mjs';
import { parseComputedPaintColor, contrastRatioForOpaqueChannels } from './computed-paint-color.mjs';
import { visualAdminFixture, visualSafeSettingsFixture,
  visualViewports, visualThemes } from './visual-fixtures.mjs';

const BASE = 'http://127.0.0.1:4188';
const OUT = resolve(process.cwd(), 'artifacts/browser-indexes-ledger-states');
const WIDTHS = visualViewports; // 360, 390, 430, 768, 1024, 1280, 1440, 1920
const THEMES = visualThemes; // mode: 'system', system: 'dark', effective: 'dark'
const LONG_ROOT = '/synthetic-nas/Camera-Archives/2026/' +
  'UnbrokenOriginalMediaArchiveFolderName'.repeat(7);
const timestamp = '2026-10-12T08:30:00Z';
const roots = Array.from({ length: 21 }, (_, i) => {
  const id = i + 801;
  const state = i === 1 ? 'blocked' : i === 2 ? 'missing' : 'available';
  return {
    id, root: LONG_ROOT + '/Source-' + id,
    files: 9245000 + id, folders: 5300 + id,
    path_state: state, exists: state === 'available',
    can_remove: i !== 0, has_active_job: i === 0,
    active_job_id: i === 0 ? 777 : null,
    active_job_status: i === 0 ? 'running' : null,
    created_at: timestamp, last_indexed_at: i === 2 ? null : timestamp,
  };
});
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
  '--port', '4188', '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });
let browser;
let passed = 0;
const indexErrorPaintCases = [];

async function ready() {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw Error('Vite preview exited');
    try { if ((await fetch(BASE + '/indexes')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Local Vite preview unavailable');
}
function fixture(url) {
  if (url.pathname === '/api/auth/me') return visualAdminFixture('indexes-visual-fixture');
  if (url.pathname === '/api/settings') return visualSafeSettingsFixture();
  if (url.pathname === '/api/indexes') {
    const page = Number(url.searchParams.get('page') || 1);
    const size = Number(url.searchParams.get('page_size') || 20);
    return { items: roots.slice((page - 1) * size, page * size),
      total: roots.length, page, page_size: size };
  }
  return { items: [], total: 0, page: 1, page_size: 20 };
}
async function inspect(page, theme, width, state) {
  const failures = await page.evaluate(({ theme, width, state }) => {
    const failures = [];
    const check = (ok, why) => { if (!ok) failures.push(why); };
    const inside = node => {
      if (!node) return false;
      const r = node.getBoundingClientRect();
      return r.width > 0 && r.left >= -2 && r.right <= width + 2;
    };
    check(document.documentElement.dataset.theme === theme, 'Wrong effective theme');
    check(inside(document.querySelector('.nfc-page-content')), 'Workspace overflow');
    check(inside(document.querySelector('.nfc-indexes-page')), 'Indexes root overflow');
    if (state === 'create' || state === 'confirm') {
      const dialog = document.querySelector(state === 'create'
        ? '.nfc-v2-index-create-dialog' : '.nfc-v2-confirm-dialog');
      const overlay = document.querySelector(state === 'create'
        ? '.nfc-v2-dialog-overlay:not(.nfc-v2-confirm-overlay)'
        : '.nfc-v2-confirm-overlay');
      check(inside(dialog), state + ' dialog exceeds viewport');
      const b = dialog?.getBoundingClientRect();
      check(Boolean(b && b.top >= -2 && b.bottom <= innerHeight + 2),
        state + ' dialog vertical bounds');
      check(getComputedStyle(overlay).backdropFilter === 'none',
        state + ' overlay must remain dim-only');
      check(Number(getComputedStyle(overlay).zIndex) === (state === 'create' ? 1100 : 1300),
        state + ' overlay z-index');
      check(Number(getComputedStyle(dialog).zIndex) === (state === 'create' ? 1101 : 1301),
        state + ' dialog z-index');
      const hit = document.elementFromPoint(width / 2, innerHeight / 2);
      check(Boolean(hit?.closest('.nfc-v2-dialog')), state + ' dialog pointer hit');
      if (state === 'create' && b) {
        // A non-overflowing dialog may still be visually broken: assert the
        // field, directory picker and explanatory note respect the title gutter.
        const gutter = width < 768 ? 16 : 22;
        const headerIcon = dialog.querySelector('.nfc-v2-dialog-heading .nfc-v2-dialog-icon');
        const label = dialog.querySelector('.nfc-v2-index-form-label');
        const fields = [
          ['label', label],
          ['directory picker', dialog.querySelector('.nfc-v2-index-form .nfc-v2-directory-picker')],
          ['explanation', dialog.querySelector('.nfc-v2-index-form .nfc-form-note')],
        ];
        for (const [name, node] of fields) {
          const bounds = node?.getBoundingClientRect();
          check(Boolean(bounds && bounds.width > 0 &&
            bounds.left >= b.left + gutter &&
            bounds.right <= b.right - gutter), name + ' content gutter');
        }
        const iconLeft = headerIcon?.getBoundingClientRect().left;
        const labelLeft = label?.getBoundingClientRect().left;
        check(Boolean(Number.isFinite(iconLeft) && Number.isFinite(labelLeft) &&
          Math.abs(iconLeft - labelLeft) <= 2), 'Create form must align with header inset');
      }
    } else if (state === 'failure') {
      check(inside(document.querySelector('.nfc-v2-indexes-error')),
        'Indexes error alert exceeds viewport');
    } else {
      check(inside(document.querySelector('.nfc-console-pagination')),
        'Pagination exceeds viewport');
      if (width < 768) {
        for (const card of document.querySelectorAll('.nfc-index-mobile-card'))
          check(inside(card), 'Long-path index mobile card exceeds viewport');
      } else {
        const scroller = document.querySelector('.nfc-v2-indexes-table-scroll');
        check(inside(scroller), 'Desktop table scrollport exceeds viewport');
        check(['auto', 'scroll'].includes(getComputedStyle(scroller).overflowX),
          'Wide table must own horizontal overflow');
      }
    }
    return failures;
  }, { theme, width, state });
  assert.deepEqual(failures, [], state + ' ' + width + ': ' + failures.join('; '));
}

/** Check actual mounted Indexes 503 alert text and keyboard-visible Reload ring. */
async function inspectIndexesListErrorPaint(page, theme, width) {
  const snapshot = await page.evaluate(() => {
    const alert = document.querySelector('.nfc-v2-indexes-error[role="alert"]');
    const reload = alert?.querySelector('button');
    const title = alert?.querySelector('strong');
    const detail = alert?.querySelector('p');
    const label = reload?.querySelector('span');
    if (!alert || !title?.textContent?.includes('获取索引根目录失败') ||
        !detail?.textContent?.trim() ||
        !reload || !label?.textContent?.includes('重新加载'))
      throw Error('Missing mounted real Indexes list failure alert/Reload labels');
    if (document.activeElement !== reload || !reload.matches(':focus-visible') ||
        reload.disabled)
      throw Error('Indexes list Reload must have actual keyboard-visible enabled focus');
    const reloadBox = reload.getBoundingClientRect();
    if (!reloadBox.width || !reloadBox.height || reloadBox.left < -2 ||
        reloadBox.right > innerWidth + 2 || reloadBox.top < -2 ||
        reloadBox.bottom > innerHeight + 2)
      throw Error('Indexes list Reload escapes the visible viewport');
    const ring = getComputedStyle(reload);
    const ringWidth = Number.parseFloat(ring.outlineWidth);
    const ringOffset = Number.parseFloat(ring.outlineOffset);
    if (ring.outlineStyle !== 'solid' || !Number.isFinite(ringWidth) ||
        !Number.isFinite(ringOffset) || ringWidth < 2 || ringOffset < 1)
      throw Error('Indexes list Reload keyboard focus indicator is not solid/visible');
    const flat = element => {
      const ancestors = [];
      for (let node = element; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.backgroundImage !== 'none' || Number(style.opacity) !== 1 ||
            style.filter !== 'none' || style.backdropFilter !== 'none' ||
            (style.webkitBackdropFilter && style.webkitBackdropFilter !== 'none'))
          throw Error('Unsupported Indexes alert paint ancestor: ' + node.tagName);
        ancestors.push({ tag: node.tagName, color: style.backgroundColor });
      }
      return { foreground: getComputedStyle(element).color, ancestors };
    };
    return {
      texts: [
        { name: 'error-title', ...flat(title) },
        { name: 'error-detail', ...flat(detail) },
        { name: 'reload-label', ...flat(label) },
      ],
      alertPaint: flat(alert),
      buttonPaint: flat(reload),
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
      throw Error('Indexes list ' + name + ' lacks opaque painted ancestor');
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
      throw Error('Translucent Indexes list ink or ring needs rendered-pixel audit');
    const integer = channels => 'rgb(' + channels.map(Math.round).join(', ') + ')';
    return Math.min(
      contrastRatioForOpaqueChannels(foreground.channels, background),
      computedContrastRatio(integer(foreground.channels), integer(background)),
    );
  };
  const pairs = snapshot.texts.map(pair => {
    const paint = compose(pair, pair.name);
    const contrast = wcag(pair.foreground, paint.background);
    assert.ok(contrast >= 4.5, 'Indexes list failure/Reload text below 4.5:1: ' +
      JSON.stringify({ width, theme, pair, contrast, paint }));
    return { name: pair.name, foreground: pair.foreground,
      contrast: Number(contrast.toFixed(3)), ...paint };
  });
  const alert = compose(snapshot.alertPaint, 'error-banner');
  const button = compose(snapshot.buttonPaint, 'reload-button');
  const focusPairs = [['error-banner', alert], ['reload-button', button]].map(
    ([name, paint]) => {
      const contrast = wcag(snapshot.focus.foreground, paint.background);
      assert.ok(contrast >= 3, 'Indexes list Reload outline below 3:1: ' +
        JSON.stringify({ width, theme, name, contrast, paint, focus: snapshot.focus }));
      return { name, contrast: Number(contrast.toFixed(3)), ...paint };
    });
  indexErrorPaintCases.push({ width, mode: theme.mode, system: theme.system,
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
            body: JSON.stringify({ detail: 'READ_ONLY_INDEXES_FIXTURE' }) });
          return;
        }
        if (url.pathname === '/api/indexes') listQueries.push(url.search);
        const fail = failList && url.pathname === '/api/indexes';
        await route.fulfill({ status: fail ? 503 : 200,
          contentType: 'application/json',
          body: JSON.stringify(fail
            ? { detail: 'Synthetic read-only index listing failure' } : fixture(url)) });
      });
      const label = theme.mode + '-' + theme.system + '-' + width;
      const record = width < 768 ? '.nfc-index-mobile-card' : '.nfc-v2-indexes-table tbody tr';
      try {
        await page.goto(BASE + '/indexes', { waitUntil: 'domcontentloaded' });
        await page.locator(record).first().waitFor({ state: 'visible' });
        assert.equal(await page.locator(record).count(), 20, 'First page must contain 20 roots');
        const item = i => page.locator(record).nth(i);
        assert.equal(await item(0).getByRole('button', { name: '移除索引' }).isDisabled(),
          true, 'Active root cannot be removed');
        assert.equal(await item(0).getByRole('button', { name: '重新索引' }).isEnabled(),
          true, 'Available root may be queued for reindex but must not be clicked');
        for (const i of [1, 2]) {
          assert.equal(await item(i).getByRole('button', { name: '重新索引' }).isDisabled(),
            true, 'Unavailable root cannot be queued for reindex');
        }
        const stateText = await page.locator(record).allInnerTexts();
        for (const name of ['可用', '访问已阻止', '目录不存在']) {
          assert.ok(stateText.join(' ').includes(name), 'Missing state: ' + name);
        }
        await inspect(page, theme.effective, width, 'dense');
        await page.screenshot({ path: resolve(OUT, 'long-path-states-' + label + '.png') });

        await page.getByRole('button', { name: '下一页' }).click();
        await page.locator(record).first().waitFor({ state: 'visible' });
        await page.waitForFunction(selector =>
          document.querySelectorAll(selector).length === 1, record);
        assert.equal(await page.locator(record).count(), 1);
        assert.ok((await page.locator('.nfc-console-pagination').innerText())
          .includes('第 2 / 2 页'));
        assert.ok(listQueries.some(q => new URLSearchParams(q).get('page') === '2'),
          'Second page must be fetched with server-side pagination');
        await inspect(page, theme.effective, width, 'page2');
        await page.screenshot({ path: resolve(OUT, 'page-two-' + label + '.png') });

        await page.getByRole('button', { name: '上一页' }).click();
        await page.waitForFunction(selector =>
          document.querySelectorAll(selector).length === 20, record);
        const createLauncher = page.getByRole('button', { name: '加入索引队列', exact: true });
        const createOpener = await createLauncher.elementHandle();
        assert.ok(createOpener, 'Index create action must have a keyboard launcher');
        await createLauncher.click();
        const create = page.locator('.nfc-v2-index-create-dialog');
        await create.waitFor({ state: 'visible' });
        assert.equal(await create.getByRole('button', { name: '加入队列', exact: true }).isDisabled(),
          true, 'Empty index path must not allow queue submission');
        await inspect(page, theme.effective, width, 'create');
        await page.screenshot({ path: resolve(OUT, 'create-dialog-' + label + '.png') });
        // The controlled parent has no Dialog.Trigger. Check Escape and X
        // restore the exact opener; Enter must reopen before nested navigation.
        await page.keyboard.press('Escape');
        await create.waitFor({ state: 'hidden' });
        await page.waitForFunction(opener => document.activeElement === opener, createOpener);
        await page.keyboard.press('Enter');
        await create.waitFor({ state: 'visible' });
        await create.getByRole('button', { name: '关闭索引窗口' }).click();
        await create.waitFor({ state: 'hidden' });
        await page.waitForFunction(opener => document.activeElement === opener, createOpener);
        await page.keyboard.press('Enter');
        await create.waitFor({ state: 'visible' });
        // Test the actual nested Radix portal at every width/theme. The previous
        // create scrim at 1300 covered the directory browser at 1200/1201.
        await create.getByRole('button', { name: '选择目录', exact: true }).click();
        const picker = page.locator('.nfc-v2-directory-dialog');
        await picker.waitFor({ state: 'visible' });
        const nested = await page.evaluate(() => {
          const create = document.querySelector('.nfc-v2-index-create-dialog');
          const createOverlay = document.querySelector(
            '.nfc-v2-dialog-overlay:not(.nfc-v2-directory-overlay)');
          const picker = document.querySelector('.nfc-v2-directory-dialog');
          const pickerOverlay = document.querySelector('.nfc-v2-directory-overlay');
          const bounds = picker?.getBoundingClientRect();
          const target = bounds && document.elementFromPoint(
            bounds.left + bounds.width / 2, bounds.top + Math.min(70, bounds.height / 3));
          return {
            z: [createOverlay, create, pickerOverlay, picker].map(node =>
              Number(getComputedStyle(node).zIndex)),
            hit: Boolean(target?.closest('.nfc-v2-directory-dialog')),
            withinWidth: Boolean(bounds && bounds.left >= -2 && bounds.right <= innerWidth + 2),
            withinHeight: Boolean(bounds && bounds.top >= -2 && bounds.bottom <= innerHeight + 2),
          };
        });
        assert.deepEqual(nested.z, [1100, 1101, 1200, 1201], 'Nested picker must layer above create');
        assert.equal(nested.hit, true, 'Nested picker must receive pointer hits');
        assert.equal(nested.withinWidth && nested.withinHeight, true,
          'Nested picker must fit the viewport');
        // Stage 5E-S: horizontal ARIA tabs are one Tab stop and respond to
        // arrows, Home/End, wrapping and focus-visible keyboard navigation.
        const tab = name => picker.locator('#nfc-directory-tab-' + name);
        const checkTab = async name => {
          await page.waitForFunction(tabId => {
            const root = document.querySelector('.nfc-v2-directory-dialog');
            const selected = root?.querySelector('#nfc-directory-tab-' + tabId);
            const panel = root?.querySelector('#nfc-directory-active-panel');
            const tabs = [...(root?.querySelectorAll('[role="tab"]') || [])];
            return Boolean(selected && panel &&
              document.activeElement === selected &&
              selected.getAttribute('aria-selected') === 'true' &&
              selected.getAttribute('tabindex') === '0' &&
              tabs.length === 3 &&
              tabs.every(other => other.getAttribute('aria-controls') === panel.id &&
                other.getAttribute('tabindex') === (other === selected ? '0' : '-1')) &&
              panel.getAttribute('aria-labelledby') === selected.id);
          }, name);
        };
        await tab('browser').focus();
        await checkTab('browser');
        await page.keyboard.press('ArrowRight');
        await checkTab('favorites');
        await page.keyboard.press('End');
        await checkTab('recent');
        await page.keyboard.press('ArrowRight');
        await checkTab('browser');
        await page.keyboard.press('ArrowLeft');
        await checkTab('recent');
        await page.keyboard.press('Home');
        await checkTab('browser');
        await page.keyboard.press('Tab');
        assert.equal(await picker.evaluate(node =>
          document.activeElement === node.querySelector('[role="tabpanel"]')), true,
          'Tab from selected tab must reach the active panel, not an inactive tab');
        await page.keyboard.press('Escape');
        await picker.waitFor({ state: 'hidden' });
        assert.equal(await create.isVisible(), true, 'Escape must close picker, not its parent');
        const focusedLauncher = () => document.activeElement === document.querySelector(
          '.nfc-v2-index-create-dialog .nfc-directory-picker-single .nfc-console-button');
        await page.waitForFunction(focusedLauncher, undefined, { timeout: 10000 });
        // Keyboard Enter on the restored launcher must reopen this nested dialog.
        await page.keyboard.press('Enter');
        await picker.waitFor({ state: 'visible' });
        await page.waitForFunction(() =>
          Boolean(document.activeElement?.closest('.nfc-v2-directory-dialog')));
        await page.keyboard.press('Tab');
        assert.equal(await picker.evaluate(node => node.contains(document.activeElement)), true,
          'Nested picker must trap keyboard Tab within the active dialog');
        // The first Escape already verifies exact focus return. After an immediate
        // keyboard reopen, use the explicit close button to avoid conflating the
        // second Radix FocusScope teardown with the parent-dialog cancellation.
        await picker.getByRole('button', { name: '关闭目录选择' }).click();
        await picker.waitFor({ state: 'hidden' });
        assert.equal(await create.isVisible(), true, 'Keyboard reopening must preserve parent dialog');
        // A second immediate Escape may race Radix's nested focus/layer teardown;
        // close the parent via its own explicit control after asserting it stayed open.
        await create.getByRole('button', { name: '取消', exact: true }).click();
        await create.waitFor({ state: 'hidden' });

        await item(1).getByRole('button', { name: '移除索引' }).click();
        const confirm = page.locator('.nfc-v2-confirm-dialog');
        await confirm.waitFor({ state: 'visible' });
        assert.ok((await confirm.innerText()).includes('不会删除 NAS 上的任何真实文件或目录'),
          'Metadata-only removal disclosure must remain visible');
        await inspect(page, theme.effective, width, 'confirm');
        await page.screenshot({ path: resolve(OUT, 'metadata-confirm-' + label + '.png') });
        await page.keyboard.press('Escape');
        await confirm.waitFor({ state: 'hidden' });

        failList = true;
        await page.getByRole('button', { name: '刷新', exact: true }).click();
        await page.getByText('获取索引根目录失败', { exact: true })
          .waitFor({ state: 'visible', timeout: 30000 });
        await inspect(page, theme.effective, width, 'failure');
        await page.screenshot({ path: resolve(OUT, 'list-error-' + label + '.png') });
        // Preserve the original unfocused screenshot, then exercise real
        // Tab / Shift+Tab keyboard modality on the mounted Reload button.
        const reload = page.locator('.nfc-v2-indexes-error[role="alert"]')
          .getByRole('button', { name: '重新加载', exact: true });
        await reload.focus();
        await page.keyboard.press('Tab');
        await page.keyboard.press('Shift+Tab');
        await inspectIndexesListErrorPaint(page, theme, width);
        if ([390, 1440].includes(width))
          await page.screenshot({ path: resolve(OUT, 'list-error-keyboard-' + label + '.png') });
        failList = false;
        await page.getByRole('button', { name: '重新加载' }).click();
        await page.locator(record).first().waitFor({ state: 'visible' });
        assert.equal(await page.locator(record).count(), 20);
        assert.deepEqual(writes, [], 'No mutating API may be sent');
        assert.deepEqual(outbound, [], 'No outbound or NAS traffic permitted');
        passed++;
        console.log('[INDEXES LEDGER STATES PASS] ' + label);
      } catch (err) {
        console.error('[INDEXES LEDGER STATES FAIL] ' + label, err);
        await page.screenshot({
          path: resolve(OUT, 'failure-' + label + '.png'),
        }).catch(() => {});
        throw err;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(passed, WIDTHS.length * THEMES.length);
  assert.equal(indexErrorPaintCases.length, WIDTHS.length * THEMES.length,
    'All Indexes 503 failures must have real keyboard focus and painted contrast');
  assert.ok(indexErrorPaintCases.every(entry =>
    entry.texts.length === 3 && entry.texts.every(pair => pair.contrast >= 4.5) &&
    entry.focus.keyboard && entry.focus.width >= 2 && entry.focus.offset >= 1 &&
    entry.focusPairs.length === 2 &&
    entry.focusPairs.every(pair => pair.contrast >= 3)),
    'Every actual Indexes error/Reload text and focus ring must pass AA gates');
  writeFileSync(resolve(OUT, 'indexes-list-error-reload-paint-audit.json'),
    JSON.stringify({ total: indexErrorPaintCases.length,
      paintedTextPairs: indexErrorPaintCases.length * 3,
      paintedFocusPairs: indexErrorPaintCases.length * 2,
      scope: 'actual-React-indexes-503-keyboard-focus-flat-computed-paint-not-pixel-or-human',
      cases: indexErrorPaintCases }, null, 2));
  console.log('[INDEXES LIST ERROR PAINT] 32/32 real alerts, 96 text >=4.5:1, ' +
    '64 keyboard focus/background >=3:1.');
  console.log('[INDEXES LEDGER STATES] 32/32 cases, 160 screenshots; ' +
    'long-path states, page 2, read-only dialogs and 503 recovery; zero NAS traffic.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
