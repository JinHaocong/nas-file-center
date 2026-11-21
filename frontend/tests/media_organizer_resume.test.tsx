import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StaticRouter } from 'react-router-dom';
import * as organizer from '../src/api/media_organizer';
import type { SemanticCleanupPlan, SemanticExecutionStatus } from '../src/api/media_organizer';
import type { TaskDetail } from '../src/types/task';
import { ConsoleToastProvider } from '../src/components/ui/ConsoleToast';
import { BatchPage } from '../src/pages/Batch';
import { SemanticMediaOrganizerEditor, SemanticCleanupPlanInventory } from '../src/pages/Batch/SemanticMediaOrganizerEditor';

const route = '/batch?operation=semantic-media-organize&execution=17';
const fixtureExecution = (): SemanticExecutionStatus => ({
  job_id: 17, status: 'completed', error: null, preview_job_id: 12,
  unit: '/synthetic/Collection/NO.001', recovery_of_job_id: null,
  manual_cleanup_required: true, finalized: false, execution_enabled: true,
  publication_complete: true, deferred_publication_count: 0,
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

test('pre-freeze failure hides unusable recovery and directs to fresh preview', () => {
  const reason = '未形成可验证的冻结检查点，不能自动恢复。请保留证据并重新只读扫描。';
  const html = renderRoute({
    ...fixtureExecution(), status: 'failed', manual_cleanup_required: false,
    error: 'maintenance parent is not writable by the Worker',
    recovery_available: false, recovery_unavailable_reason: reason,
  });
  assert.ok(html.includes(reason));
  assert.ok(!html.includes('RECOVER_MEDIA_ORGANIZER_EXECUTION_17'));
  assert.ok(!html.includes('使用原冻结清单申请安全恢复'));
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

test('prepared overlapping output is not described as already published', () => {
  const prepared = { ...fixtureExecution(), publication_complete: false, deferred_publication_count: 2 };
  const html = renderRoute(prepared);
  assert.ok(html.includes('文件已安全暂存'), 'preparation and final publication must be distinct');
  assert.ok(html.includes('冻结计划中的待发布目标数'), 'deferred count must be described as frozen plan data');
  assert.ok(!html.includes('媒体文件已发布'), 'partial publication must not claim completion');
  assert.ok(!html.includes('服务器已完成清理'));
  assert.ok(html.includes('核查清理清单'));
});

test('active and failed cleanup never present frozen deferred counts as remaining work', () => {
  for (const status of ['queued', 'running', 'failed'] as const) {
    const partial = {
      ...fixtureExecution(), publication_complete: false, deferred_publication_count: 2,
      cleanup: { job_id: 21, status, error: status === 'failed' ? 'synthetic interruption' : null, recovery_confirmation: status === 'failed' ? 'SERVER_RETRY_21' : null },
    };
    const html = renderRoute(partial);
    assert.ok(html.includes('部分原始路径或暂存数据可能已清理'));
    assert.ok(html.includes('不代表当前剩余进度'), `frozen count caveat is needed during ${status}`);
    assert.ok(!html.includes('媒体文件已发布'));
    assert.ok(!html.includes('均已保留'));
  }
});

test('cleanup inventory renders separately authorized release/publication and retained outputs', () => {
  const root = '/synthetic/Collection/NO.001';
  const link = (path: string, target: string) => ({
    path: `${root}/${path}`, published_path: `${root}/${target}`,
    identity: [7, 31, 8, 99] as [number, number, number, number],
  });
  const plan: SemanticCleanupPlan = {
    job_id: 17, reviewed_execution_job_id: 17, unit: root,
    plan_sha256: 'a'.repeat(64), manifest_checksum: 'b'.repeat(64),
    plan_kind: 'review_only', page: 1, page_size: 25,
    total_original_links: 1, total_staged_links: 2,
    total_deferred_publications: 51, total_released_original_links: 31,
    total_retained_original_links: 75,
    original_links: [link('legacy/source.jpg', '003.jpg')],
    staged_links: [link('.stage/000001.jpg', '001.jpg'), link('.stage/000002.jpg', '002.jpg')],
    deferred_publications: [{
      path: `${root}/002.jpg`, stage_path: `${root}/.stage/pending.jpg`,
      source_path: `${root}/source.jpg`, identity: [7, 32, 8, 99],
    }],
    released_original_links: [{ ...link('001.jpg', '002.jpg'), stage_path: `${root}/.stage/released.jpg` }],
    retained_original_links: [link('004.jpg', '004.jpg')],
    wrapper_directories: [{ path: `${root}/legacy`, identity: [7, 30] }],
    retained_wrapper_directories: [{ path: `${root}/P [1 8B]`, identity: [7, 35] }],
    stage: { path: `${root}/.stage`, identity: [7, 40] },
    cleanup_authorized: false, finalized: false, zero_change_rescan_verified: false,
    namespace_exclusive_custody_proven: false, read_only: true,
    confirmation: 'SERVER_CLEANUP_UNIT_17_PLAN_A',
  };
  const html = renderToStaticMarkup(<SemanticCleanupPlanInventory
    plan={plan} page={1} pageSize={25} busy={false} onPageChange={() => {}} />);
  for (const label of ['确认后释放的原始路径', '确认后完成发布的目标', '保留的最终文件', '保留的目标目录']) {
    assert.ok(html.includes(label), `review must expose ${label}`);
  }
  for (const path of ['/002.jpg', '/.stage/pending.jpg', '/.stage/released.jpg', '/004.jpg', '/P [1 8B]']) {
    assert.ok(html.includes(`${root}${path}`), `review must show ${path}`);
  }
  assert.ok(html.includes('第 1 / 3 页'), 'pagination includes retained rows beyond original/staged totals');
  assert.ok(!html.includes('已发布文件'), 'pending final paths must not be described as already published');
  const snapshotPlan = {
    ...plan, verification_scope: 'worker_handoff_snapshot' as const, live_inventory_verified: false,
  };
  const snapshotHtml = renderToStaticMarkup(<SemanticCleanupPlanInventory
    plan={snapshotPlan} page={1} pageSize={25} busy={false} onPageChange={() => {}} />);
  assert.ok(snapshotHtml.includes('上次 Worker 完整核验的结果'), 'shared artifacts are a recorded snapshot');
  assert.ok(snapshotHtml.includes('执行前再次核验'), 'current live inventory must still be checked by Worker');
});
