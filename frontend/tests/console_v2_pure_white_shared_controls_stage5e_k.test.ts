import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { isSelectableConsoleOption } from '../src/components/ui/selectModel';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const select = read('src/components/ui/ConsoleSelect.tsx');
const confirm = read('src/components/ui/ConsoleConfirmDialog.tsx');
const tasks = read('src/pages/Tasks/index.tsx');
const quarantine = read('src/pages/Quarantine/index.tsx');
const taskActions = read('src/components/tasks/TaskActionBar.tsx');
const taskDelete = read('src/components/tasks/TaskDeleteButton.tsx');
const workflow = read('../.github/workflows/ui-v044-validation.yml');

describe('Pure White Stage 5E-K native shared control fail-closed safety', () => {
  test('accepts only exactly one currently enabled option', () => {
    const options = Object.freeze([
      { value: 'all', disabled: false },
      { value: 'running' },
      { value: 'archived', disabled: true },
    ]);
    assert.equal(isSelectableConsoleOption('all', options), true);
    assert.equal(isSelectableConsoleOption('running', options), true);
    assert.equal(isSelectableConsoleOption('archived', options), false);
    assert.equal(isSelectableConsoleOption('gone', options), false);
    assert.equal(isSelectableConsoleOption('', options), false);
    assert.equal(isSelectableConsoleOption('all', []), false);
    assert.equal(isSelectableConsoleOption('all', [
      { value: 'all' }, { value: 'all', disabled: true },
    ]), false, 'duplicate identities are ambiguous, including disabled duplicates');
    assert.equal(isSelectableConsoleOption('all', [
      { value: 'all' }, { value: 'all' },
    ]), false);
    assert.equal(isSelectableConsoleOption('running', options), true);
    assert.equal(options.length, 3, 'predicate must not mutate caller options');
  });

  test('ConsoleSelect still uses native select, but rejects disabled, stale and ambiguous events', () => {
    for (const needle of [
      'export interface ConsoleSelectOption { value: string; label: string; disabled?: boolean; }',
      'options: readonly ConsoleSelectOption[]',
      'disabled={disabled}',
      'aria-label={label}',
      'const next = event.currentTarget.value;',
      'if (!disabled && isSelectableConsoleOption(next, options)) onChange(next);',
      'disabled={option.disabled}',
      '<select',
      'htmlFor={id}',
    ]) assert.ok(select.includes(needle), needle);
    assert.doesNotMatch(select, /from ['"]antd['"]|<Dropdown\b|<div role="listbox"/);
    assert.ok(tasks.includes('<ConsoleSelect id="nfc-task-status-filter"'));
    assert.ok(tasks.includes('<ConsoleSelect id="nfc-task-type-filter"'));
    assert.ok(quarantine.includes('<ConsoleSelect id="quarantine-state-filter"'));
  });

  test('shared confirmation blocks cancel and confirm callback when busy and blocks confirmation when disabled', () => {
    for (const needle of [
      'if (!busy) onOpenChange(next);',
      'onEscapeKeyDown={event => { if (busy) event.preventDefault(); }}',
      'onPointerDownOutside={event => event.preventDefault()}',
      'disabled={busy}',
      'disabled={busy || disabled} loading={busy}',
      'onClick={() => { if (!busy && !disabled) onConfirm(); }}',
      'onClick={() => { if (!busy) onOpenChange(false); }}',
    ]) assert.ok(confirm.includes(needle), needle);
    assert.equal((confirm.match(/onClick=\{\(\) => \{ if \(!busy\) onOpenChange\(false\); \}\}/g) || []).length,
      2, 'both close button and Cancel action must be busy-guarded');
    assert.doesNotMatch(confirm, /onClick=\{onConfirm\}|onClick=\{\(\) => onOpenChange\(false\)\}/);
    assert.ok(taskDelete.includes('disabled={!availability.enabled}'));
    assert.ok(taskDelete.includes('busy={deleteMutation.isPending}'));
    assert.ok(taskActions.includes('disabled={confirmAction ==='));
    assert.ok(taskActions.includes('busy={isAnyPending}'));
  });

  test('existing permission checks and Plan/Quarantine confirmation authority remain caller-owned', () => {
    for (const needle of [
      'onOpenChange={closeCleanup}',
      'confirmText="删除记录" busy={cleanupBusy}',
      'selectedEntryIds.length === 0 || !isAdmin || isSafeMode || !allowDelete',
    ]) assert.ok(quarantine.includes(needle), needle);
    assert.ok(taskDelete.includes('getTaskDeleteAvailability(task)'));
    assert.ok(taskActions.includes('getTaskActionAvailability('));
    assert.doesNotMatch(select + confirm, /fetch\(|useMutation|quarantineApi|tasksApi|deleteTask\(/);
  });

  test('full exact-HEAD browser overlay and dense-page matrix remains in CI', () => {
    for (const script of [
      'node scripts/browser-overlay-smoke.mjs',
      'node scripts/browser-task-overlays.mjs',
      'node scripts/browser-quarantine-plan-overlays.mjs',
      'node scripts/browser-quarantine-bulk-overlays.mjs',
      'node scripts/browser-workspace-cascade.mjs',
      'node scripts/browser-task-ledger-states.mjs',
      'node scripts/browser-indexes-ledger-states.mjs',
      'node scripts/browser-media-ledger-states.mjs',
    ]) assert.ok(workflow.includes(script), script);
    assert.ok(workflow.includes('Checkout exact candidate HEAD'));
    assert.ok(workflow.includes('Verify candidate identity'));
    const chromium = read('scripts/browser-workspace-cascade.mjs');
    for (const needle of [
      "request.method() !== 'GET'",
      'assert.deepEqual(writes, []',
      'assert.deepEqual(outbound, []',
      '32/32 cases, 352 screenshots',
    ]) assert.ok(chromium.includes(needle), needle);
  });
});
