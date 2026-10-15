import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { dispatchTaskActionOnce } from '../src/components/tasks/task_action_single_flight';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const source = read('src/components/tasks/TaskActionBar.tsx');
const allCaps = { supports_pause: true, supports_resume: true, supports_cancel: true, supports_retry: true };

describe('Pure White Stage 5E-V Task action synchronous single-flight fence', () => {
  test('second Retry/Cancel is blocked synchronously while first request awaits settlement', async () => {
    const lock = { current: false };
    let resolveFirst!: () => void;
    const pending = new Promise<void>(resolve => { resolveFirst = resolve; });
    let calls = 0;
    let starts = 0;
    let finishes = 0;
    const start = () => { starts += 1; };
    const finish = () => { finishes += 1; };
    const task = { status: 'failed' as const, capabilities: allCaps };
    const first = dispatchTaskActionOnce(lock, task, 'retry', () => { calls += 1; return pending; }, start, finish);
    assert.equal(lock.current, true, 'acquires the lock before yielding to React/Promises');
    assert.equal(starts, 1);
    assert.equal(await dispatchTaskActionOnce(lock, task, 'retry', async () => { calls += 1; }, start, finish), false);
    assert.equal(await dispatchTaskActionOnce(lock, { status: 'running', capabilities: allCaps }, 'cancel', async () => { calls += 1; }, start, finish), false);
    assert.equal(calls, 1, 'only first mutation may dispatch');
    resolveFirst();
    assert.equal(await first, true);
    assert.equal(lock.current, false);
    assert.equal(finishes, 1);
    assert.equal(await dispatchTaskActionOnce(lock, task, 'retry', async () => { calls += 1; }, start, finish), true);
    assert.equal(calls, 2, 'once settled, a retry is possible subject to latest policy/server gate');
    assert.equal(finishes, 2);
  });

  test('denied task status/capability never acquires lock or invokes mutation callbacks', async () => {
    const lock = { current: false };
    let calls = 0;
    const bad = { status: 'completed' as const, capabilities: allCaps };
    for (const action of ['pause', 'resume', 'cancel', 'retry'] as const) {
      assert.equal(await dispatchTaskActionOnce(lock, bad, action,
        async () => { calls += 1; }, () => { calls += 1; }, () => { calls += 1; }), false);
      assert.equal(lock.current, false);
    }
    assert.equal(await dispatchTaskActionOnce(lock, null, 'retry', async () => { calls += 1; },
      () => { calls += 1; }, () => { calls += 1; }), false);
    assert.equal(calls, 0);
  });

  test('error and synchronous callback throw release the lock and allow an explicit retry', async () => {
    const lock = { current: false };
    const task = { status: 'running' as const, capabilities: allCaps };
    let finishCount = 0;
    await assert.rejects(dispatchTaskActionOnce(lock, task, 'pause', async () => { throw Error('network'); },
      () => {}, () => { finishCount += 1; }), /network/);
    assert.equal(lock.current, false);
    await assert.rejects(dispatchTaskActionOnce(lock, task, 'pause', async () => {},
      () => { throw Error('start callback'); }, () => { finishCount += 1; }), /start callback/);
    assert.equal(lock.current, false);
    assert.equal(finishCount, 2);
    assert.equal(await dispatchTaskActionOnce(lock, task, 'pause', async () => {},
      () => {}, () => { finishCount += 1; }), true);
    assert.equal(finishCount, 3);
  });

  test('four Task actions, confirmation close and source contracts share the same sync lock', () => {
    for (const token of [
      'const actionInFlight = useRef(false);',
      'const isAnyPending = activeAction !== null || actionInFlight.current;',
      'if (activeAction !== null || actionInFlight.current) return;',
      'void dispatchTaskActionOnce(',
      "dispatch('pause', () => pauseMutation.mutateAsync())",
      "dispatch('resume', () => resumeMutation.mutateAsync())",
      "dispatch('cancel', () => cancelMutation.mutateAsync())",
      "dispatch('retry', () => retryMutation.mutateAsync())",
      'if (!next && !isAnyPending && !actionInFlight.current) setConfirmAction(null);',
      "getTaskActionAvailability(task, 'retry')",
      'onError: async (error: Error) =>',
      "queryClient.invalidateQueries({ queryKey: ['taskDetail', task.id] })",
      'setCreatedRetryId(res.job.id)',
    ]) assert.ok(source.includes(token), token);
    assert.equal(source.split('onError: async (error: Error) =>').length - 1, 4);
    assert.doesNotMatch(source, /(?:pause|resume|cancel|retry)Mutation\.mutate\(/);
    const ci = read('../.github/workflows/ui-v044-validation.yml');
    const browser = read('scripts/browser-task-overlays.mjs');
    assert.ok(ci.includes('node scripts/browser-task-overlays.mjs'));
    assert.ok(browser.includes("request.method() !== 'GET'"));
    assert.ok(browser.includes('assert.deepEqual(writes, []'));
  });
});
