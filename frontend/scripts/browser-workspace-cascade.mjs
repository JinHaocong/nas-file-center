/**
 * Stage 5E-A: actual Dashboard, Plans, Tasks workspace cascade in Chromium.
 * Playwright serves synthetic local GET fixtures and denies all writes/outbound.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';
import { computedContrastRatio } from './computed-contrast.mjs';
import { visualAdminFixture, visualSafeSettingsFixture,
  visualViewports, visualThemes } from './visual-fixtures.mjs';

const BASE = 'http://127.0.0.1:4186';
const OUT = resolve(process.cwd(), 'artifacts/browser-workspace-cascade');
const WIDTHS = visualViewports; // 360, 390, 430, 768, 1024, 1280, 1440, 1920
const THEMES = visualThemes; // mode: 'system', system: 'dark', effective: 'dark'
const PAGES = [
  { path: '/dashboard', id: 'dashboard', heading: 'NAS File Center', selector: '.nfc-dashboard-page' },
  { path: '/plans', id: 'plans', heading: '执行计划', selector: '.nfc-plans-page' },
  { path: '/tasks', id: 'tasks', heading: '任务中心', selector: '.nfc-tasks-page' },
  { path: '/indexes', id: 'indexes', heading: '文件索引', selector: '.nfc-indexes-page' },
  { path: '/media', id: 'media', heading: '媒体完整性', selector: '.nfc-media-page' },
  { path: '/quarantine', id: 'quarantine', heading: '文件隔离区', selector: '.nfc-quarantine-page' },
];
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
  '--port', '4186', '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });
let browser;
let passed = 0;
const checkboxKeyboardAudit = [];
const dashboardHeroPaintAudit = [];

async function ready() {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw Error('Vite preview exited');
    try { if ((await fetch(BASE + '/login')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Local Vite preview unavailable');
}

const DENSE_ROOT = '/visual-fixture/NAS/Very-Long-Archive-Name/Photography-2026/Original-Camera-Exports-and-Unsorted-Video-Files';
const DENSE_PAGES = [
  { path: '/plans', id: 'plans', row: '.nfc-v2-plan-table tbody tr',
    card: '.nfc-plan-mobile-card', scroll: '.nfc-v2-plan-table-scroll' },
  { path: '/tasks', id: 'tasks', row: '.nfc-v2-task-table tbody tr',
    card: '.nfc-task-mobile-card', scroll: '.nfc-v2-task-table-scroll' },
  { path: '/indexes', id: 'indexes', row: '.nfc-v2-indexes-table tbody tr',
    card: '.nfc-index-mobile-card', scroll: '.nfc-v2-indexes-table-scroll' },
  { path: '/media', id: 'media', row: '.nfc-v2-media-table tbody tr',
    card: '.nfc-v2-media-mobile .nfc-index-mobile-card',
    scroll: '.nfc-v2-media-table-scroll', count: 3 },
  { path: '/quarantine', id: 'quarantine', row: '.nfc-v2-quarantine-table tbody tr',
    card: '.nfc-quarantine-mobile-card',
    scroll: '.nfc-v2-quarantine-table-scroll', count: 3 },
];
function denseFixture(path) {
  const timestamp = '2026-10-12T08:30:00Z';
  if (path === '/api/plans') return {
    items: [
      { id: 301, name: 'Visual Fixture — Deep Archive Photo and Video Deduplication Plan 2026',
        kind: 'dedupe', status: 'ready', expected_changes: 136,
        expected_reclaim_bytes: 9865489321, created_at: timestamp },
      { id: 302, name: 'Second confirmed retention plan', kind: 'organizer',
        status: 'completed', expected_changes: 24,
        expected_reclaim_bytes: 10240, created_at: timestamp },
    ], total: 2, page: 1, page_size: 20,
  };
  if (path === '/api/tasks') return {
    items: [
      { id: 501, job_type: 'scan_and_verify_deep_archive_long_history',
        status: 'failed', created_at: timestamp, started_at: timestamp,
        finished_at: timestamp, heartbeat_at: timestamp, retry_of: null,
        progress: { current: 124, total: 500, percent: 24.8, message: 'Checking deep NAS paths' },
        capabilities: { supports_pause: false, supports_resume: false,
          supports_cancel: false, supports_retry: false },
        error_code: 'VALIDATION_PATH_IDENTITY_CHANGED',
        error: 'Read-only fixture: root identity changed under the archived path' },
      { id: 502, job_type: 'index', status: 'completed',
        created_at: timestamp, started_at: timestamp, finished_at: timestamp,
        heartbeat_at: timestamp, retry_of: null, error: null, error_code: null,
        progress: { current: 500, total: 500, percent: 100, message: null },
        capabilities: { supports_pause: false, supports_resume: false,
          supports_cancel: false, supports_retry: false } },
    ], total: 2, page: 1, page_size: 50,
  };
  if (path === '/api/indexes') return {
    items: [
      { id: 701, root: DENSE_ROOT, files: 12455678, folders: 98340,
        path_state: 'available', exists: true, can_remove: false,
        has_active_job: true, active_job_id: 777, active_job_status: 'running',
        created_at: timestamp, last_indexed_at: timestamp },
      { id: 702, root: DENSE_ROOT + '/Unavailable-Recovery-Snapshot',
        files: 1474, folders: 52, path_state: 'missing', exists: false,
        can_remove: false, has_active_job: false, active_job_id: null,
        active_job_status: null, created_at: timestamp, last_indexed_at: null },
    ], total: 2, page: 1, page_size: 20,
  };
  if (path === '/api/media') {
    const asset = (id, mediaKind, integrity, verification, canDelete) => ({
      id, indexed_path_id: id + 1000, root_key: DENSE_ROOT,
      path: DENSE_ROOT + '/2026-Photo-Video-Metadata-and-Integrity/' +
        id + '-Original-Camera-Capture-Super-Long-Filename.' +
        (mediaKind === 'video' ? 'mp4' : 'raw'),
      relative_path: '2026-Photo-Video-Metadata-and-Integrity/' + id,
      basename: id + '-Original-Camera-Capture-Super-Long-Filename',
      size: 7785234567, mtime_ns: 1700000000000000000, media_kind: mediaKind,
      width: mediaKind === 'video' ? 3840 : 8192,
      height: mediaKind === 'video' ? 2160 : 5464,
      format: mediaKind === 'video' ? 'MP4' : 'RAW',
      date_taken: '2026-10-12', camera: 'Visual Fixture Camera / Not a Real Device',
      orientation: 1, duration_seconds: mediaKind === 'video' ? 420.5 : null,
      codec: mediaKind === 'video' ? 'HEVC' : null,
      bitrate: mediaKind === 'video' ? 24000000 : null,
      fps: mediaKind === 'video' ? 59.94 : null, audio_codec: 'AAC',
      integrity_status: integrity, integrity_reason_code:
        integrity === 'corrupt' ? 'HASH_MISMATCH_FROZEN_EVIDENCE' : null,
      integrity_detail: null, verification_status: verification,
      verification_reason_code: null, verification_detail: null,
      verification_checked_at: timestamp, can_direct_delete: canDelete,
      probed_at: timestamp,
    });
    return {
      items: [asset(801, 'image', 'healthy', 'verified', false),
        asset(802, 'video', 'corrupt', 'changed', true),
        asset(803, 'image', 'unknown', 'unverified', false)],
      total: 3, page: 1, page_size: 50,
    };
  }
  if (path === '/api/quarantine') {
    const entry = (id, state) => ({
      id, original_path: DENSE_ROOT + '/Originals/Deep-Archive-' + id +
        '-Protected-Filename-With-Metadata.raw',
      quarantine_path: DENSE_ROOT + '/.nas-file-center-trash/' + id +
        '/Visual-Fixture-Private-Quarantine-Long-Path',
      task_id: 501, plan_item_id: 100, state, size: 987654321,
      hash: 'c'.repeat(64), mtime_ns: 1700000000000000000,
      device: 1, inode: id + 5000, quarantined_at: timestamp,
      expires_at: null, restored_at: state === 'restored' ? timestamp : null,
      purged_at: null, last_error: state === 'conflict' ? 'SAFE_PATH_CONFLICT' : null,
      created_at: timestamp, updated_at: timestamp,
    });
    return {
      items: [entry(901, 'active'), entry(902, 'conflict'),
        entry(903, 'restored')], total: 3, page: 1, page_size: 20,
    };
  }
  return null;
}
function fixture(path, dense = false) {
  if (path === '/api/auth/me') return visualAdminFixture('css-visual-fixture');
  if (path === '/api/media/summary') return {
    total: dense ? 3 : 0, image: dense ? 2 : 0, video: dense ? 1 : 0,
    healthy: dense ? 1 : 0, corrupt: dense ? 1 : 0, unknown: dense ? 1 : 0,
    verification_unverified: dense ? 1 : 0, verification_baseline: 0,
    verification_verified: dense ? 1 : 0, verification_changed: dense ? 1 : 0,
    verification_unknown: 0,
  };
  if (path === '/api/dashboard/summary') return {
    indexed_files: 100000, indexed_folders: 2000, queued_or_running_jobs: 0,
    plan_count: 5, latest_scan_id: null, duplicate_group_count: 0,
    latest_reclaimable_bytes: 0,
  };
  if (path === '/api/settings') return visualSafeSettingsFixture();
  if (dense) {
    const populated = denseFixture(path);
    if (populated) return populated;
  }
  return { items: [], total: 0, page: 1, page_size: 50 };
}

// Browser-computed v056 semantic ownership on actual React route workspaces.
// This checks resolved CSS custom properties (not every rendered text pixel).
const w2ThemeAudit = [];
const w2Surfaces = ['canvas', 'surface', 'surface-soft', 'surface-strong'];
const w2TextRoles = ['text', 'text-muted', 'text-subtle'];

function w2Luminance(hex) {
  const channels = [1, 3, 5].map(index =>
    Number.parseInt(hex.slice(index, index + 2), 16) / 255)
    .map(value => value <= 0.04045
      ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}
function w2Contrast(foreground, background) {
  const a = w2Luminance(foreground), b = w2Luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
async function auditW2ComputedTheme(page, item, width, theme) {
  const measured = await page.evaluate(() => {
    const workspace = document.querySelector('.nfc-app-main');
    if (!workspace) throw Error('Missing actual right-workspace semantic scope');
    const style = getComputedStyle(workspace);
    const names = ['canvas', 'surface', 'surface-soft', 'surface-strong',
      'text', 'text-muted', 'text-subtle'];
    return {
      effective: document.documentElement.dataset.theme,
      values: Object.fromEntries(names.map(name =>
        [name, style.getPropertyValue('--nfc-w2-' + name).trim().toLowerCase()])),
    };
  });
  assert.equal(measured.effective, theme.effective,
    'Computed-theme audit must see actual effective theme: ' + item.id + '/' + width);
  for (const [role, value] of Object.entries(measured.values)) {
    assert.match(value, /^#[0-9a-f]{6}$/,
      item.id + '/' + theme.mode + '/' + width + ': --nfc-w2-' + role +
      ' must be resolved to an opaque hex CSS token');
  }
  const bright = w2TextRoles.map(role => w2Luminance(measured.values[role]));
  if (theme.effective === 'light') {
    assert.ok(bright[0] < bright[1] && bright[1] < bright[2],
      'Light semantic text hierarchy must survive on ' + item.id);
  } else {
    assert.ok(bright[0] > bright[1] && bright[1] > bright[2],
      'Dark semantic text hierarchy must survive on ' + item.id);
  }
  let minimum = Infinity;
  let compared = 0;
  for (const background of w2Surfaces) {
    for (const foreground of w2TextRoles) {
      const ratio = w2Contrast(measured.values[foreground], measured.values[background]);
      assert.ok(ratio >= 4.5,
        item.id + '/' + width + '/' + theme.mode + '-' + theme.system +
        ': computed --nfc-w2-' + foreground + ' / --nfc-w2-' + background +
        ' = ' + ratio.toFixed(2) + ':1, expected >= 4.5:1');
      minimum = Math.min(minimum, ratio);
      compared++;
    }
  }
  assert.equal(compared, 12, 'Each rendered route must audit 3 text roles x 4 surfaces');
  w2ThemeAudit.push({
    route: item.path, width, mode: theme.mode, system: theme.system,
    effective: measured.effective, values: measured.values,
    compared, minimumContrast: Number(minimum.toFixed(3)),
  });
}

// Separate from token-vs-token assertions: check the color of real heading
// glyphs against the alpha-composited *painted ancestor* backgrounds.
// Ledger page headers are flat by contract; fail closed for unknown color
// spaces, background images, opacity effects or a missing solid ancestor.
// Dashboard's separate hero/gradient styling remains outside this scoped audit.
const paintedHeadingAudit = [];
async function auditPaintedLedgerHeading(page, item, width, theme) {
  if (item.id === 'dashboard') return;
  const target = page.getByRole('heading', { name: item.heading, exact: true });
  const rendered = await target.evaluate(element => {
    if (!element.closest('.nfc-app-main'))
      throw Error('Ledger heading is outside the expected workspace');
    const bounds = element.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0)
      throw Error('Ledger heading has no visible layout box');
    // Chromium may resolve color-mix() to color(srgb ... / alpha).
    // Treat unsupported/out-of-gamut colors as unverified, never white.
    const readColor = color => {
      const rgb = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(\d*\.?\d+))?\s*\)$/.exec(color);
      const srgb = /^color\(srgb\s+(\d*\.?\d+)\s+(\d*\.?\d+)\s+(\d*\.?\d+)(?:\s*\/\s*(\d*\.?\d+))?\s*\)$/.exec(color);
      if (!rgb && !srgb) throw Error('Unknown rendered CSS color: ' + color);
      const match = rgb ?? srgb;
      const channels = match.slice(1, 4).map(Number);
      if (srgb) for (let i = 0; i < 3; i++) channels[i] *= 255;
      const alpha = match[4] === undefined ? 1 : Number(match[4]);
      if (![...channels, alpha].every(Number.isFinite) ||
          channels.some(c => c < 0 || c > 255) || alpha < 0 || alpha > 1)
        throw Error('Invalid rendered CSS color: ' + color);
      return { channels, alpha };
    };
    const textStyle = getComputedStyle(element);
    const text = readColor(textStyle.color);
    if (text.alpha !== 1) throw Error('Translucent heading text requires separate paint audit');
    const layers = [];
    for (let node = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.backgroundImage !== 'none')
        throw Error('Image/gradient ancestor needs pixel-specific audit: ' + node.tagName);
      if (Number(style.opacity) !== 1)
        throw Error('Opacity ancestor needs pixel-specific audit: ' + node.tagName);
      const surface = readColor(style.backgroundColor);
      if (surface.alpha > 0)
        layers.push({ color: surface.channels, alpha: surface.alpha,
          node: node.tagName.toLowerCase() });
      if (surface.alpha === 1) break;
    }
    if (!layers.length || layers[layers.length - 1].alpha !== 1)
      throw Error('No verifiable solid painted ancestor for ledger heading');
    let background = [0, 0, 0];
    for (const layer of [...layers].reverse())
      background = background.map((channel, i) =>
        layer.color[i] * layer.alpha + channel * (1 - layer.alpha));
    const asRgb = channels => 'rgb(' + channels.map(Math.round).join(', ') + ')';
    return {
      selector: element.tagName.toLowerCase(),
      actualForeground: textStyle.color,
      foreground: asRgb(text.channels),
      paintedBackground: asRgb(background),
      layers: layers.map(({ node, alpha }) => ({ node, alpha })),
    };
  });
  const ratio = computedContrastRatio(rendered.foreground, rendered.paintedBackground);
  const record = {
    route: item.path, width, mode: theme.mode, system: theme.system,
    effective: theme.effective, ...rendered, contrast: Number(ratio.toFixed(3)),
  };
  paintedHeadingAudit.push(record);
  assert.ok(ratio >= 4.5,
    'Real ledger heading painted contrast below 4.5:1: ' + JSON.stringify(record));
}

// Actual metric card ink/surface proof for both normal and pointer-hover
// states; unlike a token comparison, this resolves the winner after every
// imported CSS layer and alpha-composites its actual painted ancestors.
const metricHoverPaintAudit = [];
async function metricCardPaintSample(card, state) {
  return card.evaluate((node, state) => {
    const parseColor = color => {
      const rgb = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d*\.?\d+)(?:\s*,\s*(\d*\.?\d+))?\s*\)$/.exec(color);
      const srgb = /^color\(srgb\s+(\d*\.?\d+)\s+(\d*\.?\d+)\s+(\d*\.?\d+)(?:\s*\/\s*(\d*\.?\d+))?\s*\)$/.exec(color);
      if (!rgb && !srgb) throw Error('Unsupported computed metric paint: ' + color);
      const parts = rgb ?? srgb;
      const channels = parts.slice(1, 4).map(Number);
      const alpha = parts[4] === undefined ? 1 : Number(parts[4]);
      if (srgb) for (let i = 0; i < 3; i++) channels[i] *= 255;
      if (![...channels, alpha].every(Number.isFinite) ||
          channels.some(c => c < 0 || c > 255) || alpha < 0 || alpha > 1)
        throw Error('Out-of-range metric color: ' + color);
      return { channels, alpha };
    };
    const roundedRgb = parts => 'rgb(' + parts.map(Math.round).join(', ') + ')';
    const roles = ['label', 'value'];
    const metrics = roles.map(role => {
      const target = node.querySelector('.nfc-metric-' + role);
      if (!target || !target.textContent?.trim())
        throw Error('Missing real rendered metric ' + role);
      const text = getComputedStyle(target);
      const ink = parseColor(text.color);
      if (ink.alpha !== 1) throw Error('Semi-transparent metric ink needs pixel-level audit');
      const layers = [];
      for (let parent = target; parent; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (style.backgroundImage !== 'none' || Number(style.opacity) !== 1)
          throw Error('Non-flat metric paint requires pixel-level audit: ' + parent.tagName);
        const color = parseColor(style.backgroundColor);
        if (color.alpha > 0) layers.push({
          channels: color.channels, alpha: color.alpha, node: parent.tagName.toLowerCase(),
        });
        if (color.alpha === 1) break;
      }
      if (!layers.length || layers[layers.length - 1].alpha !== 1)
        throw Error('No opaque ancestor behind metric ' + role);
      let painted = [0, 0, 0];
      for (const layer of [...layers].reverse())
        painted = painted.map((channel, i) =>
          layer.channels[i] * layer.alpha + channel * (1 - layer.alpha));
      return {
        role, foreground: roundedRgb(ink.channels),
        background: roundedRgb(painted),
        layers: layers.map(({ node, alpha }) => ({ node, alpha })),
      };
    });
    return {
      state, hovered: node.matches(':hover'),
      computedCardBackground: getComputedStyle(node).backgroundColor,
      metrics,
    };
  }, state);
}
async function auditMetricHoverPaint(page, item, width, theme) {
  if (item.id !== 'dashboard' && item.id !== 'media') return;
  const selector = item.id === 'dashboard'
    ? '.nfc-v2-dashboard-metrics .nfc-metric-card'
    : '.nfc-media-page > .nfc-metric-grid .nfc-metric-card';
  const card = page.locator(selector).first();
  await card.waitFor({ state: 'visible' });
  // Run AFTER its accepted screenshot; hovering must not affect baselines.
  await page.mouse.move(0, 0);
  for (const state of ['normal', 'hover']) {
    if (state === 'hover') await card.hover();
    const snap = await metricCardPaintSample(card, state);
    assert.equal(snap.hovered, state === 'hover',
      'Pointer state must be genuinely active when comparing metric paint');
    assert.equal(snap.metrics.length, 2);
    for (const role of snap.metrics) {
      const actual = computedContrastRatio(role.foreground, role.background);
      const record = {
        route: item.path, width, mode: theme.mode, system: theme.system,
        effective: theme.effective, state,
        computedCardBackground: snap.computedCardBackground,
        ...role, contrast: Number(actual.toFixed(3)),
      };
      metricHoverPaintAudit.push(record);
      assert.ok(actual >= 4.5,
        'Rendered metric ' + state + ' paint falls below 4.5:1: ' + JSON.stringify(record));
    }
  }
  await page.mouse.move(0, 0);
}

// Same-document CSS theme invalidation: deliberately flip only the root's
// effective CSS theme. This is NOT a replacement for ThemeProvider/user-action
// tests, which live in browser-theme-resilience.mjs. We preserve the provider
// mode, storage, and system settings and restore the effective theme in finally.
const liveMetricThemeAudit = [];
async function metricThemeSnapshot(page, card) {
  const [tokens, paint] = await Promise.all([
    page.evaluate(() => {
      const root = document.documentElement;
      const workspace = document.querySelector('.nfc-app-main');
      if (!workspace) throw Error('No right-workspace theme owner');
      const style = getComputedStyle(workspace);
      const names = ['--nfc-w2-text', '--nfc-w2-text-muted',
        '--nfc-w2-surface', '--nfc-w2-surface-soft'];
      return {
        effective: root.dataset.theme,
        values: Object.fromEntries(names.map(name =>
          [name, style.getPropertyValue(name).trim().toLowerCase()])),
      };
    }),
    metricCardPaintSample(card, 'normal'),
  ]);
  assert.equal(paint.hovered, false, 'Live theme audit requires non-hovered metric card');
  const contrasts = paint.metrics.map(role => {
    const ratio = computedContrastRatio(role.foreground, role.background);
    assert.ok(ratio >= 4.5,
      'Live metric theme paint fell below 4.5:1: ' + JSON.stringify({ tokens, role }));
    return { role: role.role, foreground: role.foreground,
      background: role.background, contrast: Number(ratio.toFixed(3)) };
  });
  return {
    tokens, cardBackground: paint.computedCardBackground, contrasts,
  };
}
async function auditLiveMetricThemeCascade(page, item, width, theme) {
  if (item.id !== 'dashboard' && item.id !== 'media') return;
  const selector = item.id === 'dashboard'
    ? '.nfc-v2-dashboard-metrics .nfc-metric-card'
    : '.nfc-media-page > .nfc-metric-grid .nfc-metric-card';
  const card = page.locator(selector).first();
  await card.waitFor({ state: 'visible' });
  await page.mouse.move(0, 0);
  const original = await page.evaluate(() => ({
    effective: document.documentElement.dataset.theme,
    colorScheme: document.documentElement.style.colorScheme,
    storedMode: localStorage.getItem('nfc_theme_mode'),
  }));
  assert.equal(original.effective, theme.effective);
  // Chromium can briefly expose new root tokens with a still-transitioning
  // historical Console v2 metric label. Observe post-style/repaint values,
  // not that transient mixed-color frame. This never relaxes the AA threshold.
  const awaitPaintFlush = () => page.evaluate(() =>
    new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const initial = await metricThemeSnapshot(page, card);
  const oppositeTheme = theme.effective === 'light' ? 'dark' : 'light';
  let inverted;
  try {
    await page.evaluate(next => {
      document.documentElement.dataset.theme = next;
      document.documentElement.style.colorScheme = next;
    }, oppositeTheme);
    await awaitPaintFlush();
    inverted = await metricThemeSnapshot(page, card);
    assert.equal(inverted.tokens.effective, oppositeTheme);
    for (const name of Object.keys(initial.tokens.values)) {
      assert.notEqual(inverted.tokens.values[name], initial.tokens.values[name],
        'Live CSS theme must replace semantic owner ' + name);
    }
    assert.notEqual(inverted.contrasts[1].foreground,
      initial.contrasts[1].foreground,
      'Actual metric value ink must update without navigation');
  } finally {
    await page.evaluate(before => {
      document.documentElement.dataset.theme = before.effective;
      document.documentElement.style.colorScheme = before.colorScheme;
    }, original);
  }
  await awaitPaintFlush();
  const restored = await metricThemeSnapshot(page, card);
  assert.deepEqual(restored.tokens, initial.tokens,
    'Every semantic palette token must fully restore in the same document');
  assert.deepEqual(restored.contrasts.map(x => x.foreground),
    initial.contrasts.map(x => x.foreground),
    'Actual metric ink must fully restore after opposite CSS theme');
  assert.equal(await page.evaluate(() => localStorage.getItem('nfc_theme_mode')),
    original.storedMode, 'CSS-only probe must never persist a theme change');
  liveMetricThemeAudit.push({
    route: item.path, width, mode: theme.mode, system: theme.system,
    initialEffective: theme.effective, oppositeEffective: oppositeTheme,
    initial, inverted, restored, providerModeUntouched: true,
  });
}

// Unlike the CSS-only inversion above, use the real authenticated Header
// theme menu and ThemeProvider state (including System mode and persistence).
// A mounted workspace must repaint actual metric text/surfaces after user
// interaction, without navigation or a synthetic document.dataset mutation.
// Run after accepted screenshots to keep their 352-image baseline intact.
const providerMetricThemeAudit = [];
const providerModeLabels = {
  light: '浅色模式', dark: '深色模式', system: '跟随系统',
};
async function selectWorkspaceTheme(page, mode, effective) {
  const isMobile = (page.viewportSize()?.width ?? 0) < 768;
  const menu = page.locator('.nfc-header-command-cluster details.nfc-v2-dropdown').first();
  if (isMobile) {
    // CSS intentionally hides the cramped Header dropdown at phone widths.
    // Exercise its accessible equivalent in the actual mobile navigation drawer.
    await page.getByRole('button', { name: '打开导航菜单' }).click();
    const dialog = page.getByRole('dialog', { name: 'NAS File Center 主导航' });
    await dialog.getByRole('group', { name: '界面主题' })
      .getByRole('button', { name: providerModeLabels[mode] }).click();
    await dialog.waitFor({ state: 'hidden' });
  } else {
    await menu.locator('summary[aria-label="切换界面主题"]').click();
    await menu.getByRole('button', { name: providerModeLabels[mode] }).click();
  }
  await page.waitForFunction(({ mode, effective, label }) => {
    const root = document.documentElement;
    const selected = document.querySelector(
      '.nfc-header-command-cluster details.nfc-v2-dropdown button[aria-pressed="true"]');
    return root.dataset.theme === effective && root.style.colorScheme === effective &&
      localStorage.getItem('nfc_theme_mode') === mode &&
      selected?.textContent?.includes(label);
  }, { mode, effective, label: providerModeLabels[mode] }, { timeout: 10000 });
  if (!isMobile) assert.equal(await menu.getAttribute('open'), null,
    'Real Header theme menu should close after user selection');
  // React effects and reduced-motion paint must settle before steady-state
  // contrast checks; intermediate-frame visual acceptance remains separate.
  await page.evaluate(() => new Promise(resolve =>
    requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
// Observe post-mutation browser animation frames, not just the settled
// ThemeProvider result. Capture starts BEFORE the real theme-menu click, so
// Playwright round-trips cannot accidentally skip the first rendered frame.
// This is computed flat-paint contrast, NOT a screenshot/pixel-level claim.
const providerMetricFrameAudit = [];
// Keep the existing reduced-motion acceptance unchanged. Sample normal motion
// on mobile, tablet edge and desktop with every explicit/System theme fixture.
const NORMAL_MOTION_WIDTHS = new Set([360, 768, 1440]);
const normalMotionMetricFrameAudit = [];
const PROVIDER_FRAME_COUNT = 12;
async function armProviderMetricFrames(page, selector, expectedBefore, expectedAfter) {
  await page.evaluate(({ selector, expectedBefore, expectedAfter, count }) => {
    const root = document.documentElement;
    if (root.dataset.theme !== expectedBefore)
      throw Error('Frame observer armed on wrong initial theme');
    if (!document.querySelector(selector))
      throw Error('Missing mounted metric card for frame observer');
    let resolveFrames, rejectFrames;
    window.__nfcMetricThemeFrameCapture = new Promise((resolve, reject) => {
      resolveFrames = resolve;
      rejectFrames = reject;
    });
    let started = false;
    const frames = [];
    const observer = new MutationObserver(() => {
      if (started || root.dataset.theme !== expectedAfter) return;
      started = true;
      observer.disconnect();
      const collect = timestamp => {
        try {
          const card = document.querySelector(selector);
          if (!card) throw Error('Metric card disappeared during theme switch');
          const parse = color => {
            const rgb = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d*\.?\d+)(?:\s*,\s*(\d*\.?\d+))?\s*\)$/.exec(color);
            const srgb = /^color\(srgb\s+(\d*\.?\d+)\s+(\d*\.?\d+)\s+(\d*\.?\d+)(?:\s*\/\s*(\d*\.?\d+))?\s*\)$/.exec(color);
            if (!rgb && !srgb) throw Error('Unrecognized frame color: ' + color);
            const parts = rgb ?? srgb;
            const channels = parts.slice(1, 4).map(Number);
            const alpha = parts[4] === undefined ? 1 : Number(parts[4]);
            if (srgb) for (let i = 0; i < 3; i++) channels[i] *= 255;
            if (![...channels, alpha].every(Number.isFinite) ||
                channels.some(channel => channel < 0 || channel > 255) ||
                alpha < 0 || alpha > 1)
              throw Error('Out-of-range frame color: ' + color);
            return { channels, alpha };
          };
          const asRgb = channels => 'rgb(' + channels.map(Math.round).join(', ') + ')';
          const roles = ['label', 'value'].map(role => {
            const target = card.querySelector('.nfc-metric-' + role);
            if (!target || !target.textContent?.trim())
              throw Error('Missing real frame metric ' + role);
            const ink = parse(getComputedStyle(target).color);
            if (ink.alpha !== 1)
              throw Error('Translucent metric ink requires pixel-level audit');
            const layers = [];
            for (let ancestor = target; ancestor; ancestor = ancestor.parentElement) {
              const style = getComputedStyle(ancestor);
              if (style.backgroundImage !== 'none' || Number(style.opacity) !== 1)
                throw Error('Non-flat metric frame requires pixel-level audit');
              const layer = parse(style.backgroundColor);
              if (layer.alpha > 0) layers.push(layer);
              if (layer.alpha === 1) break;
            }
            if (!layers.length || layers[layers.length - 1].alpha !== 1)
              throw Error('No opaque ancestor behind metric frame');
            let painted = [0, 0, 0];
            for (const layer of [...layers].reverse())
              painted = painted.map((channel, i) =>
                layer.channels[i] * layer.alpha + channel * (1 - layer.alpha));
            return { role, foreground: asRgb(ink.channels), background: asRgb(painted) };
          });
          frames.push({
            frame: frames.length + 1, atMs: Number(timestamp.toFixed(2)),
            effective: root.dataset.theme, roles,
          });
          if (frames.length < count) requestAnimationFrame(collect);
          else { clearTimeout(timeout); resolveFrames(frames); }
        } catch (error) {
          clearTimeout(timeout);
          rejectFrames(String(error));
        }
      };
      requestAnimationFrame(collect);
    });
    const timeout = setTimeout(() => {
      observer.disconnect();
      rejectFrames('ThemeProvider frame capture did not finish in 10 seconds');
    }, 10000);
    observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] });
  }, { selector, expectedBefore, expectedAfter, count: PROVIDER_FRAME_COUNT });
}
async function readProviderMetricFrames(page, expected, item, width, theme, phase) {
  const frames = await page.evaluate(() => window.__nfcMetricThemeFrameCapture);
  assert.equal(frames.length, PROVIDER_FRAME_COUNT,
    'Must sample every requested paint frame: ' + phase);
  const contrasts = [];
  for (const frame of frames) {
    assert.equal(frame.effective, expected,
      'Root theme changed unexpectedly during captured frames: ' + phase);
    assert.equal(frame.roles.length, 2);
    for (const role of frame.roles) {
      const ratio = computedContrastRatio(role.foreground, role.background);
      const record = {
        phase, route: item.path, width, mode: theme.mode, system: theme.system,
        expectedEffective: expected, ...frame, role: role.role,
        foreground: role.foreground, background: role.background,
        contrast: Number(ratio.toFixed(3)),
      };
      contrasts.push(record);
      assert.ok(ratio >= 4.5,
        'Actual per-frame metric contrast below 4.5:1: ' + JSON.stringify(record));
    }
  }
  await page.evaluate(() => { delete window.__nfcMetricThemeFrameCapture; });
  return contrasts;
}

async function auditProviderMetricTheme(page, item, width, theme, motion = 'reduce') {
  if (item.id !== 'dashboard' && item.id !== 'media') return;
  const selector = item.id === 'dashboard'
    ? '.nfc-v2-dashboard-metrics .nfc-metric-card'
    : '.nfc-media-page > .nfc-metric-grid .nfc-metric-card';
  const card = page.locator(selector).first();
  await card.waitFor({ state: 'visible' });
  await page.mouse.move(0, 0);
  const originalMode = await page.evaluate(() => localStorage.getItem('nfc_theme_mode'));
  assert.equal(originalMode, theme.mode);
  let transitionEvidence;
  if (motion === 'no-preference') {
    transitionEvidence = await page.evaluate(selector => {
      const card = document.querySelector(selector);
      if (!card) throw Error('Missing actual metric for normal-motion transition audit');
      const label = card.querySelector('.nfc-metric-label');
      const value = card.querySelector('.nfc-metric-value');
      if (!label || !value) throw Error('Missing metric ink for normal-motion transition audit');
      const of = el => ({
        property: getComputedStyle(el).transitionProperty,
        duration: getComputedStyle(el).transitionDuration,
      });
      return {
        reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
        card: of(card), label: of(label), value: of(value),
      };
    }, selector);
    assert.equal(transitionEvidence.reducedMotion, false,
      'Normal-motion frame audit must exercise actual browser motion preferences');
    const props = role => transitionEvidence[role].property.split(',').map(x => x.trim());
    for (const role of ['card', 'label', 'value']) {
      for (const forbidden of ['all', 'color', 'background', 'background-color']) {
        assert.ok(!props(role).includes(forbidden),
          'Metric ' + role + ' may not transition theme paint in normal motion: ' +
          JSON.stringify(transitionEvidence));
      }
    }
    assert.ok(props('card').includes('border-color') &&
      props('value').includes('transform'),
    'Normal motion must retain real hover and value motion: ' +
    JSON.stringify(transitionEvidence));
    assert.ok(transitionEvidence.card.duration.split(',').some(x => parseFloat(x) > 0),
      'Normal motion must not silently inherit reduced-motion transition suppression');
  }
  const initial = await metricThemeSnapshot(page, card);
  assert.equal(initial.tokens.effective, theme.effective);
  const opposite = theme.effective === 'light' ? 'dark' : 'light';
  let changed, changedFrames, restoredFrames;
  try {
    await armProviderMetricFrames(page, selector, theme.effective, opposite);
    await selectWorkspaceTheme(page, opposite, opposite);
    changedFrames = await readProviderMetricFrames(
      page, opposite, item, width, theme, 'changed');
    changed = await metricThemeSnapshot(page, card);
    assert.equal(changed.tokens.effective, opposite);
    for (const name of Object.keys(initial.tokens.values)) {
      assert.notEqual(changed.tokens.values[name], initial.tokens.values[name],
        'ThemeProvider user action must change workspace semantic palette: ' + name);
    }
    assert.notEqual(changed.contrasts[1].foreground, initial.contrasts[1].foreground,
      'ThemeProvider user action must repaint real metric value ink');
  } finally {
    // Recover through the actual user control even if the contrast check fails.
    // System mode must be restored as System, not replaced by its current color.
    await armProviderMetricFrames(page, selector, opposite, theme.effective);
    await selectWorkspaceTheme(page, theme.mode, theme.effective);
    restoredFrames = await readProviderMetricFrames(
      page, theme.effective, item, width, theme, 'restored');
  }
  const restored = await metricThemeSnapshot(page, card);
  assert.deepEqual(restored.tokens, initial.tokens,
    'ThemeProvider must restore computed workspace tokens after user flow');
  assert.deepEqual(restored.contrasts.map(x => [x.foreground, x.background]),
    initial.contrasts.map(x => [x.foreground, x.background]),
    'Actual painted metric ink and background must restore after user flow');
  assert.equal(await page.evaluate(() => localStorage.getItem('nfc_theme_mode')), originalMode,
    'ThemeProvider must restore original explicit/System user preference');
  if (motion === 'reduce') {
    providerMetricThemeAudit.push({
      route: item.path, width, mode: theme.mode, system: theme.system,
      initialEffective: theme.effective, oppositeEffective: opposite,
      initial, changed, restored, realUserControl: true,
    });
  }
  const evidence = {
    route: item.path, width, mode: theme.mode, system: theme.system,
    oppositeEffective: opposite, changedFrames, restoredFrames,
    motion, ...(transitionEvidence ? { transitionEvidence } : {}),
  };
  if (motion === 'no-preference') normalMotionMetricFrameAudit.push(evidence);
  else providerMetricFrameAudit.push(evidence);
}


// Decorative dashboard gradients must remain isolated from readable hero
// copy. Refuse any actual gradient/background image behind those text roles;
// then compare computed ink over alpha-composited real ancestor solid paint.
async function auditDashboardHeroPaint(page, width, theme) {
  const result = await page.evaluate(() => {
    const illustration = document.querySelector('.nfc-v2-hero-illustration');
    if (!illustration || getComputedStyle(illustration).display !== 'none' ||
        illustration.getClientRects().length !== 0)
      throw Error('Decorative hero gradient must not overlap readable text');
    const parse = value => {
      const rgb = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d*\.?\d+)(?:\s*,\s*(\d*\.?\d+))?\s*\)$/.exec(value);
      const srgb = /^color\(srgb\s+(\d*\.?\d+)\s+(\d*\.?\d+)\s+(\d*\.?\d+)(?:\s*\/\s*(\d*\.?\d+))?\s*\)$/.exec(value);
      if (!rgb && !srgb) throw Error('Unsupported dashboard hero computed color: ' + value);
      const m = rgb || srgb, channels = m.slice(1, 4).map(Number);
      const alpha = m[4] === undefined ? 1 : Number(m[4]);
      if (srgb) for (let i = 0; i < 3; i++) channels[i] *= 255;
      if (channels.some(n => !Number.isFinite(n) || n < 0 || n > 255) ||
          !Number.isFinite(alpha) || alpha < 0 || alpha > 1)
        throw Error('Invalid dashboard hero color: ' + value);
      return { channels, alpha };
    };
    const rgb = x => 'rgb(' + x.map(Math.round).join(', ') + ')';
    const pairs = [
      ['eyebrow', '.nfc-v2-dashboard-hero .nfc-v2-hero-eyebrow'],
      ['heading', '.nfc-v2-dashboard-hero .nfc-page-title'],
      ['description', '.nfc-v2-dashboard-hero .nfc-page-description'],
      ['caption', '.nfc-v2-dashboard-hero .nfc-v2-hero-caption'],
    ].map(([name, selector]) => {
      const element = document.querySelector(selector);
      if (!element || !element.textContent?.trim() ||
          !element.getClientRects().length)
        throw Error('Missing actually rendered Dashboard hero ink: ' + selector);
      const ink = parse(getComputedStyle(element).color);
      if (ink.alpha !== 1) throw Error('Hero ink requires pixel audit: ' + name);
      const layers = [];
      for (let node = element; node; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.backgroundImage !== 'none' || Number(style.opacity) !== 1 ||
            style.filter !== 'none' || style.backdropFilter !== 'none')
          throw Error('Hero text placed over gradient/compositor effect: ' + name);
        const layer = parse(style.backgroundColor);
        if (layer.alpha > 0) layers.push(layer);
        if (layer.alpha === 1) break;
      }
      if (!layers.length || layers.at(-1).alpha !== 1)
        throw Error('No opaque actual Dashboard hero ancestor: ' + name);
      let surface = [0, 0, 0];
      for (const layer of layers.reverse())
        surface = surface.map((v, i) => layer.channels[i] * layer.alpha +
          v * (1 - layer.alpha));
      return { name, foreground: rgb(ink.channels), background: rgb(surface) };
    });
    return { gradientIllustrationHidden: true, pairs };
  });
  for (const pair of result.pairs) {
    const contrast = computedContrastRatio(pair.foreground, pair.background);
    pair.contrast = Number(contrast.toFixed(3));
    assert.ok(contrast >= 4.5,
      'Real Dashboard hero text/composited background below AA: ' +
      JSON.stringify({ width, theme, ...pair }));
  }
  dashboardHeroPaintAudit.push({
    width, mode: theme.mode, system: theme.system, effective: theme.effective,
    ...result,
  });
}

async function inspect(page, theme, width, item) {
  const violations = await page.evaluate(({ theme, width, item }) => {
    const get = selector => {
      const el = document.querySelector(selector);
      if (!el) throw Error('Missing actual React CSS target: ' + selector);
      return el;
    };
    const failures = [];
    const check = (ok, message) => { if (!ok) failures.push(message); };
    const workspace = get('.nfc-app-main');
    const pageContent = get('.nfc-app-main .nfc-page-content');
    const screen = get(item.selector);
    const inside = el => {
      const r = el.getBoundingClientRect();
      return r.left >= -2 && r.right <= width + 2;
    };
    check(document.documentElement.dataset.theme === theme, 'Wrong effective theme');
    check(inside(pageContent), 'Workspace overflow');
    check(inside(screen), 'Page root overflow');
    if (width >= 768) {
      check(getComputedStyle(workspace).overflowY === 'hidden',
        'Desktop outer workspace unexpectedly scrolls');
      check(getComputedStyle(pageContent).overflowY === 'auto',
        'Desktop page must own single scrolling region');
      check(getComputedStyle(get('.nfc-app-shell')).overflowY === 'hidden',
        'Desktop shell adds a second scroller');
    } else {
      check(getComputedStyle(workspace).overflowY === 'visible',
        'Mobile must keep normal document scrolling');
    }
    if (item.id === 'dashboard') {
      const metrics = get('.nfc-v2-dashboard-metrics .nfc-metric-grid');
      const content = get('.nfc-v2-dashboard-content');
      check(inside(metrics), 'Dashboard metrics overflow');
      check(inside(content), 'Dashboard columns overflow');
      check(getComputedStyle(metrics).display === 'grid', 'Metric layout lost grid');
    } else {
      if (item.id === 'media') {
        const mediaMetrics = get('.nfc-media-page > .nfc-metric-grid');
        check(inside(mediaMetrics), 'Media metrics overflow viewport');
        check(getComputedStyle(mediaMetrics).display === 'grid',
          'Media metrics lost their responsive grid');
      }
      const head = get(item.selector + ' > .nfc-page-header');
      const panel = get(item.selector + ' > .nfc-data-panel');
      const mb = getComputedStyle(head).marginBottom;
      check(mb === '0px', 'Ledger duplicate heading margin: ' + mb);
      check(inside(head), 'Ledger header overflow');
      check(inside(panel), 'Ledger panel overflow');
      check(parseFloat(getComputedStyle(screen).rowGap) >= 10,
        'Ledger page gap must own vertical rhythm');
    }
    return failures;
  }, { theme, width, item });
  assert.deepEqual(violations, [], item.id + ' ' + width + ': ' + violations.join('; '));
}

async function inspectDense(page, item, width) {
  await page.waitForFunction(({ row, card }) =>
    Boolean(document.querySelector(row) || document.querySelector(card)),
  { row: item.row, card: item.card }, { timeout: 10000 });
  const failures = await page.evaluate(({ item, width }) => {
    const errors = [];
    const isMobile = width < 768;
    const selectors = isMobile ? item.card : item.row;
    const rows = [...document.querySelectorAll(selectors)];
    const expectedCount = item.count ?? 2;
    if (rows.length !== expectedCount)
      errors.push('Expected ' + expectedCount + ' dense records, got ' + rows.length);
    const container = document.querySelector('.nfc-page-content');
    const outer = container?.getBoundingClientRect();
    for (const row of rows) {
      const rect = row.getBoundingClientRect();
      if (!Number.isFinite(rect.width) || rect.width <= 0) errors.push('Zero-width dense row/card');
      if (isMobile && (rect.left < -2 || rect.right > width + 2))
        errors.push('Mobile dense card exceeds viewport bounds');
    }
    if (!isMobile) {
      const scroll = document.querySelector(item.scroll);
      if (!scroll) errors.push('Desktop wide-table scroller missing');
      else {
        const r = scroll.getBoundingClientRect();
        if (r.left < -2 || r.right > width + 2)
          errors.push('Wide-table scrollport exceeds viewport');
        if (!['auto', 'scroll'].includes(getComputedStyle(scroll).overflowX))
          errors.push('Wide table must own horizontal overflow');
      }
    }
    if (item.id === 'plans' && !isMobile) {
      const firstColumn = document.querySelector('.nfc-v2-plans-page .nfc-v2-plan-table th:first-child');
      const title = document.querySelector('.nfc-v2-plans-page .nfc-v2-plan-name span');
      const colWidth = firstColumn?.getBoundingClientRect().width ?? 0;
      const titleWidth = title?.getBoundingClientRect().width ?? 0;
      if (colWidth < 240 || titleWidth < 140)
        errors.push('Plan list name column collapsed (' + colWidth + '/' + titleWidth + 'px)');
    }
    if (item.id === 'media') {
      const selector = '.nfc-v2-media-checkbox[aria-label^="选择可永久删除损坏媒体"]';
      const controls = [...document.querySelectorAll(selector)];
      const unique = new Map(controls.map(x => [x.getAttribute('aria-label'), x]));
      const enabled = id => unique.get('选择可永久删除损坏媒体 #' + id)?.disabled === false;
      if (unique.size !== 3 || enabled(801) || !enabled(802) || enabled(803))
        errors.push('Only corrupt frozen-evidence media #802 may be selected for delete Preview');
      const statusText = rows.map(x => x.innerText).join(' ');
      for (const label of ['SHA256 通过', '内容变化', '未建立基线', '损坏']) {
        if (!statusText.includes(label)) errors.push('Media badge missing ' + label);
      }
    }
    if (item.id === 'quarantine') {
      const selector = '.nfc-v2-quarantine-checkbox[aria-label^="选择隔离条目"]';
      const controls = [...document.querySelectorAll(selector)];
      const unique = new Map(controls.map(x => [x.getAttribute('aria-label'), x]));
      const enabled = id => unique.get('选择隔离条目 #' + id)?.disabled === false;
      if (unique.size !== 3 || !enabled(901) || enabled(902) || enabled(903))
        errors.push('Only active quarantine entry #901 may be selected');
      const statusText = rows.map(x => x.innerText).join(' ');
      for (const label of ['已隔离', '冲突', '已恢复']) {
        if (!statusText.includes(label)) errors.push('Quarantine state missing ' + label);
      }
    }
    if (!outer || outer.left < -2 || outer.right > width + 2)
      errors.push('Dense data caused workspace viewport overflow');
    return errors;
  }, { item, width });
  assert.deepEqual(failures, [], item.id + ' dense ' + width + ': ' + failures.join('; '));
}

async function inspectNativeCheckboxKeyboard(page, item, width, theme) {
  if (item.id !== 'media' && item.id !== 'quarantine') return;
  // The dense fixture has exactly one eligible row. Disabled controls must
  // remain truly native-disabled, not merely visually muted, and neither
  // the checkbox checked state nor the backend may change during focus.
  const media = item.id === 'media';
  const prefix = media ? '选择可永久删除损坏媒体 #' : '选择隔离条目 #';
  const eligibleId = media ? 802 : 901;
  const blockedIds = media ? [801, 803] : [902, 903];
  const eligible = page.getByRole('checkbox', { name: prefix + eligibleId, exact: true });
  const before = await eligible.isChecked();
  assert.equal(await eligible.isEnabled(), true, item.id + ' eligible checkbox must be enabled');
  for (const id of blockedIds) {
    const blocked = page.getByRole('checkbox', { name: prefix + id, exact: true });
    assert.equal(await blocked.isDisabled(), true,
      item.id + ' protected record #' + id + ' must stay natively disabled');
    assert.equal(await blocked.isChecked(), false,
      item.id + ' protected record #' + id + ' must stay unchecked');
  }
  await eligible.focus();
  // Genuine keyboard modality is required; programmatic .focus() alone
  // can leave :focus-visible unset in Chromium.
  await page.keyboard.press('Tab');
  await page.keyboard.press('Shift+Tab');
  const state = await eligible.evaluate((input, kind) => {
    // A data-panel-body may have a transparent computed background because a
    // historical !important ledger override owns the visible card. Looking at
    // that element alone is not the painted surface. Walk the ACTUAL checkbox
    // ancestors and alpha-composite their backgrounds over the first opaque
    // ancestor. Never pass rgba(...,0) as if it were a solid WCAG background.
    const pageRoot = input.closest(kind === 'media'
      ? '.nfc-v2-media-page' : '.nfc-v2-quarantine-ledger');
    // CSS color-mix() can compute to color(srgb r g b / alpha),
    // whereas older declarations compute to rgb()/rgba(). Both are sRGB;
    // fail closed on unknown spaces or out-of-gamut/invalid channels.
    const parsePaintedColor = color => {
      const rgb = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*(\d*\.?\d+))?\s*\)$/.exec(color);
      const srgb = /^color\(srgb\s+(\d*\.?\d+)\s+(\d*\.?\d+)\s+(\d*\.?\d+)(?:\s*\/\s*(\d*\.?\d+))?\s*\)$/.exec(color);
      if (!rgb && !srgb) throw new Error('Unresolvable computed painted surface: ' + color);
      const match = rgb ?? srgb;
      const channels = match.slice(1, 4).map(Number);
      const alpha = match[4] === undefined ? 1 : Number(match[4]);
      if (srgb) for (let i = 0; i < channels.length; i++) channels[i] *= 255;
      if (![...channels, alpha].every(Number.isFinite) ||
          channels.some(channel => channel < 0 || channel > 255) ||
          alpha < 0 || alpha > 1)
        throw new Error('Out-of-range computed painted surface: ' + color);
      return { rgb: channels, alpha };
    };
    const layers = [];
    for (let node = input.parentElement; node; node = node.parentElement) {
      const color = getComputedStyle(node).backgroundColor;
      const { rgb, alpha } = parsePaintedColor(color);
      if (alpha > 0) layers.push({
        rgb, alpha, node: node.tagName.toLowerCase(),
      });
      if (alpha === 1) break;
    }
    // The document canvas may have an implicit color, but that must not
    // silently be assumed: a missing opaque layer fails the contrast gate.
    if (!pageRoot || !layers.length || layers[layers.length - 1].alpha !== 1)
      throw new Error('No opaque painted ancestor for native checkbox');
    let composited = [0, 0, 0];
    for (const layer of [...layers].reverse())
      composited = layer.rgb.map((channel, i) =>
        channel * layer.alpha + composited[i] * (1 - layer.alpha));
    const paintedBackground = 'rgb(' + composited.map(Math.round).join(', ') + ')';
    const style = getComputedStyle(input);
    const box = input.getBoundingClientRect();
    return {
      nativeType: input instanceof HTMLInputElement && input.type === 'checkbox',
      accessibleName: input.getAttribute('aria-label'),
      focused: document.activeElement === input,
      focusVisible: input.matches(':focus-visible'),
      checked: input.checked,
      disabled: input.disabled,
      width: Number(box.width.toFixed(1)),
      height: Number(box.height.toFixed(1)),
      inViewport: box.left >= -2 && box.right <= innerWidth + 2 &&
        box.top >= -2 && box.bottom <= innerHeight + 2,
      outlineStyle: style.outlineStyle,
      outlineWidth: parseFloat(style.outlineWidth),
      outlineColor: style.outlineColor,
      surfaceBackground: paintedBackground,
      paintedLayerCount: layers.length,
      transitionDuration: style.transitionDuration,
    };
  }, item.id);
  const contrast = computedContrastRatio(state.outlineColor, state.surfaceBackground);
  const record = { route: item.path, width, theme: theme.mode + '-' + theme.system,
    eligibleId, blockedIds, ...state, focusContrast: Number(contrast.toFixed(2)) };
  checkboxKeyboardAudit.push(record);
  assert.equal(state.nativeType, true, item.id + ' must use a native input');
  assert.equal(state.accessibleName, prefix + eligibleId);
  assert.equal(state.focused && state.focusVisible, true,
    'Real Tab-return focus must remain visible: ' + JSON.stringify(record));
  assert.equal(state.disabled, false);
  assert.equal(state.checked, before, 'Focus-only audit must not change selection');
  assert.equal(await eligible.isChecked(), before, 'React selection state must stay stable');
  assert.ok(state.inViewport && state.width >= 17 && state.height >= 17,
    'Focused checkbox must remain in viewport: ' + JSON.stringify(record));
  assert.equal(state.outlineStyle, 'solid');
  assert.ok(state.outlineWidth >= 3 && contrast >= 3,
    'Computed checkbox ring must be at least 3px and 3:1: ' + JSON.stringify(record));
  assert.equal(state.transitionDuration, '0s',
    'Checkbox keyboard focus indicator must never animate: ' + JSON.stringify(record));
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
      const outbound = [], writes = [];
      let denseMode = false;
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
            body: JSON.stringify({ detail: 'READ_ONLY_WORKSPACE_FIXTURE' }) });
          return;
        }
        await route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify(fixture(url.pathname, denseMode)) });
      });
      const label = theme.mode + '-' + theme.system + '-' + width;
      try {
        for (const item of PAGES) {
          await page.goto(BASE + item.path, { waitUntil: 'domcontentloaded' });
          await page.getByRole('heading', { name: item.heading, exact: true }).waitFor();
          await inspect(page, theme.effective, width, item);
          await auditW2ComputedTheme(page, item, width, theme);
          await auditPaintedLedgerHeading(page, item, width, theme);
          await page.screenshot({
            path: resolve(OUT, item.id + '-' + label + '.png'),
            fullPage: false,
          });
          if (item.id === 'dashboard') await auditDashboardHeroPaint(page, width, theme);
          await auditMetricHoverPaint(page, item, width, theme);
          await auditLiveMetricThemeCascade(page, item, width, theme);
          await auditProviderMetricTheme(page, item, width, theme);
          if (NORMAL_MOTION_WIDTHS.has(width) &&
              (item.id === 'dashboard' || item.id === 'media')) {
            // The same mounted, synthetic GET-only page remains authenticated.
            // Keep the old reduced-motion run and 352 screenshot baseline intact.
            await page.emulateMedia({ reducedMotion: 'no-preference' });
            try {
              await auditProviderMetricTheme(page, item, width, theme, 'no-preference');
            } finally {
              await page.emulateMedia({ reducedMotion: 'reduce' });
            }
          }
        }
        // A second pass mounts populated realistic ledgers without any backend writes.
        // Preserve six empty-state routes, add five dense real pages, including status gates.
        denseMode = true;
        for (const item of DENSE_PAGES) {
          await page.goto(BASE + item.path, { waitUntil: 'domcontentloaded' });
          await inspectDense(page, item, width);
          await page.screenshot({
            path: resolve(OUT, item.id + '-dense-' + label + '.png'),
            fullPage: false,
          });
          // Inspect after screenshots to preserve the accepted visual baseline.
          await inspectNativeCheckboxKeyboard(page, item, width, theme);
        }
        denseMode = false;
        assert.deepEqual(writes, [], 'No write or Generate action may reach backend');
        assert.deepEqual(outbound, [], 'No outbound or real NAS traffic');
        passed++;
        console.log('[WORKSPACE CASCADE PASS] ' + label);
      } catch (err) {
        console.error('[WORKSPACE CASCADE FAIL] ' + label, err);
        await page.screenshot({ path: resolve(OUT, 'failure-' + label + '.png') })
          .catch(() => {});
        throw err;
      } finally {
        await context.close();
      }
    }
  }
  assert.equal(passed, WIDTHS.length * THEMES.length);
  assert.equal(dashboardHeroPaintAudit.length, WIDTHS.length * THEMES.length,
    'Dashboard hero gradients must stay hidden and text must pass every viewport/theme');
  assert.ok(dashboardHeroPaintAudit.every(c =>
    c.gradientIllustrationHidden && c.pairs.length === 4 &&
    c.pairs.every(p => p.contrast >= 4.5)),
  'Hero eyebrow/title/description/caption must have opaque-painted AA contrast');
  writeFileSync(resolve(OUT, 'dashboard-hero-gradient-isolation-audit.json'),
    JSON.stringify({ cases: dashboardHeroPaintAudit, total: dashboardHeroPaintAudit.length,
      paintedTextPairs: dashboardHeroPaintAudit.length * 4,
      audited: 'rendered-Dashboard-hero-solid-composited-paint-hidden-decorative-gradient' }, null, 2));
  console.log('[WORKSPACE HERO GRADIENT ISOLATION] 32/32 visible hero cases; ' +
    '128/128 computed opaque-painted hero text pairs >= 4.5:1; decorative gradient hidden.');
  assert.equal(w2ThemeAudit.length, WIDTHS.length * THEMES.length * PAGES.length,
    'All six real rendered routes must audit computed w2 palette at every width/theme');
  assert.ok(w2ThemeAudit.every(item => item.compared === 12 && item.minimumContrast >= 4.5),
    'All 192 rendered route/theme cases must preserve 12 AA contrast token pairs');
  writeFileSync(resolve(OUT, 'w2-computed-theme-audit.json'),
    JSON.stringify({ cases: w2ThemeAudit, total: w2ThemeAudit.length,
      comparisons: w2ThemeAudit.length * 12, audited: 'computed-css-tokens-not-human-signoff' }, null, 2));
  console.log('[WORKSPACE W2 THEME] 192/192 actual-route computed token cases, ' +
    '2304/2304 solid semantic foreground/surface pairs >= 4.5:1, no NAS access.');
  assert.equal(paintedHeadingAudit.length, WIDTHS.length * THEMES.length * (PAGES.length - 1),
    'All five real ledger headings must have actual painted contrast evidence');
  assert.ok(paintedHeadingAudit.every(item => item.contrast >= 4.5),
    'No actual ledger heading may lose AA painted contrast');
  writeFileSync(resolve(OUT, 'painted-ledger-heading-audit.json'),
    JSON.stringify({ cases: paintedHeadingAudit, total: paintedHeadingAudit.length,
      audited: 'actual-computed-foreground-over-composited-flat-background' }, null, 2));
  console.log('[WORKSPACE PAINTED HEADING] 160/160 rendered ledger heading cases, ' +
    'computed text over verified alpha-composited opaque backgrounds >= 4.5:1.');
  assert.equal(metricHoverPaintAudit.length, WIDTHS.length * THEMES.length * 2 * 2 * 2,
    'Dashboard/Media metric label and value must pass normal and hover painted audits');
  assert.ok(metricHoverPaintAudit.every(item => item.contrast >= 4.5),
    'Every real metric ink/surface contrast must pass the same AA gate');
  writeFileSync(resolve(OUT, 'metric-hover-painted-contrast-audit.json'),
    JSON.stringify({ cases: metricHoverPaintAudit, total: metricHoverPaintAudit.length,
      audited: 'real-metric-ink-over-composited-surface-in-normal-and-hover' }, null, 2));
  console.log('[WORKSPACE METRIC HOVER] 256/256 real foreground/painted-background ' +
    'normal and hover text pairs >= 4.5:1 on Dashboard and Media.');
  assert.equal(liveMetricThemeAudit.length, WIDTHS.length * THEMES.length * 2,
    'Dashboard and Media live CSS palette inversion must cover all viewport/theme cases');
  assert.ok(liveMetricThemeAudit.every(item =>
    item.initial.tokens.effective === item.restored.tokens.effective &&
    item.initial.tokens.effective !== item.inverted.tokens.effective &&
    item.inverted.contrasts.every(role => role.contrast >= 4.5) &&
    item.restored.contrasts.every(role => role.contrast >= 4.5)),
  'No live theme inversion or restoration may lose metric contrast');
  writeFileSync(resolve(OUT, 'live-metric-theme-cascade-audit.json'),
    JSON.stringify({ cases: liveMetricThemeAudit, total: liveMetricThemeAudit.length,
      audited: 'same-document-css-theme-invalidation-not-themeprovider-user-action' }, null, 2));
  console.log('[WORKSPACE LIVE CSS THEME] 64/64 Dashboard/Media same-document ' +
    'inverse-and-restore cases, 256/256 painted metric text contrasts >= 4.5:1.');
  assert.equal(providerMetricThemeAudit.length, WIDTHS.length * THEMES.length * 2,
    'Actual Header/ThemeProvider metric flows must cover both routes, all widths and themes');
  assert.ok(providerMetricThemeAudit.every(item =>
    item.initial.tokens.effective === item.restored.tokens.effective &&
    item.initial.tokens.effective !== item.changed.tokens.effective &&
    item.changed.contrasts.every(role => role.contrast >= 4.5) &&
    item.restored.contrasts.every(role => role.contrast >= 4.5)),
  'Real user theme changes and restorations must preserve 4.5:1 painted metric contrast');
  writeFileSync(resolve(OUT, 'provider-metric-theme-user-action-audit.json'),
    JSON.stringify({ cases: providerMetricThemeAudit, total: providerMetricThemeAudit.length,
      audited: 'real-header-themeprovider-user-action-steady-state-not-transient-pixels' }, null, 2));
  console.log('[WORKSPACE REAL PROVIDER THEME] 64/64 real Header user action/restore ' +
    'sequences, 256/256 painted metric text contrasts >= 4.5:1.');
  assert.equal(providerMetricFrameAudit.length, WIDTHS.length * THEMES.length * 2,
    'Real user theme frame audit must cover both metrics routes at all width/mode cases');
  const frameCount = providerMetricFrameAudit.reduce((sum, c) =>
    sum + c.changedFrames.length + c.restoredFrames.length, 0);
  assert.equal(frameCount, WIDTHS.length * THEMES.length * 2 * 2 *
    PROVIDER_FRAME_COUNT * 2,
  'Capture 12 first painted frames x 2 theme actions x 2 metric roles in all 64 cases');
  assert.ok(providerMetricFrameAudit.every(c =>
    [...c.changedFrames, ...c.restoredFrames].every(record => record.contrast >= 4.5)),
  'Every sampled rendered frame must preserve >= 4.5:1 metric text contrast');
  writeFileSync(resolve(OUT, 'provider-metric-theme-frame-audit.json'),
    JSON.stringify({ cases: providerMetricFrameAudit, sequences: providerMetricFrameAudit.length,
      sampledContrastPairs: frameCount,
      audited: 'real-themeprovider-rAF-computed-flat-paint-not-pixel-level-video-or-human-signoff' }, null, 2));
  console.log('[WORKSPACE PROVIDER THEME FRAMES] 64/64 change/restore sequences, ' +
    frameCount + ' sampled frame/role painted contrast pairs >= 4.5:1.');
  assert.equal(normalMotionMetricFrameAudit.length,
    NORMAL_MOTION_WIDTHS.size * THEMES.length * 2,
    'Normal-motion real user metric frames must cover all modes and selected widths/routes');
  const normalMotionContrastCount = normalMotionMetricFrameAudit.reduce((sum, item) =>
    sum + item.changedFrames.length + item.restoredFrames.length, 0);
  assert.equal(normalMotionContrastCount,
    NORMAL_MOTION_WIDTHS.size * THEMES.length * 2 * 2 * PROVIDER_FRAME_COUNT * 2,
    'Normal-motion must capture 12 frames x 2 directions x 2 actual text roles');
  assert.ok(normalMotionMetricFrameAudit.every(item =>
    [...item.changedFrames, ...item.restoredFrames].every(frame => frame.contrast >= 4.5)),
  'Normal-motion theme transitions must preserve painted text contrast on every frame');
  writeFileSync(resolve(OUT, 'provider-metric-theme-normal-motion-frame-audit.json'),
    JSON.stringify({ cases: normalMotionMetricFrameAudit,
      sequences: normalMotionMetricFrameAudit.length,
      sampledContrastPairs: normalMotionContrastCount,
      motion: 'prefers-reduced-motion: no-preference',
      audited: 'real-Header-or-mobile-ThemeProvider-rAF-flat-paint-not-pixel-level-visual-signoff' }, null, 2));
  console.log('[WORKSPACE NORMAL-MOTION PROVIDER FRAMES] ' +
    normalMotionMetricFrameAudit.length + ' real Dashboard/Media user-flow sequences, ' +
    normalMotionContrastCount + ' frame/role pairs >= 4.5:1.');
  assert.equal(checkboxKeyboardAudit.length, WIDTHS.length * THEMES.length * 2,
    'Every Media and Quarantine dense viewport/theme must have computed checkbox evidence');
  writeFileSync(resolve(OUT, 'checkbox-keyboard-audit.json'),
    JSON.stringify({ cases: checkboxKeyboardAudit, total: checkboxKeyboardAudit.length }, null, 2));
  console.log('[WORKSPACE CHECKBOX] ' + checkboxKeyboardAudit.length +
    '/64 native keyboard focus cases, all computed ring contrast >= 3:1');
  console.log('[WORKSPACE CASCADE] 32/32 cases, 352 screenshots; ' +
    'real six-page empty + five-page dense CSS/status gates; synthetic GET only; no NAS access.');
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
