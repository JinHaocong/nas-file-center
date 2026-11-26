import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import TestRenderer, { act, type ReactTestRenderer } from 'react-test-renderer';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ConsoleToastProvider } from '../src/components/ui/ConsoleToast';
import { DirectoryDiffPage } from '../src/pages/DirectoryDiff';

import { directoryDiffApi } from '../src/api/domain';

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
