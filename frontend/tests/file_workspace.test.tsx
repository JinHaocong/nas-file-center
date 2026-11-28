import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Link, MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import TestRenderer, { act, type ReactTestRenderer } from 'react-test-renderer';

import { filesystemApi } from '../src/api/filesystem';
import { MediaThumbnail } from '../src/components/ui/MediaThumbnail';
import { DashboardPage } from '../src/pages/Dashboard';
import { WorkspaceEntries } from '../src/pages/Dashboard/WorkspaceEntries';

const root = '/development/library';
const album = root + '/照片 & 旅行 ';

/** Flush the filesystem query notifications without timers surviving the test. */
async function settle() {
  await new Promise(resolve => setTimeout(resolve, 15));
}

test('keyboard browsing follows the rendered rows and only opens quick look for eligible files', () => {
  const folder = { path: album, name: '照片', type: 'directory' as const };
  const photo = { path: root + '/DSC_0431.JPG', name: 'DSC_0431.JPG', type: 'file' as const };
  const document = { path: root + '/说明.txt', name: '说明.txt', type: 'file' as const };
  const focused: string[] = [];
  const selected: string[] = [];
  const opened: string[] = [];
  const nodes = [folder, photo, document].map(entry => ({ dataset: { workspaceEntry: entry.path }, disabled: false,
    focus: () => focused.push(entry.path), scrollIntoView() {}, closest: () => ({ querySelectorAll: () => nodes }) }));
  const view = TestRenderer.create(<WorkspaceEntries entries={[photo, folder, document]} list pending={false}
    selectedPath={photo.path} selectedRef={React.createRef()} openOnClick={false} quickLookEnabled
    onOpen={() => {}} onInspect={() => {}} onSelect={entry => selected.push(entry.path)}
    onQuickLook={entry => opened.push(entry.path)} />);
  const key = (row: typeof photo | typeof folder, value: string, index: number) =>
    view.root.findByProps({ title: row.path, type: 'button' }).props.onKeyDown({
      key: value, preventDefault() {}, currentTarget: nodes[index],
    });
  key(photo, 'ArrowUp', 1);
  key(folder, 'ArrowDown', 0);
  key(photo, ' ', 1);
  key(document, ' ', 2);
  assert.deepEqual(selected, [folder.path, photo.path]);
  assert.deepEqual(focused, selected);
  assert.deepEqual(opened, [photo.path]);
  view.unmount();
});

test('file workspace opens directories deliberately and Back restores the parent selection', async t => {
  t.mock.method(filesystemApi, 'listDirectory', async (path?: string) => ({
    path: path ?? root, parent: path === album ? root : null,
    items: path === album ? [{ name: '封面.jpg', path: album + '/封面.jpg', type: 'file' as const }]
      : [{ name: '照片 & 旅行 ', path: album, type: 'directory' as const }],
    page: 1, page_size: 50, total: 1, has_more: false, allowed_roots: [root],
  }));
  t.mock.method(filesystemApi, 'listFavorites', async () => ({ items: [] }));
  t.mock.method(filesystemApi, 'listRecent', async () => ({ items: [] }));
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { title: '' } });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: Object.assign(new EventTarget(), { innerWidth: 1440 }) });
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function History() {
    const location = useLocation();
    const navigate = useNavigate();
    return <><output>{location.search}</output><button onClick={() => navigate(-1)}>返回</button></>;
  }
  let view!: ReactTestRenderer;
  t.after(() => {
    act(() => view.unmount());
    query.clear();
    Reflect.deleteProperty(globalThis, 'document');
    Reflect.deleteProperty(globalThis, 'window');
  });
  await act(async () => {
    view = TestRenderer.create(<MemoryRouter initialEntries={['/dashboard']}>
      <QueryClientProvider client={query}><DashboardPage /><History /></QueryClientProvider>
    </MemoryRouter>);
    await settle();
  });
  await act(settle);

  const params = () => new URLSearchParams(view.root.findByType('output').children.join(''));
  const entry = () => view.root.findByProps({ title: album, type: 'button' });
  const workspaceWindow = view.root.findByProps({ className: 'nfc-file-workspace-window' });
  assert.equal(workspaceWindow.findByProps({ 'aria-label': '文件空间工具' }).type, 'div');
  assert.equal(workspaceWindow.findByProps({ 'aria-label': '文件列表' }).type, 'div');
  assert.equal(view.root.findByType('h1').children.join(''), '文件空间');
  assert.equal(view.root.findByProps({ 'aria-label': '列表视图', type: 'button' }).props['aria-pressed'], true);
  await act(async () => { view.root.findByProps({ 'aria-label': '网格视图', type: 'button' }).props.onClick(); });
  assert.equal(view.root.findByProps({ 'aria-label': '网格视图', type: 'button' }).props['aria-pressed'], true);
  await act(async () => { entry().props.onClick(); await settle(); });
  assert.equal(params().get('selected'), album);
  assert.equal(params().get('directory'), null);
  const inspector = view.root.findByProps({ 'aria-label': '目录详情', className: 'nfc-file-workspace-inspector' });
  assert.deepEqual(inspector.findByType(MediaThumbnail).props, { path: album, kind: 'directory', size: 'cover' });

  await act(async () => { entry().props.onDoubleClick(); await settle(); });
  assert.equal(params().get('directory'), album);
  assert.ok(JSON.stringify(view.toJSON()).includes('封面.jpg'));

  const back = view.root.findAllByType('button').find(button => button.children.join('') === '返回');
  assert.ok(back);
  await act(async () => { back.props.onClick(); await settle(); });
  assert.equal(params().get('selected'), album);
  assert.equal(entry().props['aria-pressed'], true);
});

test('reading another page keeps pagination mounted without enabling old entries', async t => {
  let resolveNext!: () => void;
  const nextPage = new Promise<void>(resolve => { resolveNext = resolve; });
  t.mock.method(filesystemApi, 'listDirectory', async (_path: string | undefined, _directoriesOnly: boolean, page: number) => {
    if (page === 2) await nextPage;
    const name = page === 2 ? '第二页.jpg' : '第一页.jpg';
    return { path: root, parent: null, items: [{ name, path: root + '/' + name, type: 'file' as const }],
      page, page_size: 50, total: 120, has_more: true, allowed_roots: [root] };
  });
  t.mock.method(filesystemApi, 'listFavorites', async () => ({ items: [] }));
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { title: '' } });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: Object.assign(new EventTarget(), { innerWidth: 1440 }) });
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let view!: ReactTestRenderer;
  t.after(() => {
    resolveNext();
    act(() => view.unmount());
    query.clear();
    Reflect.deleteProperty(globalThis, 'document');
    Reflect.deleteProperty(globalThis, 'window');
  });
  await act(async () => {
    view = TestRenderer.create(<MemoryRouter initialEntries={['/dashboard']}>
      <QueryClientProvider client={query}><DashboardPage /></QueryClientProvider>
    </MemoryRouter>);
    await settle();
  });
  await act(settle);
  const paginator = view.root.findByProps({ 'aria-label': '列表分页' });
  await act(async () => { paginator.findByProps({ 'aria-label': '下一页' }).props.onClick(); await settle(); });
  assert.equal(view.root.findByProps({ 'aria-label': '列表分页' }), paginator);
  assert.equal(view.root.findByProps({ title: root + '/第一页.jpg', type: 'button' }).props.disabled, true);
  await act(async () => { resolveNext(); await settle(); });
  assert.equal(view.root.findByProps({ 'aria-label': '列表分页' }), paginator);
  assert.equal(view.root.findByProps({ title: root + '/第二页.jpg', type: 'button' }).props.disabled, false);
});

test('returning from organizer restores the exact file workspace and its independent list position', async t => {
  const origin = '/dashboard?' + new URLSearchParams({ directory: root, search: '照片', selected: album });
  t.mock.method(filesystemApi, 'listDirectory', async () => ({
    path: root, parent: null, items: [{ name: '照片 & 旅行 ', path: album, type: 'directory' as const }],
    page: 1, page_size: 50, total: 1, has_more: false, allowed_roots: [root],
  }));
  t.mock.method(filesystemApi, 'listFavorites', async () => ({ items: [] }));
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { title: '' } });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: Object.assign(new EventTarget(), { innerWidth: 1440 }) });
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let scroller: { scrollTop: number };
  let view!: ReactTestRenderer;
  function Organizer() {
    const location = useLocation();
    const navigate = useNavigate();
    return <button onClick={() => navigate(location.state.fileWorkspaceReturn, { state: { restoreFileWorkspace: true } })}>回到原位</button>;
  }
  t.after(() => {
    act(() => view.unmount());
    query.clear();
    Reflect.deleteProperty(globalThis, 'document');
    Reflect.deleteProperty(globalThis, 'window');
  });
  await act(async () => {
    view = TestRenderer.create(<MemoryRouter initialEntries={[origin]}>
      <QueryClientProvider client={query}><Routes>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/batch" element={<Organizer />} />
      </Routes></QueryClientProvider>
    </MemoryRouter>, {
      createNodeMock: element => element.props.className === 'nfc-file-workspace-list-scroll'
        ? (scroller = { scrollTop: 0 }) : null,
    });
    await settle();
  });
  await act(settle);

  const launch = view.root.findAllByType(Link).find(link => link.props.className === 'nfc-file-workspace-action');
  assert.deepEqual(launch?.props.state, { fileWorkspaceReturn: origin });
  scroller!.scrollTop = 220;
  const anchor = launch!.findByType('a');
  await act(async () => {
    anchor.props.onClick({ button: 0, preventDefault() {} });
    await settle();
  });
  const resume = view.root.findAllByType('button').find(button => button.children.join('') === '回到原位');
  assert.ok(resume);
  await act(async () => { resume.props.onClick(); await settle(); });
  assert.equal(view.root.findByProps({ title: album, type: 'button' }).props['aria-pressed'], true);
  assert.equal(view.root.findByProps({ 'aria-label': '搜索当前目录' }).props.value, '照片');
  assert.equal(scroller!.scrollTop, 220);
});

test('the folder inspector uses the selected directory overview and skips unbounded root summaries', async t => {
  const paths: string[] = [];
  t.mock.method(filesystemApi, 'listDirectory', async () => ({
    path: root, parent: null, items: [{ name: '照片 & 旅行 ', path: album, type: 'directory' as const }],
    page: 1, page_size: 50, total: 1, has_more: false, allowed_roots: [root],
  }));
  t.mock.method(filesystemApi, 'listFavorites', async () => ({ items: [] }));
  t.mock.method(filesystemApi, 'directoryOverview', async (path: string) => {
    paths.push(path);
    return { overview: { images: 268, videos: 2, files: 272, total_bytes: 3072 } };
  });
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { title: '' } });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: Object.assign(new EventTarget(), { innerWidth: 1440 }) });
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let view!: ReactTestRenderer;
  t.after(() => {
    act(() => view.unmount());
    query.clear();
    Reflect.deleteProperty(globalThis, 'document');
    Reflect.deleteProperty(globalThis, 'window');
  });
  await act(async () => {
    view = TestRenderer.create(<MemoryRouter initialEntries={['/dashboard']}>
      <QueryClientProvider client={query}><DashboardPage /></QueryClientProvider>
    </MemoryRouter>);
    await settle();
  });
  await act(settle);
  assert.deepEqual(paths, []);
  await act(async () => { view.root.findByProps({ title: album, type: 'button' }).props.onClick(); await settle(); });
  await act(settle);
  assert.deepEqual(paths, [album]);
  const inspector = view.root.findByProps({ className: 'nfc-file-workspace-inspector' });
  assert.ok(inspector.findAllByType('dd').some(node => node.children.join('') === '268 张图 · 2 段视频'));
  assert.ok(inspector.findAllByType('dd').some(node => node.children.join('') === '3.00 KB'));
});
