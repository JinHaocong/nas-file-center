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
    const inventory = read('docs/console-v2-css-ownership.md');
    assert.ok(inventory.includes('CSS cascade'));
    assert.ok(inventory.includes('index.css'));
    assert.ok(inventory.includes('visual acceptance'));
  });

  test('no application code or immutable plan security workflows change in this tranche', () => {
    const plan = read('src/pages/Plans/PlanDetail.tsx');
    const settings = read('src/pages/Settings/index.tsx');
    assert.ok(plan.includes('ConsoleConfirmDialog'));
    assert.ok(settings.includes('canSave'));
  });
});
