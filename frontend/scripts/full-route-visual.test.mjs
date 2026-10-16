/** Protect all-route visual coverage without importing (and starting) Playwright. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { visualViewports, visualThemes } from './visual-fixtures.mjs';

const browser = readFileSync('scripts/browser-full-route-visual.mjs', 'utf8');
const routes = readFileSync('src/router/index.tsx', 'utf8');
const workflow = readFileSync('../.github/workflows/ui-v044-validation.yml', 'utf8');

test('all declared React routes, including every parameterized detail page, have a named visual case', () => {
  const declared = [...routes.matchAll(/<Route\s+path="([^"]+)"/g)]
    .map(x => x[1].replace(/^\/+/, '')).filter(x => x && x !== '*').sort();
  const cases = browser.split('// Ensure the inventory')[0];
  const covered = [...cases.matchAll(/path: '\/([^']+)'/g)]
    .map(x => x[1]).sort();
  const expected = covered.map(x => x.replace(/\/1(?=\/|$)/g, '/:id')).sort();
  assert.equal(declared.length, 24);
  assert.deepEqual(expected, declared);
  assert.equal(new Set(covered).size, 24);
});

test('8x4 safe Chrome visual suite has protected exact-head screenshot upload jobs', () => {
  const job = workflow.slice(workflow.indexOf('  full-route-visual-audit:'));
  assert.ok(job.startsWith('  full-route-visual-audit:\n'));
  assert.match(job, /width: \[360, 390, 430, 768, 1024, 1280, 1440, 1920\]/);
  assert.equal(visualViewports.length, 8);
  assert.equal(visualThemes.length, 4);
  for (const phrase of [
    'Checkout exact candidate HEAD', 'Verify candidate identity',
    'Install isolated Chromium test runner',
    'Build actual production frontend',
    'fonts-noto-cjk', 'node scripts/browser-full-route-visual.mjs',
    'if: always()', 'manifest.json', 'name: full-route-visual-', 'fail-fast: false',
  ]) assert.ok((job + browser).includes(phrase), 'missing audit gate: ' + phrase);
});

test('real browser checks do not mutate or read from NAS and fail on layout/render errors', () => {
  for (const phrase of [
    "if (request.method() !== 'GET')",
    "url.origin !== BASE", "await route.abort('blockedbyclient')",
    "status: 405", "pageErrors", "horizontalOverflow", "tab.screenshot",
    "assert.deepEqual(failures, []", "writeFileSync(resolve(OUT, 'manifest.json')",
  ]) assert.ok(browser.includes(phrase), 'unsafe or missing visual gate ' + phrase);
  assert.doesNotMatch(browser, /await fetch\(['"]https?:\/\/|https:\/\/.*nas/i);
});


test('download verification actual 390px form/table defect has owned responsive UI guards', () => {
  const page = readFileSync('src/pages/DownloadVerification/index.tsx', 'utf8');
  const css = readFileSync('src/styles/console-v2-download-verification.css', 'utf8');
  const entry = readFileSync('src/main.tsx', 'utf8');
  for (const phrase of [
    'nfc-download-verify-page',
    'nfc-download-verify-field',
    'nfc-download-verify-table-scroll',
    'aria-label="校验历史"',
    'aria-label="校验明细"',
  ]) assert.ok(page.includes(phrase), 'missing actual Download Verification UI hook ' + phrase);
  assert.match(css, /grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
  assert.match(css, /@media \(max-width: 767px\)/);
  assert.match(css, /grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.match(css, /min-width:\s*720px/);
  assert.match(css, /overflow-x:\s*auto/);
  assert.ok(entry.includes("import './styles/console-v2-download-verification.css';"));
  assert.ok(browser.includes("item.id === 'download-verification'"));
  assert.ok(browser.includes("field?.querySelector('label')"));
  assert.ok(browser.includes("Download verification remote folder field is missing"));
  assert.ok(browser.includes("'-selected-detail.png'"));
  assert.ok(browser.includes("'Mobile six-column history should scroll within its panel'"));
  assert.ok(browser.includes("path === '/api/plans/legacy/summary'"));
});
