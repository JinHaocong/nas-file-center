import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.2 Taste redesign contract', () => {
  test('palette moves from generic SaaS blue to a graphite and jade product identity', () => {
    const tokens = read('src/design/tokens.ts');
    assert.match(tokens, /accent:\s*['"]#167a5c['"]/i);
    assert.match(tokens, /accent:\s*['"]#4fd1a1['"]/i);
    assert.doesNotMatch(tokens, /#335cff|#7f8cff/i);
  });

  test('data typography uses optical hierarchy and tabular numerics', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('--nfc-font-display'));
    assert.ok(css.includes('--nfc-font-mono'));
    assert.match(css, /font-variant-numeric:\s*tabular-nums/);
    assert.ok(css.includes('.nfc-metric-value'));
    assert.ok(css.includes('font-feature-settings'));
  });

  test('persistent surfaces stop reading as generic border shadow cards', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('/* v0.4.2 Taste Redesign */'));
    assert.ok(css.includes('.nfc-data-panel'));
    assert.ok(css.includes('--nfc-panel-separator'));
    assert.ok(css.includes('.nfc-data-panel::before'));
    assert.ok(css.includes('.nfc-metric-card::before'));
  });

  test('dashboard gains an asymmetric metric composition instead of four equal cards', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-metric-grid > .nfc-metric-card:first-child'));
    assert.match(css, /grid-column:\s*span 2/);
    assert.ok(css.includes('.nfc-dashboard-rail'));
  });

  test('sidebar and header gain a deliberate workspace chrome layer', () => {
    const sidebar = read('src/components/Sidebar.tsx');
    const header = read('src/components/Header.tsx');
    const css = read('src/index.css');
    assert.ok(sidebar.includes('nfc-sidebar-meta'));
    assert.ok(sidebar.includes('CONTROL PLANE'));
    assert.ok(header.includes('nfc-header-product-mark'));
    assert.ok(css.includes('.nfc-sidebar-meta'));
    assert.ok(css.includes('.nfc-header-product-mark'));
  });

  test('dashboard content removes all-caps AI-style eyebrow treatment', () => {
    const dashboard = read('src/pages/Dashboard/index.tsx');
    assert.doesNotMatch(dashboard, /eyebrow=["']OVERVIEW["']/);
    assert.match(dashboard, /eyebrow=["']Operations overview["']/);
  });

  test('taste redesign preserves reduced motion and tactile control feedback', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('prefers-reduced-motion: reduce'));
    assert.ok(css.includes(':active'));
    assert.ok(css.includes('scale(0.98)') || css.includes('scale(0.985)'));
  });

  test('design contract records the taste-skill audit and anti-card direction', () => {
    const design = read('../DESIGN.md');
    assert.ok(design.includes('v0.4.2 Taste-Skill Redesign'));
    assert.ok(design.includes('Graphite + Jade'));
    assert.ok(design.includes('DESIGN_VARIANCE: 5'));
    assert.ok(design.includes('MOTION_INTENSITY: 4'));
    assert.ok(design.includes('VISUAL_DENSITY: 7'));
    assert.ok(design.includes('reduce generic card chrome'));
  });
});
