import test from 'node:test';
import assert from 'node:assert/strict';
import React, { useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import TestRenderer, { act } from 'react-test-renderer';

import { StepList } from '../src/components/workflows/StepList';

import type { WorkflowStep } from '../src/types/workflow';

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
