import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { getTaskDeleteAvailability } from '../src/components/tasks/task_cleanup';
import { getScanDeleteAvailability } from '../src/components/scans/scan_cleanup';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Stage 5E-N feature-owned destructive confirmation and auth single-flight', () => {
  test('Task delete acquires a synchronous lock and awaits mutation settlement', () => {
    const source = read('src/components/tasks/TaskDeleteButton.tsx');
    for (const token of [
      'const deleteInFlight = useRef(false);',
      'if (!getTaskDeleteAvailability(task).enabled || deleteMutation.isPending || deleteInFlight.current) return;',
      'deleteInFlight.current = true;',
      'await deleteMutation.mutateAsync();',
      'deleteInFlight.current = false;',
      'onError: async (err: Error) =>',
      "queryClient.removeQueries({ queryKey: ['taskLogs', task.id] });",
      'onSuccess?.();',
    ]) assert.ok(source.includes(token), token);
    assert.ok(source.indexOf('deleteInFlight.current = true;') <
      source.indexOf('await deleteMutation.mutateAsync();'));
    assert.match(source, /try \{[\s\S]*?await deleteMutation\.mutateAsync\(\);[\s\S]*?\} catch \{[\s\S]*?\} finally \{[\s\S]*?deleteInFlight\.current = false;/);
    assert.doesNotMatch(source, /deleteMutation\.mutate\(/);
    for (const status of ['queued', 'running', 'paused', 'cancel_requested'] as const) {
      assert.equal(getTaskDeleteAvailability({ status }).enabled, false);
    }
    assert.equal(getTaskDeleteAvailability({ status: 'completed' }).enabled, true);
  });

  test('Task Confirm blocks dismissal through the pre-render lock window', () => {
    const source = read('src/components/tasks/TaskDeleteButton.tsx');
    for (const token of [
      'onOpenChange={next => { if (!deleteMutation.isPending && !deleteInFlight.current) setOpen(next); }}',
      'onConfirm={() => { void confirmDelete(); }}',
      'busy={deleteMutation.isPending}',
      'disabled={!availability.enabled || deleteMutation.isPending}',
    ]) assert.ok(source.includes(token), token);
  });

  test('Scan Delete awaits the parent request and guards close, repeated confirm and retry', () => {
    const child = read('src/components/scans/ScanDeleteButton.tsx');
    const parent = read('src/pages/Scans/index.tsx');
    for (const token of [
      'const deleteInFlight = useRef(false);',
      'const busy = loading || submitting;',
      'if (!getScanDeleteAvailability(scan).canDelete || busy || deleteInFlight.current) return;',
      'deleteInFlight.current = true;',
      'setSubmitting(true);',
      'await onDelete();',
      'setOpen(false);',
      'deleteInFlight.current = false;',
      'setSubmitting(false);',
      'onOpenChange={next => { if (!busy && !deleteInFlight.current) setOpen(next); }}',
      'onConfirm={() => { void confirmDelete(); }}',
      'busy={busy}',
      '扫描元数据',
      '不会直接删除 NAS 上的文件',
    ]) assert.ok(child.includes(token), token);
    assert.equal(parent.split('onDelete={() => deleteScanMutation.mutateAsync(scan.id)}').length - 1, 2);
    assert.doesNotMatch(parent, /deleteScanMutation\.mutate\(scan\.id\)/);
    for (const status of ['queued', 'running']) {
      assert.equal(getScanDeleteAvailability({ status }).canDelete, false);
    }
    assert.equal(getScanDeleteAvailability({ status: 'completed', has_dependent_plan: true }).canDelete, false);
  });

  test('Password change single-flight protects submit, close, Escape and field mutations', () => {
    const source = read('src/components/ChangePasswordModal.tsx');
    for (const token of [
      'const submitLock = useRef(false);',
      'if (submitting || submitLock.current) return;',
      'submitLock.current = true;',
      'await authApi.changePassword({',
      'submitLock.current = false;',
      'if (!next && !submitting && !submitLock.current) close();',
      'onEscapeKeyDown={event => { if (submitting || submitLock.current) event.preventDefault(); }}',
      'if (!submitLock.current) setOldPassword(event.target.value)',
      'if (!submitLock.current) setNewPassword(event.target.value)',
      'if (!submitLock.current) setConfirmPassword(event.target.value)',
      "toast.success('密码修改成功，其他设备会话已安全注销')",
      'old_password: oldPassword',
      'new_password: newPassword',
    ]) assert.ok(source.includes(token), token);
    assert.equal(source.split('if (submitting || submitLock.current) return;').length - 1, 2);
    assert.ok(source.indexOf('submitLock.current = true;') <
      source.indexOf('await authApi.changePassword({'));
    assert.match(source, /try \{[\s\S]*?await authApi\.changePassword\([\s\S]*?\} finally \{\s*submitLock\.current = false;/);
  });

  test('Existing read-only Chromium evidence remains isolated from NAS mutations', () => {
    const ci = read('../.github/workflows/ui-v044-validation.yml');
    const runner = read('scripts/browser-task-overlays.mjs');
    for (const token of [
      'Checkout exact candidate HEAD',
      'Verify candidate identity',
      'node scripts/browser-task-overlays.mjs',
      'node scripts/browser-workspace-cascade.mjs',
      'node scripts/browser-media-ledger-states.mjs',
      'Upload visual evidence',
    ]) assert.ok(ci.includes(token), token);
    assert.match(runner, /request\.method\(\) !== 'GET'/);
    assert.ok(runner.includes('status: 405'));
  });
});
