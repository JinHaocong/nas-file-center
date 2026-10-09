import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { getTaskDeleteAvailability } from '../src/components/tasks/task_cleanup';
import { getTaskActionAvailability } from '../src/components/tasks/task_actions';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 Task Center Radix overlays', () => {
  test('the detail inspector is a controlled Radix sheet without Ant Drawer/Descriptions', () => {
    const drawer = read('src/components/tasks/TaskDetailDrawer.tsx');
    const sheet = read('src/components/ui/ConsoleSheet.tsx');
    for (const token of ['ConsoleSheet', 'TaskProgress', 'TaskLogTable',
      'TaskDeleteButton', 'TaskActionBar', 'nfc-overlay-section',
      'nfc-code-block', 'sanitizeContext', 'calculateTaskEta',
      'taskDetail', 'return isActive ? 3000 : false']) {
      assert.ok(drawer.includes(token), token);
    }
    assert.match(sheet, /<Dialog.Root/);
    assert.match(sheet, /<Dialog.Portal>/);
    assert.match(sheet, /<Dialog.Content/);
    assert.match(sheet, /<Dialog.Close asChild>/);
    assert.match(sheet, /aria-label="关闭详情抽屉"/);
    assert.match(drawer, /<TaskLogTable key=\{task.id\} taskId=\{task.id\}/);
    assert.match(drawer, /<TaskDeleteButton key=\{task.id\}/);
    assert.match(drawer, /<TaskActionBar key=\{task.id\}/);
    assert.doesNotMatch(drawer, /from ['"]antd['"]|<Drawer\b|<Descriptions\b/);
  });

  test('task deletion requires a terminal status and an explicit protected confirm', () => {
    const button = read('src/components/tasks/TaskDeleteButton.tsx');
    const dialog = read('src/components/ui/ConsoleConfirmDialog.tsx');
    for (const status of ['queued', 'running', 'paused', 'cancel_requested'] as const) {
      assert.equal(getTaskDeleteAvailability({ status }).enabled, false, status);
    }
    for (const status of ['completed', 'failed', 'cancelled'] as const) {
      assert.equal(getTaskDeleteAvailability({ status }).enabled, true, status);
    }
    for (const token of [
      'getTaskDeleteAvailability(task)', 'disabled={!availability.enabled}',
      'if (!availability.enabled || deleteMutation.isPending) return',
      'tasksApi.deleteTask(task.id)', 'invalidateQueries',
      "queryClient.removeQueries({ queryKey: ['taskDetail', task.id] })",
      "queryClient.removeQueries({ queryKey: ['taskLogs', task.id] })",
      'onSuccess?.()', '<ConsoleConfirmDialog',
    ]) assert.ok(button.includes(token), token);
    assert.match(dialog, /onEscapeKeyDown=/);
    assert.match(dialog, /onPointerDownOutside=\{event => event.preventDefault\(\)\}/);
    assert.match(dialog, /if \(!busy\) onOpenChange\(next\)/);
    assert.match(dialog, /disabled=\{busy \|\| disabled\}/);
    assert.doesNotMatch(button, /from ['"]antd['"]|<Popconfirm/);
  });

  test('history cleanup retains terminal-only selection, warnings and busy lock', () => {
    const modal = read('src/components/tasks/TaskHistoryCleanupModal.tsx');
    for (const status of ['completed', 'failed', 'cancelled']) {
      assert.ok(modal.includes("value: '" + status + "'"), status);
    }
    for (const safety of [
      'selectedStatuses.length === 0',
      'cleanupMutation.isPending', 'tasksApi.clearTaskHistory(statuses)',
      'queryClient.invalidateQueries',
      'Task Logs', 'Audit 审计记录', '绝不会删除',
      '不是仅清理当前分页', 'onCleaned?.()', '<Dialog.Overlay',
      'onPointerDownOutside={event => event.preventDefault()}',
    ]) assert.ok(modal.includes(safety), safety);
    assert.doesNotMatch(modal, /from ['"]antd['"]|<Modal\b|<Checkbox.Group/);
    assert.match(modal, /<input type="checkbox"/);
  });

  test('cancel and retry require secondary confirmation, while pause/resume stay gated', () => {
    const actions = read('src/components/tasks/TaskActionBar.tsx');
    assert.equal(getTaskActionAvailability({
      status: 'completed',
      capabilities: { supports_pause: true, supports_resume: true, supports_cancel: true, supports_retry: true },
    }, 'cancel').enabled, false);
    for (const token of [
      "getTaskActionAvailability(task, 'pause')",
      "getTaskActionAvailability(task, 'resume')",
      "getTaskActionAvailability(task, 'cancel')",
      "getTaskActionAvailability(task, 'retry')",
      'if (confirmAction ===',
      '<ConsoleConfirmDialog',
      'tasksApi.pauseTask(task.id)', 'tasksApi.resumeTask(task.id)',
      'tasksApi.cancelTask(task.id)', 'tasksApi.retryTask(task.id)',
      'onViewTask(id)',
      'setCreatedRetryId(res.job.id)',
      'return',
    ]) assert.ok(actions.includes(token), token);
    assert.doesNotMatch(actions, /from ['"]antd['"]|<Popconfirm\b|notification\.success/);
  });

  test('event log panel uses native responsive table with sanitized expandable context', () => {
    const log = read('src/components/tasks/TaskLogTable.tsx');
    for (const token of [
      'useResponsive', 'nfc-task-log-mobile-list', 'nfc-task-log-mobile-card',
      'nfc-v2-log-table', '<ConsoleSelect', '<ConsolePagination',
      "queryKey: ['taskLogs', taskId, page, pageSize, level]",
      'sanitizeContext(record.context)', 'getTaskLogs(taskId',
      'setPage(1)', 'setExpandedRowKeys([])', "aria-expanded={expanded}",
    ]) assert.ok(log.includes(token), token);
    assert.doesNotMatch(log, /from ['"]antd['"]|<Table\b|<Pagination\b|<Tag\b/);
    assert.match(log, /pageSizes=\{\[20, 50, 100\]\}/);
  });

  test('portal-specific themed CSS supports nested modals and mobile sheets', () => {
    const css = read('src/styles/console-v2-task-overlays.css');
    const main = read('src/main.tsx');
    for (const token of [
      '.nfc-v2-sheet-overlay', '.nfc-v2-confirm-overlay',
      'z-index: 1301', '.nfc-v2-sheet.nfc-overlay-drawer',
      '.nfc-v2-task-facts', '.nfc-v2-task-context',
      '.nfc-v2-history-statuses', '.nfc-v2-log-table',
      "[data-theme='dark']", '@media (max-width: 767px)',
      'prefers-reduced-motion: reduce',
    ]) assert.ok(css.includes(token), token);
    assert.ok(main.indexOf("import './styles/console-v2-task-overlays.css';") >
      main.indexOf("import './styles/console-v2-tasks.css';"));
  });
});
