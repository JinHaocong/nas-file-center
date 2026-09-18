import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.1 premium visual pass contract', () => {
  test('design tokens expose premium elevation and motion primitives', () => {
    const css = read('src/index.css');
    for (const token of [
      '--nfc-shadow-xs',
      '--nfc-shadow-sm',
      '--nfc-shadow-md',
      '--nfc-ease-standard',
      '--nfc-ease-emphasized',
      '--nfc-motion-enter',
    ]) {
      assert.ok(css.includes(token), token);
    }
  });

  test('app shell and shared surfaces have deliberate motion', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-page-content > *',
      '.nfc-page-header',
      '.nfc-data-panel',
      '.nfc-metric-card',
      '.nfc-quick-action',
      '.nfc-sidebar-menu .ant-menu-item',
    ]) {
      assert.ok(css.includes(selector), selector);
    }
    assert.ok(css.includes('@keyframes nfc-enter'));
    assert.ok(css.includes('@keyframes nfc-status-pulse'));
  });

  test('Ant Design controls are visually normalized by shared NFC chrome', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.ant-btn',
      '.ant-input',
      '.ant-select-selector',
      '.ant-table-wrapper',
      '.ant-modal-content',
      '.ant-drawer-content',
      '.ant-dropdown-menu',
    ]) {
      assert.ok(css.includes(selector), selector);
    }
    assert.ok(css.includes('box-shadow: var(--nfc-shadow-sm)'));
  });

  test('navigation gains selected-state depth and motion', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-sidebar-menu .ant-menu-item-selected::before'));
    assert.ok(css.includes('translateX('));
    assert.ok(css.includes('var(--nfc-ease-standard)'));
  });

  test('status badge supports live-state pulse while reduced motion still wins', () => {
    const source = read('src/components/ui/StatusBadge.tsx');
    assert.ok(source.includes('nfc-status-live'));
    for (const status of ['running', 'executing', 'validating']) {
      assert.ok(source.includes(status), status);
    }
    const css = read('src/index.css');
    assert.ok(css.includes('prefers-reduced-motion: reduce'));
    assert.ok(css.includes('.nfc-status-live'));
  });

  test('theme provider overrides Ant component chrome instead of relying on defaults', () => {
    const source = read('src/contexts/ThemeContext.tsx');
    for (const component of ['Button:', 'Input:', 'Select:', 'Table:', 'Modal:', 'Drawer:']) {
      assert.ok(source.includes(component), component);
    }
  });

  test('representative surfaces add stagger, section accents and refined interaction chrome', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.nfc-data-panel-title::before',
      '.nfc-metric-grid .nfc-metric-card:nth-child(2)',
      '.nfc-dashboard-layout > :nth-child(2)',
      '.nfc-mobile-record-list > *',
      '.nfc-header-actions .ant-btn',
      '.ant-switch',
      '.ant-checkbox-wrapper',
      '.ant-tabs-tab',
      '::-webkit-scrollbar',
    ]) {
      assert.ok(css.includes(selector), selector);
    }
  });

  test('frozen design contract has a v0.4.1 premium visual amendment', () => {
    const source = read('../DESIGN.md');
    assert.ok(source.includes('v0.4.1 Premium Visual Pass'));
    assert.ok(source.includes('Motion hierarchy'));
    assert.ok(source.includes('Ant Design is infrastructure, not visual identity'));
  });
});
