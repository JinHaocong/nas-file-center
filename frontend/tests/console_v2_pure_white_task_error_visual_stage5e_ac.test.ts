import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const drawer = read('src/components/tasks/TaskDetailDrawer.tsx');
const css = read('src/styles/console-v2-task-overlays.css');
const browser = read('scripts/browser-task-ledger-states.mjs');
const shared = read('scripts/visual-fixtures.mjs');

describe('Pure White Stage 5E-AC Task error visual density and shared safe fixture', () => {
  test('long diagnostics are compact until expanded, but the complete original text remains', () => {
    for (const token of [
      'const LONG_ERROR_THRESHOLD = 240;',
      'const ERROR_PREVIEW_CHARS = 160;',
      'task.error.length > LONG_ERROR_THRESHOLD',
      'task.error.slice(0, ERROR_PREVIEW_CHARS)',
      '<details className="nfc-v2-task-error-details">',
      '<summary>', '展开完整错误信息', '收起完整错误信息',
      '<p className="nfc-prewrap-error">{task.error}</p>',
      'role="alert"', '<TaskActionBar key={task.id} task={task}',
    ]) assert.ok(drawer.includes(token), token);
    for (const token of [
      '-webkit-line-clamp: 3', 'summary:focus-visible',
      '[open] .nfc-v2-task-error-collapse', 'overflow-wrap: anywhere',
    ]) assert.ok(css.includes(token), token);
  });

  test('32-case read-only Chromium checks compact/expanded geometries and keyboard Enter', () => {
    for (const token of [
      '360, 390, 430, 768, 1024, 1280, 1440, 1920',
      "mode: 'system', system: 'dark', effective: 'dark'",
      "mode === 'drawer' || mode === 'drawer-expanded'",
      'alertRect.height <= 210', 'Compact error must leave Execution visible',
      "sheet.locator('.nfc-v2-task-error-details')",
      "await disclosure.locator('summary').focus();",
      "await page.keyboard.press('Enter');",
      "await disclosure.locator('.nfc-prewrap-error').innerText(), LONG_ERROR",
      "'expanded-error-' + label", "'long-error-' + label",
      '32/32 cases, 160 screenshots',
      "request.method() !== 'GET'", 'status: 405',
      'assert.deepEqual(writes, []', 'assert.deepEqual(outbound, []',
    ]) assert.ok(browser.includes(token), token);
    const workflow = read('../.github/workflows/ui-v044-validation.yml');
    assert.ok(workflow.includes('node scripts/browser-task-ledger-states.mjs'));
    assert.ok(workflow.includes('Install and verify Chinese screenshot fonts'));
  });

  test('three routes consume shared deterministic defaults without relaxing write denial', () => {
    for (const token of [
      'visualAdminFixture(username)', 'visualSafeSettingsFixture()',
      'allow_mutation: false', 'allow_delete: false', 'safe_mode: true',
      'visualViewports = Object.freeze', 'visualThemes = Object.freeze',
      "'2026-10-12T08:30:00Z'",
    ]) assert.ok(shared.includes(token), token);
    for (const path of [
      'scripts/browser-task-ledger-states.mjs',
      'scripts/browser-indexes-ledger-states.mjs',
      'scripts/browser-workspace-cascade.mjs',
    ]) {
      const source = read(path);
      for (const token of [
        "from './visual-fixtures.mjs'", 'visualAdminFixture(', 'visualSafeSettingsFixture()',
        'const WIDTHS = visualViewports', 'const THEMES = visualThemes',
        "request.method() !== 'GET'", 'status: 405', 'url.origin !== BASE',
      ]) assert.ok(source.includes(token), path + ': ' + token);
    }
  });
});
