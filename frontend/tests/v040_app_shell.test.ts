import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('v0.4.0 responsive App Shell contract', () => {
  test('semantic product tokens and responsive CSS contract exist', () => {
    const css = read('src/index.css');
    assert.match(css, /--nfc-canvas/);
    assert.match(css, /--nfc-surface-1/);
    assert.match(css, /--nfc-hairline/);
    assert.match(css, /--nfc-page-gutter/);
    assert.match(css, /@media\s*\(max-width:\s*767px\)/);
    assert.match(css, /prefers-reduced-motion/);
  });

  test('responsive hook defines mobile tablet and desktop states', () => {
    const source = read('src/hooks/useResponsive.ts');
    assert.match(source, /useBreakpoint/);
    assert.match(source, /isMobile/);
    assert.match(source, /isTablet/);
    assert.match(source, /isDesktop/);
  });

  test('navigation uses Drawer on mobile and Sider on desktop', () => {
    const source = read('src/components/layout/ResponsiveNav.tsx');
    assert.match(source, /Drawer/);
    assert.match(source, /Sidebar/);
    assert.match(source, /isMobile/);
  });

  test('MainLayout uses responsive navigation and semantic page shell classes', () => {
    const source = read('src/layouts/MainLayout.tsx');
    assert.match(source, /ResponsiveNav/);
    assert.match(source, /useResponsive/);
    assert.match(source, /nfc-app-shell/);
    assert.match(source, /nfc-page-content/);
  });

  test('Header keeps safety and worker state reachable on mobile', () => {
    const source = read('src/components/Header.tsx');
    assert.match(source, /SafeModeBadge/);
    assert.match(source, /WorkerStatusBadge/);
    assert.match(source, /mobile|isMobile/);
    assert.match(source, /aria-label=.*导航|aria-label=.*菜单/);
  });

  test('router contract remains unchanged during C1 shell work', () => {
    const source = read('src/router/index.tsx');
    for (const route of [
      'dashboard',
      'indexes',
      'scans',
      'path-match',
      'rename',
      'batch',
      'organizer',
      'workflows',
      'plans',
      'quarantine',
      'tasks',
      'audit',
      'settings',
    ]) {
      assert.match(source, new RegExp(`path=["']${route}["']`));
    }
  });
});
