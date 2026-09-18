import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.3 modern console reset', () => {
  test('theme leaves jade behind for an electric blue product accent', () => {
    const tokens = read('src/design/tokens.ts');
    assert.match(tokens, /accent:\s*'#0A84FF'/);
    assert.match(tokens, /accent:\s*'#4DA3FF'/);
    assert.doesNotMatch(tokens, /#167a5c/i);
    assert.doesNotMatch(tokens, /#4fd1a1/i);
  });

  test('desktop navigation is a light floating workspace rail instead of a permanent dark slab', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('/* v0.4.3 Modern Console Reset */'));
    assert.ok(css.includes('--nfc-nav-surface'));
    assert.ok(css.includes('.nfc-sidebar.nfc-sidebar'));
    assert.ok(css.includes('background: var(--nfc-nav-surface) !important'));
    assert.ok(css.includes('box-shadow: var(--nfc-shell-shadow)'));
  });

  test('mobile navigation has a persistent bottom dock with primary routes and More', () => {
    const layout = read('src/layouts/MainLayout.tsx');
    const dock = read('src/components/layout/MobileDock.tsx');
    assert.match(layout, /<MobileDock/);
    assert.match(dock, /\/dashboard/);
    assert.match(dock, /\/scans/);
    assert.match(dock, /\/plans/);
    assert.match(dock, /\/tasks/);
    assert.match(dock, /更多/);
    assert.match(dock, /nfc-mobile-dock/);
  });

  test('mobile page content reserves safe space for the bottom dock', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('--nfc-mobile-dock-height'));
    assert.match(css, /padding-bottom:\s*calc\([^;]*var\(--nfc-mobile-dock-height\)/);
  });

  test('header becomes a compact command bar rather than a traditional admin toolbar', () => {
    const header = read('src/components/Header.tsx');
    const css = read('src/index.css');
    assert.match(header, /nfc-header-workspace/);
    assert.match(header, /nfc-header-command-cluster/);
    assert.ok(css.includes('.nfc-header.nfc-header'));
    assert.ok(css.includes('border: 1px solid var(--nfc-workspace-hairline)'));
  });

  test('data surfaces avoid heavy gray table chrome', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-data-panel .ant-table-thead > tr > th'));
    assert.ok(css.includes('background: transparent !important'));
    assert.ok(css.includes('.nfc-data-panel'));
    assert.ok(css.includes('border-radius: var(--nfc-surface-radius)'));
  });

  test('task worker status uses a compact premium status strip', () => {
    const worker = read('src/components/tasks/WorkerStatusCard.tsx');
    assert.match(worker, /nfc-worker-status-strip/);
    assert.match(worker, /nfc-worker-primary/);
    assert.match(worker, /nfc-worker-stat/);
  });

  test('mobile task cards avoid desktop-table visual density', () => {
    const css = read('src/index.css');
    assert.ok(css.includes('.nfc-task-mobile-card'));
    assert.ok(css.includes('border-radius: 18px'));
    assert.ok(css.includes('.nfc-mobile-record-actions'));
  });

  test('design notes record the new product direction and references', () => {
    const design = read('../DESIGN.md');
    assert.ok(design.includes('v0.4.3 Modern Console Reset'));
    assert.ok(design.includes('Vercel Geist'));
    assert.ok(design.includes('Raycast'));
    assert.ok(design.includes('mobile bottom dock'));
  });
});
