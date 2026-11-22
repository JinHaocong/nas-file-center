import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import TestRenderer, { act, type ReactTestRenderer } from 'react-test-renderer';

import { DirectoryPicker } from '../src/components/DirectoryPicker';
import { ConsoleToastProvider } from '../src/components/ui/ConsoleToast';
import { BatchPage } from '../src/pages/Batch';

const selection = '/synthetic/parent';
const previewId = '9007199254740993';
const batchId = '9007199254740994';
const progress = { current: 2, total: 2, message: null };
const readyUnit = {
  unit: selection + '/ready', status: 'ready', reason: null, operation: 'flatten_pure_media',
  totals: { P: 1, V: 0, Other: 0 }, groups: [], conflicts: [], sample_moves: [],
  needed_moves: 1, renamed_count: 1, total_files: 1, total_proposals: 51,
  mapping_id: 'preview-mapping', truncated: true, read_only: true,
};
const blockedUnit = {
  ...readyUnit, unit: selection + '/blocked', status: 'blocked', mapping_id: null,
  conflicts: [{ reason: 'target_path_exists', target: selection + '/blocked/001.jpg' }],
};
const preview = {
  job_id: previewId, selection, status: 'completed', error: null,
  progress, execution_enabled: true, units: [readyUnit, blockedUnit], page: 1, page_size: 25, filtered_total: 2,
  summary: {
    unit_count: 2, ready_count: 1, blocked_count: 1, already_organized_count: 0,
    skipped_count: 0, file_count: 2, needed_moves: 1, renamed_count: 1,
    totals: { P: 2, V: 0, Other: 0 }, total_bytes: 40, wrapper_cleanup_count: 1,
  },
};
const report = {
  job_id: batchId, preview_job_id: previewId, selection, status: 'completed', error: null,
  progress, page: 1, page_size: 25, filtered_total: 2,
  summary: { success_count: 1, skipped_count: 0, conflict_count: 1, failed_count: 0 },
  items: [
    { unit: selection + '/ready', status: 'success' },
    { unit: selection + '/blocked', status: 'conflict', reason: '目标路径已存在' },
  ],
};

/** Wait for React Query's scheduled result notifications. */
const settle = () => new Promise(resolve => setTimeout(resolve, 20));

test.beforeEach(() => {
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { title: '' } });
});

test.afterEach(() => { Reflect.deleteProperty(globalThis, 'document'); });

/** Render the real Batch entry with a fresh query client. */
async function openBatch(location: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let view!: ReactTestRenderer;
  await act(async () => {
    view = TestRenderer.create(<MemoryRouter initialEntries={[location]}>
      <QueryClientProvider client={client}>
        <ConsoleToastProvider><BatchPage /></ConsoleToastProvider>
      </QueryClientProvider>
    </MemoryRouter>);
    await settle();
  });
  return { view, dispose: () => { view.unmount(); client.clear(); } };
}

test('one selected directory previews automatically and repeated confirmation starts only one batch', async t => {
  const requests: Array<{ url: string; body: unknown }> = [];
  let finishBatch!: (response: Response) => void;
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    if (options.method === 'POST') {
      requests.push({ url, body: JSON.parse(String(options.body)) });
      if (url.endsWith('/batches')) return new Promise<Response>(resolve => { finishBatch = resolve; });
      return Response.json({ job_id: previewId, status: 'queued' });
    }
    if (url.includes('/batches/')) return Response.json(report);
    return Response.json(preview);
  });
  const { view, dispose } = await openBatch('/batch?operation=media-organize');
  t.after(dispose);
  await act(async () => {
    view.root.findByType(DirectoryPicker).props.onChange(selection);
    await settle();
  });
  assert.deepEqual(requests, [{
    url: '/api/media-organizer/previews', body: { selection, batch_flow: true },
  }], 'selecting a directory must immediately submit a recursive preview');
  assert.match(JSON.stringify(view.toJSON()), /目标路径已存在/);
  assert.match(JSON.stringify(view.toJSON()), /blocked\/001.jpg/);
  const confirm = view.root.findAllByType('button').find(button =>
    button.findAllByType('span').some(span => span.children.join('') === '确认整理全部'));
  assert.ok(confirm && !confirm.props.disabled, 'a conflicting neighbor must not block ready work');
  await act(async () => {
    confirm.props.onClick();
    confirm.props.onClick();
    await settle();
  });
  assert.deepEqual(requests.slice(1), [{
    url: `/api/media-organizer/previews/${previewId}/batches`, body: {},
  }]);
  await act(async () => {
    finishBatch(Response.json({ job_id: batchId, status: 'queued' }));
    await settle();
  });
  assert.match(JSON.stringify(view.toJSON()), /整理结果/);
  assert.match(JSON.stringify(view.toJSON()), /目标路径已存在/);
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /EXECUTE_MEDIA_ORGANIZER|RECOVER_MEDIA_ORGANIZER|维护窗口/);
});

test('opening the batch result URL preserves the exact string job ID and loads the existing report', async t => {
  const requests: string[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(options.method, 'GET');
    requests.push(url);
    if (url.includes('/batches/')) return Response.json(report);
    return Response.json(preview);
  });
  const { view, dispose } = await openBatch(`/batch?operation=media_package-organize&batch=${batchId}`);
  t.after(dispose);
  assert.ok(requests.some(url => url.startsWith(`/api/media-organizer/batches/${batchId}?`)));
  assert.match(JSON.stringify(view.toJSON()), /整理结果/);
  assert.match(JSON.stringify(view.toJSON()), /目标路径已存在/);
});

test('preview filtering and complete source-to-target mapping request the right pages', async t => {
  const requests: string[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(options.method, 'GET');
    requests.push(url);
    const query = new URLSearchParams(url.split('?')[1]);
    if (url.includes('/mappings/')) {
      const second = query.get('page') === '2';
      return Response.json({ page: second ? 2 : 1, page_size: 50, total_moves: 51, moves: [{
        source: selection + (second ? '/ready/last.jpg' : '/ready/first.jpg'),
        target: selection + (second ? '/ready/051.jpg' : '/ready/001.jpg'), kind: 'P', bytes: 20,
      }] });
    }
    return Response.json(preview);
  });
  const { view, dispose } = await openBatch(`/batch?operation=media-organize&preview=${previewId}`);
  t.after(dispose);
  await act(async () => {
    view.root.findByProps({ id: 'media-organizer-batch-filter' }).props.onChange({ target: { value: 'ready' } });
    await settle();
  });
  assert.ok(requests.some(url => url.includes('status_filter=ready')));
  const openMapping = view.root.findAllByType('button').find(button =>
    button.findAllByType('span').some(span => span.children.join('').includes('查看完整映射')));
  assert.ok(openMapping);
  await act(async () => { openMapping.props.onClick(); await settle(); });
  assert.match(JSON.stringify(view.toJSON()), /first.jpg/);
  const nextPage = view.root.findAllByProps({ 'aria-label': '下一页' }).find(button => !button.props.disabled);
  assert.ok(nextPage);
  await act(async () => { nextPage.props.onClick(); await settle(); });
  assert.match(JSON.stringify(view.toJSON()), /last.jpg/);
  assert.ok(requests.some(url => url.endsWith('/mappings/preview-mapping?page=2&page_size=50')));
});


test('a legacy execution URL opens directory selection without a historical execution request', async t => {
  const requests = t.mock.method(globalThis, 'fetch', async () => {
    throw new Error('unexpected request');
  });
  const { view, dispose } = await openBatch('/batch?operation=semantic-media-organize&execution=35');
  t.after(dispose);
  assert.match(JSON.stringify(view.toJSON()), /选择文件夹后自动扫描子目录/);
  assert.equal(requests.mock.callCount(), 0);
});
