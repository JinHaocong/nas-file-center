/**
 * Assemble the 8 separately uploaded, exact-HEAD visual CI artifacts into an
 * OFFLINE human-review worklist. This tool cannot approve any screenshot.
 *
 * Usage (from frontend/):
 * node scripts/build-visual-review-pack.mjs artifacts/full-route-visual \
 *   artifacts/visual-review-pack <40-character artifact HEAD SHA>
 *
 * Extract each width's full-route-visual-<width>-<sha>.zip at
 * artifacts/full-route-visual/<width>/ before invoking.
 */
import assert from 'node:assert/strict';
import {
  existsSync, mkdirSync, readFileSync, statSync, writeFileSync,
} from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { visualViewports, visualThemes } from './visual-fixtures.mjs';
import { requiresFullPageReview, FULL_PAGE_REVIEW_WIDTHS,
  requiresWorkspaceScrollReview, WORKSPACE_SCROLL_REVIEW_WIDTH,
  requiresExpandedInteractionFullPageReview } from './visual-screenshot-policy.mjs';

const ROOT = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(ROOT, 'browser-full-route-visual.mjs'), 'utf8');
const cases = [...source.matchAll(/\{ path: '([^']+)', id: '([^']+)'/g)]
  .map(([, path, id]) => ({ path, id }));
assert.equal(cases.length, 25, 'Route audit inventory is not 25; inspect before building review pack');
assert.equal(new Set(cases.map(x => x.path)).size, cases.length);
assert.equal(new Set(cases.map(x => x.id)).size, cases.length);
const WIDTHS = [...visualViewports];
const THEMES = visualThemes.map(x => x.mode + '-' + x.system);
assert.equal(WIDTHS.length * THEMES.length * cases.length, 800);

export function buildReviewPack(rootDir, destination, expectedHeadSha) {
  assert.match(expectedHeadSha || '', /^[a-f0-9]{40}$/, 'Supply the exact GitHub artifact HEAD SHA');
  const input = resolve(rootDir);
  const output = resolve(destination);
  assert.notEqual(input, output, 'Output must not overwrite the input screenshots');
  const rows = [];
  for (const width of WIDTHS) {
    const directory = join(input, String(width));
    const manifestPath = join(directory, 'manifest.json');
    assert.ok(existsSync(manifestPath), 'Missing extracted CI manifest: ' + manifestPath);
    const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
    assert.equal(manifest.width, width, 'Wrong width manifest: ' + width);
    assert.equal(manifest.routes, cases.length);
    assert.equal(manifest.themes, THEMES.length);
    assert.equal(manifest.captured, cases.length * THEMES.length);
    assert.deepEqual(manifest.failures, [], 'CI manifest reported failures at width ' + width);
    assert.ok(Array.isArray(manifest.report));
    assert.equal(manifest.report.length, cases.length * THEMES.length);
    const indexed = new Map();
    for (const result of manifest.report) {
      assert.equal(result.width, width);
      assert.ok(cases.some(item => item.path === result.route), 'Unknown route: ' + result.route);
      assert.ok(THEMES.includes(result.theme), 'Unknown theme: ' + result.theme);
      assert.deepEqual(result.problems, [], 'Browser failure for ' + result.route);
      assert.equal(result.screenshotFullPage, requiresFullPageReview(width),
        'Missing or wrong theme-independent screenshot depth for ' + [width, result.route, result.theme].join(' '));
      if (requiresWorkspaceScrollReview(width, result.route)) {
        const scroll = result.workspaceScroll;
        assert.ok(scroll && Number.isFinite(scroll.maxScroll) && scroll.maxScroll >= 0 &&
          scroll.visibleHeight >= 100 && scroll.bottomReached === true,
        'Missing desktop inner scroll provenance: ' + [width, result.route, result.theme].join(' '));
        const expected = scroll.maxScroll > 48 &&
          ['auto', 'scroll'].includes(scroll.overflowY);
        assert.equal(scroll.scrollable, expected,
          'Wrong desktop inner scroll eligibility: ' + result.route);
        assert.equal(scroll.captured, expected,
          'Missing desktop scroll-bottom screenshot: ' + [width, result.route, result.theme].join(' '));
        if (result.route === '/settings') assert.ok(scroll.scrollable && scroll.maxScroll >= 100,
          'Settings desktop workspace lower content is not covered');
      }
      if (result.route === '/download-verification') {
        const pixels = result.detailScreenshotPixels;
        const expectedFullPage = requiresExpandedInteractionFullPageReview(width);
        assert.ok(pixels && pixels.fullPage === expectedFullPage &&
          pixels.width === width && Number.isFinite(pixels.documentHeight) &&
          pixels.documentHeight >= 900 &&
          (expectedFullPage
            ? pixels.height >= pixels.documentHeight - 2
            : pixels.height === 900) &&
          (width > 430 || pixels.documentHeight > 900),
          'Download selected-detail theme/full-page evidence missing: ' +
            [width, result.theme].join(' '));
      }
      if (result.route === '/download-sources') {
        const pixels = result.sourceEditorScreenshotPixels;
        const fullPage = requiresExpandedInteractionFullPageReview(width);
        assert.ok(pixels && pixels.width === width && pixels.fullPage === fullPage &&
          Number.isFinite(pixels.documentHeight) && pixels.documentHeight >= 900 &&
          (fullPage
            ? pixels.height >= pixels.documentHeight - 2
            : pixels.height === 900) &&
          (width > 430 || pixels.documentHeight > 900),
          'Source editor complete mobile screenshot missing: ' +
            [width, result.theme].join(' '));
      }
      const key = result.route + '|' + result.theme;
      assert.ok(!indexed.has(key), 'Duplicate screenshot case: ' + key);
      indexed.set(key, result);
    }
    for (const route of cases) for (const theme of THEMES) {
      assert.ok(indexed.has(route.path + '|' + theme),
        'Missing width/theme/route: ' + [width, theme, route.path].join(' '));
      const file = route.id + '-' + theme + '-' + width + '.png';
      const image = join(directory, file);
      assert.ok(existsSync(image) && statSync(image).isFile() && statSync(image).size > 8,
        'Missing or empty screenshot: ' + image);
      const imageHref = relative(output, image).split(sep).join('/');
      const manifestRow = indexed.get(route.path + '|' + theme);
      let workspaceBottom = '';
      if (requiresWorkspaceScrollReview(width, route.path) &&
          manifestRow.workspaceScroll.scrollable) {
        const bottom = join(directory, route.id + '-' + theme + '-' + width +
          '-workspace-bottom.png');
        assert.ok(existsSync(bottom) && statSync(bottom).isFile() && statSync(bottom).size > 8,
          'Missing desktop scroll-bottom PNG: ' + bottom);
        workspaceBottom = relative(output, bottom).split(sep).join('/');
      }
      // Additional real interaction states were previously present in ZIP
      // files but not surfaced in the human gallery. Require exact-HEAD
      // evidence of their existence and attach it to the SAME route decision.
      const supplements = [];
      const add = (name, label) => {
        const extra = join(directory, name + '.png');
        assert.ok(existsSync(extra) && statSync(extra).isFile() &&
          statSync(extra).size > 8, 'Missing interaction screenshot: ' + extra);
        supplements.push({
          label, image: relative(output, extra).split(sep).join('/'),
        });
      };
      if (route.id === 'download-verification') {
        add(route.id + '-' + theme + '-' + width + '-remote-picker', '来源目录选择弹窗');
        add(route.id + '-' + theme + '-' + width + '-selected-detail', '校验明细展开态');
      } else if (route.id === 'download-sources') {
        add(route.id + '-' + theme + '-' + width + '-source-editor', '新增来源编辑弹窗');
      } else if (route.id === 'schedules') {
        add('scheduler-list-503-' + theme + '-' + width, '调度列表 503 错误态');
        if ([390, 1440].includes(width))
          add('scheduler-list-503-keyboard-' + theme + '-' + width,
            '调度列表重试按钮键盘聚焦');
      }
      rows.push({ route: route.path, width, theme, image: imageHref,
        workspaceBottom, supplements,
        capture: requiresFullPageReview(width) ? 'FULL_PAGE' : 'VIEWPORT',
        status: 'UNREVIEWED', notes: '' });
    }
  }
  assert.equal(rows.length, 800);
  mkdirSync(output, { recursive: true });
  const csvValue = x => '"' + String(x).replaceAll('"', '""') + '"';
  const csv = [
    'route,width,theme,image,workspace_bottom_image,interaction_count,capture,manual_status,notes',
    ...rows.map(r => [r.route, r.width, r.theme, r.image, r.workspaceBottom,
      r.supplements.length, r.capture, r.status, r.notes]
      .map(csvValue).join(',')),
  ].join('\n') + '\n';
  writeFileSync(join(output, 'review-worklist.csv'), csv);
  const template = readFileSync(join(ROOT, 'visual-review-template.html'), 'utf8');
  const json = JSON.stringify({ sourceHeadSha: expectedHeadSha, rows })
    .replaceAll('<', '\\u003c');
  assert.ok(template.includes('__REVIEW_DATA__'));
  writeFileSync(join(output, 'index.html'),
    template.replace('__REVIEW_DATA__', json));
  writeFileSync(join(output, 'evidence.json'), JSON.stringify({
    sourceHeadSha: expectedHeadSha, source: '8 separate GitHub UI Validation artifacts',
    automatedCases: rows.length, widths: WIDTHS, themes: THEMES,
    desktopWorkspaceWidth: WORKSPACE_SCROLL_REVIEW_WIDTH,
    desktopWorkspaceBottomCases: rows.filter(row => Boolean(row.workspaceBottom)).length,
    interactionScreenshots: rows.reduce((total, row) => total + row.supplements.length, 0),
    fullPageWidths: FULL_PAGE_REVIEW_WIDTHS,
    fullPageCases: rows.filter(row => row.capture === 'FULL_PAGE').length,
    viewportCases: rows.filter(row => row.capture === 'VIEWPORT').length,
    manualApproved: 0, manualReviewComplete: false,
    warning: 'Artifact names/HEAD must be verified against GitHub by the operator. Automated browser success does not constitute human review or NAS acceptance.',
  }, null, 2) + '\n');
  return rows.length;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const count = buildReviewPack(
      process.argv[2] || 'artifacts/full-route-visual',
      process.argv[3] || 'artifacts/visual-review-pack', process.argv[4]);
    console.log('Generated ' + count + ' UNREVIEWED human visual cases. Zero approved.');
  } catch (err) {
    console.error(err);
    process.exitCode = 1;
  }
}
