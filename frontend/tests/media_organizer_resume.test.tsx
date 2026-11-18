import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StaticRouter } from 'react-router-dom';
import * as organizer from '../src/api/media_organizer';
import type { SemanticExecutionStatus } from '../src/api/media_organizer';
import type { TaskDetail } from '../src/types/task';
import { ConsoleToastProvider } from '../src/components/ui/ConsoleToast';
import { BatchPage } from '../src/pages/Batch';
import { SemanticMediaOrganizerEditor } from '../src/pages/Batch/SemanticMediaOrganizerEditor';

const route = '/batch?operation=semantic-media-organize&execution=17';
const fixtureExecution = (): SemanticExecutionStatus & { execution_enabled: boolean } => ({
  job_id: 17, status: 'completed', error: null, preview_job_id: 12,
  unit: '/synthetic/Collection/NO.001', recovery_of_job_id: null,
  manual_cleanup_required: true, finalized: false, execution_enabled: true,
  progress: { current: 4, total: 4, message: null, phase: 'manual_cleanup_required' },
  cleanup: null,
});

const fixtureTask = (job_type: string, id: number, payload: Record<string, unknown>): TaskDetail => ({
  id, job_type, payload, checkpoint: {}, status: 'failed',
  capabilities: { supports_pause: false, supports_resume: false, supports_cancel: false, supports_retry: false },
  progress: { current: 1, total: 2, percent: 50, message: null },
  created_at: null, started_at: null, finished_at: null, heartbeat_at: null,
  error: 'synthetic interruption', error_code: 'EXECUTION_ERROR', retry_of: null,
});

function renderRoute(
  execution: SemanticExecutionStatus | undefined,
  location = route,
  component: React.ReactElement = <SemanticMediaOrganizerEditor />,
) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  if (execution) queryClient.setQueryData(['semanticMediaExecution', execution.job_id], execution);
  try {
    return renderToStaticMarkup(
      <StaticRouter location={location}>
        <QueryClientProvider client={queryClient}>
          <ConsoleToastProvider>{component}</ConsoleToastProvider>
        </QueryClientProvider>
      </StaticRouter>,
    );
  } finally {
    queryClient.clear();
  }
}

test('refreshing a durable execution URL opens its real cleanup review without a preview', async t => {
  const requests: string[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    requests.push(url);
    assert.equal(options.method, 'GET');
    assert.equal(options.credentials, 'include');
    assert.equal(url, '/api/media-organizer/executions/17');
    return new Response(JSON.stringify(fixtureExecution()), { status: 200 });
  });
  const verified = await organizer.mediaOrganizerApi.getExecution(17);
  const html = renderRoute(verified, route, <BatchPage />);
  assert.ok(html.includes('独立清理与恢复'), 'Batch must select organizer from the durable URL');
  assert.ok(html.includes('核查清理清单'), 'authenticated existing execution can continue to cleanup');
  assert.ok(html.includes('/synthetic/Collection/NO.001'), 'unit comes from the execution response');
  assert.deepEqual(requests, ['/api/media-organizer/executions/17']);
});

test('refreshing a finalized execution with a failed cleanup still exposes its recovery token', () => {
  const html = renderRoute({
    ...fixtureExecution(), finalized: true, manual_cleanup_required: false,
    cleanup: { job_id: 21, status: 'failed', error: 'synthetic final checkpoint interruption', recovery_confirmation: 'SERVER_RETRY_21' },
  });
  assert.ok(html.includes('SERVER_RETRY_21'), 'failed cleanup recovery survives a refresh');
  assert.ok(html.includes('确认并恢复本次清理'), 'finalized original must not hide cleanup recovery');
});

test('publication recovery uses authenticated execution eligibility without re-running preview', () => {
  const html = renderRoute({
    ...fixtureExecution(), status: 'failed', manual_cleanup_required: false,
    error: 'synthetic publication interruption',
  });
  assert.ok(html.includes('RECOVER_MEDIA_ORGANIZER_EXECUTION_17'), 'publication recovery is reachable from Task Center');
  assert.ok(html.includes('使用原冻结清单申请安全恢复'));
});

test('partial cleanup never claims that all original and staged entries are retained', () => {
  const pending = renderRoute(fixtureExecution());
  assert.ok(pending.includes('均已保留'), 'publication-only status describes retained inputs');
  for (const status of ['queued', 'running', 'failed'] as const) {
    const html = renderRoute({
      ...fixtureExecution(),
      cleanup: { job_id: 21, status, error: status === 'failed' ? 'synthetic interruption' : null, recovery_confirmation: status === 'failed' ? 'SERVER_RETRY_21' : null },
    });
    assert.ok(!html.includes('均已保留'), `retention claim must be absent during ${status} cleanup`);
    assert.ok(html.includes('部分原始路径或暂存数据可能已清理'), `partial cleanup state must be described during ${status}`);
  }
});

test('execution and cleanup task handoffs resolve only their exact durable execution', () => {
  assert.equal(organizer.semanticOrganizerTaskHref(fixtureTask('media-organizer-execute', 17, {})), route);
  assert.equal(organizer.semanticOrganizerTaskHref(fixtureTask('media-organizer-cleanup', 21, { execution_job_id: 17 })), route);
  for (const value of [undefined, '17', 0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(organizer.semanticOrganizerTaskHref(fixtureTask('media-organizer-cleanup', 21, { execution_job_id: value })), null);
  }
  assert.equal(organizer.semanticOrganizerTaskHref(fixtureTask('unrelated-task', 17, { execution_job_id: 17 })), null);
  const updated = organizer.withSemanticExecutionId(new URLSearchParams('unrelated=keep'), 18);
  assert.equal(updated.get('unrelated'), 'keep');
  assert.equal(organizer.semanticExecutionIdFromSearch(updated), 18);
  const cleared = organizer.withSemanticExecutionId(updated, null);
  assert.equal(cleared.has('execution'), false);
  assert.equal(cleared.get('operation'), 'semantic-media-organize');
});

test('invalid or ambiguous execution URL IDs cannot select a cached execution', () => {
  for (const value of ['0', '-1', '17oops', '17.0', '9007199254740992', '17&execution=18']) {
    const html = renderRoute(fixtureExecution(), `/batch?operation=semantic-media-organize&execution=${value}`);
    assert.ok(html.includes('执行任务编号无效'), `invalid durable ID must be rejected: ${value}`);
    assert.ok(!html.includes('核查清理清单'));
    assert.ok(!html.includes('/synthetic/Collection/NO.001'));
  }
});

test('cleanup recovery stays disabled when the validated execution disables mutation', () => {
  const execution = {
    ...fixtureExecution(), execution_enabled: false,
    cleanup: { job_id: 21, status: 'failed' as const, error: 'synthetic interruption', recovery_confirmation: 'SERVER_RETRY_21' },
  };
  assert.equal(organizer.canRecoverSemanticCleanup(execution, 'SERVER_RETRY_21'), false);
});
