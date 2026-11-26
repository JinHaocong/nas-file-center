import test from 'node:test';
import assert from 'node:assert/strict';
import React, { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import TestRenderer, { act, type ReactTestRenderer } from 'react-test-renderer';

import { authApi } from '../src/api/auth';
import { indexesApi } from '../src/api/domain';
import { workflowApi } from '../src/api/workflows';
import { ConsoleToastProvider } from '../src/components/ui/ConsoleToast';
import { StepList } from '../src/components/workflows/StepList';
import { AuthProvider } from '../src/contexts/AuthContext';
import { WorkflowBuilderPage } from '../src/pages/Workflows/WorkflowBuilder';

import type { WorkflowRevisionResponse, WorkflowStep } from '../src/types/workflow';

test('workflow steps open individually and follow a step through reordering', t => {
  const scan: WorkflowStep = { id: 'scan', type: 'scan', root_ids: [1] };
  const rename: WorkflowStep = { id: 'first', type: 'rename', pattern: 'IMG', replacement: '相册' };
  const touch: WorkflowStep = { id: 'second', type: 'touch', touch_now: true, mtime_ns: null };
  const client = new QueryClient();
  const focused: string[] = [];

  function Draft() {
    const [steps, setSteps] = useState<WorkflowStep[]>([scan, rename, touch]);
    return <QueryClientProvider client={client}><StepList mode="file" steps={steps} onChange={setSteps} /></QueryClientProvider>;
  }

  const view = TestRenderer.create(<Draft />, {
    createNodeMock: element => element.props.className === 'nfc-workflow-step-list'
      ? { querySelectorAll: () => ['scan', 'first', 'second'].map(id => ({
        dataset: { stepId: id }, focus: () => focused.push(id),
      })) }
      : null,
  });
  t.after(() => { act(() => view.unmount()); client.clear(); });

  const toggles = () => view.root.findAllByType('button').filter(node =>
    node.props.className?.includes('nfc-v2-step-toggle'));
  const open = () => toggles().map(node => node.props['aria-expanded']);
  const action = (label: string) => view.root.findAllByType('button')
    .find(node => node.props['aria-label'] === label);

  assert.deepEqual(open(), [false, false, false]);
  act(() => toggles()[1].props.onClick());
  assert.deepEqual(open(), [false, true, false]);
  act(() => toggles()[2].props.onClick());
  assert.deepEqual(open(), [false, false, true]);
  act(() => action('上移步骤')!.props.onClick());
  assert.deepEqual(open(), [false, true, false]);
  assert.equal(focused.at(-1), 'second');
  act(() => action('删除步骤')!.props.onClick());
  assert.deepEqual(open(), [false, false]);
  assert.equal(focused.at(-1), 'first');
});

test('jumping to a historical workflow revision asks before discarding edited fields and steps', async t => {
  const historical: WorkflowRevisionResponse = {
    revision: 1, definition_sha256: 'first', created_at: '2026-01-01', created_by_user_id: 1,
    definition: { schema_version: 1, mode: 'file', steps: [{ id: 'old', type: 'scan', root_ids: [1] }] },
  };
  const current: WorkflowRevisionResponse = {
    ...historical, revision: 2, definition_sha256: 'second',
    definition: { ...historical.definition, steps: [{ id: 'current', type: 'scan', root_ids: [1] }] },
  };
  t.mock.method(authApi, 'getMe', async () => ({ id: 1, username: 'demo', role: 'admin' }));
  t.mock.method(indexesApi, 'listIndexes', async () => ({ items: [], page: 1, page_size: 100, total: 0 }));
  t.mock.method(workflowApi, 'getWorkflow', async () => ({
    id: 1, name: '已保存工作流', description: '', current_revision: 2, is_builtin: false,
    created_by_user_id: 1, archived_at: null, created_at: '2026-01-01', updated_at: '2026-01-01',
    definition: current.definition,
  }));
  t.mock.method(workflowApi, 'listRevisions', async () => [current, historical]);
  const getRevision = t.mock.method(workflowApi, 'getRevision', async () => historical);

  // Keep the real editor and drawer actions mounted without a browser portal.
  const sheets = require('../src/components/ui/ConsoleSheet') as typeof import('../src/components/ui/ConsoleSheet');
  const dialogs = require('../src/components/ui/ConsoleConfirmDialog') as typeof import('../src/components/ui/ConsoleConfirmDialog');
  t.mock.method(sheets, 'ConsoleSheet', ({ open, children, title }: React.ComponentProps<typeof sheets.ConsoleSheet>) =>
    open ? <section aria-label={title}>{children}</section> : null);
  t.mock.method(dialogs, 'ConsoleConfirmDialog', ({ open, title, confirmText, onOpenChange, onConfirm }:
    React.ComponentProps<typeof dialogs.ConsoleConfirmDialog>) => open ? <section role="dialog" aria-label={title}>
      <button onClick={() => onOpenChange(false)}>取消</button><button onClick={onConfirm}>{confirmText}</button>
    </section> : null);
  t.mock.method(globalThis, 'fetch', async () => { throw new Error('Unexpected network request'); });
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { title: '' } });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: Object.assign(new EventTarget(), { innerWidth: 1440 }) });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  function CurrentAddress() {
    const { pathname, search } = useLocation();
    return <output>{pathname + search}</output>;
  }
  let view!: ReactTestRenderer;
  t.after(() => {
    act(() => view.unmount());
    client.clear();
    Reflect.deleteProperty(globalThis, 'document');
    Reflect.deleteProperty(globalThis, 'window');
  });
  await act(async () => {
    view = TestRenderer.create(<MemoryRouter initialEntries={['/workflows/1']}>
      <QueryClientProvider client={client}><ConsoleToastProvider><AuthProvider>
        <Routes><Route path="/workflows/:id" element={<WorkflowBuilderPage />} /></Routes><CurrentAddress />
      </AuthProvider></ConsoleToastProvider></QueryClientProvider>
    </MemoryRouter>);
  });

  const address = () => view.root.findByType('output').children.join('');
  const button = (text: string) => view.root.findAllByType('button').find(node =>
    node.children.join('') === text || node.findAllByType('span').some(label =>
      label.props.className === 'nfc-console-button-label' && label.children.join('') === text));
  const name = () => view.root.findAllByType('input').find(input => input.props.id?.endsWith('-name'));
  /** Flush React Query notifications while checking for the expected editor state. */
  async function waitFor(ready: () => boolean) {
    for (let attempt = 0; attempt < 50 && !ready(); attempt++) {
      await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)); });
    }
    assert.ok(ready());
  }

  await waitFor(() => name()?.props.value === '已保存工作流' && !name()?.props.disabled);
  const draftSteps: WorkflowStep[] = [{ id: 'edited', type: 'scan', root_ids: [1] }];
  act(() => {
    name()!.props.onChange({ target: { value: '未保存草稿' } });
    view.root.findByType(StepList).props.onChange(draftSteps);
    button('版本历史')!.props.onClick();
  });
  await waitFor(() => Boolean(button('跳转')));
  act(() => button('跳转')!.props.onClick());
  assert.equal(address(), '/workflows/1', '历史跳转确认前不能切换当前编辑页');
  assert.equal(getRevision.mock.callCount(), 0);
  assert.equal(view.root.findByProps({ role: 'dialog' }).props['aria-label'], '未保存的更改');

  act(() => button('取消')!.props.onClick());
  assert.equal(name()?.props.value, '未保存草稿');
  assert.deepEqual(view.root.findByType(StepList).props.steps, draftSteps);
  assert.ok(button('跳转'), '取消后留在版本历史抽屉');

  act(() => button('跳转')!.props.onClick());
  act(() => button('确认跳转')!.props.onClick());
  await waitFor(() => view.root.findAllByType(StepList)[0]?.props.steps[0]?.id === 'old');
  assert.equal(address(), '/workflows/1?revision=1');
  assert.equal(getRevision.mock.callCount(), 1);
  assert.equal(name()?.props.disabled, true);
  assert.equal(button('跳转'), undefined);

  act(() => button('返回当前最新版')!.props.onClick());
  await waitFor(() => !name()?.props.disabled && view.root.findAllByType(StepList)[0]?.props.steps[0]?.id === 'current');
  assert.equal(address(), '/workflows/1');
  assert.equal(name()?.props.value, '已保存工作流');
});
