import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mkdtempSync, mkdirSync, rmSync, readFileSync, writeFileSync, unlinkSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { visualViewports, visualThemes } from './visual-fixtures.mjs';
import { requiresFullPageReview, requiresWorkspaceScrollReview } from './visual-screenshot-policy.mjs';
import { buildReviewPack } from './build-visual-review-pack.mjs';

const SHA = '7b561c89988f5298f08d7894b1b4642020cd7db3';
const cases = [...readFileSync('scripts/browser-full-route-visual.mjs', 'utf8')
  .matchAll(/\{ path: '([^']+)', id: '([^']+)'/g)]
  .map(([, route, id]) => ({ route, id }));
const themes = visualThemes.map(x => x.mode + '-' + x.system);
// Valid, tiny one-pixel PNG. The source runner saves its actual Chromium frames.
const png = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/qv8AAAAASUVORK5CYII=',
  'base64');

function fixture() {
  const dir = mkdtempSync(join(tmpdir(), 'nfc-visual-review-'));
  const input = join(dir, 'screenshots');
  const output = join(dir, 'review');
  for (const width of visualViewports) {
    const place = join(input, String(width));
    mkdirSync(place, { recursive: true });
    const report = [];
    for (const theme of themes) for (const item of cases) {
      const nested = requiresWorkspaceScrollReview(width, item.route);
      const scrolled = nested && item.route === '/settings';
      report.push({ route: item.route, width, theme,
        screenshotFullPage: requiresFullPageReview(width),
        ...(item.route === '/download-sources' && {
          sourceEditorScreenshotPixels: {
            width, height: width === 390 ? 1480 : 900,
            documentHeight: width === 390 ? 1480 : 900,
            fullPage: requiresFullPageReview(width),
          },
        }),
        ...(item.route === '/download-verification' && {
          detailScreenshotPixels: {
            width, height: width === 390 ? 1999 : 900,
            documentHeight: width === 390 ? 1999 : 900,
            fullPage: requiresFullPageReview(width),
          },
        }),
        ...(nested && { workspaceScroll: {
          overflowY: 'auto', maxScroll: scrolled ? 1800 : 0,
          scrollable: scrolled, bottomReached: true,
          visibleHeight: 700, captured: scrolled,
        } }),
        problems: [] });
      writeFileSync(join(place, item.id + '-' + theme + '-' + width + '.png'), png);
      if (scrolled) writeFileSync(
        join(place, item.id + '-' + theme + '-' + width + '-workspace-bottom.png'), png);
      const addExtra = filename =>
        writeFileSync(join(place, filename + '.png'), png);
      if (item.route === '/download-verification') {
        addExtra(item.id + '-' + theme + '-' + width + '-remote-picker');
        addExtra(item.id + '-' + theme + '-' + width + '-selected-detail');
      } else if (item.route === '/download-sources') {
        addExtra(item.id + '-' + theme + '-' + width + '-source-editor');
      } else if (item.route === '/schedules') {
        addExtra('scheduler-list-503-' + theme + '-' + width);
        if ([390, 1440].includes(width))
          addExtra('scheduler-list-503-keyboard-' + theme + '-' + width);
      }
    }
    writeFileSync(join(place, 'manifest.json'), JSON.stringify({
      width, routes: cases.length, themes: themes.length,
      captured: report.length, failures: [], report,
    }));
  }
  return { dir, input, output };
}

test('produces exactly 800 separately unapproved human decisions and an offline gallery', () => {
  const f = fixture();
  try {
    assert.equal(buildReviewPack(f.input, f.output, SHA), 800);
    const csv = readFileSync(join(f.output, 'review-worklist.csv'), 'utf8');
    assert.equal(csv.trimEnd().split('\n').length, 801);
    assert.equal((csv.match(/"UNREVIEWED"/g) || []).length, 800);
    const page = readFileSync(join(f.output, 'index.html'), 'utf8');
    assert.ok(page.includes(SHA));
    assert.ok(page.includes('manualReviewComplete: false'));
    assert.ok(page.includes('人工通过'));
    assert.ok(page.includes('补充证据：桌面主工作区已独立滚动到底部'));
    assert.ok(page.includes('settings-light-dark-1440-workspace-bottom.png'));
    assert.ok(page.includes('"workspaceBottom":""'));
    assert.ok(page.includes('交互态补充证据：'));
    assert.ok(page.includes('download-verification-system-dark-390-selected-detail.png'));
    assert.ok(page.includes('scheduler-list-503-keyboard-dark-light-1440.png'));

    assert.ok(page.includes('浏览器全页截图（仅文档滚动；内部滚动区仍需另查）'));
    assert.ok(page.includes('视口首屏截图（长页及内部滚动区仍需补充审查）'));
    assert.ok(page.includes('"capture":"FULL_PAGE"'));
    assert.ok(page.includes('"capture":"VIEWPORT"'));
    assert.equal(csv.trimEnd().split('\n').filter(x => x.includes('"FULL_PAGE"')).length, 200);
    assert.equal(csv.trimEnd().split('\n').filter(x => x.includes('"VIEWPORT"')).length, 600);
    assert.ok(page.includes('../screenshots/360/login-light-dark-360.png'));
    assert.ok(page.includes('../screenshots/1920/settings-system-dark-1920.png'));
    assert.ok(!page.includes('__REVIEW_DATA__'));
    const evidence = JSON.parse(readFileSync(join(f.output, 'evidence.json'), 'utf8'));
    assert.equal(evidence.desktopWorkspaceWidth, 1440);
    assert.equal(evidence.desktopWorkspaceBottomCases, 4);
    assert.equal(evidence.interactionScreenshots, 136);
    assert.equal(csv.trimEnd().split('\n').filter(x =>
      x.includes('"2","FULL_PAGE"')).length >= 1, true);
    assert.equal(csv.trimEnd().split('\n').filter(x =>
      x.includes('workspace-bottom.png')).length, 4);
    assert.deepEqual([evidence.fullPageWidths, evidence.fullPageCases, evidence.viewportCases],
      [[390, 1440], 200, 600]);
    assert.deepEqual([evidence.sourceHeadSha, evidence.automatedCases,
      evidence.manualApproved, evidence.manualReviewComplete], [SHA, 800, 0, false]);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test('fails closed for an omitted screenshot, duplicate case or fake browser success', () => {
  const f = fixture();
  try {
    unlinkSync(join(f.input, '390', 'tasks-light-dark-390.png'));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA), /Missing or empty screenshot/);
    writeFileSync(join(f.input, '390', 'tasks-light-dark-390.png'), png);
    const file = join(f.input, '390', 'manifest.json');
    const manifest = JSON.parse(readFileSync(file, 'utf8'));
    manifest.report[1] = manifest.report[0];
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA), /Duplicate screenshot case/);
    manifest.report[1] = { route: cases[1].route, width: 390,
      theme: themes[0], problems: ['horizontal overflow'] };
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA), /Browser failure/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test('rejects missing/wrong provenance SHA and incomplete width coverage', () => {
  const f = fixture();
  try {
    assert.throws(() => buildReviewPack(f.input, f.output, ''), /exact GitHub artifact HEAD SHA/);
    assert.throws(() => buildReviewPack(f.input, f.output, 'deadbeef'), /exact GitHub artifact HEAD SHA/);
    rmSync(join(f.input, '1920'), { recursive: true, force: true });
    assert.throws(() => buildReviewPack(f.input, f.output, SHA), /Missing extracted CI manifest/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test('rejects a missing or theme-specific full-page screenshot contract in any manifest', () => {
  const f = fixture();
  try {
    const file = join(f.input, '390', 'manifest.json');
    const manifest = JSON.parse(readFileSync(file, 'utf8'));
    const dark = manifest.report.find(x => x.theme === 'dark-light');
    dark.screenshotFullPage = false;
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Missing or wrong theme-independent screenshot depth/);
    dark.screenshotFullPage = true;
    delete manifest.report[1].screenshotFullPage;
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Missing or wrong theme-independent screenshot depth/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test('fails closed on missing, forged or unstated desktop workspace-bottom evidence', () => {
  const f = fixture();
  try {
    const image = join(f.input, '1440', 'settings-dark-light-1440-workspace-bottom.png');
    unlinkSync(image);
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Missing desktop scroll-bottom PNG/);
    writeFileSync(image, png);
    const file = join(f.input, '1440', 'manifest.json');
    const manifest = JSON.parse(readFileSync(file, 'utf8'));
    const settings = manifest.report.find(x =>
      x.route === '/settings' && x.theme === 'dark-light');
    settings.workspaceScroll.captured = false;
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Missing desktop scroll-bottom screenshot/);
    settings.workspaceScroll.captured = true;
    delete settings.workspaceScroll;
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Missing desktop inner scroll provenance/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test('rejects missing supplemental interaction screenshots and mode-dependent full-page metadata', () => {
  const f = fixture();
  try {
    const missing = join(f.input, '390',
      'download-verification-system-dark-390-selected-detail.png');
    unlinkSync(missing);
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Missing interaction screenshot/);
    writeFileSync(missing, png);
    const file = join(f.input, '390', 'manifest.json');
    const manifest = JSON.parse(readFileSync(file, 'utf8'));
    const row = manifest.report.find(x =>
      x.route === '/download-verification' && x.theme === 'system-dark');
    row.detailScreenshotPixels.fullPage = false;
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Download selected-detail theme\/full-page evidence missing/);
    row.detailScreenshotPixels.fullPage = true;
    row.detailScreenshotPixels.height = 900;
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Download selected-detail theme\/full-page evidence missing/);
    delete row.detailScreenshotPixels;
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Download selected-detail theme\/full-page evidence missing/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});

test('rejects source editor cropped mobile form, wrong theme depth and missing metrics', () => {
  const f = fixture();
  try {
    const file = join(f.input, '390', 'manifest.json');
    const manifest = JSON.parse(readFileSync(file, 'utf8'));
    const row = manifest.report.find(x =>
      x.route === '/download-sources' && x.theme === 'system-dark');
    row.sourceEditorScreenshotPixels.height = 900;
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Source editor complete mobile screenshot missing/);
    row.sourceEditorScreenshotPixels.height = 1480;
    row.sourceEditorScreenshotPixels.fullPage = false;
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Source editor complete mobile screenshot missing/);
    row.sourceEditorScreenshotPixels.fullPage = true;
    delete row.sourceEditorScreenshotPixels;
    writeFileSync(file, JSON.stringify(manifest));
    assert.throws(() => buildReviewPack(f.input, f.output, SHA),
      /Source editor complete mobile screenshot missing/);
  } finally { rmSync(f.dir, { recursive: true, force: true }); }
});
