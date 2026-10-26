import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mkdtempSync, mkdirSync, rmSync, readFileSync, writeFileSync, unlinkSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { visualViewports, visualThemes } from './visual-fixtures.mjs';
import { requiresFullPageReview } from './visual-screenshot-policy.mjs';
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
      report.push({ route: item.route, width, theme,
        screenshotFullPage: requiresFullPageReview(width), problems: [] });
      writeFileSync(join(place, item.id + '-' + theme + '-' + width + '.png'), png);
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
