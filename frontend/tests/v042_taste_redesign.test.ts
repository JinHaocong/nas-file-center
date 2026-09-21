import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.2 taste principles carried into the current control plane', () => {
  test('historical palette decision remains documented while later skins may supersede it', () => {
    const design = read('../DESIGN.md');
    assert.ok(design.includes('Graphite + Jade'));
    assert.ok(design.includes('v0.4.3 Modern Console Reset'));
    assert.ok(design.includes('supersedes the v0.4.2 Graphite + Jade'));
  });

  test('data typography keeps tabular numerics and mono/display ownership', () => {
    const legacy = read('src/index.css');
    const foundation = read('src/styles/foundation.css');
    assert.ok(legacy.includes('--nfc-font-display'));
    assert.ok(legacy.includes('--nfc-font-mono'));
    assert.match(foundation, /font-variant-numeric:\s*tabular-nums/);
  });

  test('the current surface system keeps the original anti-generic-card principle', () => {
    const primitives = read('src/styles/primitives.css');
    assert.match(primitives, /\.nfc-page-header[\s\S]*background:\s*transparent[\s\S]*box-shadow:\s*none/);
    assert.match(primitives, /\.nfc-metric-grid[\s\S]*gap:\s*0/);
    assert.match(primitives, /\.nfc-metric-card[\s\S]*border-radius:\s*0[\s\S]*box-shadow:\s*none/);
  });

  test('dashboard retains a deliberate main-column and operational rail composition', () => {
    const css = read('src/styles/pages/dashboard.css');
    assert.match(css, /grid-template-columns:\s*minmax\(0, 1\.82fr\)\s+minmax\(284px, 0\.58fr\)/);
    assert.ok(css.includes('.nfc-dashboard-rail'));
  });

  test('sidebar and header retain explicit workspace chrome semantics', () => {
    const sidebar = read('src/components/Sidebar.tsx');
    const header = read('src/components/Header.tsx');
    const shell = read('src/styles/shell.css');
    assert.ok(sidebar.includes('nfc-sidebar-meta'));
    assert.ok(sidebar.includes('CONTROL PLANE'));
    assert.ok(header.includes('nfc-header-workspace'));
    assert.ok(shell.includes('.nfc-sidebar.nfc-sidebar'));
    assert.ok(shell.includes('.nfc-header-workspace'));
  });

  test('dashboard content avoids a generic all-caps overview label', () => {
    const dashboard = read('src/pages/Dashboard/index.tsx');
    assert.doesNotMatch(dashboard, /eyebrow=["']OVERVIEW["']/);
    assert.match(dashboard, /eyebrow=["']Operations overview["']/);
  });

  test('current responsive layer preserves reduced-motion behavior', () => {
    const css = read('src/styles/responsive.css');
    assert.ok(css.includes('prefers-reduced-motion: reduce'));
  });

  test('historical taste-skill audit remains recorded', () => {
    const design = read('../DESIGN.md');
    assert.ok(design.includes('v0.4.2 Taste-Skill Redesign'));
    assert.ok(design.includes('reduce generic card chrome'));
  });
});
