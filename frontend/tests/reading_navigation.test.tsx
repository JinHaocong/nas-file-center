import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import TestRenderer, { act, type ReactTestRenderer } from 'react-test-renderer';

import { CodePath } from '../src/components/ui/CodePath';
import { ConsolePagination } from '../src/components/ui/ConsolePagination';

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
