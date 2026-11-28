import test, { type TestContext } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import TestRenderer, { act, type ReactTestRenderer } from 'react-test-renderer';

import { tasksApi } from '../src/api/tasks';
import { authApi } from '../src/api/auth';
import { TaskLogTable } from '../src/components/tasks/TaskLogTable';
import { CodePath } from '../src/components/ui/CodePath';
import { ConsolePagination } from '../src/components/ui/ConsolePagination';
import { ConsoleToastProvider } from '../src/components/ui/ConsoleToast';
import { AuthProvider } from '../src/contexts/AuthContext';
import { TasksPage } from '../src/pages/Tasks';
import type { TaskEvent, TaskItem } from '../src/types/task';

test('clipped paths disclose in place, exact copying confirms, and short paths stay selectable text', async t => {
  const sizes = { scrollWidth: 80, clientWidth: 80, scrollHeight: 20, clientHeight: 20 };
  const copied: string[] = [];
  const previousNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  const previousObserver = Object.getOwnPropertyDescriptor(globalThis, 'ResizeObserver');
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true, value: { clipboard: { writeText: async (text: string) => { copied.push(text); } } },
  });
  let measure = () => {};
  class Observer {
    constructor(callback: () => void) { measure = callback; }
    observe() {}
    disconnect() {}
  }
  Object.defineProperty(globalThis, 'ResizeObserver', { configurable: true, value: Observer });
  let view!: ReactTestRenderer;
  t.after(() => {
    act(() => view.unmount());
    if (previousNavigator) Object.defineProperty(globalThis, 'navigator', previousNavigator);
    else Reflect.deleteProperty(globalThis, 'navigator');
    if (previousObserver) Object.defineProperty(globalThis, 'ResizeObserver', previousObserver);
    else Reflect.deleteProperty(globalThis, 'ResizeObserver');
  });
  act(() => {
    view = TestRenderer.create(<CodePath value="/data/a" />, { createNodeMock: item => item.type === 'code' ? sizes : null });
  });
  assert.equal(view.root.findAllByProps({ 'aria-label': '展开完整路径' }).length, 0);
  const value = '/data/ 目录 & 原图 /' + '照片文件'.repeat(12) + '.JPEG';
  act(() => { sizes.scrollWidth = 410; view.update(<CodePath value={value} />); });
  const opener = view.root.findByProps({ 'aria-label': '展开完整路径' });
  assert.equal(opener.props['aria-controls'], view.root.findByType('code').props.id);
  act(() => opener.props.onClick());
  assert.equal(view.root.findByProps({ 'aria-label': '收起完整路径' }).props['aria-expanded'], true);
  assert.equal(view.root.findByType('code').children.join(''), value);
  await act(async () => { view.root.findByProps({ 'aria-label': '复制完整路径' }).props.onClick(); });
  assert.deepEqual(copied, [value]);
  assert.equal(view.root.findByProps({ role: 'status' }).children.join(''), '已复制');
  assert.equal(view.root.findByProps({ 'aria-label': '复制完整路径' }).props['data-copied'], true);
  act(() => view.root.findByProps({ 'aria-label': '收起完整路径' }).props.onClick());
  act(() => { sizes.clientWidth = 500; measure(); });
  assert.equal(view.root.findAllByProps({ 'aria-label': '展开完整路径' }).length, 0);
  act(() => view.update(<CodePath value={null} />));
  assert.equal(view.root.findAllByType('button').length, 0);
});

test('pagination validates jumps on Enter within forms and synchronizes size and shrinking totals', t => {
  const calls: Array<[number, number]> = [];
  const onChange = (next: number, size: number) => { calls.push([next, size]); };
  let view!: ReactTestRenderer;
  const render = (page: number, pageSize: number, total: number) => (
    <ConsolePagination page={page} pageSize={pageSize} total={total} onChange={onChange} />
  );
  act(() => { view = TestRenderer.create(render(1, 20, 247)); });
  t.after(() => { act(() => view.unmount()); });
  const input = () => view.root.findByProps({ 'aria-label': '跳转页码' });
  const type = (text: string) => act(() => input().props.onChange({ target: { value: text } }));
  for (const invalid of ['0', '14', '2.5', '1e1', '']) {
    type(invalid);
    let prevented = false;
    let stopped = false;
    act(() => input().props.onKeyDown({ key: 'Enter', nativeEvent: { isComposing: false },
      preventDefault() { prevented = true; }, stopPropagation() { stopped = true; } }));
    assert.ok(prevented && stopped, 'Enter must not submit a containing operation form');
    assert.equal(input().props['aria-invalid'], true);
    assert.equal(input().props['aria-describedby'], view.root.findByProps({ role: 'alert' }).props.id);
    assert.equal(calls.length, 0);
  }
  type('9');
  act(() => view.root.findByProps({ 'aria-label': '转到输入页码' }).props.onClick());
  assert.deepEqual(calls, [[9, 20]]);
  act(() => view.update(render(9, 20, 247)));
  assert.equal(input().props.value, '9');
  type('12');
  act(() => view.root.findByProps({ 'aria-label': '每页记录数' }).props.onChange({ target: { value: '50' } }));
  assert.deepEqual(calls.at(-1), [1, 50]);
  act(() => view.update(render(1, 50, 247)));
  assert.equal(input().props.value, '1');
  assert.equal(input().props['aria-invalid'], undefined);
  act(() => view.update(render(5, 50, 0)));
  assert.deepEqual(calls, [[9, 20], [1, 50]], 'loading totals must not initiate a page change');
  act(() => view.update(render(5, 50, 76)));
  assert.deepEqual(calls.at(-1), [2, 50]);
  act(() => view.update(render(2, 50, 76)));
  assert.equal(input().props.value, '2');
  assert.equal(view.root.findByProps({ 'aria-label': '下一页' }).props.disabled, true);
});

/** Mount the real reading components with a fresh query cache and desktop layout. */
async function mountTaskReader(t: TestContext, content: React.ReactNode) {
  const previousDocument = Object.getOwnPropertyDescriptor(globalThis, 'document');
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  Object.defineProperty(globalThis, 'document', { configurable: true, value: Object.assign(new EventTarget(), { title: '' }) });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: Object.assign(new EventTarget(), { innerWidth: 1440 }) });
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = (children: React.ReactNode) => <MemoryRouter initialEntries={['/tasks']}>
    <QueryClientProvider client={query}><ConsoleToastProvider>{children}</ConsoleToastProvider></QueryClientProvider>
  </MemoryRouter>;
  const view = TestRenderer.create(wrapper(content));
  t.after(() => {
    act(() => view.unmount());
    query.clear();
    if (previousDocument) Object.defineProperty(globalThis, 'document', previousDocument);
    else Reflect.deleteProperty(globalThis, 'document');
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow);
    else Reflect.deleteProperty(globalThis, 'window');
  });
  await settleTaskPage();
  return { view, update: (children: React.ReactNode) => act(() => view.update(wrapper(children))) };
}

/** Let React Query deliver batched notifications before observing the rendered controls. */
async function settleTaskPage() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 15)); });
}

/** Release delayed responses during the test or during teardown after an assertion fails. */
function pauseTaskResponse(t: TestContext) {
  let release!: () => void;
  const wait = new Promise<void>(resolve => { release = resolve; });
  t.after(release);
  return { wait, release };
}

const taskItem: TaskItem = {
  id: '90071992547409931', job_type: 'media-analysis', status: 'completed',
  capabilities: { supports_pause: false, supports_resume: false, supports_cancel: false, supports_retry: false },
  progress: { current: 1, total: 1, message: null, percent: 100 },
  created_at: null, started_at: null, finished_at: null, heartbeat_at: null,
  error: null, error_code: null, retry_of: null,
};
const taskLog: TaskEvent = {
  id: 1, timestamp: '2026-11-26T14:00:00Z', level: 'info', event_type: 'sample',
  message: '第一页日志', context: { count: 3 },
};

test('task paging preserves the paginator without leaving the preceding page actionable', async t => {
  const secondPage = pauseTaskResponse(t);
  const filteredPage = pauseTaskResponse(t);
  const nextId = '90071992547409932';
  t.mock.method(tasksApi, 'getWorkerStatus', async () => ({ status: 'offline' }));
  t.mock.method(tasksApi, 'listTasks', async ({ page = 1, pageSize = 50, status }) => {
    if (page === 2) await secondPage.wait;
    if (status === 'failed') await filteredPage.wait;
    const items = status === 'failed' ? [] : [page === 1 ? taskItem : { ...taskItem, id: nextId }];
    return { items, page, page_size: pageSize, total: status === 'failed' ? 0 : 210 };
  });
  const { view } = await mountTaskReader(t, <TasksPage />);
  const paginator = view.root.findByProps({ 'aria-label': '列表分页' });
  const deleteButtons = (id: string) => view.root.findAllByProps({ 'aria-label': '删除任务 #' + id });
  assert.ok(deleteButtons(String(taskItem.id)).length > 0);

  act(() => paginator.findByProps({ 'aria-label': '下一页' }).props.onClick());
  await settleTaskPage();
  assert.equal(view.root.findByProps({ 'aria-label': '列表分页' }), paginator);
  assert.equal(paginator.findByProps({ 'aria-label': '跳转页码' }).props.value, '2');
  assert.equal(deleteButtons(String(taskItem.id)).length, 0);
  assert.match(JSON.stringify(view.toJSON()), /正在加载任务列表/);

  secondPage.release();
  await settleTaskPage();
  assert.equal(view.root.findByProps({ 'aria-label': '列表分页' }), paginator);
  assert.ok(deleteButtons(nextId).length > 0);

  act(() => view.root.findByProps({ 'aria-label': '状态' }).props.onChange({ currentTarget: { value: 'failed' } }));
  await settleTaskPage();
  assert.equal(view.root.findAllByProps({ 'aria-label': '列表分页' }).length, 0);
  assert.equal(deleteButtons(nextId).length, 0);
});

test('the task toolbar searches visible names and exact IDs on the current page', async t => {
  const indexed = { ...taskItem, id: '90071992547409932', job_type: 'index-root' };
  t.mock.method(tasksApi, 'getWorkerStatus', async () => ({ status: 'online' }));
  t.mock.method(tasksApi, 'listTasks', async () => ({ items: [taskItem, indexed], total: 120, page: 1, page_size: 50 }));
  const { view } = await mountTaskReader(t, <TasksPage />);
  const search = view.root.findByProps({ 'aria-label': '搜索当前页任务' });
  assert.equal(search.props.placeholder, '搜索任务');
  assert.equal(view.root.findByProps({ className: 'nfc-page-header' }).findAllByType('button').length, 1,
    'only Refresh is in the title bar');
  act(() => search.props.onChange({ currentTarget: { value: '文件索引' } }));
  assert.equal(view.root.findAllByProps({ 'data-task-row': String(taskItem.id) }).length, 0);
  assert.equal(view.root.findAllByProps({ 'data-task-row': indexed.id }).length, 1);
  act(() => search.props.onChange({ currentTarget: { value: '#' + taskItem.id } }));
  assert.equal(view.root.findAllByProps({ 'data-task-row': String(taskItem.id) }).length, 1);
  assert.equal(view.root.findAllByProps({ 'data-task-row': indexed.id }).length, 0);
  assert.ok(view.root.findByProps({ 'aria-label': '列表分页' }));
});

test('task-row pause keeps feedback local, retries a failed request and waits for the Worker', async t => {
  const failed = pauseTaskResponse(t);
  const accepted = pauseTaskResponse(t);
  const actionId = '90071992547409933';
  const other = { ...taskItem, id: '90071992547409934' };
  let current: TaskItem = { ...taskItem, id: actionId, status: 'running',
    capabilities: { ...taskItem.capabilities, supports_pause: true, supports_resume: true } };
  const calls: Array<string | number> = [];
  t.mock.method(tasksApi, 'getWorkerStatus', async () => ({ status: 'online' }));
  t.mock.method(tasksApi, 'listTasks', async () => ({ items: [current, other], total: 2, page: 1, page_size: 50 }));
  t.mock.method(tasksApi, 'pauseTask', async (id: string | number) => {
    calls.push(id);
    if (calls.length === 1) {
      await failed.wait;
      throw { status: 0, message: '暂停请求超时' };
    }
    await accepted.wait;
    current = Object.assign({ ...current }, { pause_requested: true });
    return current;
  });
  const { view } = await mountTaskReader(t, <TasksPage />);
  const firstRow = () => view.root.findByProps({ 'data-task-row': actionId });
  const command = () => firstRow().findAllByType('button').find(node => node.props['data-task-inline-action'] === 'pause')!;
  const trigger = command();
  await act(async () => { trigger.props.onClick(); trigger.props.onClick(); });
  assert.deepEqual(calls, [actionId]);
  assert.match(JSON.stringify(view.toJSON()), /正在请求暂停/);
  assert.equal(command().props['aria-busy'], true);

  failed.release();
  await settleTaskPage();
  assert.equal(view.root.findByProps({ 'data-task-feedback': actionId }).findByProps({ role: 'alert' }).children.join(''),
    '暂停请求超时');
  assert.equal(view.root.findAllByProps({ 'data-task-feedback': other.id }).length, 0);
  act(() => view.root.findAllByType('button').find(node => node.props['data-task-inline-retry'] === actionId)!.props.onClick());
  accepted.release();
  await settleTaskPage();
  assert.deepEqual(calls, [actionId, actionId]);
  assert.match(JSON.stringify(view.toJSON()), /等待 Worker 暂停/);
  assert.doesNotMatch(JSON.stringify(view.toJSON()), /暂停请求超时/);
});

test('completed organizer rows link to the exact conflicts report from its counts', async t => {
  const task = { ...taskItem, job_type: 'media-organizer-batch', organizer_result: {
    success_count: 38, conflict_count: 2, skipped_count: 0, failed_count: 0, conflicts_available: true,
  } };
  t.mock.method(tasksApi, 'getWorkerStatus', async () => ({ status: 'online' }));
  t.mock.method(tasksApi, 'listTasks', async () => ({ items: [task], total: 1, page: 1, page_size: 50 }));
  t.mock.method(authApi, 'getMe', async () => ({ id: 1, username: 'demo-admin', role: 'admin' }));
  const { view } = await mountTaskReader(t, <AuthProvider><TasksPage /></AuthProvider>);
  const receipt = view.root.findByProps({ 'data-task-feedback': String(task.id) });
  assert.ok(receipt.findByProps({ role: 'status' }));
  assert.match(JSON.stringify(view.toJSON()), /38/);
  assert.equal(receipt.findByType('a').props.href, '/batch?operation=media-organize&batch=' + task.id + '&result=conflict');
});

test('event log paging keeps navigation and drops placeholder data across filters or tasks', async t => {
  const secondPage = pauseTaskResponse(t);
  const otherQuery = pauseTaskResponse(t);
  const taskId = String(taskItem.id);
  const nextId = '90071992547409932';
  t.mock.method(tasksApi, 'getTaskLogs', async (id, { page = 1, pageSize = 50, level }) => {
    if (id !== taskId || level === 'error') await otherQuery.wait;
    if (page === 2) await secondPage.wait;
    const items = page === 1 ? [taskLog] : [{ ...taskLog, id: 2, message: '第二页日志' }];
    return { items, page, page_size: pageSize, total: 150 };
  });
  const { view, update } = await mountTaskReader(t, <TaskLogTable taskId={taskId} />);
  const paginator = view.root.findByProps({ 'aria-label': '列表分页' });
  const content = () => JSON.stringify(view.toJSON());

  act(() => paginator.findByProps({ 'aria-label': '下一页' }).props.onClick());
  await settleTaskPage();
  assert.equal(view.root.findByProps({ 'aria-label': '列表分页' }), paginator);
  assert.equal(paginator.findByProps({ 'aria-label': '跳转页码' }).props.value, '2');
  assert.match(content(), /正在加载事件日志/);
  assert.doesNotMatch(content(), /第一页日志/);

  secondPage.release();
  await settleTaskPage();
  assert.equal(view.root.findByProps({ 'aria-label': '列表分页' }), paginator);
  assert.match(content(), /第二页日志/);

  update(<TaskLogTable taskId={nextId} />);
  await settleTaskPage();
  assert.equal(view.root.findAllByProps({ 'aria-label': '列表分页' }).length, 0);
  assert.doesNotMatch(content(), /第二页日志/);
  update(<TaskLogTable taskId={taskId} />);
  await settleTaskPage();
  assert.match(content(), /第二页日志/);

  act(() => view.root.findByProps({ 'aria-label': '级别' }).props.onChange({ currentTarget: { value: 'error' } }));
  await settleTaskPage();
  assert.equal(view.root.findAllByProps({ 'aria-label': '列表分页' }).length, 0);
  assert.doesNotMatch(content(), /第二页日志/);
});

test('event context disclosure only references a mounted target', async t => {
  t.mock.method(tasksApi, 'getTaskLogs', async () => ({ items: [taskLog], page: 1, page_size: 50, total: 1 }));
  const { view } = await mountTaskReader(t, <TaskLogTable taskId={taskItem.id} />);
  const trigger = view.root.findByProps({ className: 'nfc-v2-log-expand' });
  assert.equal(trigger.props['aria-controls'], undefined);
  act(() => trigger.props.onClick());
  assert.equal(trigger.props['aria-expanded'], true);
  assert.ok(view.root.findByProps({ id: trigger.props['aria-controls'] }).findByType('pre'));
  act(() => trigger.props.onClick());
  assert.equal(trigger.props['aria-controls'], undefined);
});
