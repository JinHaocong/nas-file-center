import assert from 'node:assert/strict';
import { describe, test } from 'node:test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { getPaginationState } from '../src/components/ui/paginationModel';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 Task Center native UI migration', () => {
  test('task page removes Ant table select pagination tooltip and buttons', () => {
    const source = read('src/pages/Tasks/index.tsx');
    assert.doesNotMatch(source, /from ['"]antd['"]|from ['"]@ant-design\/icons['"]/);
    assert.doesNotMatch(source, /<(?:Table|Select|Pagination|Tooltip|Empty|Button|Alert)\b/);
    for (const token of [
      'ConsoleButton', 'ConsoleSelect', 'ConsolePagination', 'ConsoleEmpty',
      '<table className="nfc-v2-task-table">', 'ResponsiveDataView', 'StatusBadge',
    ]) assert.ok(source.includes(token), token);
  });

  test('filter options preserve all seven states and server-side query semantics', () => {
    const source = read('src/pages/Tasks/index.tsx');
    for (const status of [
      'queued', 'running', 'paused', 'cancel_requested', 'cancelled', 'failed', 'completed',
    ]) assert.ok(source.includes("value: '" + status + "'"), status);
    for (const kind of [
      'fclones-scan', 'index-root', 'workflow-scheduled',
      'media-analysis', 'media-integrity-verify',
    ]) assert.ok(source.includes("value: '" + kind + "'"), kind);
    assert.match(source, /status: statusFilter === 'all' \? undefined : statusFilter/);
    assert.match(source, /jobType: jobTypeFilter === 'all' \? undefined : jobTypeFilter/);
    assert.match(source, /setPage\(1\)/);
    const select = read('src/components/ui/ConsoleSelect.tsx');
    assert.match(select, /<select/);
    assert.match(select, /aria-label=\{label\}/);
    assert.match(select, /onChange=\{event => onChange\(event.target.value\)\}/);
    assert.doesNotMatch(select, /from ['"]antd['"]/);
  });

  test('no lossy change to live polling, ETA, deep link, and task deletion guards', () => {
    const source = read('src/pages/Tasks/index.tsx');
    for (const token of [
      "queryKey: ['tasksList', page, pageSize, statusFilter, jobTypeFilter]",
      'return hasActive ? 3000 : false',
      "setInterval(() =>", "currentTime",
      "searchParams.get('task')", "next.delete('task')",
      'TaskProgress', 'TaskDeleteButton', 'TaskDetailDrawer',
      'TaskHistoryCleanupModal', 'WorkerStatusCard', 'handleDeleted',
    ]) assert.ok(source.includes(token), token);
    assert.match(source, /pageSizes=\{\[20, 50, 100, 200\]\}/);
    assert.match(source, /onSuccess=\{\(\) => handleDeleted\(task.id\)\}/);
    assert.match(source, /isError \? \[\] : data\?\.items \|\| \[\]/);
  });

  test('progress uses native semantic control and retains unknown-progress fail closed', () => {
    const progress = read('src/components/tasks/TaskProgress.tsx');
    assert.doesNotMatch(progress, /from ['"]antd['"]|<Progress\b|<Spin\b|<Text\b/);
    assert.match(progress, /computeProgressPercentage\(current, total, progress\?\.percent\)/);
    assert.match(progress, /calculateTaskEta\(status, current, total, startedAt, progress\?\.percent, now\)/);
    assert.match(progress, /if \(total > 0 && percent !== null\)/);
    assert.match(progress, /<progress className="nfc-v2-native-progress" max=\{100\} value=\{percent\}/);
    assert.match(progress, /进度未知/);
    assert.match(progress, /nfc-v2-progress-spinner/);
    assert.match(progress, /ETA:/);
  });

  test('filter pagination retains previous 200-record ceiling and reset behavior', () => {
    const model = getPaginationState(4, 200, 650);
    assert.deepEqual(model, { pages: 4, current: 4, start: 601, end: 650 });
    assert.deepEqual(getPaginationState(1, 50, 0), { pages: 1, current: 1, start: 0, end: 0 });
    assert.deepEqual(getPaginationState(20, 50, 80), { pages: 2, current: 2, start: 51, end: 80 });
  });

  test('new CSS stays scoped, responsive and keyboard accessible', () => {
    const source = read('src/styles/console-v2-tasks.css');
    const entry = read('src/main.tsx');
    assert.match(entry, /import '\.\/styles\/console-v2-phase2\.css';[\s\S]*import '\.\/styles\/console-v2-tasks\.css';/);
    for (const selector of [
      '.nfc-v2-shell .nfc-console-select', '.nfc-v2-task-table',
      '.nfc-v2-native-progress', '.nfc-v2-task-alert',
      '.nfc-v2-progress-spinner',
    ]) assert.ok(source.includes(selector), selector);
    assert.match(source, /\.nfc-console-select:focus-visible/);
    assert.match(source, /@media \(max-width: 767px\)/);
    assert.match(source, /prefers-reduced-motion: reduce/);
  });
});
