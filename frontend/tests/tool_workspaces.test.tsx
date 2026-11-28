import test, { type TestContext } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import TestRenderer, { act, type ReactTestRenderer } from 'react-test-renderer';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useNavigate, type NavigateFunction } from 'react-router-dom';

import { ConsoleButton } from '../src/components/ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../src/components/ui/ConsoleConfirmDialog';
import { ConsoleToastProvider } from '../src/components/ui/ConsoleToast';
import { AuthProvider } from '../src/contexts/AuthContext';
import { DirectoryDiffPage } from '../src/pages/DirectoryDiff';
import { SettingsPage } from '../src/pages/Settings';

import { authApi } from '../src/api/auth';
import { auditApi, dataLifecycleApi, directoryDiffApi } from '../src/api/domain';

import type { AuditRetentionPreview } from '../src/types';

test('reversing comparison directories discards the directional result and uses the swapped paths next', async t => {
  const descriptors = ['window', 'document'].map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)] as const);
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    innerWidth: 1440, setTimeout, clearTimeout, addEventListener() {}, removeEventListener() {},
  } });
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { title: '' } });
  const requests: Array<{ root_a: string; root_b: string }> = [];
  const previousPreview = directoryDiffApi.preview;
  directoryDiffApi.preview = async input => {
    requests.push(input);
    return { ...input, entries_a: 0, entries_b: 0, skipped_symlinks_a: 0, skipped_symlinks_b: 0,
      counts: {}, total: 0, items: [] };
  };
  const client = new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } });
  let page!: ReactTestRenderer;
  t.after(() => {
    if (page) act(() => page.unmount());
    directoryDiffApi.preview = previousPreview;
    client.clear();
    for (const [name, descriptor] of descriptors) {
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else Reflect.deleteProperty(globalThis, name);
    }
  });
  act(() => {
    page = TestRenderer.create(<QueryClientProvider client={client}>
      <ConsoleToastProvider><DirectoryDiffPage /></ConsoleToastProvider>
    </QueryClientProvider>);
  });
  const inputs = () => page.root.findAllByType('input').filter(input => input.props['aria-label'] === '目录路径');
  const preview = () => page.root.findAllByType('button')
    .find(button => button.findAllByType('span').some(span => span.children.includes('生成只读差异')))!;
  act(() => {
    inputs()[0].props.onChange({ target: { value: '/data/A' } });
    inputs()[1].props.onChange({ target: { value: '/data/B' } });
  });
  await act(async () => { preview().props.onClick(); });
  assert.ok(page.root.findAllByType('h2').some(heading => heading.children.includes('目录差异结果')));
  const swap = page.root.findAllByType('button').find(button => button.props['aria-label'] === '交换目录 A 和 B');
  assert.ok(swap, 'comparison has a keyboard-accessible swap button');
  act(() => swap.props.onClick());
  assert.deepEqual(inputs().map(input => input.props.value), ['/data/B', '/data/A']);
  assert.ok(!page.root.findAllByType('h2').some(heading => heading.children.includes('目录差异结果')));
  await act(async () => { preview().props.onClick(); });
  assert.deepEqual(requests, [{ root_a: '/data/A', root_b: '/data/B' }, { root_a: '/data/B', root_b: '/data/A' }]);
});

/** Use the actual settings route and seed its read-only server responses. */
async function openSettings(t: TestContext, path: string) {
  t.mock.method(authApi, 'getMe', async () => ({ id: 1, username: 'demo', role: 'admin' }));
  const documentBefore = Object.getOwnPropertyDescriptor(globalThis, 'document');
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { title: '' } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity } } });
  client.setQueryData(['settings'], { allowed_roots: [] });
  client.setQueryData(['dataLifecyclePolicy'], { audit_retention_days: 30, updated_at: null });
  client.setQueryData(['auditRetentionPreview'], previewWithCount(1));
  client.setQueryData(['quarantineRetentionPolicy'], { quarantine_retention_days: 90 });
  client.setQueryData(['resourcePolicy'], {
    id: 1, scan_threads: 2, hash_threads: 2, io_limit: 'normal', job_priority: 'normal',
    active_window_enabled: true, active_window_start: '01:00', active_window_end: '07:00',
    active_window_timezone: 'Asia/Seoul', outside_window_mode: 'limited', revision: 1, updated_at: null,
    effective_now: { profile: 'full', resource_jobs_admitted: true, effective_thread_cap: 2 },
  });
  client.setQueryData(['activeSessions'], { sessions: [] });
  t.mock.method(dataLifecycleApi, 'getPolicy', async () => ({ audit_retention_days: 30, updated_at: null }));
  let navigate!: NavigateFunction;
  /** Expose browser history operations while preserving the real settings component. */
  function HistoryProbe() {
    navigate = useNavigate();
    return null;
  }
  let view!: ReactTestRenderer;
  t.after(() => {
    act(() => view?.unmount());
    client.clear();
    if (documentBefore) Object.defineProperty(globalThis, 'document', documentBefore);
    else Reflect.deleteProperty(globalThis, 'document');
  });
  await act(async () => {
    view = TestRenderer.create(<MemoryRouter initialEntries={['/settings', path]}>
      <QueryClientProvider client={client}><ConsoleToastProvider><AuthProvider>
        <HistoryProbe /><SettingsPage />
      </AuthProvider></ConsoleToastProvider></QueryClientProvider>
    </MemoryRouter>);
  });
  return { view, goBack: () => act(() => navigate(-1)) };
}

/** Use different server counts to distinguish an obsolete result from the latest one. */
function previewWithCount(deleteCount: number): AuditRetentionPreview {
  return { retention_days: 30, enabled: true, cutoff: null, total_count: 10, delete_count: deleteCount,
    keep_count: 10 - deleteCount, oldest_timestamp: null, newest_timestamp: null };
}

test('leaving retention via browser Back discards the outstanding cleanup confirmation', async t => {
  let complete!: (preview: AuditRetentionPreview) => void;
  t.mock.method(auditApi, 'getRetentionPreview', () => new Promise<AuditRetentionPreview>(resolve => { complete = resolve; }));
  const { view, goBack } = await openSettings(t, '/settings#retention');
  const apply = () => view.root.findAllByType(ConsoleButton).find(button => button.props.children === '执行审计清理')!;
  let pending!: Promise<void>;
  act(() => { pending = apply().props.onClick(); });
  assert.equal(apply().props.loading, true);
  goBack();
  await act(async () => { complete(previewWithCount(1)); await pending; });
  assert.equal(view.root.findByType(ConsoleConfirmDialog).props.open, false);
});

test('the safety tab offers ZSpace authorization to an administrator', async t => {
  t.mock.method(globalThis, 'fetch', async (input: string | URL | Request) => {
    assert.equal(String(input), '/api/settings/zspace-authorization');
    return Response.json({ status: 'needs_login' });
  });
  const { view } = await openSettings(t, '/settings#safety');
  const buttons = () => view.root.findAllByType(ConsoleButton);
  for (let attempt = 0; attempt < 30 && !buttons().some(button => button.props.children === '连接极空间'); attempt++) {
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
  }
  assert.ok(buttons().some(button => button.props.children === '连接极空间'));
});

test('a discarded cleanup preview cannot clear the pending state of a later request', async t => {
  const queries: Array<(preview: AuditRetentionPreview) => void> = [];
  t.mock.method(auditApi, 'getRetentionPreview', () => new Promise<AuditRetentionPreview>(resolve => { queries.push(resolve); }));
  const { view } = await openSettings(t, '/settings#retention');
  const apply = () => view.root.findAllByType(ConsoleButton).find(button => button.props.children === '执行审计清理')!;
  const auditDialog = () => view.root.findAllByType(ConsoleConfirmDialog).find(dialog => dialog.props.danger)!;
  const switchTo = (tab: string) => act(() => view.root.findByProps({ id: 'settings-tab-' + tab }).props.onClick());
  act(() => { apply().props.onClick(); });
  switchTo('appearance');
  switchTo('retention');
  assert.equal(apply().props.loading, false);
  act(() => { apply().props.onClick(); });
  assert.equal(queries.length, 2);
  await act(async () => { queries[0](previewWithCount(1)); });
  assert.equal(apply().props.loading, true);
  assert.equal(auditDialog().props.open, false);
  await act(async () => { queries[1](previewWithCount(2)); });
  assert.equal(apply().props.loading, false);
  assert.equal(auditDialog().props.open, true);
  assert.match(renderToStaticMarkup(auditDialog().props.description), /预计清理 <strong[^>]*>2<\/strong>/);
});

test('database maintenance previews space and refreshes after a confirmed archive', async t => {
  const requests: string[] = [];
  let journalRows = 12;
  t.mock.method(globalThis, 'fetch', async (input: string | URL | Request, init?: RequestInit) => {
    requests.push(`${init?.method ?? 'GET'} ${input}`);
    if (String(input).endsWith('/archive')) {
      assert.deepEqual(JSON.parse(String(init?.body)), { kind: 'operation_journal' });
      journalRows = 0;
      return Response.json({ rows: 12, files: ['operation-journal-example.json.gz'] });
    }
    return Response.json({
      database: {
        database_bytes: 8000000, wal_bytes: 4000000, reusable_bytes: 1000000,
        estimated_reclaimable_bytes: 5000000, wal_retained_limit_bytes: 67108864, active_jobs: 0,
      },
      task_events: { jobs: 0, rows: 0 },
      operation_journal: { rows: journalRows },
      policy: { automatic: false, task_event_retention_days: 30, operation_journal_retention_days: 90 },
    });
  });
  const { view } = await openSettings(t, '/settings#retention');
  const archiveButton = () => view.root.findAllByType(ConsoleButton)
    .find(button => button.props.children === '归档一批操作流水');
  for (let attempt = 0; attempt < 30 && !archiveButton(); attempt++) {
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
  }
  assert.equal(archiveButton()?.props.disabled, false);
  act(() => archiveButton()!.props.onClick());
  const dialog = view.root.findAllByType(ConsoleConfirmDialog).find(candidate => !candidate.props.danger)!;
  assert.equal(dialog.props.open, true);
  assert.deepEqual(requests, ['GET /api/database-maintenance']);
  await act(async () => { dialog.props.onConfirm(); });
  for (let attempt = 0; attempt < 30 && !archiveButton()?.props.disabled; attempt++) {
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
  }
  assert.deepEqual(requests, [
    'GET /api/database-maintenance',
    'POST /api/database-maintenance/archive',
    'GET /api/database-maintenance',
  ]);
  assert.equal(archiveButton()?.props.disabled, true);
});

test('the enabled resource window renders its saved IANA time zone outside the common list', async t => {
  const { view } = await openSettings(t, '/settings#resources');
  const timeZone = view.root.findAllByType('select').find(select => select.props.value === 'Asia/Seoul');
  assert.ok(timeZone, 'the saved time zone is in the form');
  assert.ok(timeZone.findAllByType('option').some(option => option.props.value === 'Asia/Seoul'),
    'the saved time zone has a corresponding native option');
});
