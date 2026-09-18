import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.2 console quality gate', () => {
  test('console layer defines a crisp workspace rhythm and Feihong-compatible motion curve', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('/* v0.4.2 Console Quality Gate */'));
    assert.ok(css.includes('--nfc-console-row-height: 46px'));
    assert.ok(css.includes('--nfc-console-ease-out: cubic-bezier(0.16, 1, 0.3, 1)'));
    assert.ok(css.includes('--nfc-sidebar-canvas'));
  });

  test('header is crisp rather than glassmorphic', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-header.nfc-header'));
    assert.ok(css.includes('backdrop-filter: none'));
    assert.ok(css.includes('-webkit-backdrop-filter: none'));
  });

  test('sidebar becomes a deep graphite workspace in both desktop and mobile navigation', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-sidebar,'));
    assert.ok(css.includes('.nfc-mobile-sidebar'));
    assert.ok(css.includes('background: var(--nfc-sidebar-canvas) !important'));
    assert.ok(css.includes('.nfc-sidebar-menu .ant-menu-item-selected'));
  });

  test('primary controls expose hover active focus-visible and disabled states', () => {
    const css = read('src/index.css');
    for (const selector of [
      '.ant-btn:not(:disabled):hover',
      '.ant-btn:not(:disabled):active',
      '.ant-btn:focus-visible',
      '.ant-btn:disabled',
      '.ant-input:disabled',
      '.ant-select-disabled .ant-select-selector',
    ]) {
      assert.ok(css.includes(selector), selector);
    }
  });

  test('operational tables use a fixed scan-friendly row rhythm and numeric alignment', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-data-panel .ant-table-tbody > tr'));
    assert.ok(css.includes('height: var(--nfc-console-row-height)'));
    assert.match(css, /font-variant-numeric:\s*tabular-nums/);
  });

  test('nested decorative entrance motion is removed from dense console surfaces', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-page-header-copy > *'));
    assert.ok(css.includes('.nfc-metric-grid .nfc-metric-card'));
    assert.ok(css.includes('animation: none'));
  });

  test('representative page eyebrows read as product context instead of all-caps labels', () => {
    const plans = read('src/pages/Plans/index.tsx');
    const workflows = read('src/pages/Workflows/WorkflowList.tsx');
    assert.match(plans, /eyebrow=["']Execution control["']/);
    assert.match(workflows, /eyebrow=["']Automation workflows["']/);
    assert.doesNotMatch(plans, /eyebrow=["']EXECUTION["']/);
    assert.doesNotMatch(workflows, /eyebrow=["']AUTOMATION["']/);
  });

  test('semantic safety colors remain independent from the jade product accent', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('--nfc-accent: #167a5c'));
    assert.ok(css.includes('--nfc-success: #168a54'));
    assert.ok(css.includes('--nfc-warning: #a86406'));
    assert.ok(css.includes('--nfc-danger: #c73a49'));
  });

  test('design contract records the adapted Feihong console quality gate', () => {
    const design = read('../DESIGN.md');
    assert.ok(design.includes('Feihong Console Quality Gate'));
    assert.ok(design.includes('function before decoration'));
    assert.ok(design.includes('46px'));
    assert.ok(design.includes('semantic colors remain authoritative'));
  });
});
