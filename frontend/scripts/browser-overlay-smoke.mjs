/**
 * Chromium smoke checks for the real React/Radix ScanCreate -> DirectoryPicker stack.
 * API requests are intercepted with read-only synthetic data: NEVER contact a NAS.
 * This is computed-style evidence, not production NAS / complete visual acceptance.
 *
 * Run after npm run build:
 *   npm install --no-save --package-lock=false playwright@1.56.1
 *   npx playwright install chromium
 *   node scripts/browser-overlay-smoke.mjs
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';
import { computedContrastRatio } from './computed-contrast.mjs';

const ROOT = process.cwd();
const PORT = 4179;
const BASE_URL = 'http://127.0.0.1:' + PORT;
const OUTPUT = resolve(ROOT, 'artifacts/browser-overlay');
const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920];
const MODES = [
  { mode: 'light', system: 'dark', effective: 'light' },
  { mode: 'dark', system: 'light', effective: 'dark' },
  { mode: 'system', system: 'light', effective: 'light' },
  { mode: 'system', system: 'dark', effective: 'dark' },
];
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview',
  '--host', '127.0.0.1', '--port', String(PORT), '--strictPort',
], { cwd: ROOT, stdio: 'ignore' });

let browser;
let completed = 0;
const compositedPaintCases = [];

async function ready() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (server.exitCode !== null) throw new Error('Vite preview exited early');
    try {
      const response = await fetch(BASE_URL + '/login');
      if (response.ok) return;
    } catch { /* startup */ }
    await sleep(200);
  }
  throw new Error('Vite preview did not become ready');
}

function mockResponse(url) {
  const pathname = new URL(url).pathname;
  if (pathname === '/api/auth/me') {
    return { id: 1, username: 'visual-fixture-admin', role: 'admin', is_admin: true };
  }
  if (pathname === '/api/filesystem/list') {
    return {
      path: '/visual-fixture', parent: null, allowed_roots: ['/visual-fixture'],
      items: [{ name: 'Long-Test-Folder', path: '/visual-fixture/Long-Test-Folder',
        is_dir: true, is_directory: true }], total: 1, page: 1, page_size: 100,
    };
  }
  if (pathname === '/api/filesystem/favorites' || pathname === '/api/filesystem/recent') {
    return { items: [] };
  }
  if (pathname === '/api/scans') return { items: [], total: 0, page: 1, page_size: 20 };
  return { items: [], total: 0, status: 'ok', safe_mode: true };
}

async function inspect(page, theme, width) {
  return page.evaluate(({ theme, width }) => {
    const css = selector => {
      const element = document.querySelector(selector);
      if (!element) throw new Error('Missing actual React/Radix DOM: ' + selector);
      const style = getComputedStyle(element);
      const box = element.getBoundingClientRect();
      return {
        z: Number(style.zIndex), filter: style.backdropFilter,
        webkitFilter: style.webkitBackdropFilter,
        background: style.backgroundColor, color: style.color,
        rect: { left: box.left, right: box.right, top: box.top, bottom: box.bottom },
      };
    };
    const scan = css('.nfc-v2-scan-create-modal');
    const directory = css('.nfc-v2-directory-dialog');
    const scanOverlay = css('.nfc-v2-scan-create-overlay');
    const dirOverlay = css('.nfc-v2-directory-overlay');
    const primary = css('.nfc-v2-directory-dialog .nfc-console-button-primary');
    const expected = theme === 'dark' ? 'rgb(36, 36, 34)' : 'rgb(255, 255, 255)';
    const expectedButtonText = theme === 'dark' ? 'rgb(32, 32, 31)' : 'rgb(255, 255, 255)';
    const errors = [];
    const check = (pass, message) => { if (!pass) errors.push(message); };
    check(document.documentElement.dataset.theme === theme,
      'document theme disagrees with system/theme choice');
    for (const [name, overlay] of [['scan', scanOverlay], ['directory', dirOverlay]]) {
      // Chromium exposes the standard property but may omit the nonstandard
      // webkit alias. An absent alias is not an active blur filter.
      check(overlay.filter === 'none' &&
        (overlay.webkitFilter === undefined || overlay.webkitFilter === 'none'),
        name + ' scrim has blur/filter: ' + overlay.filter + ' / ' + overlay.webkitFilter);
    }
    check(scan.background === expected, 'Scan modal background: ' + scan.background);
    check(directory.background === expected, 'Directory modal background: ' + directory.background);
    check(primary.color === expectedButtonText, 'Directory primary text: ' + primary.color);
    check(scanOverlay.z === 1190 && scan.z === 1191,
      'Scan overlay/dialog z pair: ' + scanOverlay.z + '/' + scan.z);
    check(dirOverlay.z === 1200 && directory.z === 1201,
      'Directory overlay/dialog z pair: ' + dirOverlay.z + '/' + directory.z);
    check(directory.z > scan.z && dirOverlay.z > scan.z,
      'nested DirectoryPicker must be above parent content');
    for (const [name, box] of [['scan', scan.rect], ['directory', directory.rect]]) {
      check(box.left >= -2 && box.right <= width + 2,
        name + ' dialog horizontal overflow: ' + JSON.stringify(box));
      check(box.top >= -2 && box.bottom <= innerHeight + 2,
        name + ' dialog vertical overflow: ' + JSON.stringify(box));
    }
    const center = document.elementFromPoint(width / 2, innerHeight / 2);
    check(Boolean(center?.closest('.nfc-v2-directory-dialog')),
      'DirectoryPicker should receive pointer hits above both scrims');
    return { errors, scan, directory, scanOverlay, dirOverlay, primary };
  }, { theme, width });
}


// Actual mounted Radix portal paint: composite transparent row tint over the
// nearest opaque surface, refusing gradients/filters/opacity we cannot model.
// Modal text never borrows the tinted overlay or underlying page color.
async function inspectCompositedPortalPaint(page, visual, width) {
  const snapshot = await page.evaluate(() => {
    const parse = value => {
      const rgb = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d*\.?\d+)(?:\s*,\s*(\d*\.?\d+))?\s*\)$/.exec(value);
      const srgb = /^color\(srgb\s+(\d*\.?\d+)\s+(\d*\.?\d+)\s+(\d*\.?\d+)(?:\s*\/\s*(\d*\.?\d+))?\s*\)$/.exec(value);
      if (!rgb && !srgb) throw Error('Unsupported computed compositor color: ' + value);
      const match = rgb || srgb;
      const channels = match.slice(1, 4).map(Number);
      const alpha = match[4] === undefined ? 1 : Number(match[4]);
      if (srgb) for (let i = 0; i < 3; i++) channels[i] *= 255;
      if (channels.some(n => !Number.isFinite(n) || n < 0 || n > 255) ||
        !Number.isFinite(alpha) || alpha < 0 || alpha > 1)
        throw Error('Out-of-range compositor color: ' + value);
      return { channels, alpha };
    };
    const rgba = channels => 'rgb(' + channels.map(Math.round).join(', ') + ')';
    const selector = '.nfc-v2-directory-dialog .nfc-v2-directory-list li.is-selected';
    const row = document.querySelector(selector);
    const directory = document.querySelector('.nfc-v2-directory-dialog');
    const scan = document.querySelector('.nfc-v2-scan-create-modal');
    if (!row || !directory || !scan || !row.getBoundingClientRect().width)
      throw Error('Missing real mounted selected DirectoryPicker row or nested dialogs');
    const rowTint = parse(getComputedStyle(row).backgroundColor);
    if (!(rowTint.alpha > 0 && rowTint.alpha < 1))
      throw Error('DirectoryPicker selected row must use a real alpha tint');
    const layersFor = target => {
      const layers = [];
      for (let node = target; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.backgroundImage !== 'none' || Number(style.opacity) !== 1 ||
          style.filter !== 'none' || style.backdropFilter !== 'none' ||
          (style.webkitBackdropFilter && style.webkitBackdropFilter !== 'none'))
          throw Error('Pixel-level audit required for non-flat text paint: ' + node.className);
        const color = parse(style.backgroundColor);
        if (color.alpha > 0) layers.push(color);
        if (color.alpha === 1) break;
      }
      if (layers.length === 0 || layers.at(-1).alpha !== 1)
        throw Error('Selected DirectoryPicker row missing opaque painted ancestor');
      let painted = [0, 0, 0];
      for (const layer of layers.reverse())
        painted = painted.map((n, i) =>
          layer.channels[i] * layer.alpha + n * (1 - layer.alpha));
      return { background: rgba(painted), layers: layers.length };
    };
    const pairs = [
      ['directory-title', directory.querySelector('h2')],
      ['directory-description', directory.querySelector('.nfc-directory-picker-title p')],
      ['selected-name', row.querySelector('strong')],
      ['selected-path', row.querySelector('small')],
      ['scan-title', scan.querySelector('.nfc-v2-scan-create-header h2')],
      ['scan-description', scan.querySelector('.nfc-v2-scan-create-header p')],
    ].map(([name, element]) => {
      if (!element || !element.textContent?.trim())
        throw Error('Missing nonempty real portal text: ' + name);
      const ink = parse(getComputedStyle(element).color);
      if (ink.alpha !== 1) throw Error('Translucent text requires pixel-level inspection: ' + name);
      const { background, layers } = layersFor(element);
      return { name, foreground: rgba(ink.channels), background, layers };
    });
    const scrims = ['.nfc-v2-scan-create-overlay', '.nfc-v2-directory-overlay']
      .map(selector => {
        const element = document.querySelector(selector);
        if (!element) throw Error('Missing actual portal scrim: ' + selector);
        const style = getComputedStyle(element);
        if (style.backgroundImage !== 'none' || Number(style.opacity) !== 1 ||
          style.filter !== 'none' || style.backdropFilter !== 'none' ||
          (style.webkitBackdropFilter && style.webkitBackdropFilter !== 'none') ||
          element.children.length)
          throw Error('Unsupported scrim effects or readable children: ' + selector);
        const tint = parse(style.backgroundColor);
        if (!(tint.alpha > 0 && tint.alpha < 1))
          throw Error('Real modal scrim must alpha-composite: ' + selector);
        return { selector, alpha: tint.alpha, channels: tint.channels, z: Number(style.zIndex) };
      });
    if (!(scrims[0].z < scrims[1].z))
      throw Error('Nested DirectoryPicker scrim must remain above ScanCreate scrim');
    return { selectedAlpha: rowTint.alpha, pairs, scrims };
  });
  assert.equal(snapshot.pairs.length, 6,
    'Both real nested portal dialogs and selected translucent row must contribute paint pairs');
  for (const pair of snapshot.pairs) {
    const ratio = computedContrastRatio(pair.foreground, pair.background);
    pair.contrast = Number(ratio.toFixed(3));
    assert.ok(ratio >= 4.5,
      'Opaque-composited nested portal text below 4.5:1: ' +
      JSON.stringify({ visual, width, ...pair }));
  }
  compositedPaintCases.push({
    width, mode: visual.mode, system: visual.system,
    effective: visual.effective, ...snapshot,
  });
}

try {
  await ready();
  mkdirSync(OUTPUT, { recursive: true });
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });

  for (const width of WIDTHS) {
    for (const visual of MODES) {
      const context = await browser.newContext({
        viewport: { width, height: 900 },
        colorScheme: visual.system,
        reducedMotion: 'reduce',
      });
      await context.addInitScript(mode => {
        localStorage.setItem('nfc_theme_mode', mode);
      }, visual.mode);
      const page = await context.newPage();
      const deniedMethods = [], outbound = [];
      await page.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.origin !== BASE_URL) {
          outbound.push(request.url());
          await route.abort('blockedbyclient');
          return;
        }
        if (!url.pathname.startsWith('/api/')) {
          await route.continue();
          return;
        }
        if (request.method() !== 'GET') {
          deniedMethods.push(request.method() + ' ' + request.url());
          await route.fulfill({ status: 405, contentType: 'application/json',
            body: JSON.stringify({ error: 'READ_ONLY_BROWSER_FIXTURE' }) });
          return;
        }
        await route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify(mockResponse(request.url())) });
      });
      const label = visual.mode + '-' + visual.system + '-' + width;
      try {
        await page.goto(BASE_URL + '/scans', { waitUntil: 'domcontentloaded' });
        const scanLauncher = page.getByRole('button', { name: '新建扫描' }).first();
        const scanOpener = await scanLauncher.elementHandle();
        assert.ok(scanOpener, 'New Scan opener must exist before modal opens');
        await scanLauncher.click({ timeout: 15000 });
        const scanModal = page.locator('.nfc-v2-scan-create-modal');
        await scanModal.waitFor({ state: 'visible' });
        await page.locator('.nfc-v2-scan-create-modal')
          .getByRole('button', { name: '选择目录' }).first().click();
        await page.locator('.nfc-v2-directory-dialog').waitFor({ state: 'visible' });
        const state = await inspect(page, visual.effective, width);
        assert.deepEqual(state.errors, [], label + '\n' + state.errors.join('\n'));
        await page.screenshot({ path: resolve(OUTPUT, label + '.png') });
        // After the established screenshot baseline, choose a real local fixture
        // folder. Selection is React-only; no backend action is performed.
        const row = page.locator('.nfc-v2-directory-dialog .nfc-v2-directory-list li').first();
        await row.waitFor({ state: 'visible' });
        await row.getByRole('button', { name: '选择', exact: true }).click();
        await row.locator('..').locator('li.is-selected').first().waitFor({ state: 'visible' });
        await inspectCompositedPortalPaint(page, visual, width);
        await page.keyboard.press('Escape');
        await page.locator('.nfc-v2-directory-dialog').waitFor({ state: 'hidden' });
        await scanModal.waitFor({ state: 'visible' });
        // Closing nested DirectoryPicker must keep parent open, and closing
        // the controlled parent must restore its exact real keyboard launcher.
        await scanModal.getByRole('button', { name: '关闭新建扫描' }).click();
        await scanModal.waitFor({ state: 'hidden' });
        await page.waitForFunction(opener => document.activeElement === opener, scanOpener);
        await page.keyboard.press('Enter');
        await scanModal.waitFor({ state: 'visible' });
        await page.keyboard.press('Escape');
        await scanModal.waitFor({ state: 'hidden' });
        await page.waitForFunction(opener => document.activeElement === opener, scanOpener);
        // The real administrator password dialog renders in a root Radix Portal,
        // outside the shell's CSS variables. Check the keyboard ring actually
        // painted on each native password input, including dark/system themes.
        await page.locator('.nfc-v2-user-dropdown > summary').click();
        await page.getByRole('button', { name: '修改密码' }).click();
        const passwordModal = page.locator('.nfc-change-password-modal');
        await passwordModal.waitFor({ state: 'visible' });
        for (const id of ['nfc-old-password', 'nfc-new-password', 'nfc-confirm-password']) {
          const input = passwordModal.locator('#' + id);
          await input.focus();
          const focused = await input.evaluate(node => {
            const inputStyle = getComputedStyle(node);
            const portalStyle = getComputedStyle(node.closest('.nfc-v2-dialog'));
            return {
              keyboard: node.matches(':focus-visible'),
              outlineStyle: inputStyle.outlineStyle,
              outlineWidth: Number.parseFloat(inputStyle.outlineWidth),
              transitionDuration: inputStyle.transitionDuration,
              outlineColor: inputStyle.outlineColor,
              inputBackground: inputStyle.backgroundColor,
              portalBackground: portalStyle.backgroundColor,
              disabled: node.matches(':disabled'),
            };
          });
          assert.equal(focused.keyboard, true, label + ': focus-visible ' + id);
          assert.equal(focused.disabled, false, label + ': enabled password input ' + id);
          assert.equal(focused.outlineStyle, 'solid', label + ': solid ring ' + id);
          assert.equal(focused.transitionDuration, '0s', label + ': no password focus transition ' + id);
          assert.ok(focused.outlineWidth >= 3, label + ': ring width ' + id + ' / ' + JSON.stringify(focused));
          for (const surface of [focused.inputBackground, focused.portalBackground]) {
            assert.ok(computedContrastRatio(focused.outlineColor, surface) >= 3,
              label + ': focus contrast below 3:1 on ' + id + ' / ' + surface);
          }
        }
        await page.screenshot({ path: resolve(OUTPUT, 'password-focus-' + label + '.png') });
        await passwordModal.getByRole('button', { name: '关闭密码修改窗口' }).click();
        await passwordModal.waitFor({ state: 'hidden' });
        assert.deepEqual(deniedMethods, [], 'Browser fixture must not make mutating API requests');
        assert.deepEqual(outbound, [], 'Browser fixture must not reach outbound networks or a real NAS');
        completed += 1;
        console.log('[BROWSER OVERLAY PASS] ' + label);
      } catch (error) {
        console.error('[BROWSER OVERLAY FAIL] ' + label, error);
        await page.screenshot({ path: resolve(OUTPUT, label + '-failure.png') }).catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(completed, WIDTHS.length * MODES.length);
  assert.equal(compositedPaintCases.length, WIDTHS.length * MODES.length,
    'Actual selected translucent tint and portal paint must cover all widths/themes');
  assert.ok(compositedPaintCases.every(c =>
    c.pairs.length === 6 && c.pairs.every(pair => pair.contrast >= 4.5) &&
    c.selectedAlpha > 0 && c.selectedAlpha < 1 &&
    c.scrims.length === 2 && c.scrims.every(scrim => scrim.alpha > 0 && scrim.alpha < 1)),
  'Every real dialog label and selected tinted path must meet alpha-composited 4.5:1');
  writeFileSync(resolve(OUTPUT, 'composited-portal-text-contrast-audit.json'),
    JSON.stringify({ cases: compositedPaintCases, total: compositedPaintCases.length,
      paintedTextPairs: compositedPaintCases.length * 6,
      audited: 'actual-mounted-Radix-dialog-selected-alpha-tint-solid-composition-not-pixel-level' }, null, 2));
  console.log('[BROWSER COMPOSITED PORTAL TEXT] 32/32 mounted nested dialogs; ' +
    '192/192 painted label/path pairs >= 4.5:1, strict opaque ancestor, no outbound.');
  console.log('[BROWSER OVERLAY] ' + completed + '/' + (WIDTHS.length * MODES.length) +
    ' real Chromium cases passed; mocked read-only APIs, no NAS access.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
