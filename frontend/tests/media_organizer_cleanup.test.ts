import test from 'node:test';
import assert from 'node:assert/strict';
import * as organizer from '../src/api/media_organizer';
import type {
  SemanticCleanupPlan, SemanticExecutionStatus, SemanticPreviewPage, SemanticUnitPreview,
} from '../src/api/media_organizer';

const fixtureExecution = (): SemanticExecutionStatus => ({
  job_id: 17, status: 'completed', error: null, preview_job_id: 12,
  unit: '/synthetic/Collection/NO.001', recovery_of_job_id: null,
  manual_cleanup_required: true, finalized: false, execution_enabled: true,
  publication_complete: true, deferred_publication_count: 0,
  progress: { current: 4, total: 4, message: null, phase: 'manual_cleanup_required' },
  cleanup: null,
});

const fixturePlan = (): SemanticCleanupPlan => ({
  job_id: 17, reviewed_execution_job_id: 17,
  unit: '/synthetic/Collection/NO.001', plan_sha256: 'a'.repeat(64),
  manifest_checksum: 'b'.repeat(64), plan_kind: 'review_only', page: 2, page_size: 50,
  total_original_links: 51, total_staged_links: 51,
  total_deferred_publications: 0, total_released_original_links: 0,
  total_retained_original_links: 0,
  deferred_publications: [], released_original_links: [], retained_original_links: [],
  original_links: [{
    path: '/synthetic/Collection/NO.001/photos/last.jpg',
    published_path: '/synthetic/Collection/NO.001/051.jpg',
    identity: [7, 31, 8, 99],
  }],
  staged_links: [{
    path: '/synthetic/Collection/NO.001/.nfc-media-organizer-stage-17/000051.jpg',
    published_path: '/synthetic/Collection/NO.001/051.jpg',
    identity: [7, 31, 8, 99],
  }],
  wrapper_directories: [{ path: '/synthetic/Collection/NO.001/photos', identity: [7, 30] }],
  retained_wrapper_directories: [],
  stage: { path: '/synthetic/Collection/NO.001/.nfc-media-organizer-stage-17', identity: [7, 40] },
  cleanup_authorized: false, finalized: false, zero_change_rescan_verified: false,
  namespace_exclusive_custody_proven: false, read_only: true,
  confirmation: 'SERVER_CLEANUP_UNIT_17_PLAN_A',
});

const features = organizer;
const client = organizer.mediaOrganizerApi;

test('cleanup review requests the selected execution and full mapping page', async t => {
  const plan = fixturePlan();
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(url, '/api/media-organizer/executions/17/cleanup-plan?page=2&page_size=50');
    assert.equal(options.method, 'GET');
    assert.equal(options.credentials, 'include');
    assert.equal(options.body, undefined);
    return new Response(JSON.stringify(plan), { status: 200 });
  });
  assert.equal(typeof client.getCleanupPlan, 'function', 'cleanup review API is available');
  assert.deepEqual(await client.getCleanupPlan(17, 2, 50), plan);
});

test('initial cleanup and recovery send separate exact server tokens to their own endpoints', async t => {
  const requests: { url: string; body: unknown }[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    requests.push({ url, body: JSON.parse(String(options.body)) });
    assert.equal(options.method, 'POST');
    assert.equal(options.credentials, 'include');
    return new Response(JSON.stringify({
      job_id: requests.length === 1 ? 21 : 22, status: 'queued', execution_job_id: 17,
    }), { status: 200 });
  });
  assert.equal(typeof client.startCleanup, 'function', 'separate cleanup API is available');
  assert.equal(typeof client.recoverCleanup, 'function', 'cleanup recovery API is available');
  assert.equal((await client.startCleanup(17, 'SERVER_CLEANUP_UNIT_17_PLAN_A')).job_id, 21);
  assert.equal((await client.recoverCleanup(21, 'SERVER_RECOVER_ATTEMPT_21_PLAN_A')).job_id, 22);
  assert.deepEqual(requests, [
    { url: '/api/media-organizer/executions/17/cleanup', body: { confirmation: 'SERVER_CLEANUP_UNIT_17_PLAN_A' } },
    { url: '/api/media-organizer/cleanups/21/recover', body: { confirmation: 'SERVER_RECOVER_ATTEMPT_21_PLAN_A' } },
  ]);
});

test('cleanup custody rejection stays a visible API conflict', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(
    JSON.stringify({ detail: 'synthetic custody proof unavailable' }), { status: 409 },
  ));
  assert.equal(typeof client.startCleanup, 'function');
  await assert.rejects(client.startCleanup(17, fixturePlan().confirmation), (error: any) => {
    assert.equal(error.status, 409);
    assert.equal(error.message, 'synthetic custody proof unavailable');
    return true;
  });
});

test('grouped work is selectable only when the server supplied its execution token', () => {
  assert.equal(typeof features.executableSemanticUnits, 'function');
  const flat: SemanticUnitPreview = {
    unit: '/synthetic/flat', status: 'ready', reason: null, operation: 'flatten_pure_media',
    totals: { P: 1, V: 0, Other: 0 }, groups: [], needed_moves: 1, renamed_count: 1,
    total_files: 1, total_proposals: 1, sample_moves: [], mapping_id: 'a'.repeat(64),
    truncated: false, input_fingerprint: 'b'.repeat(64), conflicts: [], read_only: true,
  };
  const grouped: SemanticUnitPreview = {
    ...flat, unit: '/synthetic/grouped', operation: 'sort_mixed_media',
    totals: { P: 1, V: 1, Other: 0 }, needed_moves: 2, renamed_count: 2,
    total_files: 2, total_proposals: 2,
    groups: [
      { kind: 'P', name: 'P [1 5B]', destination: '/synthetic/grouped/P [1 5B]', count: 1, bytes: 5 },
      { kind: 'V', name: 'V [1 5B]', destination: '/synthetic/grouped/V [1 5B]', count: 1, bytes: 5 },
    ],
  };
  const blocked: SemanticUnitPreview = {
    ...flat, unit: '/synthetic/blocked', status: 'blocked', reason: 'synthetic blocker',
    operation: null, needed_moves: 0, renamed_count: 0, mapping_id: null,
    total_proposals: 0, conflicts: ['synthetic blocker'],
  };
  const page: SemanticPreviewPage = {
    job_id: 12, status: 'completed', error: null, selection: '/synthetic',
    progress: { current: 3, total: 3, message: null },
    execution_enabled: true, page: 1, page_size: 25, filtered_total: 3, read_only: true,
    summary: {
      unit_count: 3, ready_count: 2, blocked_count: 0, already_organized_count: 0,
      skipped_count: 0, file_count: 4, needed_moves: 3, renamed_count: 3,
      elapsed_seconds: 1, read_only: true,
    },
    units: [flat, grouped, blocked],
    confirmation_tokens: {
      [flat.unit]: 'FLAT_APPROVAL', [grouped.unit]: 'GROUP_APPROVAL', [blocked.unit]: 'INVALID',
    },
  };
  assert.deepEqual(features.executableSemanticUnits(page), [flat, grouped]);
  assert.deepEqual(features.executableSemanticUnits({ ...page, confirmation_tokens: {} }), []);
  assert.deepEqual(features.executableSemanticUnits({ ...page, execution_enabled: false }), []);
  assert.deepEqual(features.executableSemanticUnits({
    ...page, summary: { ...page.summary!, blocked_count: 1 },
  }), []);
  assert.deepEqual(features.executableSemanticUnits(undefined), []);
});

test('completed publication keeps polling through queued cleanup and recovery handoff', () => {
  assert.equal(typeof features.semanticExecutionNeedsPolling, 'function');
  const published = fixtureExecution();
  assert.equal(features.semanticExecutionNeedsPolling(published), false);
  assert.equal(features.semanticExecutionNeedsPolling(published, 21), true);
  for (const status of ['queued', 'running', 'paused', 'cancel_requested'] as const) {
    assert.equal(features.semanticExecutionNeedsPolling({
      ...published, cleanup: { job_id: 21, status, error: null, recovery_confirmation: null },
    }, 21), true);
  }
  const failed: SemanticExecutionStatus = {
    ...published,
    cleanup: { job_id: 21, status: 'failed', error: 'synthetic interruption', recovery_confirmation: 'SERVER_RETRY_21' },
  };
  assert.equal(features.semanticExecutionNeedsPolling(failed, 21), false);
  assert.equal(features.semanticExecutionNeedsPolling(failed, 22), true);
  assert.equal(features.semanticExecutionNeedsPolling({
    ...published, manual_cleanup_required: false, finalized: true,
    cleanup: { job_id: 22, status: 'completed', error: null, recovery_confirmation: null },
  }, 22), false);
});

test('cleanup confirmation binds the reviewed execution, unit, and exact independent token', () => {
  assert.equal(typeof features.canConfirmSemanticCleanup, 'function');
  const execution = fixtureExecution();
  const plan = fixturePlan();
  assert.equal(features.canConfirmSemanticCleanup(execution, plan, plan.confirmation), true);
  assert.equal(features.canConfirmSemanticCleanup({
    ...execution, publication_complete: false, deferred_publication_count: 2,
  }, plan, plan.confirmation), true, 'prepared output must still support separate confirmation');
  for (const confirmation of ['', 'EXECUTE_APPROVAL', `${plan.confirmation} `]) {
    assert.equal(features.canConfirmSemanticCleanup(execution, plan, confirmation), false);
  }
  assert.equal(features.canConfirmSemanticCleanup(execution, { ...plan, reviewed_execution_job_id: 18 }, plan.confirmation), false);
  assert.equal(features.canConfirmSemanticCleanup(execution, { ...plan, unit: '/synthetic/other' }, plan.confirmation), false);
  assert.equal(features.canConfirmSemanticCleanup({ ...execution, finalized: true }, plan, plan.confirmation), false);
  assert.equal(features.canConfirmSemanticCleanup({ ...execution, execution_enabled: false }, plan, plan.confirmation), false);
  assert.equal(features.canConfirmSemanticCleanup({ ...execution, manual_cleanup_required: false }, plan, plan.confirmation), false);
  assert.equal(features.canConfirmSemanticCleanup({
    ...execution, cleanup: { job_id: 21, status: 'failed', error: 'synthetic interruption', recovery_confirmation: null },
  }, plan, plan.confirmation), false);
  assert.equal(features.canConfirmSemanticCleanup(execution, undefined, plan.confirmation), false);
});

test('a failed cleanup remains recoverable after original execution finalization', () => {
  assert.equal(typeof features.canRecoverSemanticCleanup, 'function');
  const execution: SemanticExecutionStatus = {
    ...fixtureExecution(), finalized: true, manual_cleanup_required: false,
    cleanup: { job_id: 21, status: 'failed', error: 'synthetic completion interruption', recovery_confirmation: 'SERVER_RETRY_21' },
  };
  assert.equal(features.canRecoverSemanticCleanup(execution, 'SERVER_RETRY_21'), true);
  assert.equal(features.canRecoverSemanticCleanup(execution, 'SERVER_RETRY_20'), false);
  assert.equal(features.canRecoverSemanticCleanup(execution, ''), false);
  assert.equal(features.canRecoverSemanticCleanup({
    ...execution, cleanup: { ...execution.cleanup!, recovery_confirmation: null },
  }, 'SERVER_RETRY_21'), false);
  assert.equal(features.canRecoverSemanticCleanup({
    ...execution, cleanup: { ...execution.cleanup!, status: 'running' },
  }, 'SERVER_RETRY_21'), false);
});
