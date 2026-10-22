import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync, rmSync, renameSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { visualViewports } from './visual-fixtures.mjs';
import { stageVisualArtifacts } from './stage-visual-review-artifacts.mjs';

const SHA = '6a56a3357cf979e8e4ec60d6db1a97ae8cf754c3';
const OTHER = '7b561c89988f5298f08d7894b1b4642020cd7db3';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'nfc-visual-artifacts-'));
  const input = join(root, 'downloads');
  const output = join(root, 'full-route-visual');
  mkdirSync(input);
  for (const width of visualViewports) {
    const directory = join(input, 'full-route-visual-' + width + '-' + SHA);
    mkdirSync(directory);
    writeFileSync(join(directory, 'manifest.json'), JSON.stringify({ width }));
  }
  return { root, input, output };
}
function withFixture(fn) {
  const fixtureData = fixture();
  try { fn(fixtureData); }
  finally { rmSync(fixtureData.root, { recursive: true, force: true }); }
}

test('stages eight and only eight exact-head artifacts into the 800-case input layout', () => {
  withFixture(({ input, output }) => {
    assert.equal(stageVisualArtifacts(input, output, SHA), 8);
    assert.deepEqual(readdirSync(output).map(Number).sort((a, b) => a - b),
      [...visualViewports].sort((a, b) => a - b));
    for (const width of visualViewports)
      assert.ok(existsSync(join(output, String(width), 'manifest.json')));
    assert.deepEqual(readdirSync(input), []);
  });
});
test('rejects a stale head, mixed heads and does not touch the output on validation failure', () => {
  withFixture(({ input, output }) => {
    assert.throws(() => stageVisualArtifacts(input, output, OTHER),
      /Mixed or stale PR HEAD artifact/);
    assert.equal(existsSync(output), false);
    const old = join(input, 'full-route-visual-360-' + SHA);
    const changed = join(input, 'full-route-visual-360-' + OTHER);
    renameSync(old, changed);
    assert.throws(() => stageVisualArtifacts(input, output, SHA),
      /Mixed or stale PR HEAD artifact/);
    assert.equal(existsSync(output), false);
  });
});
test('rejects missing, duplicate and unexpected artifact downloads', () => {
  withFixture(({ input, output }) => {
    rmSync(join(input, 'full-route-visual-390-' + SHA), { recursive: true });
    assert.throws(() => stageVisualArtifacts(input, output, SHA),
      /exactly eight/);
    assert.equal(existsSync(output), false);
  });
  withFixture(({ input, output }) => {
    mkdirSync(join(input, 'full-route-visual-0360-' + SHA));
    assert.throws(() => stageVisualArtifacts(input, output, SHA), /exactly eight/);
    assert.equal(existsSync(output), false);
  });
  withFixture(({ input, output }) => {
    writeFileSync(join(input, 'unexpected.zip'), 'not a trusted artifact');
    assert.throws(() => stageVisualArtifacts(input, output, SHA), /exactly eight/);
    assert.equal(existsSync(output), false);
  });
});
test('rejects preexisting output or untrusted malformed exact HEAD', () => {
  withFixture(({ input, output }) => {
    mkdirSync(output);
    assert.throws(() => stageVisualArtifacts(input, output, SHA),
      /Refusing to overwrite/);
    assert.throws(() => stageVisualArtifacts(input, output, 'deadbeef'),
      /full exact GitHub/);
  });
});


test('unified artifact job waits for all eight real Chromium jobs and preserves exact SHA', () => {
  const workflow = readFileSync('../.github/workflows/ui-v044-validation.yml', 'utf8');
  const start = workflow.indexOf('  human-visual-review-pack:');
  assert.ok(start !== -1, 'Missing post-Chromium human review job');
  const job = workflow.slice(start);
  for (const phrase of [
    'needs: full-route-visual-audit',
    'Checkout exact candidate HEAD',
    'Verify candidate identity',
    'actions/download-artifact@v4',
    'full-route-visual-*-${{ github.event.pull_request.head.sha || github.sha }}',
    'merge-multiple: false',
    'node scripts/stage-visual-review-artifacts.mjs',
    'node scripts/build-visual-review-pack.mjs',
    'actions/upload-artifact@v4',
    'human-visual-review-800-${{ github.event.pull_request.head.sha || github.sha }}',
    'if-no-files-found: error',
    'frontend/artifacts/full-route-visual/',
    'frontend/artifacts/visual-review-pack/',
  ]) assert.ok(job.includes(phrase), 'Lost review delivery rule: ' + phrase);
  assert.doesNotMatch(job, /continue-on-error:\s*true/);
  const runner = readFileSync('scripts/run-tests.mjs', 'utf8');
  assert.ok(runner.includes('node --test scripts/stage-visual-review-artifacts.test.mjs'));
});
