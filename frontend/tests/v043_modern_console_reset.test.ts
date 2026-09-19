import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.3 console invariants carried into v0.4.7', () => {
  test('theme remains a blue-accent neutral control plane rather than returning to jade', () => {
    const tokens = read('src/design/tokens.ts');
    assert.match(tokens, /accent:\s*'#[0-9A-F]{6}'/);
    assert.doesNotMatch(tokens, /#167a5c/i);
    assert.doesNotMatch(tokens, /#4fd1a1/i);
  });

  test('desktop sidebar remains the deliberate elevated navigation anchor', () => {
    const css = read('src/styles/shell.css');
    assert.match(css, /\.nfc-sidebar\.nfc-sidebar[\s\S]*background:\s*var\(--nfc-nav-surface\) !important/);
    assert.match(css, /\.nfc-sidebar\.nfc-sidebar[\s\S]*box-shadow:/);
  });

  test('mobile navigation retains a persistent bottom dock with primary routes and More', () => {
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
    const css = read('src/index.css') + read('src/styles/responsive.css');
    assert.ok(css.includes('--nfc-mobile-dock-height'));
    assert.match(css, /padding-bottom:\s*calc\([^;]*var\(--nfc-mobile-dock-height\)/);
  });

  test('header remains a compact command surface but is integrated instead of floating', () => {
    const header = read('src/components/Header.tsx');
    const css = read('src/styles/shell.css');
    assert.match(header, /nfc-header-workspace/);
    assert.match(header, /nfc-header-command-cluster/);
    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*border-bottom:\s*1px solid var\(--nfc-border-soft\)/);
    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*border-radius:\s*0/);
    assert.match(css, /\.nfc-header\.nfc-header[\s\S]*box-shadow:\s*none/);
  });

  test('data surfaces use restrained table chrome and compact density', () => {
    const css = read('src/styles/primitives.css');
    assert.match(css, /\.nfc-data-panel \.ant-table-thead > tr > th[\s\S]*text-transform:\s*none/);
    assert.match(css, /\.nfc-data-panel-dense[\s\S]*box-shadow:\s*none/);
  });

  test('task worker status retains a compact status strip', () => {
    const worker = read('src/components/tasks/WorkerStatusCard.tsx');
    assert.match(worker, /nfc-worker-status-strip/);
    assert.match(worker, /nfc-worker-primary/);
    assert.match(worker, /nfc-worker-stat/);
  });

  test('mobile task cards remain a dedicated mobile representation', () => {
    const page = read('src/pages/Tasks/index.tsx');
    assert.match(page, /nfc-task-mobile-card/);
    assert.match(page, /nfc-mobile-record-actions/);
  });

  test('historical design notes remain available for context', () => {
    const design = read('../DESIGN.md');
    assert.ok(design.includes('v0.4.3 Modern Console Reset'));
    assert.ok(design.includes('Vercel Geist'));
    assert.ok(design.includes('Raycast'));
    assert.ok(design.includes('mobile bottom dock'));
  });
});
