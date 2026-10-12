import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { buildBatchDraft, isBatchOperation } from '../src/utils/batchDraftSafety';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('Console v2 Batch native Draft-only UI', () => {
  test('quarantine keeps exact Plan name, kind and source-only operation payload', () => {
    const input = ['/nas/DiskA/file1.txt', '/nas/DiskA/dir'];
    const result = buildBatchDraft(' 隔离批次 ', 'quarantine', input, '');
    assert.deepEqual(result.draft, {
      name: '隔离批次', kind: 'batch-quarantine',
      items: [
        { operation: 'quarantine', source: input[0] },
        { operation: 'quarantine', source: input[1] },
      ],
    });
    assert.deepEqual(input, ['/nas/DiskA/file1.txt', '/nas/DiskA/dir']);
  });

  test('touch only includes exact operation and source (no target/mtime guess)', () => {
    const result = buildBatchDraft('批量处理', 'touch', ['/nas/A/1', '/nas/A/2'], '');
    assert.deepEqual(result.draft, {
      name: '批量处理', kind: 'batch-touch',
      items: [
        { operation: 'touch', source: '/nas/A/1' },
        { operation: 'touch', source: '/nas/A/2' },
      ],
    });
  });

  test('move splits one mapping per line and retains exact source/target fields', () => {
    const result = buildBatchDraft('move', 'move', [],
      ' /nas/A/f1 -> /nas/B/f1 \n/nas/A/f2 -> /nas/B/f2\n');
    assert.deepEqual(result.draft, {
      name: 'move', kind: 'batch-move',
      items: [
        { operation: 'move', source: '/nas/A/f1', target: '/nas/B/f1' },
        { operation: 'move', source: '/nas/A/f2', target: '/nas/B/f2' },
      ],
    });
  });

  test('rename respects operation and keeps mappings, no implicit name normalization', () => {
    assert.deepEqual(buildBatchDraft('rename', 'rename', [],
      '/nas/A/one.txt -> /nas/A/two.txt').draft?.items,
      [{ operation: 'rename', source: '/nas/A/one.txt', target: '/nas/A/two.txt' }]);
  });

  test('rejects empty name and missing paths/mappings before server mutation', () => {
    assert.equal(buildBatchDraft(' ', 'touch', ['/nas/A/file'], '').error, '请输入计划名称');
    assert.match(buildBatchDraft('批量处理', 'quarantine', [], '').error || '', /至少/);
    assert.match(buildBatchDraft('批量处理', 'move', [], '').error || '', /至少/);
    assert.match(buildBatchDraft('批量处理', 'rename', [], '  ').error || '', /至少/);
  });

  test('unknown and disabled operations can never become backend Plan items', () => {
    for (const op of ['hardlink', 'reflink', 'unlink', 'delete', 'restore', '']) {
      assert.equal(isBatchOperation(op), false);
      assert.equal(buildBatchDraft('unsafe', op, ['/nas/A'], '').draft, undefined);
    }
    for (const op of ['quarantine', 'touch', 'move', 'rename']) assert.equal(isBatchOperation(op), true);
  });

  test('invalid mapping separators, extra arrows and empty halves fail closed', () => {
    for (const mapping of [
      '/nas/A/file /nas/B/file',
      '/nas/A/file -> ',
      ' -> /nas/B/file',
      '/nas/A/file -> /nas/B/file -> /nas/C/file',
      '/nas/A/file -> /nas/A/file',
    ]) {
      assert.equal(buildBatchDraft('test', 'move', [], mapping).draft, undefined, mapping);
    }
  });

  test('rejects non-absolute paths without changing the originals', () => {
    assert.equal(buildBatchDraft('test', 'touch', ['relative/path'], '').draft, undefined);
    assert.equal(buildBatchDraft('test', 'move', [], 'relative -> /nas/B/file').draft, undefined);
    assert.equal(buildBatchDraft('test', 'rename', [], '/nas/A/file -> relative').draft, undefined);
  });

  test('blocks duplicate quarantine sources and conflicting mapping collisions', () => {
    assert.equal(buildBatchDraft('test', 'quarantine', ['/nas/A/x', '/nas/A/x'], '').draft, undefined);
    assert.equal(buildBatchDraft('test', 'touch', ['/nas/A/x', '/nas/A/x'], '').draft, undefined);
    assert.equal(buildBatchDraft('test', 'move', [],
      '/nas/A/x -> /nas/B/x\n/nas/A/x -> /nas/B/y').draft, undefined);
    assert.equal(buildBatchDraft('test', 'rename', [],
      '/nas/A/x -> /nas/B/x\n/nas/A/y -> /nas/B/x').draft, undefined);
  });

  test('submit has a synchronous single-flight guard with no Freeze/Validate/Execute call', () => {
    const page = read('src/pages/Batch/index.tsx');
    const helper = read('src/utils/batchDraftSafety.ts');
    for (const token of [
      'planGuard.current', 'if (planGuard.current) return;',
      'buildBatchDraft(name, operation, paths, mappingsText)',
      'await planMutation.mutateAsync(draft)', 'useConsoleToast',
      "navigate('/plans/' + created.id)", '<DirectoryPicker multiple value={paths}',
      'value={mappingsText}', 'type="radio"', 'name="batch-operation"',
      '<fieldset', '<legend', 'nfc-batch-operation-grid',
      'kind: ', 'batch-', 'value="hardlink" disabled', 'value="reflink" disabled',
      '<ConsoleButton', '<ConsoleIcon',
    ]) assert.ok((page + helper).includes(token), token);
    assert.doesNotMatch(page, /from ['"]antd['"]|@ant-design\/icons|<Form\b|<Radio\.|<Alert\b/);
    assert.doesNotMatch(page, /executePlan|freezePlan|validatePlan|deletePlan|\/execute/);
  });

  test('scoped CSS retains accessible dark/mobile/focus/reduced-motion surfaces', () => {
    const css = read('src/styles/console-v2-batch.css');
    for (const token of [
      '.nfc-v2-batch', '.nfc-batch-operation-grid', '.nfc-v2-batch-radio',
      '.nfc-v2-batch-field', "[data-theme='dark']", ':focus-visible',
      '@media (max-width:767px)', '@media (max-width:390px)',
      '@media (prefers-reduced-motion:reduce)', 'min-height:44px',
    ]) assert.ok(css.includes(token), token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-batch.css';"));
  });
});
