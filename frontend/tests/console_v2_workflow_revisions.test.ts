import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { canConfirmRevisionDrawerRollback } from '../src/utils/workflowRevisionActions';
import { copyExactText } from '../src/utils/clipboard';
const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');

describe('Console v2 native revision drawer: immutable history and rollback', () => {
  test('rollback guard fails closed on permission, archive, builtin, stale revision, and invalid targets', () => {
    const state = {
      role: 'admin', isBuiltin: false, isArchived: false,
      currentRevision: 7, selectedRevision: 3, expectedRevision: 7,
      availableRevisions: [1, 2, 3, 7], busy: false,
    };
    assert.equal(canConfirmRevisionDrawerRollback(state), true);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, role: 'user' }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, role: undefined }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, isBuiltin: true }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, isArchived: true }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, busy: true }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, currentRevision: 8 }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, expectedRevision: 6 }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, selectedRevision: 7 }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, selectedRevision: 8 }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, selectedRevision: 0 }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, selectedRevision: 2.5 }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, selectedRevision: Number.MAX_SAFE_INTEGER + 1 }), false);
    assert.equal(canConfirmRevisionDrawerRollback({ ...state, availableRevisions: [1, 2, 7] }), false);
  });

  test('no Ant Drawer/Table/Modal/Popconfirm; preserves desktop/mobile truth and inspector data', () => {
    const s = read('src/components/workflows/RevisionDrawer.tsx');
    for (const term of [
      'ConsoleSheet', '<ConsoleSheet', '<Dialog.Root', '<Dialog.Portal',
      '<Dialog.Overlay', '<Dialog.Content', '<Dialog.Title',
      '<ConsoleConfirmDialog', '<ConsoleButton', '<ConsoleIcon',
      '<ConsoleEmpty', 'useResponsive', 'nfc-v2-revision-mobile-list',
      '<table', '<thead', '<tbody', '<th scope="col">', 'revisionItems.map',
      'definition_sha256', 'JSON.stringify(inspectRevision.definition, null, 2)',
      'formatDateTime', 'aria-live="polite"', 'role="status"', 'role="alert"',
      "queryKey: ['workflowRevisions', workflowId]", 'enabled: open && !!workflowId',
    ]) assert.ok(s.includes(term), term);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Drawer\b|<Modal\b|<Popconfirm\b|<Table\b|<Tag\b/);
  });

  test('rollback is rechecked at confirm and locks exact expected revision and duplicate clicks', () => {
    const s = read('src/components/workflows/RevisionDrawer.tsx');
    for (const term of [
      'canConfirmRevisionDrawerRollback({', 'role: user?.role',
      'isBuiltin, isArchived, currentRevision', 'availableRevisions: revisionNumbers',
      'rollbackInFlight.current', 'rollbackMutation.isPending',
      'setRollbackIntent({ revision, expectedRevision: currentRevision })',
      'target_revision: intent.revision', 'expected_current_revision: intent.expectedRevision',
      'rollbackInFlight.current = true', 'onRollbackSuccess(data)',
      'toast.success', 'toast.error', 'void refetch()', 'onSettled:',
      'onOpenChange={next =>', 'busy={rollbackMutation.isPending',
    ]) assert.ok(s.includes(term), term);
  });

  test('SHA256 copy is exact even on non-HTTPS fallback, with clear failure state', async () => {
    const source = read('src/components/workflows/RevisionDrawer.tsx');
    for (const term of [
      'copyExactText(sha', 'navigator.clipboard', 'fallback: copyUsingSelection',
      'document.execCommand(\'copy\')', 'field.select()', 'field.remove()',
      'previous.focus()', 'title={sha}', 'role="status"',
      '复制完整 Definition SHA256', '请手动选择复制',
    ]) assert.ok(source.includes(term), term);
    const sha = 'ABCDEF' + 'a'.repeat(58);
    const copied: string[] = [];
    assert.equal(await copyExactText(sha, { writer: null, fallback: text => {
      copied.push(text); return true;
    }}), 'copied');
    assert.deepEqual(copied, [sha]);
    assert.equal(await copyExactText(sha, { writer: null, fallback: () => false }), 'failed');
  });

  test('CSS portal stacking, light/dark/mobile, focus and reduced-motion are scoped', () => {
    const css = read('src/styles/console-v2-workflow-revisions.css');
    const main = read('src/main.tsx');
    for (const term of [
      '.nfc-v2-revision-sheet', '.nfc-v2-revision-inspect-overlay',
      'z-index: 1401', ':focus-visible', "[data-theme='dark']",
      '@media (max-width: 767px)', 'min-height: 44px',
      '@media (prefers-reduced-motion: reduce)', 'max-height:',
    ]) assert.ok(css.includes(term), term);
    assert.ok(main.includes("import './styles/console-v2-workflow-revisions.css';"));
  });
});
