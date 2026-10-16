/**
 * Final acceptance: actual React app on EVERY declared route, not a component mock.
 * 8 CI jobs × 4 effective theme modes × 25 routes = 800 real Chromium visits.
 * GET APIs are 100% synthetic; any outbound or mutating request fails closed.
 * Captures screenshot, route, page heading, render/runtime errors and viewport overflow.
 * Screenshot collection is evidence to REVIEW; it does not automatically approve UI.
 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { chromium } from 'playwright';
import { visualThemes, visualViewports, visualAdminFixture, visualSafeSettingsFixture } from './visual-fixtures.mjs';
import { computedContrastRatio } from './computed-contrast.mjs';

const routes = Object.freeze([
  { path: '/login', id: 'login', public: true },
  { path: '/dashboard', id: 'dashboard' },
  { path: '/indexes', id: 'indexes' },
  { path: '/media', id: 'media' },
  { path: '/archive-recovery', id: 'archive-recovery' },
  { path: '/scans', id: 'scans' },
  { path: '/scans/1', id: 'scan-detail', template: 'scans/:id' },
  { path: '/scans/1/dedupe', id: 'scan-dedupe', template: 'scans/:id/dedupe' },
  { path: '/path-match', id: 'path-match' },
  { path: '/directory-diff', id: 'directory-diff' },
  { path: '/download-verification', id: 'download-verification' },
  { path: '/download-sources', id: 'download-sources' },
  { path: '/filename-audit', id: 'filename-audit' },
  { path: '/rename', id: 'rename' },
  { path: '/batch', id: 'batch' },
  { path: '/organizer', id: 'organizer' },
  { path: '/workflows', id: 'workflows' },
  { path: '/workflows/1', id: 'workflow-detail', template: 'workflows/:id' },
  { path: '/schedules', id: 'schedules' },
  { path: '/plans', id: 'plans' },
  { path: '/plans/1', id: 'plan-detail', template: 'plans/:id' },
  { path: '/quarantine', id: 'quarantine' },
  { path: '/tasks', id: 'tasks' },
  { path: '/audit', id: 'audit' },
  { path: '/settings', id: 'settings' },
]);

// Ensure the inventory changes when a new React route is introduced.
const router = readFileSync('src/router/index.tsx', 'utf8');
const declared = [...router.matchAll(/<Route\s+path="([^"]+)"/g)]
  .map(m => m[1].replace(/^\/+/, '')).filter(path => path !== '*' && path !== '');
const tested = routes.map(r => r.template || r.path.slice(1));
assert.equal(new Set(tested).size, tested.length, 'Duplicate visual route case');
assert.deepEqual([...tested].sort(), [...declared].sort(),
  'Visual matrix must include every router path, including dynamic details');
assert.equal(routes.length, 25);

const width = Number(process.env.NFC_VISUAL_WIDTH);
assert.ok(visualViewports.includes(width), 'Set NFC_VISUAL_WIDTH to one of the eight required widths');
const PORT = 4196;
const BASE = 'http://127.0.0.1:' + PORT;
const OUT = resolve('artifacts/full-route-visual', String(width));
mkdirSync(OUT, { recursive: true });
const server = spawn(process.execPath, [
  'node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1',
  '--port', String(PORT), '--strictPort',
], { cwd: process.cwd(), stdio: 'ignore' });

async function ready() {
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw Error('Vite preview exited before startup');
    try { if ((await fetch(BASE + '/login')).ok) return; } catch {}
    await sleep(200);
  }
  throw Error('Vite preview failed to start');
}
const TS = '2026-10-16T08:00:00Z';
const fixtureScan = {
  id: 1, name: 'Mock 完整扫描 / 图片视频资料归档', status: 'completed',
  created_at: TS, started_at: TS, finished_at: TS, root_paths: ['/mock/library'],
  mode: 'fclones', roots: ['/mock/library'], total_files: 12500,
  total_size: 8712312000, total_groups: 2, total_files_in_groups: 5,
  duplicate_group_count: 2, duplicate_files: 5,
  reclaimable_bytes: 1350000000, error: null,
};
const fixturePlan = {
  id: 1, name: 'Mock 精确去重审查计划', kind: 'dedupe', status: 'draft',
  created_at: TS, updated_at: TS, expected_changes: 2,
  expected_reclaim_bytes: 1350000000, items: [], total: 0,
  preview_digest: 'synthetic-read-only', can_execute: false,
};
const fixtureWorkflow = {
  id: 1, name: 'Mock 文件巡检工作流', description: '浏览器截图专用模拟数据',
  current_revision: 1, is_builtin: false, mode: 'file',
  created_by_user_id: 1, archived_at: null,
  definition: { schema_version: 1, mode: 'file', steps: [] },
  created_at: TS, updated_at: TS,
};
const downloadRun = {
  id: 7, work_job_id: 16, remote_root: 'PikPak/Movies', local_root: '/mock/library/movies',
  result: 'DIFFERENT', job_status: 'completed', checked: 8, total: 9,
  bytes_checked: 9443284231, error_code: null, created_at: TS, finished_at: TS,
};
const page = items => ({ items, total: items.length, page: 1, page_size: 50 });
function fixture(path) {
  if (path === '/api/auth/me') return visualAdminFixture('full-site-visual-mock');
  if (path === '/api/settings') return {
    ...visualSafeSettingsFixture(), protect_last_file: true, allowed_roots: ['/mock/library'],
    quarantine_root: '/mock/quarantine', fclones_binary: 'fclones',
    verification_hash: 'sha256',
  };
  if (path === '/api/auth/sessions') return { sessions: [] };
  if (path === '/api/data-lifecycle') return {
    audit_retention_days: 30, updated_at: TS,
  };
  if (path === '/api/audit/retention-preview') return {
    retention_days: 30, total_count: 24, keep_count: 24, delete_count: 0,
    cutoff: TS, oldest_timestamp: TS,
  };
  if (path === '/api/quarantine/retention-policy') return {
    quarantine_retention_days: 30,
  };
  if (path === '/api/settings/resource-policy') return {
    revision: 1, scan_threads: 2, hash_threads: 2,
    io_limit: 'normal', job_priority: 'normal',
    active_window_enabled: false, active_window_start: null,
    active_window_end: null, active_window_timezone: 'UTC',
    outside_window_mode: 'limited',
    effective_now: {
      profile: 'normal', effective_thread_cap: 2,
      resource_jobs_admitted: 0, resource_jobs_running: 0,
      active_window_open: true,
    },
  };
  if (path === '/api/dashboard/summary') return {
    indexed_files: 123456, indexed_folders: 5100, queued_or_running_jobs: 0,
    plan_count: 12, latest_scan_id: 1, duplicate_group_count: 2,
    latest_reclaimable_bytes: 1350000000,
  };
  if (path === '/api/media/summary') return {
    total: 3, image: 2, video: 1, healthy: 2, corrupt: 1, unknown: 0,
    verification_unverified: 1, verification_baseline: 0, verification_verified: 1,
    verification_changed: 1, verification_unknown: 0,
  };
  if (path === '/api/scans/1') return fixtureScan;
  if (path === '/api/scans/1/groups') return page([]);
  if (path === '/api/scans') return page([fixtureScan]);
  if (path === '/api/plans/1/items' || path === '/api/plans/1/operation-journal') return page([]);
  if (path === '/api/plans/legacy/summary') return {
    plan_count: 2, item_count: 8, affected_scan_count: 1,
  };
  if (path === '/api/plans/1') return fixturePlan;
  if (path === '/api/plans') return page([fixturePlan]);
  if (path === '/api/workflows/1') return fixtureWorkflow;
  if (path === '/api/workflows/1/revisions') return [];
  if (path === '/api/workflows') return [fixtureWorkflow];
  if (path === '/api/download-verifications/sources/1/browse') return {
    path: '', items: [{ name: 'PikPak', kind: 'directory', size: null }],
  };
  if (path === '/api/download-verifications/sources') return { items: [
    { id: 1, name: 'AList', provider: 'alist', base_url: 'http://alist:5244',
      username: '', has_password: false, revision: 1, active: true },
  ] };
  if (path === '/api/download-verifications/configuration') return {
    configured: false, endpoint: '', mode: 'strict', read_only: true,
  };
  if (path === '/api/download-verifications') return page([downloadRun]);
  if (path === '/api/download-verifications/7/items') return page([
    { relative_path: 'movies/Archive.Movie.2026.mkv', kind: 'file',
      status: 'HASH_MISMATCH', remote_size: 500000, local_size: 500000,
      remote_sha256: 'f'.repeat(64), local_sha256: '0'.repeat(64), reason_code: 'HASH_MISMATCH' },
    { relative_path: 'movies/Only-on-NAS.mkv', kind: 'file',
      status: 'ONLY_LOCAL', remote_size: null, local_size: 800000,
      remote_sha256: null, local_sha256: null, reason_code: 'ONLY_LOCAL' },
  ]);
  if (path === '/api/indexes') return page([
    { id: 1, root: '/mock/library', files: 12500, folders: 500,
      path_state: 'available', exists: true, can_remove: false, has_active_job: false,
      created_at: TS, last_indexed_at: TS },
  ]);
  if (path === '/api/tasks') return page([]);
  if (path === '/api/media') return page([]);
  if (path === '/api/quarantine') return page([]);
  if (path === '/api/audit') return page([]);
  if (path === '/api/filesystem/list') return {
    path: '/mock/library', parent: null, allowed_roots: ['/mock'],
    items: [{name:'Movies', path:'/mock/library/Movies', type:'directory', is_dir:true}],
    total: 1, page: 1, page_size: 50,
  };
  if (path === '/api/filesystem/favorites' || path === '/api/filesystem/recent') return page([]);
  return page([]);
}

let browser;
const report = [];
const failures = [];
try {
  await ready();
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  for (const theme of visualThemes) {
    const context = await browser.newContext({
      viewport: { width, height: 900 }, colorScheme: theme.system,
      reducedMotion: 'reduce',
    });
    const writes = [], outbound = [], pageErrors = [];
    let loginFixture = false;
    await context.addInitScript(mode => localStorage.setItem('nfc_theme_mode', mode), theme.mode);
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== BASE) {
        outbound.push(request.method() + ' ' + url.href);
        await route.abort('blockedbyclient');
      } else if (url.pathname.startsWith('/api/')) {
        if (request.method() !== 'GET') {
          writes.push(request.method() + ' ' + url.pathname);
          await route.fulfill({ status: 405, contentType: 'application/json',
            body: JSON.stringify({ error: 'READ_ONLY_VISUAL_AUDIT' }) });
        } else if (url.pathname === '/api/auth/me' && loginFixture) {
          // The login route must remain a real unauthenticated page.
          await route.fulfill({ status: 401, contentType: 'application/json',
            body: JSON.stringify({ detail: 'synthetic unauthenticated fixture' }) });
        } else {
          await route.fulfill({ status: 200, contentType: 'application/json',
            body: JSON.stringify(fixture(url.pathname)) });
        }
      } else {
        await route.continue();
      }
    });
    const tab = await context.newPage();
    tab.on('pageerror', err => pageErrors.push(err.message));
    const themeLabel = theme.mode + '-' + theme.system;
    for (const item of routes) {
      const beforeErrors = pageErrors.length;
      const problems = [];
      try {
        loginFixture = Boolean(item.public);
        await tab.goto(BASE + item.path, { waitUntil: 'domcontentloaded' });
        if (item.public) await tab.locator('#nfc-login-theme-select').waitFor();
        else await tab.locator('#main-content').waitFor();
        await tab.waitForTimeout(160);
        const audit = await tab.evaluate(() => {
          const main = document.querySelector('main') || document.querySelector('#root');
          const shell = document.querySelector('.nfc-v2-shell');
          const visible = main?.innerText?.trim() || '';
          const heading = [...document.querySelectorAll('h1,h2')].map(x =>
            x.innerText.trim()).filter(Boolean).slice(0, 4);
          const area = main?.getBoundingClientRect();
          const header = document.querySelector('.nfc-v2-header');
          const identity = header?.querySelector('.nfc-v2-breadcrumb > strong');
          const parentCrumb = header?.querySelector('.nfc-v2-breadcrumb > span');
          const commandCluster = header?.querySelector('.nfc-header-command-cluster');
          const left = header?.querySelector('.nfc-v2-header-left');
          const identityStyle = identity ? getComputedStyle(identity) : null;
          return {
            pathname: location.pathname,
            effectiveTheme: document.documentElement.dataset.theme,
            title: document.title,
            heading,
            visibleChars: visible.length,
            horizontalOverflow: document.documentElement.scrollWidth - window.innerWidth,
            mainRight: area?.right ?? null,
            hasShell: Boolean(shell),
            busy: Boolean(main?.querySelector('.nfc-session-loading')),
            mobileHeader: header && identity && commandCluster && left && parentCrumb ? {
              identityText: identity.textContent?.trim() || '',
              identityHeight: identity.getBoundingClientRect().height,
              identityLineHeight: parseFloat(identityStyle.lineHeight),
              identityWrap: identityStyle.whiteSpace,
              parentCrumbDisplay: getComputedStyle(parentCrumb).display,
              commandsLeft: commandCluster.getBoundingClientRect().left,
              commandsRight: commandCluster.getBoundingClientRect().right,
              leftRight: left.getBoundingClientRect().right,
            } : null,
          };
        });
        if (audit.pathname !== item.path) problems.push('Route redirected: ' + audit.pathname);
        if (audit.effectiveTheme !== theme.effective) problems.push('Theme mismatch');
        if (!item.public && !audit.hasShell) problems.push('Missing authenticated React shell');
        if (audit.visibleChars < 25) problems.push('Empty/near-empty rendered page');
        if (audit.busy) problems.push('Still showing session loading');
        if (audit.horizontalOverflow > 3) problems.push(
          'Document horizontal overflow: ' + audit.horizontalOverflow + 'px');
        if (width <= 768 && !item.public) {
          const h = audit.mobileHeader;
          if (!h) problems.push('Mobile page header controls are missing');
          else {
            if (!h.identityText) problems.push('Mobile page identity is empty');
            if (h.identityWrap !== 'nowrap' ||
                h.identityHeight > h.identityLineHeight + 2) problems.push(
              'Narrow-header breadcrumb wraps onto two lines: ' + h.identityText);
            if (h.parentCrumbDisplay !== 'none') problems.push(
              'Redundant mobile parent breadcrumb consumes horizontal space');
            if (h.leftRight > h.commandsLeft + 2) problems.push(
              'Mobile page identity overlaps header status controls');
            if (h.commandsRight > width + 2) problems.push(
              'Mobile header actions exceed viewport width');
          }
        }
        if (item.id === 'dashboard') {
          // Actual 768/1024 Chromium PNGs show a huge blank heading-to-action gap.
          // Inspect resolved layout after all CSS layers, not source token text.
          const geom = await tab.evaluate(() => {
            const hero = document.querySelector('.nfc-v2-dashboard-hero');
            const copy = hero?.querySelector('.nfc-page-header-copy');
            const actions = hero?.querySelector('.nfc-page-actions');
            const metrics = document.querySelector('.nfc-v2-dashboard-metrics');
            if (!hero || !copy || !actions || !metrics) return null;
            const h = hero.getBoundingClientRect();
            const c = copy.getBoundingClientRect();
            const a = actions.getBoundingClientRect();
            const m = metrics.getBoundingClientRect();
            const style = getComputedStyle(copy);
            return {
              heroHeight: Number(h.height.toFixed(1)),
              copyFlexBasis: style.flexBasis,
              copyFlexGrow: style.flexGrow,
              copyHeight: Number(c.height.toFixed(1)),
              actionGap: Number((a.top - c.bottom).toFixed(1)),
              metricGap: Number((m.top - h.bottom).toFixed(1)),
              actionVisible: a.width > 30 && a.height > 25,
            };
          });
          audit.dashboardGeometry = geom;
          if (!geom) problems.push('Dashboard title/action/metric geometry is missing');
          else if (width >= 768 && width <= 1024) {
            if (geom.copyFlexBasis !== 'auto' || geom.copyFlexGrow !== '0')
              problems.push('Dashboard tablet flex-basis is not content-sized: ' +
                geom.copyFlexBasis + ' grow=' + geom.copyFlexGrow);
            if (geom.heroHeight > 300 || geom.actionGap > 96 || geom.actionGap < -2)
              problems.push('Dashboard tablet hero has excessive vertical gap: ' +
                JSON.stringify(geom));
            if (!geom.actionVisible || geom.metricGap < -2 || geom.metricGap > 90)
              problems.push('Dashboard tablet refresh/metrics are mispositioned: ' +
                JSON.stringify(geom));
          }
        }
        if (item.id === 'dashboard' && width === 768) {
          // Screenshot-grounded intrinsic table geometry: contain horizontal
          // overflow and reject the former one-glyph-per-line scan filename.
          const scans = await tab.evaluate(() => {
            const scroll = document.querySelector('.nfc-v2-recent-scans-scroll');
            const table = scroll?.querySelector('.nfc-v2-recent-scans-table');
            const name = table?.querySelector('tbody tr:first-child td:first-child .nfc-v2-row-link');
            if (!scroll || !table || !name) return null;
            const rect = name.getBoundingClientRect();
            return {
              accessibleName: scroll.getAttribute('aria-label') ?? '',
              tabIndex: scroll.tabIndex,
              scrollClient: scroll.clientWidth,
              scrollContent: scroll.scrollWidth,
              scrollOverflow: getComputedStyle(scroll).overflowX,
              tableWidth: Math.round(table.getBoundingClientRect().width),
              filenameWidth: Math.round(rect.width),
              filenameHeight: Math.round(rect.height),
              filenameText: name.textContent?.trim() ?? '',
              rightEdge: Math.round(scroll.getBoundingClientRect().right),
            };
          });
          audit.recentScansGeometry = scans;
          if (!scans) problems.push('Tablet Dashboard recent scans table/name missing');
          else {
            if (scans.tabIndex !== 0 || !scans.accessibleName.includes('最近扫描'))
              problems.push('Scrollable recent scans region is not keyboard-accessible');
            if (scans.scrollOverflow !== 'auto' ||
                scans.scrollContent < scans.scrollClient + 120 ||
                scans.tableWidth < 840 || scans.rightEdge > width + 2)
              problems.push('Tablet recent scans must scroll inside panel: ' +
                JSON.stringify(scans));
            if (scans.filenameWidth < 145 || scans.filenameHeight > 72 ||
                !scans.filenameText.includes('Mock'))
              problems.push('Tablet recent scans filename is squeezed or missing: ' +
                JSON.stringify(scans));
          }
        }
        if (item.id === 'download-verification') {
          const form = await tab.evaluate(() => {
            const field = document.querySelector('.nfc-download-verify-field');
            const name = field?.querySelector('label');
            const input = field?.querySelector('input');
            const scroller = document.querySelector('.nfc-download-verify-table-scroll');
            return {
              hasAccessibleField: Boolean(field && name && input),
              labelBottom: name?.getBoundingClientRect().bottom ?? 0,
              inputTop: input?.getBoundingClientRect().top ?? 0,
              scrollerClient: scroller?.clientWidth ?? 0,
              scrollerContent: scroller?.scrollWidth ?? 0,
              scrollerOverflow: scroller ? getComputedStyle(scroller).overflowX : '',
            };
          });
          if (!form.hasAccessibleField) problems.push('Download verification remote folder field is missing');
          if (form.inputTop < form.labelBottom + 4) problems.push(
            'Download verification form field overlaps label');
          if (form.scrollerContent <= form.scrollerClient && width <= 430) problems.push(
            'Mobile six-column history should scroll within its panel');
          if (form.scrollerOverflow !== 'auto') problems.push(
            'Download verification table lost local horizontal scrollbar');
        }
        if (pageErrors.length > beforeErrors) problems.push(
          'Uncaught React errors: ' + pageErrors.slice(beforeErrors).join('; '));
        const name = item.id + '-' + themeLabel + '-' + width;
        await tab.screenshot({
          path: resolve(OUT, name + '.png'),
          fullPage: (width === 390 || width === 1440) && theme.mode === 'light',
          animations: 'disabled',
        });
        // Real keyboard bypass regression: the first Tab on every authenticated
        // page must expose a legible skip link; Enter moves focus to the real
        // main landmark. Keep this AFTER baseline screenshots, not in their pixels.
        if (!item.public) {
          await tab.keyboard.press('Tab');
          const focusAudit = await tab.evaluate(() => {
            const skip = document.querySelector('.nfc-v2-skip-link');
            const navToggle = document.querySelector('.nfc-header-nav-toggle');
            const style = skip ? getComputedStyle(skip) : null;
            const rect = skip?.getBoundingClientRect();
            const navMotion = navToggle ? getComputedStyle(navToggle) : null;
            return {
              firstTabOnSkip: Boolean(skip && document.activeElement === skip),
              skipText: skip?.textContent?.trim() ?? '',
              skipHref: skip?.getAttribute('href') ?? '',
              skipVisible: Boolean(rect && rect.top >= -1 && rect.left >= -1 &&
                rect.right <= innerWidth + 1 && rect.bottom <= innerHeight + 1 &&
                rect.width >= 80 && rect.height >= 44),
              focusOutline: Boolean(style && style.outlineStyle !== 'none' &&
                parseFloat(style.outlineWidth) >= 2),
              focusColor: style?.color ?? '',
              focusBackground: style?.backgroundColor ?? '',
              focusOutlineColor: style?.outlineColor ?? '',
              skipTransitionSeconds: style?.transitionDuration ?? '',
              skipAnimationSeconds: style?.animationDuration ?? '',
              reducedMotion: matchMedia('(prefers-reduced-motion: reduce)').matches,
              navTransitionSeconds: navMotion?.transitionDuration ?? '',
              navAnimationSeconds: navMotion?.animationDuration ?? '',
            };
          });
          if (!focusAudit.firstTabOnSkip || focusAudit.skipText !== '跳转到主要内容' ||
              focusAudit.skipHref !== '#main-content') problems.push(
            'First Tab must focus an accessible skip-to-main link');
          if (!focusAudit.skipVisible || !focusAudit.focusOutline) problems.push(
            'Keyboard skip link is clipped, hidden or has no visible focus outline');
          // Check focused computed colors after ALL CSS layers, not token strings.
          // WCAG AA: >=4.5:1 text and >=3:1 non-text focus indication.
          const focusTextContrast = computedContrastRatio(
            focusAudit.focusColor, focusAudit.focusBackground);
          const focusOutlineContrast = computedContrastRatio(
            focusAudit.focusOutlineColor, focusAudit.focusBackground);
          audit.skipFocusContrast = {
            text: Number(focusTextContrast.toFixed(2)),
            outline: Number(focusOutlineContrast.toFixed(2)),
          };
          if (focusTextContrast < 4.5) problems.push(
            'Skip link computed text contrast below 4.5:1: ' + focusTextContrast.toFixed(2));
          if (focusOutlineContrast < 3) problems.push(
            'Skip link computed focus indicator contrast below 3:1: ' + focusOutlineContrast.toFixed(2));
          if (!focusAudit.reducedMotion ||
              [focusAudit.navTransitionSeconds, focusAudit.navAnimationSeconds,
                focusAudit.skipTransitionSeconds, focusAudit.skipAnimationSeconds]
                .flatMap(value => value.split(','))
                .some(value => {
                  const number = parseFloat(value);
                  return !Number.isFinite(number) || (value.trim().endsWith('ms') ?
                    number / 1000 : number) > 0.001;
                })) problems.push('Reduced motion is not enforced on primary navigation');
          await tab.keyboard.press('Enter');
          const skipped = await tab.evaluate(() => ({
            mainFocused: document.activeElement?.id === 'main-content',
            locationHash: location.hash,
            mainTabIndex: document.querySelector('#main-content')?.tabIndex,
          }));
          if (!skipped.mainFocused || skipped.locationHash !== '#main-content' ||
              skipped.mainTabIndex !== -1) problems.push(
            'Skip-to-main activation did not move keyboard focus to main landmark');
        }
        if (item.id === 'dashboard' && width === 768) {
          // AFTER the normal screenshot and skip-link focus checks.
          const scroll = tab.locator('.nfc-v2-recent-scans-scroll');
          await scroll.focus();
          // Programmatic .focus() alone does not guarantee :focus-visible.
          // Walk the real Tab sequence into the first row and Shift+Tab
          // back to the scroll region before checking keyboard focus chrome.
          await tab.keyboard.press('Tab');
          await tab.keyboard.press('Shift+Tab');
          const focus = await scroll.evaluate(element => {
            const style = getComputedStyle(element);
            return {
              isFocused: document.activeElement === element,
              focusVisible: element.matches(':focus-visible'),
              outline: style.outlineStyle,
              outlineWidth: parseFloat(style.outlineWidth),
              outlineColor: style.outlineColor,
              transitionDuration: style.transitionDuration,
              computedAccent: style.getPropertyValue('--v2-indigo').trim(),
            };
          });
          audit.recentScansFocus = focus;
          if (!focus.isFocused || !focus.focusVisible ||
              focus.outline === 'none' || focus.outlineWidth < 2)
            problems.push('Tablet recent scans keyboard focus indicator is missing: ' +
              JSON.stringify(focus));
          await tab.keyboard.press('ArrowRight');
          await tab.waitForTimeout(120);
          const scrollLeft = await scroll.evaluate(element => element.scrollLeft);
          audit.recentScansKeyboardScrollLeft = Number(scrollLeft.toFixed(1));
          if (scrollLeft < 3)
            problems.push('Tablet recent scans do not respond to keyboard ArrowRight');
        }
        if (item.id === 'download-verification') {
          // Exercise the real Radix remote chooser against strictly read-only AList fixtures.
          const pickerAction = tab.getByRole('button', { name: '选择目录' }).first();
          await pickerAction.click();
          const remotePicker = tab.getByRole('dialog', { name: '选择来源目录' });
          await remotePicker.waitFor();
          await remotePicker.getByRole('button', { name: /PikPak/ }).waitFor();
          await tab.screenshot({ path: resolve(OUT, name + '-remote-picker.png'), animations: 'disabled' });
          await remotePicker.getByRole('button', { name: '选择此目录' }).click();
          await remotePicker.waitFor({ state: 'hidden' });
          // Capture the interactive detailed evidence table, not only the landing state.
          const action = tab.getByRole('button', { name: '查看条目' }).first();
          await action.click();
          await tab.getByRole('table', { name: '校验明细' }).waitFor();
          await tab.screenshot({
            path: resolve(OUT, name + '-selected-detail.png'),
            fullPage: width === 390 && theme.mode === 'light',
            animations: 'disabled',
          });
          if (pageErrors.length > beforeErrors) problems.push(
            'Uncaught detail-panel React errors: ' + pageErrors.slice(beforeErrors).join('; '));
        }
        if (item.id === 'download-sources') {
          // Source editor is a separate route; no POST requests are issued by this fixture.
          await tab.getByRole('button', { name: '新增来源' }).click();
          await tab.getByRole('textbox', { name: '来源名称' }).waitFor();
          await tab.screenshot({ path: resolve(OUT, name + '-source-editor.png'), animations: 'disabled' });
          await tab.getByRole('button', { name: '取消' }).click();
        }
        report.push({ route: item.path, width, theme: themeLabel, ...audit, problems });
        if (problems.length) failures.push({ route: item.path, theme: themeLabel, problems });
      } catch (err) {
        const message = String(err?.message || err);
        failures.push({ route: item.path, theme: themeLabel, problems: [message] });
        report.push({ route: item.path, width, theme: themeLabel, problems: [message] });
        await tab.screenshot({
          path: resolve(OUT, item.id + '-' + themeLabel + '-' + width + '-failed.png'),
          animations: 'disabled',
        }).catch(() => {});
      }
    }
    if (writes.length) failures.push({ theme: themeLabel, problems: ['Mutating API: ' + writes.join(', ')] });
    if (outbound.length) failures.push({ theme: themeLabel, problems: ['External requests: ' + outbound.join(', ')] });
    await context.close();
  }
  writeFileSync(resolve(OUT, 'manifest.json'),
    JSON.stringify({ width, routes: routes.length, themes: visualThemes.length,
      captured: report.length, failures, report }, null, 2));
  console.log('[FULL ROUTE AUDIT] width=' + width + ', routes=' + routes.length +
    ', themes=' + visualThemes.length + ', captures=' + report.length +
    ', failures=' + failures.length + '; screenshot manifest saved.');
  assert.deepEqual(failures, [], 'All-route mock visual audit detected failures; see manifest.json');
  assert.equal(report.length, routes.length * visualThemes.length);
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
