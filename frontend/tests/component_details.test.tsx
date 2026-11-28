import assert from 'node:assert/strict';
import test from 'node:test';

import TestRenderer, { act } from 'react-test-renderer';

import { ConsoleButton } from '../src/components/ui/ConsoleButton';
import { ProgressMotionTrack } from '../src/components/ui/ProgressMotionTrack';

test('loading replaces the icon in the same slot and keeps the button label', () => {
  const render = (loading: boolean) => <ConsoleButton loading={loading} leadingIcon={<span>+</span>}>添加</ConsoleButton>;
  const view = TestRenderer.create(render(false));
  const slot = view.root.findByProps({ className: 'nfc-console-button-icon' });
  act(() => view.update(render(true)));
  const button = view.root.findByType('button');
  assert.equal(view.root.findByProps({ className: 'nfc-console-button-icon' }), slot);
  assert.equal(button.props.disabled, true);
  assert.equal(button.props['aria-busy'], true);
  assert.equal(view.root.findByProps({ className: 'nfc-console-button-label' }).children.join(''), '添加');
  view.unmount();
});

test('text-only loading retains the label and uses an out-of-flow indicator', () => {
  const view = TestRenderer.create(<ConsoleButton loading>保存</ConsoleButton>);
  const indicator = view.root.findByProps({ className: 'nfc-console-button-busy-overlay' });
  assert.equal(indicator.props['aria-hidden'], 'true');
  assert.equal(view.root.findByProps({ className: 'nfc-console-button-label' }).children.join(''), '保存');
  view.unmount();
});

test('animated progress reuses the visible fill and reports the updated native value immediately', () => {
  const render = (value: number) => <ProgressMotionTrack value={value}>
    <progress value={value} max={100} aria-label="任务进度" />
  </ProgressMotionTrack>;
  const view = TestRenderer.create(render(27));
  const fill = view.root.findByProps({ className: 'nfc-progress-motion-fill' });
  act(() => view.update(render(71)));
  assert.equal(view.root.findByProps({ className: 'nfc-progress-motion-fill' }), fill);
  assert.equal(fill.props['aria-hidden'], 'true');
  assert.equal(view.root.findByType('progress').props.value, 71);
  assert.equal(view.root.findByProps({ className: 'nfc-progress-motion' }).props.style['--nfc-progress-fraction'], .71);
  view.unmount();
});
