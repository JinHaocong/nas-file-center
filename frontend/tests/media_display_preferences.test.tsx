import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import TestRenderer, { act, type ReactTestRenderer } from 'react-test-renderer';

import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { authApi } from '../src/api/auth';
import { filesystemApi } from '../src/api/filesystem';
import { AuthProvider, useAuth } from '../src/contexts/AuthContext';
import { ConsoleToastProvider } from '../src/components/ui/ConsoleToast';
import { DirectoryShelf } from '../src/pages/Dashboard/DirectoryShelf';
import type { RecentPath } from '../src/types';

import { MediaThumbnail, ThumbnailSwitch } from '../src/components/ui/MediaThumbnail';
import { DisplayPreferencesProvider } from '../src/contexts/DisplayPreferencesContext';

const storageKey = 'nfc_show_media_thumbnails';

/** Exercise the provider and thumbnail consumers using a controllable visible viewport. */
test('one preference governs every view, cancels in-flight work, persists and follows other tabs', async t => {
  let stored: string | null = 'off';
  const storage = {
    getItem: () => stored,
    setItem: (_key: string, value: string) => { stored = value; },
  };
  const fakeWindow = Object.assign(new EventTarget(), { localStorage: storage });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: fakeWindow });
  const observations = new Set<(visible: boolean) => void>();
  class Visibility {
    readonly notify: (visible: boolean) => void;
    constructor(callback: (items: Array<{ isIntersecting: boolean }>) => void) {
      this.notify = visible => callback([{ isIntersecting: visible }]);
    }
    observe() { observations.add(this.notify); }
    disconnect() { observations.delete(this.notify); }
  }
  Object.defineProperty(globalThis, 'IntersectionObserver', { configurable: true, value: Visibility });
  const requests: Array<{ url: string; signal: AbortSignal }> = [];
  t.mock.method(globalThis, 'fetch', (url: string, options: RequestInit) => {
    const signal = options.signal!;
    requests.push({ url, signal });
    return new Promise<Response>((_, reject) => signal.addEventListener('abort', () => reject(new Error('cancelled'))));
  });
  let view!: ReactTestRenderer;
  const mount = () => {
    view = TestRenderer.create(<DisplayPreferencesProvider>
      <ThumbnailSwitch /><ThumbnailSwitch />
      <MediaThumbnail kind="directory" path="/媒体 & 旅行" />
      <MediaThumbnail kind="image" path="/data/影#像.jfif" />
      <MediaThumbnail kind="video" path="/data/小片.mov" />
      <MediaThumbnail kind="file" path="/data/info.txt" />
    </DisplayPreferencesProvider>, { createNodeMock: () => ({}) });
  };
  t.after(async () => {
    await act(() => view.unmount());
    Reflect.deleteProperty(globalThis, 'window');
    Reflect.deleteProperty(globalThis, 'IntersectionObserver');
  });
  act(mount);
  const switches = () => view.root.findAllByProps({ role: 'switch' });
  assert.ok(switches().every(item => item.props['aria-checked'] === false));
  assert.equal(observations.size, 0);
  assert.equal(requests.length, 0);

  act(() => switches()[0].props.onClick());
  assert.equal(stored, 'on');
  assert.ok(switches().every(item => item.props['aria-checked'] === true));
  assert.equal(observations.size, 3, 'unsupported files go directly to an icon');
  assert.equal(requests.length, 0, 'waiting for the viewport must not read from the NAS');
  act(() => observations.forEach(notify => notify(true)));
  assert.equal(requests.length, 2, 'visible thumbnails share a bounded request queue');
  const first = new URL(requests[0].url, 'http://localhost');
  assert.equal(first.pathname, '/api/media/thumbnail');
  assert.equal(first.searchParams.get('path'), '/媒体 & 旅行');
  assert.equal(first.searchParams.get('kind'), 'directory');
  assert.equal(new URL(requests[1].url, 'http://localhost').searchParams.get('path'), '/data/影#像.jfif');

  await act(async () => { switches()[1].props.onClick(); });
  assert.equal(stored, 'off');
  assert.equal(observations.size, 0);
  assert.ok(requests.every(item => item.signal.aborted));
  assert.equal(requests.length, 2, 'a queued request must not start after disabling thumbnails');
  act(() => view.unmount());
  act(mount);
  assert.ok(switches().every(item => item.props['aria-checked'] === false));
  assert.equal(requests.length, 2);

  stored = 'on';
  act(() => {
    fakeWindow.dispatchEvent(Object.assign(new Event('storage'), { key: storageKey, storageArea: {} }));
  });
  assert.equal(switches()[0].props['aria-checked'], false);
  act(() => {
    fakeWindow.dispatchEvent(Object.assign(new Event('storage'), { key: storageKey, storageArea: storage }));
  });
  assert.equal(switches()[0].props['aria-checked'], true);
});

test('the switch remains usable when local storage is blocked', t => {
  const fakeWindow = new EventTarget();
  Object.defineProperty(fakeWindow, 'localStorage', { get() { throw new Error('unavailable'); } });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: fakeWindow });
  let view!: ReactTestRenderer;
  act(() => { view = TestRenderer.create(<DisplayPreferencesProvider><ThumbnailSwitch /></DisplayPreferencesProvider>); });
  t.after(() => {
    act(() => view.unmount());
    Reflect.deleteProperty(globalThis, 'window');
  });
  const toggle = view.root.findByProps({ role: 'switch' });
  assert.equal(toggle.props['aria-checked'], true);
  act(() => toggle.props.onClick());
  assert.equal(toggle.props['aria-checked'], false);
});

test('one unavailable cover falls back locally and a neighboring JPEG is released on unmount', async t => {
  class Visible {
    constructor(private callback: (items: Array<{ isIntersecting: boolean }>) => void) {}
    observe() { this.callback([{ isIntersecting: true }]); }
    disconnect() {}
  }
  Object.defineProperty(globalThis, 'IntersectionObserver', { configurable: true, value: Visible });
  const requests: string[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string) => {
    const path = new URL(url, 'http://localhost').searchParams.get('path')!;
    requests.push(path);
    if (path === '/library/empty') return new Response(null, { status: 404 });
    return new Response(new Blob(['jpeg'], { type: 'image/jpeg' }), { headers: { 'Content-Type': 'image/jpeg' } });
  });
  t.mock.method(URL, 'createObjectURL', () => 'blob:thumbnail-test');
  const revoke = t.mock.method(URL, 'revokeObjectURL', () => {});
  let view!: ReactTestRenderer;
  t.after(() => { Reflect.deleteProperty(globalThis, 'IntersectionObserver'); });
  await act(async () => {
    view = TestRenderer.create(<>
      <MediaThumbnail kind="directory" path="/library/empty" size="cover" />
      <MediaThumbnail kind="directory" path="/library/album" representativeFile="/library/album/001.jpg" size="cover" />
    </>, { createNodeMock: () => ({}) });
  });
  assert.deepEqual(requests.sort(), ['/library/album/001.jpg', '/library/empty']);
  assert.equal(view.root.findAllByType('img').length, 1);
  assert.equal(view.root.findByType('img').props.src, 'blob:thumbnail-test');
  assert.equal(view.root.findAllByProps({ className: 'nfc-media-thumbnail is-cover is-unavailable' }).length, 1);
  act(() => view.unmount());
  assert.equal(revoke.mock.callCount(), 1);
});

test('the directory shelf hides previous-account paths while the new history is loading', async t => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  let currentUser = { id: 1, username: 'first', role: 'admin' };
  const record = (path: string): RecentPath => ({ id: 1, path, exists: true, last_used_at: '2026-01-01' });
  let complete!: (value: { items: RecentPath[] }) => void;
  const incoming = new Promise<{ items: RecentPath[] }>(resolve => { complete = resolve; });
  t.mock.method(authApi, 'getMe', async () => currentUser);
  t.mock.method(filesystemApi, 'listRecent', () => currentUser.id === 1
    ? Promise.resolve({ items: [record('/data/first-only')] }) : incoming);
  let refresh!: () => Promise<void>;
  function SessionShelf() {
    const auth = useAuth();
    refresh = auth.refreshUser;
    return auth.user ? <DirectoryShelf /> : null;
  }
  let view!: ReactTestRenderer;
  await act(async () => {
    view = TestRenderer.create(<MemoryRouter><QueryClientProvider client={client}><ConsoleToastProvider>
      <AuthProvider><SessionShelf /></AuthProvider>
    </ConsoleToastProvider></QueryClientProvider></MemoryRouter>);
  });
  t.after(() => { act(() => view.unmount()); client.clear(); });
  const links = () => view.root.findAllByType('a').map(a => a.props.title);
  async function waitForDirectory(path: string) {
    for (let n = 0; n < 50 && !links().includes(path); n++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
    }
    assert.ok(links().includes(path));
  }
  await waitForDirectory('/data/first-only');
  currentUser = { id: 2, username: 'second', role: 'user' };
  await act(async () => { await refresh(); });
  assert.ok(!links().includes('/data/first-only'));
  complete({ items: [record('/data/second-only')] });
  await waitForDirectory('/data/second-only');
});
