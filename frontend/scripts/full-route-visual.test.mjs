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
