/**
 * Final Acceptance integration: all automated gates must validate the same
 * exact PR HEAD, not GitHub's synthetic pull_request merge ref.
 *
 * This source contract is intentionally not a substitute for inspecting the
 * latest Check Runs and Workflow Runs on GitHub before merging.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const readWorkflow = name => readFileSync('../.github/workflows/' + name, 'utf8');
const ui = readWorkflow('ui-v044-validation.yml');
const release = readWorkflow('release-validation.yml');
const dependency = readWorkflow('dependency-audit.yml');
const organizer = readWorkflow('organizer-advanced-c5-closure.yml');
const runner = readFileSync('scripts/run-tests.mjs', 'utf8');
const candidateRef = 'ref: ${{ github.event.pull_request.head.sha || github.sha }}';
const expectedSha = 'EXPECTED_SHA: ${{ github.event.pull_request.head.sha || github.sha }}';
const compareSha = 'test "$(git rev-parse HEAD)" = "${EXPECTED_SHA}"';

function job(workflow, name) {
  const start = workflow.indexOf('\n  ' + name + ':\n');
  assert.ok(start !== -1, 'Missing required CI job ' + name);
  const from = start + name.length + 5;
  const following = workflow.slice(from);
  const end = following.search(/\n  [a-z][a-z0-9-]*:\n/);
  return end < 0 ? following : following.slice(0, end);
}

function requireExactCandidate(source, label) {
  assert.ok(source.includes(candidateRef), label + ' must checkout exact candidate ref');
  assert.ok(source.includes(expectedSha), label + ' must set expected candidate SHA');
  const verifiesHead = source.includes(compareSha) ||
    (source.includes('CANDIDATE_SHA="$(git rev-parse HEAD)"') &&
      source.includes('test "${CANDIDATE_SHA}" = "${EXPECTED_SHA}"'));
  assert.ok(verifiesHead, label + ' must prove actual checkout SHA equals PR HEAD');
  assert.doesNotMatch(source, /continue-on-error:\s*true/, label + ' must not bypass failure');
}

test('PR frontend and backend jobs independently checkout and verify the exact HEAD', () => {
  for (const name of ['backend-regression', 'frontend-validation', 'browser-overlay-smoke']) {
    requireExactCandidate(job(ui, name), 'UI Validation / ' + name);
  }
  assert.match(job(ui, 'backend-regression'), /pytest -q/);
  const frontend = job(ui, 'frontend-validation');
  for (const command of ['npm ci', 'npm test', 'npm run typecheck', 'npm run build']) {
    assert.ok(frontend.includes(command), 'UI frontend missing ' + command);
  }
  const browser = job(ui, 'browser-overlay-smoke');
  for (const script of [
    'browser-theme-resilience.mjs',
    'browser-overlay-smoke.mjs',
    'browser-task-overlays.mjs',
    'browser-quarantine-plan-overlays.mjs',
    'browser-quarantine-bulk-overlays.mjs',
    'browser-plan-lifecycle-overlays.mjs',
    'browser-workflow-preview-overlays.mjs',
    'browser-organizer-dedupe-overlays.mjs',
    'browser-workspace-cascade.mjs',
    'browser-task-ledger-states.mjs',
    'browser-indexes-ledger-states.mjs',
    'browser-media-ledger-states.mjs',
    'browser-archive-recovery-selection.mjs',
    'browser-archive-recovery-task-continuity.mjs',
  ]) assert.ok(browser.includes('node scripts/' + script), 'Missing browser CI gate ' + script);
  assert.ok(ui.includes("      - 'frontend/**'"), 'UI PR trigger must run on frontend changes');
});

test('release regression, Docker and dependency audit use the exact candidate and hard gates', () => {
  requireExactCandidate(job(release, 'regression'), 'Release Validation / regression');
  requireExactCandidate(job(release, 'linux-amd64-docker'), 'Release Validation / Docker');
  const regression = job(release, 'regression');
  for (const command of ['pytest --disable-warnings -q', 'npm test',
    'npm run typecheck', 'npm run build', 'npm ci']) {
    assert.ok(regression.includes(command), 'Missing release validation ' + command);
  }
  const docker = job(release, 'linux-amd64-docker');
  assert.ok(docker.includes('--platform linux/amd64'));
  assert.ok(docker.includes('CANDIDATE_SHA="$(git rev-parse HEAD)"'));
  assert.ok(docker.includes('test "${CANDIDATE_SHA}" = "${EXPECTED_SHA}"'));
  requireExactCandidate(dependency, 'Dependency Audit');
  assert.ok(dependency.includes('npm ci --ignore-scripts'));
  assert.ok(dependency.includes('npm audit --omit=dev --audit-level=moderate'));
  assert.ok(dependency.includes('  pull_request:'));
  assert.ok(dependency.includes('  push:'));
});

test('Organizer full regression and Docker evidence use the same exact source identity', () => {
  requireExactCandidate(job(organizer, 'closure-regression'), 'Organizer C5 / closure');
  requireExactCandidate(job(organizer, 'linux-amd64-docker'), 'Organizer C5 / Docker');
  assert.ok(organizer.includes('CANDIDATE_SHA="$(git rev-parse HEAD)"'));
  assert.ok(organizer.includes('organizer-c5-${CANDIDATE_SHA::7}'));
  assert.ok(!organizer.includes('organizer-c5-${GITHUB_SHA::7}'),
    'Docker tag must not claim GitHub synthetic merge ref identity');
  assert.ok(organizer.includes("      - 'frontend/**'"));
});

test('the integration guard is included in the executed frontend test runner', () => {
  assert.ok(runner.includes("node --test scripts/final-integration-gates.test.mjs"));
});
