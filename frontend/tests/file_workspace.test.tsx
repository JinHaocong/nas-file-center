import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import TestRenderer, { act, type ReactTestRenderer } from 'react-test-renderer';

import { filesystemApi } from '../src/api/filesystem';
import { DashboardPage } from '../src/pages/Dashboard';

const root = '/development/library';
const album = root + '/照片 & 旅行 ';

/** Flush the filesystem query notifications without timers surviving the test. */
async function settle() {
  await new Promise(resolve => setTimeout(resolve, 15));
}

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
  await act(async () => { entry().props.onClick(); await settle(); });
  assert.equal(params().get('selected'), album);
  assert.equal(params().get('directory'), null);

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
