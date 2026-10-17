import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const tasks = read('src/components/tasks/TaskHistoryCleanupModal.tsx');
const plans = read('src/components/plans/PlanHistoryCleanupModal.tsx');
const checkbox = read('src/components/ui/ConsoleCheckbox.tsx');
const ci = read('../.github/workflows/ui-v044-validation.yml');

describe('Stage 5E-L terminal-history modal native control and single-flight safety', () => {
  test('Tasks history synchronously locks duplicate confirmation until awaited mutation settles', () => {
    for (const token of [
      'const submitting = useRef(false)',
      'if (submitting.current || cleanupMutation.isPending || selectedStatuses.length === 0) return',
      'const selected = TERMINAL_OPTIONS.map(option => option.value)',
      '.filter(status => selectedStatuses.includes(status))',
      'if (selected.length === 0) return',
      'submitting.current = true',
      'await cleanupMutation.mutateAsync(selected)',
      'submitting.current = false',
      'const closeSafely = () =>',
      'if (!submitting.current && !cleanupMutation.isPending) setOpen(false)',
      'onClick={closeSafely}',
      'if (!cleanupMutation.isPending && !submitting.current) setOpen(next)',
      'if (cleanupMutation.isPending || submitting.current) event.preventDefault()',
      'onPointerDownOutside={event => event.preventDefault()}',
    ]) assert.ok(tasks.includes(token), token);
    assert.doesNotMatch(tasks, /cleanupMutation\.mutate\(/,
      'Task cleanup must await the single-flight mutation rather than fire-and-forget');
    assert.equal((tasks.match(/onClick=\{closeSafely\}/g) || []).length, 2);
  });

  test('Plan history uses its existing synchronous lock for both buttons and controlled dismissal', () => {
    for (const token of [
      'const submitting = useRef(false)',
      'const closeSafely = () =>',
      'if (!cleanupMutation.isPending && !submitting.current) setOpen(false)',
      'if (submitting.current || cleanupMutation.isPending) return',
      'if (submitting.current || selectedStatuses.length === 0) return',
      'submitting.current = true',
      'await cleanupMutation.mutateAsync(selected)',
      'submitting.current = false',
      'if (!cleanupMutation.isPending && !submitting.current) setOpen(next)',
      'if (cleanupMutation.isPending || submitting.current) event.preventDefault()',
      'onPointerDownOutside={event => event.preventDefault()}',
    ]) assert.ok(plans.includes(token), token);
    assert.equal((plans.match(/onClick=\{closeSafely\}/g) || []).length, 2);
  });

  test('both use the guarded native checkbox and preserve exact terminal status allowlists', () => {
    assert.match(checkbox, /<input \{\.\.\.props\} ref=\{ref\} type="checkbox" checked=\{checked\}/);
    assert.ok(checkbox.includes('onChange={event => {'), 'Guarded native onChange is registered');
    assert.ok(checkbox.includes('onCheckedChange(event.currentTarget.checked)'), 'Original controlled callback survives');
    assert.ok(checkbox.includes("event.currentTarget.matches(':disabled')"), 'Native disabled/fieldset guard');
    assert.ok(checkbox.includes("closest('[aria-disabled=\"true\"], [inert], [hidden]')"), 'Inert/aria-disabled ancestor guard');
    assert.match(tasks, /<ConsoleCheckbox value=\{option.value\}/);
    assert.match(tasks, /onCheckedChange=\{checked => toggle\(option.value, checked\)\}/);
    assert.match(plans, /<ConsoleCheckbox checked=\{selectedStatuses.includes\(item.value\)\}/);
    assert.match(plans, /onCheckedChange=\{checked => \{/);
    for (const state of ['completed', 'failed', 'cancelled']) {
      assert.ok(tasks.includes("value: '" + state + "'"), state);
    }
    for (const state of ['completed', 'failed']) {
      assert.ok(plans.includes("value: '" + state + "'"), state);
    }
    assert.doesNotMatch(plans, /value:\s*['"](?:draft|frozen|ready|executing|running)['"]/);
    assert.doesNotMatch(tasks, /value:\s*['"](?:queued|running|paused|cancel_requested)['"]/);
    assert.doesNotMatch(tasks + plans, /<input type="checkbox"/);
  });

  test('metadata-only warnings, API ownership and audit log protections stay intact', () => {
    for (const token of [
      'tasksApi.clearTaskHistory(statuses)',
      'selectedStatuses.length === 0',
      'Task Logs', 'Audit 审计记录', '绝不会删除',
      '不是仅清理当前分页',
      'queryClient.invalidateQueries',
    ]) assert.ok(tasks.includes(token), token);
    for (const token of [
      'plansApi.clearHistory(statuses)',
      'PLAN_HISTORY_OPTIONS.map(x => x.value)',
      '.filter(x => selectedStatuses.includes(x))',
      'Delete ≠ Undo', 'BatchPlan 及 BatchPlanItem',
      'NAS 存储上的任何文件', 'Audit 审计记录与关联的任务',
      '运行中 (validating / executing)',
    ]) assert.ok(plans.includes(token), token);
  });

  test('existing full localhost read-only Chromium suites remain on latest PR HEAD', () => {
    for (const cmd of [
      'Checkout exact candidate HEAD', 'Verify candidate identity',
      'node scripts/browser-task-overlays.mjs',
      'node scripts/browser-quarantine-plan-overlays.mjs',
      'node scripts/browser-workspace-cascade.mjs',
      'node scripts/browser-task-ledger-states.mjs',
      'node scripts/browser-indexes-ledger-states.mjs',
      'node scripts/browser-media-ledger-states.mjs',
      'Upload visual evidence',
    ]) assert.ok(ci.includes(cmd), cmd);
    const browser = read('scripts/browser-task-overlays.mjs');
    for (const token of [
      'const WIDTHS = [360, 390, 430, 768, 1024, 1280, 1440, 1920]',
      "request.method() !== 'GET'",
      'status: 405',
    ]) assert.ok(browser.includes(token), token);
  });
});
