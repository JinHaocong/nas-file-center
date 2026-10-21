import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 owned CSS cleanup — migration tranche 1', () => {
  test('native Console v2 and Settings CSS cannot regress to old AntD class selectors', () => {
    const names = readdirSync(resolve(process.cwd(), 'src/styles'))
      .filter(name => /^console-v2(?:-[a-z0-9-]+)?\.css$/.test(name));
    assert.ok(names.length >= 40, 'expected all Console v2 native style modules');
    for (const path of [...names.map(name => 'src/styles/' + name),
      'src/styles/pages/settings.css']) {
      assert.doesNotMatch(read(path), /\.ant-[a-z][a-z0-9-]*/i, path);
    }
    const guard = read('scripts/check-console-css-ownership.mjs');
    assert.ok(guard.includes("readdirSync(root)"));
    assert.ok(guard.includes("'settings:pages/settings.css'"));
    assert.ok(guard.includes("if (errors.length) process.exitCode = 1"));
    assert.ok(read('scripts/run-tests.mjs').includes(
      'node scripts/check-console-css-ownership.mjs'));
  });

  test('Settings retains native grid, control and session layout including breakpoints', () => {
    const css = read('src/styles/pages/settings.css');
    for (const text of [
      '.nfc-settings-grid', '.nfc-settings-panel-runtime',
      '.nfc-settings-panel-lifecycle', '.nfc-settings-panel-resource',
      '.nfc-settings-panel-sessions', '.nfc-settings-retention-actions',
      '.nfc-settings-subpanel-danger', '.nfc-settings-resource-controls',
      '.nfc-settings-inline-control', '.nfc-data-panel-body',
      '.nfc-settings-subpanel > .nfc-action-bar > span',
      '@media (max-width: 1199px)', '@media (max-width: 900px)',
      '@media (max-width: 767px)', '@media (max-width: 520px)',
      '@media (max-width: 480px)',
    ]) assert.ok(css.includes(text), text);
    assert.ok(read('src/main.tsx').includes(
      "import './styles/pages/settings.css';"));
    assert.ok(read('src/main.tsx').includes(
      "import './styles/console-v2-settings.css';"));
  });

  test('console shell retains native semantic status colors, accessible focus, dark theme and mobile controls', () => {
    const css = read('src/styles/console-v2.css');
    for (const token of [
      '.nfc-v2-shell', '.nfc-v2-header',
      '.nfc-v2-header .nfc-header-status-badge.is-safe',
      '.nfc-v2-header .nfc-header-status-badge.is-danger',
      "[data-theme='dark'] .nfc-v2-header",
      ':focus-visible', '@media (max-width: 767px)',
      '@media (prefers-reduced-motion: reduce)',
    ]) assert.ok(css.includes(token), token);
    const inventory = read('../docs/console-v2-css-ownership.md');
    assert.ok(inventory.includes('CSS cascade'));
    assert.ok(inventory.includes('index.css'));
    assert.ok(inventory.includes('visual acceptance'));
  });

  test('Media, Indexes and Audit retain neutral fallback surfaces without legacy blue', () => {
    const specs = [
      { path: 'src/styles/console-v2-media.css', count: 22,
        roots: ['--v2-indigo,#262625', '--v2-indigo,#e9e9e6',
          '--nfc-surface-2,#f7f7f5', '--nfc-surface-2,#2d2d2a'] },
      { path: 'src/styles/console-v2-indexes.css', count: 22,
        roots: ['--v2-indigo,#262625', '--v2-indigo,#e9e9e6',
          '--nfc-surface-1,#ffffff', '--nfc-surface-1,#242422'] },
      { path: 'src/styles/console-v2-audit-and-worker.css', count: 18,
        roots: ['--v2-indigo,#262625', '--v2-indigo,#e9e9e6',
          '--nfc-surface-1,#ffffff', '--nfc-surface-1,#242422'] },
    ];
    let count = 0;
    for (const { path, count: expected, roots } of specs) {
      const css = read(path);
      const fallback = [...css.matchAll(/var\(--[a-z0-9-]+,#[0-9a-f]{3,8}\)/gi)];
      assert.equal(fallback.length, expected, 'Unexpected native fallback inventory: ' + path);
      count += fallback.length;
      assert.doesNotMatch(css, /#(?:286ff1|83b5ff|1a2434|222e41|111827|36435a|2c3a4e|172338|182438|f1f5fb|afbdce)\b/i, path);
      for (const token of roots) assert.ok(css.includes(token), path + ': ' + token);
      assert.ok(css.includes("[data-theme='dark']"), 'Missing independent dark theme: ' + path);
    }
    assert.equal(count, 62);
    // The three owned modules consume the existing neutral aliases: do not
    // overwrite global theme tokens or turn danger/success into monochrome.
    const shell = read('src/styles/console-v2.css');
    for (const token of ['--v2-indigo: #252525', '--v2-indigo: #e9e9e6',
      '--v2-paper: #ffffff', '--v2-paper: #242422']) {
      assert.ok(shell.includes(token), 'Missing source-of-truth alias ' + token);
    }
    const media = read('src/styles/console-v2-media.css');
    assert.ok(media.includes('.nfc-v2-media-status.is-corrupt'));
    assert.ok(media.includes('.nfc-v2-media-status.is-healthy'));
    const main = read('src/main.tsx');
    for (const token of ['console-v2-media.css', 'console-v2-indexes.css',
      'console-v2-audit-and-worker.css']) {
      assert.ok(main.includes("import './styles/" + token + "';"), token);
    }
    // These are opaque neutral fallbacks. Preserve AA text and 3:1 focus
    // contrast if a top-level alias is unavailable in a detached portal.
    const luminance = (hex: string) => {
      const values = hex.replace('#', '').match(/.{2}/g);
      assert.ok(values && values.length === 3);
      const rgb = values.map(v => {
        const c = parseInt(v, 16) / 255;
        return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
      });
      return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722;
    };
    const ratio = (first: string, second: string) => {
      const [high, low] = [luminance(first), luminance(second)].sort((a, b) => b - a);
      return (high + 0.05) / (low + 0.05);
    };
    for (const [surface, textColor, focus] of [
      ['#ffffff', '#20201f', '#262625'],
      ['#242422', '#f5f5f2', '#e9e9e6'],
    ]) {
      assert.ok(ratio(surface, textColor) >= 4.5);
      assert.ok(ratio(surface, focus) >= 3);
    }
  });

  test('no application code or immutable plan security workflows change in this tranche', () => {
    const plan = read('src/pages/Plans/PlanDetail.tsx');
    const settings = read('src/pages/Settings/index.tsx');
    assert.ok(plan.includes('ConsoleConfirmDialog'));
    assert.ok(settings.includes('canSave'));
  });
});
