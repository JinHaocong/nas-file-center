import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import TestRenderer, { act, type ReactTestRenderer } from 'react-test-renderer';

import { DirectoryPicker } from '../src/components/DirectoryPicker';
import { ConsoleConfirmDialog } from '../src/components/ui/ConsoleConfirmDialog';
import { ConsoleSheet } from '../src/components/ui/ConsoleSheet';
import { ConsoleToastProvider } from '../src/components/ui/ConsoleToast';
import { DisplayPreferencesProvider } from '../src/contexts/DisplayPreferencesContext';
import { BatchPage } from '../src/pages/Batch';
import { MediaOrganizerPreviewReport } from '../src/pages/Batch/MediaOrganizerBatchReports';
import { PlanDetailPage } from '../src/pages/Plans/PlanDetail';

import type { MediaBatchPreview } from '../src/api/mediaOrganizerBatch';

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
  job_id: previewId, selection, status: 'completed' as const, error: null,
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

/** Wait for the expected render even when query notifications arrive in a later tick. */
async function waitForRenderedText(view: ReactTestRenderer, text: string) {
  const deadline = Date.now() + 2000;
  while (!JSON.stringify(view.toJSON()).includes(text) && Date.now() < deadline) {
    await act(settle);
  }
  assert.ok(JSON.stringify(view.toJSON()).includes(text), `Expected the rendered page to contain ${text}`);
}

test.beforeEach(() => {
  Object.defineProperty(globalThis, 'document', { configurable: true, value: Object.assign(new EventTarget(), { title: '' }) });
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: Object.assign(new EventTarget(), { innerWidth: 1440, setTimeout, clearTimeout }),
  });
});

test.after(() => {
  Reflect.deleteProperty(globalThis, 'document');
  Reflect.deleteProperty(globalThis, 'window');
});

test('mobile media organizer opens a controlled sheet without inserting rows or changing their order', t => {
  const settings = Object.assign(new EventTarget(), {
    innerWidth: 390,
    localStorage: { getItem: () => 'on', setItem: () => {} },
  });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: settings });
  const allUnits = [readyUnit, blockedUnit, ...['third', 'fourth', 'fifth'].map(name =>
    ({ ...readyUnit, unit: selection + '/' + name }))] as MediaBatchPreview['units'];
  const render = (index: number, detailBusy = false) => (
    <DisplayPreferencesProvider>
      <MediaOrganizerPreviewReport preview={{ ...preview, units: allUnits }} selected={allUnits[index]}
        onSelect={() => {}} onDetails={() => {}} action={null} footer={null}
        detailBusy={detailBusy}>{null}</MediaOrganizerPreviewReport>
    </DisplayPreferencesProvider>
  );
  let view!: ReactTestRenderer;
  act(() => { view = TestRenderer.create(render(0)); });
  t.after(() => { act(() => view.unmount()); Reflect.deleteProperty(globalThis, 'window'); });

  const order = () => view.root.findByProps({ 'aria-label': '逐目录整理预览' }).findAllByType('li')
    .map(item => item.findByType('button').props.title.replace(selection + '/', ''));
  assert.deepEqual(order(), ['ready', 'blocked', 'third', 'fourth', 'fifth']);
  assert.equal(view.root.findAllByType(ConsoleSheet).length, 0);
  act(() => view.root.findByProps({ title: readyUnit.unit }).props.onClick());
  assert.equal(view.root.findByType(ConsoleSheet).props.title, '整理详情');
  assert.deepEqual(order(), ['ready', 'blocked', 'third', 'fourth', 'fifth']);
  act(() => view.update(render(0, true)));
  assert.equal(view.root.findByType(ConsoleSheet).props.dismissDisabled, true);
  act(() => view.root.findByType(ConsoleSheet).props.onClose());
  assert.equal(view.root.findByType(ConsoleSheet).props.open, true);
  act(() => view.update(render(0)));
  act(() => view.root.findByType(ConsoleSheet).props.onClose());
  assert.equal(view.root.findAllByType(ConsoleSheet).length, 0);
  act(() => view.update(render(4)));
  act(() => view.root.findByProps({ title: allUnits[4].unit }).props.onClick());
  assert.equal(view.root.findByType(ConsoleSheet).props.open, true);
  act(() => { settings.innerWidth = 1200; settings.dispatchEvent(new Event('resize')); });
  assert.deepEqual(order(), ['ready', 'blocked', 'third', 'fourth', 'fifth']);
  assert.equal(view.root.findAllByType(ConsoleSheet).length, 0);
  assert.equal(view.root.findByProps({ id: 'organizer-unit-inspection' }).type, 'section');
});

test('an archive promotion identifies whole child directories in its preview', t => {
  const unit = {
    ...readyUnit, unit: '/synthetic/old/old', operation: 'promote_repeated_archive_children',
    totals: { P: 0, V: 0, Other: 0 }, total_files: 0, total_proposals: 2, needed_moves: 2,
  } as MediaBatchPreview['units'][number];
  let view!: ReactTestRenderer;
  act(() => {
    view = TestRenderer.create(<DisplayPreferencesProvider>
      <MediaOrganizerPreviewReport preview={{ ...preview, units: [unit] }} selected={unit}
        onSelect={() => {}} onDetails={() => {}} action={null} footer={null}>{null}</MediaOrganizerPreviewReport>
    </DisplayPreferencesProvider>);
  });
  t.after(() => act(() => view.unmount()));
  const rendered = JSON.stringify(view.toJSON());
  assert.match(rendered, /整体上提 2 个子目录/);
  assert.doesNotMatch(rendered, /0 个文件/);
});

/** Render a real route with a fresh query client. */
async function openBatch(location: string, page = <BatchPage />,
  createNodeMock?: (element: React.ReactElement) => unknown) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let view!: ReactTestRenderer;
  await act(async () => {
    view = TestRenderer.create(<MemoryRouter initialEntries={[location]}>
      <QueryClientProvider client={client}>
        <ConsoleToastProvider>{page}</ConsoleToastProvider>
      </QueryClientProvider>
    </MemoryRouter>, { createNodeMock });
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
  });
  assert.deepEqual(requests, [{
    url: '/api/media-organizer/previews', body: { selection, batch_flow: true },
  }], 'selecting a directory must immediately submit a recursive preview');
  await waitForRenderedText(view, '逐目录整理预览');
  act(() => view.root.findByProps({ type: 'button', title: blockedUnit.unit }).props.onClick());
  await waitForRenderedText(view, '目标路径已存在');
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
  });
  await waitForRenderedText(view, '整理结果');
  await waitForRenderedText(view, '目标路径已存在');
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /EXECUTE_MEDIA_ORGANIZER|RECOVER_MEDIA_ORGANIZER|维护窗口/);
});

test('a directory shortcut prefills its exact path and only starts a job after clicking preview', async t => {
  const path = '/synthetic/照片 & 旅行 ';
  const requests: Array<{ url: string; method?: string; body?: BodyInit | null }> = [];
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    requests.push({ url, method: options.method, body: options.body });
    return Response.json(options.method === 'POST' ? { job_id: previewId } : { ...preview, selection: path });
  });
  function Location() {
    return <output>{useLocation().search}</output>;
  }
  const { view, dispose } = await openBatch('/batch?operation=media-organize&directory=' + encodeURIComponent(path),
    <><BatchPage /><Location /></>);
  t.after(dispose);
  assert.equal(view.root.findByProps({ 'aria-label': '目录路径' }).props.value, path);
  assert.equal(requests.length, 0);
  const button = view.root.findAllByType('button').find(item =>
    item.findAllByType('span').some(span => span.children.join('') === '预览'));
  assert.ok(button);
  await act(async () => { button.props.onClick(); await settle(); });
  assert.equal(requests.filter(item => item.method === 'POST').length, 1);
  assert.deepEqual(JSON.parse(String(requests[0].body)), { selection: path, batch_flow: true });
  const params = new URLSearchParams(view.root.findByType('output').children.join(''));
  assert.equal(params.get('preview'), previewId);
  assert.equal(params.has('directory'), false);
});

test('opening the batch result URL preserves the exact string job ID and loads the existing report', async t => {
  const requests: string[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    assert.equal(options.method, 'GET');
    requests.push(url);
    if (url.includes('/batches/')) return Response.json(report);
    return Response.json(preview);
  });
  const { view, dispose } = await openBatch(`/batch?operation=media_package-organize&batch=${batchId}&directory=%2Fother`);
  t.after(dispose);
  assert.ok(requests.some(url => url.startsWith(`/api/media-organizer/batches/${batchId}?`)));
  assert.equal(view.root.findByType(DirectoryPicker).props.value, selection);
  assert.match(JSON.stringify(view.toJSON()), /整理结果/);
  assert.match(JSON.stringify(view.toJSON()), /目标路径已存在/);
});

for (const [cleanup, message] of [
  ['pending', '报告明细已排队回收'],
  ['released', '报告文件已回收'],
  ['missing', '报告文件已不存在'],
] as const) {
  test(`an organizer batch with ${cleanup} report cleanup skips its linked preview`, async t => {
    const requests: string[] = [];
    let finishResult!: (response: Response) => void;
    t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
      assert.equal(options.method, 'GET');
      requests.push(url);
      if (url.includes('/batches/')) return new Promise<Response>(resolve => { finishResult = resolve; });
      return Response.json({ detail: '找不到此目录预览' }, { status: 404 });
    });
    const { view, dispose } = await openBatch(`/batch?operation=media-organize&preview=${previewId}&batch=${batchId}`);
    try {
      assert.equal(requests.some(url => url.includes('/previews/')), false, 'read the batch before fetching its preview');
      finishResult(Response.json({ ...report, report_cleanup_status: cleanup, items: [], filtered_total: 0,
        summary: { success_count: 2, skipped_count: 0, conflict_count: 0, failed_count: 0 } }));
      await waitForRenderedText(view, message);
      assert.equal(requests.some(url => url.includes('/previews/')), false);
      const visible = JSON.stringify(view.toJSON());
      assert.match(visible, /整理结果/);
      assert.doesNotMatch(visible, /找不到此目录预览/);
      const stats = view.root.findByProps({ className: 'nfc-v2-batch-media-stats' });
      assert.equal(stats.findAllByType('strong')[0].children.join(''), '2');
    } finally {
      await act(dispose);
    }
  });
}

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
    view.root.findByProps({ 'data-preview-filter': 'ready' }).props.onClick();
    await settle();
  });
  assert.ok(requests.some(url => url.includes('status_filter=ready')));
  const openMapping = view.root.findAllByType('button').find(button =>
    button.findAllByType('span').some(span => span.children.join('').includes('查看完整映射')));
  assert.ok(openMapping);
  await act(async () => { openMapping.props.onClick({ currentTarget: null }); await settle(); });
  assert.match(JSON.stringify(view.toJSON()), /first.jpg/);
  const nextPage = view.root.findAllByProps({ 'aria-label': '下一页' }).find(button => !button.props.disabled);
  assert.ok(nextPage);
  await act(async () => { nextPage.props.onClick(); await settle(); });
  assert.match(JSON.stringify(view.toJSON()), /last.jpg/);
  assert.ok(requests.some(url => url.endsWith('/mappings/preview-mapping?page=2&page_size=50')));
});

for (const width of [768, 1440]) {
  test(`organizer reports keep the mapping readable in the inspector at ${width}px`, async t => {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: { innerWidth: width, setTimeout, clearTimeout, addEventListener() {}, removeEventListener() {} },
    });
    let disposeView: (() => void) | undefined;
    t.after(async () => {
      await act(async () => { disposeView?.(); });
      Reflect.deleteProperty(globalThis, 'window');
    });

    const skippedUnit = {
      ...readyUnit, unit: selection + '/skipped', status: 'skipped',
      mapping_id: null, reason: '当前目录没有待整理文件',
    };
    const source = selection + '/ready/' + '相册'.repeat(40) + '.jpg';
    const target = selection + '/ready/001.jpg';
    t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
      assert.equal(options.method, 'GET');
      if (url.includes('/mappings/')) return Response.json({
        page: 1, page_size: 50, total_moves: 1, moves: [{ source, target, kind: 'P', bytes: 20 }],
      });
      if (url.includes('/batches/')) return Response.json({
        ...report,
        items: [...report.items, { unit: skippedUnit.unit, status: 'skipped', reason: '执行时跳过该目录' }],
      });
      return Response.json({ ...preview, units: [...preview.units, skippedUnit] });
    });

    let focusedMapping = false;
    const { view, dispose } = await openBatch(`/batch?operation=media-organize&preview=${previewId}&batch=${batchId}`,
      <BatchPage />, element => element.props['aria-label'] === '完整源 → 目标映射' ? {
        focus() { focusedMapping = true; },
      } : null);
    disposeView = dispose;
    await waitForRenderedText(view, '整理预览');
    await waitForRenderedText(view, '整理结果');
    const gallery = view.root.findByProps({ role: 'list', 'aria-label': '逐目录整理预览' });
    assert.equal(gallery.findAllByProps({ className: 'nfc-unit-card' }).length, 3);
    act(() => gallery.findByProps({ type: 'button', title: skippedUnit.unit }).props.onClick());
    await waitForRenderedText(view, '当前目录没有待整理文件');
    act(() => gallery.findByProps({ type: 'button', title: blockedUnit.unit }).props.onClick());
    await waitForRenderedText(view, '目标路径已存在');
    act(() => gallery.findByProps({ type: 'button', title: readyUnit.unit }).props.onClick());
    const openMapping = view.root.findAllByType('button').find(button =>
      button.findAllByType('span').some(span => span.children.join('').includes('查看完整映射')));
    assert.ok(openMapping);
    let returnedFocus = false;
    const opener = { focus() { returnedFocus = true; } };
    await act(async () => { openMapping.props.onClick({ currentTarget: opener }); });
    await waitForRenderedText(view, source);
    assert.equal(focusedMapping, true, 'opening the mapping must bring keyboard focus into the report');

    assert.deepEqual(view.root.findAllByType('caption').map(caption => caption.children.join('')), ['各整理单元结果']);
    const list = view.root.findByProps({ role: 'list', 'aria-label': '媒体文件位置调整明细' });
    assert.ok(list.findAllByType('li').length > 0);
    assert.ok(view.root.findAllByType('code').some(code => code.props.title === source));
    assert.ok(view.root.findAllByType('code').some(code => code.props.title === target));
    await waitForRenderedText(view, '目标路径已存在');
    await waitForRenderedText(view, '执行时跳过该目录');
    const closeMapping = view.root.findAllByType('button').find(button =>
      button.findAllByType('span').some(span => span.children.join('') === '关闭'));
    assert.ok(closeMapping);
    act(() => closeMapping.props.onClick());
    assert.equal(returnedFocus, true);
    assert.equal(view.root.findAllByProps({ 'aria-label': '列表分页' }).length, 2);
  });
}


test('a legacy execution URL opens directory selection without a historical execution request', async t => {
  const requests = t.mock.method(globalThis, 'fetch', async () => {
    throw new Error('unexpected request');
  });
  const { view, dispose } = await openBatch('/batch?operation=semantic-media-organize&execution=35');
  t.after(dispose);
  assert.match(JSON.stringify(view.toJSON()), /选择文件夹后自动扫描子目录/);
  assert.equal(requests.mock.callCount(), 0);
});

test('Luolcy loose files remain selected across pages and an existing package creates one draft', async t => {
  const author = '/synthetic/Luolcy/2611/261123/作者';
  const photo = `${author}/封面.jpg`;
  const video = `${author}/短片.mp4`;
  const looseId = 'a'.repeat(64);
  const planId = '9007199254740995';
  const endpoint = `/api/media-organizer/previews/${previewId}/loose-files/${looseId}`;
  const requests: Array<{ url: string; body: unknown }> = [];
  let finishAssignment!: (response: Response) => void;
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    const body = options.body ? JSON.parse(String(options.body)) : undefined;
    requests.push({ url, body });
    if (url === `${endpoint}/assignments`) {
      return new Promise<Response>(resolve => { finishAssignment = resolve; });
    }
    const query = new URLSearchParams(url.split('?')[1]);
    if (url.startsWith(`${endpoint}?`)) {
      const second = query.get('page') === '2';
      return Response.json({
        job_id: previewId, loose_id: looseId, author, page: second ? 2 : 1, page_size: 50,
        total_files: 51, packages: ['原有资源包'], read_only: true,
        files: second ? [{ source: video, kind: 'V', bytes: 100 }] : [
          { source: photo, kind: 'P', bytes: 20 },
          ...Array.from({ length: 49 }, (_, index) => ({
            source: `${author}/${index}.jpg`, kind: 'P', bytes: 1,
          })),
        ],
      });
    }
    return Response.json({
      ...preview, selection: author, filtered_total: 1,
      units: [{
        ...readyUnit, unit: author, status: 'needs_assignment', reason: '作者层散件待确认归属',
        totals: { P: 50, V: 1, Other: 0 }, needed_moves: 0, renamed_count: 0, total_files: 51,
        mapping_id: null, loose_id: looseId, total_proposals: 0, sample_moves: [], truncated: false,
      }],
      summary: {
        ...preview.summary, unit_count: 1, ready_count: 0, blocked_count: 0, file_count: 51,
        totals: { P: 50, V: 1, Other: 0 }, needed_moves: 0, renamed_count: 0,
        needs_assignment_count: 1,
      },
    });
  });
  const { view, dispose } = await openBatch(`/batch?operation=media-organize&preview=${previewId}`);
  t.after(dispose);
  assert.match(JSON.stringify(view.toJSON()), /待归属作者/);
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /确认整理全部/);
  await act(async () => {
    view.root.findByProps({ 'data-preview-filter': 'needs_assignment' }).props.onClick();
    await settle();
  });
  assert.ok(requests.some(({ url }) => url.includes('status_filter=needs_assignment')));
  const open = view.root.findAllByType('button').find(button =>
    button.findAllByType('span').some(span => span.children.join('').includes('查看散件')));
  assert.ok(open);
  await act(async () => { open.props.onClick({ currentTarget: null }); await settle(); });
  assert.ok(view.root.findByProps({ title: photo }));
  const checkboxEvent = { currentTarget: { checked: true, matches: () => false, closest: () => null } };
  act(() => view.root.findAllByType('input').find(input => input.props['aria-label'] === `选择 ${photo}`)!
    .props.onChange(checkboxEvent));
  const nextPage = view.root.findAllByProps({ 'aria-label': '下一页' }).find(button => !button.props.disabled);
  assert.ok(nextPage);
  await act(async () => { nextPage.props.onClick(); await settle(); });
  assert.ok(view.root.findByProps({ title: video }));
  act(() => {
    view.root.findAllByType('input').find(input => input.props['aria-label'] === `选择 ${video}`)!
      .props.onChange(checkboxEvent);
    view.root.findByProps({ id: 'media-organizer-existing-package' }).props.onChange({ target: { value: '原有资源包' } });
  });
  const submit = view.root.findByType('form');
  await act(async () => {
    submit.props.onSubmit({ preventDefault() {} });
    submit.props.onSubmit({ preventDefault() {} });
    await settle();
  });
  assert.deepEqual(requests.filter(request => request.body), [{
    url: `${endpoint}/assignments`, body: { sources: [photo, video], package_name: '原有资源包', new_package: false },
  }]);
  await act(async () => {
    finishAssignment(Response.json({ plan_id: planId, status: 'draft', expected_changes: 2 }));
    await settle();
  });
  assert.ok(view.root.findByType('a').props.href === `/plans/${planId}`);
  assert.match(JSON.stringify(view.toJSON()), /整理预览/);
});

test('a Luolcy author with no packages requires a valid new package name', async t => {
  const author = '/synthetic/Luolcy/2611/261123/独立作者';
  const file = `${author}/资料.txt`;
  const looseId = 'b'.repeat(64);
  const endpoint = `/api/media-organizer/previews/${previewId}/loose-files/${looseId}`;
  const drafts: unknown[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    if (options.method === 'POST') {
      assert.equal(url, `${endpoint}/assignments`);
      drafts.push(JSON.parse(String(options.body)));
      return Response.json({ plan_id: '51', status: 'draft', expected_changes: 1 });
    }
    if (url.startsWith(`${endpoint}?`)) {
      return Response.json({
        job_id: previewId, loose_id: looseId, author, page: 1, page_size: 50, total_files: 1,
        packages: [], read_only: true, files: [{ source: file, kind: 'Other', bytes: 8 }],
      });
    }
    return Response.json({
      ...preview, selection: author, filtered_total: 1,
      units: [{
        ...readyUnit, unit: author, status: 'needs_assignment', reason: '作者层散件待确认归属',
        totals: { P: 0, V: 0, Other: 1 }, needed_moves: 0, renamed_count: 0,
        mapping_id: null, loose_id: looseId, total_proposals: 0, sample_moves: [], truncated: false,
      }],
      summary: {
        ...preview.summary, unit_count: 1, ready_count: 0, blocked_count: 0, file_count: 1,
        totals: { P: 0, V: 0, Other: 1 }, needed_moves: 0, renamed_count: 0, needs_assignment_count: 1,
      },
    });
  });
  const { view, dispose } = await openBatch(`/batch?operation=media-organize&preview=${previewId}`);
  t.after(dispose);
  const open = view.root.findAllByType('button').find(button =>
    button.findAllByType('span').some(span => span.children.join('').includes('查看散件')));
  assert.ok(open);
  await act(async () => { open.props.onClick({ currentTarget: null }); await settle(); });
  assert.equal(view.root.findAllByProps({ id: 'media-organizer-existing-package' }).length, 0);
  const input = view.root.findByProps({ id: 'media-organizer-new-package' });
  act(() => {
    view.root.findAllByType('input').find(checkbox => checkbox.props['aria-label'] === `选择 ${file}`)!
      .props.onChange({ currentTarget: { checked: true, matches: () => false, closest: () => null } });
    input.props.onChange({ target: { value: '../同日其他作者' } });
  });
  const submit = view.root.findByType('form');
  act(() => { void submit.props.onSubmit({ preventDefault() {} }); });
  assert.deepEqual(drafts, []);
  assert.match(JSON.stringify(view.toJSON()), /请输入合法的资源包目录名/);

  act(() => input.props.onChange({ target: { value: '新建资源包' } }));
  await act(async () => { submit.props.onSubmit({ preventDefault() {} }); await settle(); });
  assert.deepEqual(drafts, [{ sources: [file], package_name: '新建资源包', new_package: true }]);
  assert.equal(view.root.findByType('a').props.href, '/plans/51');
});

test('a large assignment plan ID stays exact through detail, freeze, validate and confirmed execute', async t => {
  const planId = '9007199254740993';
  const endpoint = `/api/plans/${planId}`;
  const reads: string[] = [];
  const writes: string[] = [];
  let status = 'draft';
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: { innerWidth: 1280, setTimeout, clearTimeout, addEventListener() {}, removeEventListener() {} },
  });
  let disposeRoute: (() => void) | undefined;
  t.after(async () => {
    await act(async () => { disposeRoute?.(); });
    Reflect.deleteProperty(globalThis, 'window');
  });
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    if (options.method === 'POST') {
      writes.push(url);
      if (url === `${endpoint}/freeze`) status = 'frozen';
      if (url === `${endpoint}/validate`) status = 'ready';
      if (url === `${endpoint}/execute`) status = 'executing';
      return Response.json({ status, work_job_id: 21 });
    }
    reads.push(url);
    if (url === '/api/settings') return Response.json({ allow_mutation: true });
    if (url.startsWith(`${endpoint}/operation-journal?`)) {
      return Response.json({ items: [], total: 0, page: 1, page_size: 1 });
    }
    assert.equal(url, `${endpoint}?page=1&page_size=50`);
    const payload = {
      id: 0, name: '散件归属计划', kind: 'luolcy-author-assignment', status,
      expected_changes: 1, expected_reclaim_bytes: 0, created_at: '2026-11-23T03:00:00Z', items: [],
    };
    // Legacy responses serialize the ID as a JSON number, which is rounded by the JS parser.
    return new Response(JSON.stringify(payload).replace('"id":0', `"id":${planId}`));
  });
  const { view, dispose } = await openBatch(`/plans/${planId}`, <Routes>
    <Route path="/plans/:id" element={<PlanDetailPage />} />
  </Routes>);
  disposeRoute = dispose;
  assert.ok(reads.includes(`${endpoint}?page=1&page_size=50`));
  assert.ok(reads.includes(`${endpoint}/operation-journal?page=1&page_size=1`));
  assert.match(JSON.stringify(view.toJSON()), /9007199254740993/);

  for (const label of ['冻结计划 (Freeze)', 'SHA256 实时校验 (Validate)', '执行计划 (Execute)']) {
    const action = view.root.findAllByType('button').find(button =>
      button.findAllByType('span').some(span => span.children.join('') === label));
    assert.ok(action && !action.props.disabled, label);
    await act(async () => { action.props.onClick(); await settle(); });
  }
  const confirmation = view.root.findAllByType(ConsoleConfirmDialog).find(dialog => dialog.props.open);
  assert.ok(confirmation && !confirmation.props.disabled);
  const identityLine = confirmation.props.description.props.children[0];
  assert.match(React.Children.toArray(identityLine.props.children).join(''), /9007199254740993/);
  await act(async () => { confirmation.props.onConfirm(); await settle(); });
  assert.deepEqual(writes, [`${endpoint}/freeze`, `${endpoint}/validate`, `${endpoint}/execute`]);
});
