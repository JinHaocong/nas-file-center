import test, { type TestContext } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StaticRouter, MemoryRouter } from 'react-router-dom';
import TestRenderer, { act } from 'react-test-renderer';
import * as organizer from '../src/api/media_organizer';
import type { SemanticExecutionStatus } from '../src/api/media_organizer';
import { ConsoleToastProvider } from '../src/components/ui/ConsoleToast';
import { SemanticMediaOrganizerEditor } from '../src/pages/Batch/SemanticMediaOrganizerEditor';

const maintenance = {
  execution_mode: 'maintenance_window' as const,
  assurance_level: 'maintenance_window' as const,
  requires_maintenance_window: true,
  namespace_exclusive_custody_proven: false as const,
};
const failedExecution = (): SemanticExecutionStatus => ({
  ...maintenance,
  job_id: 17, status: 'failed', error: 'interrupted', preview_job_id: 12,
  unit: '/synthetic/Collection/NO.001', recovery_of_job_id: null,
  manual_cleanup_required: false, finalized: false, execution_enabled: true,
  publication_complete: false, deferred_publication_count: 0,
  progress: { current: 1, total: 4, message: null, phase: 'frozen' },
  cleanup: null,
});

test('every maintenance mutation request carries fresh explicit confirmation', async t => {
  const bodies: Record<string, unknown>[] = [];
  t.mock.method(globalThis, 'fetch', async (_url: string, options: RequestInit) => {
    bodies.push(JSON.parse(String(options.body)));
    return new Response(JSON.stringify({ job_id: 21, status: 'queued' }), { status: 200 });
  });
  await Reflect.apply(organizer.mediaOrganizerApi.startExecution, null, [12, '/synthetic/unit', 'EXECUTE', true]);
  await Reflect.apply(organizer.mediaOrganizerApi.startCleanup, null, [17, 'CLEANUP', true]);
  await Reflect.apply(organizer.mediaOrganizerApi.recoverExecution, null, [17, 'RECOVER', true]);
  await Reflect.apply(organizer.mediaOrganizerApi.recoverCleanup, null, [21, 'RECOVER_CLEANUP', true]);
  assert.equal(bodies.length, 4);
  for (const body of bodies) assert.equal(body.maintenance_window_confirmed, true);
});

test('strict clients retain the existing request contract without a maintenance assertion', async t => {
  const bodies: Record<string, unknown>[] = [];
  t.mock.method(globalThis, 'fetch', async (_url: string, options: RequestInit) => {
    bodies.push(JSON.parse(String(options.body)));
    return new Response(JSON.stringify({ job_id: 21, status: 'queued' }), { status: 200 });
  });
  await organizer.mediaOrganizerApi.startExecution(12, '/synthetic/unit', 'EXECUTE');
  await organizer.mediaOrganizerApi.startCleanup(17, 'CLEANUP');
  await organizer.mediaOrganizerApi.recoverExecution(17, 'RECOVER');
  await organizer.mediaOrganizerApi.recoverCleanup(21, 'RECOVER_CLEANUP');
  for (const body of bodies) assert.equal(Object.hasOwn(body, 'maintenance_window_confirmed'), false);
});

test('maintenance action gating requires a literal true confirmation even with the correct operation token', () => {
  const api = organizer as unknown as {
    hasMaintenanceConfirmation?: (response: Record<string, unknown> | undefined, confirmed: unknown) => boolean;
  };
  assert.equal(typeof api.hasMaintenanceConfirmation, 'function');
  const allowed = api.hasMaintenanceConfirmation!;
  for (const confirmation of [false, undefined, 'true', 1]) {
    assert.equal(allowed(maintenance, confirmation), false);
  }
  assert.equal(allowed(maintenance, true), true);
  assert.equal(allowed({ execution_mode: 'strict' }, false), true);
  assert.equal(allowed({ requires_maintenance_window: true }, false), false);
  assert.equal(allowed({ execution_mode: 'maintenance_window' }, false), false);
});

function renderExecution(execution: SemanticExecutionStatus) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  queryClient.setQueryData(['semanticMediaExecution', execution.job_id], execution);
  try {
    return renderToStaticMarkup(
      <StaticRouter location="/batch?operation=semantic-media-organize&execution=17">
        <QueryClientProvider client={queryClient}>
          <ConsoleToastProvider><SemanticMediaOrganizerEditor /></ConsoleToastProvider>
        </QueryClientProvider>
      </StaticRouter>,
    );
  } finally {
    queryClient.clear();
  }
}

test('execution recovery shows an unchecked maintenance agreement and the actual replacement risk', () => {
  const html = renderExecution(failedExecution());
  assert.match(html, /id="semantic-recovery-maintenance"[^>]*type="checkbox"|type="checkbox"[^>]*id="semantic-recovery-maintenance"/);
  assert.doesNotMatch(html.match(/<input[^>]*id="semantic-recovery-maintenance"[^>]*>/)?.[0] || '', /checked/);
  assert.ok(html.includes('替换的文件可能被误删'));
  assert.ok(html.includes('无法保证恢复'));
  assert.ok(html.includes('清理或恢复全部完成'));
  assert.match(html, /<button[^>]*disabled=""[^>]*><span>使用原冻结清单申请安全恢复/);
});

test('cleanup recovery has a separate unchecked maintenance agreement', () => {
  const html = renderExecution({
    ...failedExecution(), status: 'completed', manual_cleanup_required: true,
    cleanup: { job_id: 21, status: 'failed', error: 'interrupted cleanup', recovery_confirmation: 'RETRY_21' },
  });
  assert.match(html, /id="semantic-cleanup-recovery-maintenance"/);
  assert.match(html, /<button[^>]*disabled=""[^>]*><span>确认并恢复本次清理/);
  assert.doesNotMatch(html.match(/<input[^>]*id="semantic-cleanup-recovery-maintenance"[^>]*>/)?.[0] || '', /checked/);
});

test('strict recovery does not ask for an unrelated maintenance agreement', () => {
  const execution = { ...failedExecution(), execution_mode: 'strict', requires_maintenance_window: false, assurance_level: 'strict' };
  const html = renderExecution(execution as SemanticExecutionStatus);
  assert.doesNotMatch(html, /id="semantic-recovery-maintenance"/);
});

async function interactivePreview(t: TestContext) {
  // Exercise real React controls; Node supplies browser timer/resize boundaries.
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window');
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: Object.assign(new EventTarget(), { setTimeout, clearTimeout, setInterval, clearInterval, innerWidth: 1200 }),
  });
  t.after(() => {
    if (originalWindow) Object.defineProperty(globalThis, 'window', originalWindow);
    else Reflect.deleteProperty(globalThis, 'window');
  });
  const units = ['A', 'B'].map(name => ({
    unit: `/synthetic/${name}`, status: 'ready', reason: null,
    operation: 'sort_mixed_media', totals: { P: 1, V: 1, Other: 0 }, groups: [],
    needed_moves: 2, renamed_count: 2, total_files: 2, total_proposals: 2,
    sample_moves: [], mapping_id: null, truncated: false, conflicts: [], read_only: true,
  }));
  const page = {
    ...maintenance, job_id: 12, status: 'completed', error: null, selection: '/synthetic',
    progress: { current: 2, total: 2, message: null }, units, page: 1, page_size: 25,
    filtered_total: 2, read_only: true, execution_enabled: true,
    confirmation_tokens: { '/synthetic/A': 'EXECUTE_A', '/synthetic/B': 'EXECUTE_B' },
    summary: { unit_count: 2, ready_count: 2, blocked_count: 0, already_organized_count: 0,
      skipped_count: 0, file_count: 4, needed_moves: 4, renamed_count: 4, elapsed_seconds: 0, read_only: true },
  };
  const requests: Record<string, unknown>[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    if (url.endsWith('/execute')) {
      requests.push(JSON.parse(String(options.body)));
      return new Response(JSON.stringify({ detail: 'operation busy' }), { status: 409 });
    }
    assert.equal(url, '/api/media-organizer/previews');
    return new Response(JSON.stringify({ job_id: 12, status: 'queued' }), { status: 200 });
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  queryClient.setQueryData(['semanticMediaPreview', 12, 1, 25, 'all'], page);
  let view: ReturnType<typeof TestRenderer.create>;
  await act(async () => {
    view = TestRenderer.create(
      <MemoryRouter initialEntries={['/batch?operation=semantic-media-organize']}>
        <QueryClientProvider client={queryClient}>
          <ConsoleToastProvider><SemanticMediaOrganizerEditor /></ConsoleToastProvider>
        </QueryClientProvider>
      </MemoryRouter>,
    );
  });
  const button = (label: string) => view.root.findAllByType('button').find((node: any) =>
    node.findAllByType('span').some((span: any) => span.children.join('') === label))!;
  await act(async () => {
    view.root.findByProps({ 'aria-label': '目录路径' }).props.onChange({ target: { value: '/synthetic' } });
  });
  await act(async () => {
    button('开始只读扫描').props.onClick();
    await new Promise(resolve => setTimeout(resolve, 0));
  });
  const select = async (unit: string) => {
    await act(async () => view.root.findByProps({ id: 'semantic-execution-unit' })
      .props.onChange({ target: { value: unit } }));
  };
  const check = async () => {
    await act(async () => view.root.findAllByType('input').find((input: any) =>
      input.props.id === 'semantic-execution-maintenance')!.props.onChange({ target: { checked: true } }));
  };
  const checked = () => view.root.findAllByType('input').find((input: any) =>
    input.props.id === 'semantic-execution-maintenance')!.props.checked;
  const dispose = async () => {
    await act(async () => view.unmount());
    queryClient.clear();
  };
  return { view: view!, select, check, checked, button, requests, dispose };
}

test('changing A to B and back requires a new maintenance agreement through the real selector', async t => {
  const form = await interactivePreview(t);
  try {
    await form.select('/synthetic/A');
    await form.check();
    assert.equal(form.checked(), true);
    await form.select('/synthetic/B');
    assert.equal(form.checked(), false);
    await form.select('/synthetic/A');
    assert.equal(form.checked(), false, 'returning to A must not restore a previous agreement');
  } finally {
    await form.dispose();
  }
});

test('a rejected execution request consumes the agreement before another attempt', async t => {
  const form = await interactivePreview(t);
  try {
    await form.select('/synthetic/A');
    await form.check();
    await act(async () => form.view.root.findByProps({ id: 'semantic-execution-confirmation' })
      .props.onChange({ target: { value: 'EXECUTE_A' } }));
    assert.equal(form.button('确认并执行当前作品').props.disabled, false);
    await act(async () => {
      form.button('确认并执行当前作品').props.onClick();
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    assert.equal(form.requests.length, 1);
    assert.equal(form.requests[0].maintenance_window_confirmed, true);
    assert.equal(form.checked(), false, 'failed submissions also require a fresh agreement');
    assert.equal(form.button('确认并执行当前作品').props.disabled, true);
  } finally {
    await form.dispose();
  }
});
