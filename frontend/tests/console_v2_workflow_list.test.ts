import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { getAuthorizedWorkflowListTarget } from '../src/utils/workflowListActions';
import { getPaginationState } from '../src/components/ui/paginationModel';
import type { WorkflowListItem } from '../src/types/workflow';

const read = (file: string) => readFileSync(resolve(process.cwd(), file), 'utf8');
const active: WorkflowListItem = {
  id: 10, name: '照片整理', description: '', current_revision: 3, is_builtin: false,
  mode: 'organizer', created_by_user_id: 1, archived_at: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-02-01T00:00:00Z',
};
const archived = { ...active, archived_at: '2026-03-01T00:00:00Z' };
const builtin = { ...active, is_builtin: true };
const archive = { kind: 'archive' as const, workflowId: 10, expectedRevision: 3 };
const deletion = { kind: 'delete' as const, workflowId: 10, expectedRevision: 3 };

describe('Console v2 workflow list native migration', () => {
  test('archive confirmation rechecks RBAC, built-in, archived and revision validity', () => {
    assert.deepEqual(getAuthorizedWorkflowListTarget(archive, [active], 'admin', false), active);
    assert.equal(getAuthorizedWorkflowListTarget(archive, [active], 'user', false), null);
    assert.equal(getAuthorizedWorkflowListTarget(archive, [active], undefined, false), null);
    assert.equal(getAuthorizedWorkflowListTarget(archive, [builtin], 'admin', false), null);
    assert.equal(getAuthorizedWorkflowListTarget(archive, [archived], 'admin', false), null);
    assert.equal(getAuthorizedWorkflowListTarget(archive, [active], 'admin', true), null);
    assert.equal(getAuthorizedWorkflowListTarget({ ...archive, expectedRevision: 2 }, [active], 'admin', false), null);
    assert.equal(getAuthorizedWorkflowListTarget({ ...archive, workflowId: 11 }, [active], 'admin', false), null);
    assert.equal(getAuthorizedWorkflowListTarget({ ...archive, expectedRevision: 0 }, [active], 'admin', false), null);
    assert.equal(getAuthorizedWorkflowListTarget(null, [active], 'admin', false), null);
  });

  test('permanent delete requires archived non-builtin admin, never active, and no stale expected revision', () => {
    assert.deepEqual(getAuthorizedWorkflowListTarget(deletion, [archived], 'admin', false), archived);
    assert.equal(getAuthorizedWorkflowListTarget(deletion, [active], 'admin', false), null);
    assert.equal(getAuthorizedWorkflowListTarget(deletion, [builtin], 'admin', false), null);
    assert.equal(getAuthorizedWorkflowListTarget(deletion, [archived], 'user', false), null);
    assert.equal(getAuthorizedWorkflowListTarget(deletion, [archived], 'admin', true), null);
    assert.equal(getAuthorizedWorkflowListTarget({ ...deletion, expectedRevision: 4 }, [archived], 'admin', false), null);
    assert.equal(getAuthorizedWorkflowListTarget({ ...deletion, workflowId: Number.NaN }, [archived], 'admin', false), null);
  });

  test('same controlled 15/page model clamps on shrinking collection and supports size changes', () => {
    assert.deepEqual(getPaginationState(9, 15, 31), { pages: 3, current: 3, start: 31, end: 31 });
    assert.deepEqual(getPaginationState(9, 15, 0), { pages: 1, current: 1, start: 0, end: 0 });
    assert.deepEqual(getPaginationState(2, 30, 31), { pages: 2, current: 2, start: 31, end: 31 });
    const s = read('src/pages/Workflows/WorkflowList.tsx');
    for (const term of [
      'getPaginationState(page, pageSize, items.length)', 'visibleItems = useMemo(',
      'items.slice((currentPage - 1) * pageSize, currentPage * pageSize)',
      'visibleItems.map(workflow =>', '<ConsolePagination page={currentPage}',
      'pageSizes={[15, 30, 60]}', 'setPage(nextPage)', 'setPageSize(nextPageSize)',
      'setPage(1)', 'checked={includeArchived}',
      "queryKey: ['workflowsList', includeArchived]",
    ]) assert.ok(s.includes(term), term);
  });

  test('both responsive views, errors, loading, empty, archive checkbox and date semantics are native', () => {
    const s = read('src/pages/Workflows/WorkflowList.tsx');
    for (const term of [
      '<PageHeader', '<DataPanel', '<ActionBar', '<ResponsiveDataView',
      '<table', '<thead', '<tbody', '<th scope="col">',
      'nfc-workflow-mobile-card', 'nfc-v2-workflow-mobile-list', '<time dateTime=',
      '<ConsoleEmpty', '<ConsoleButton', '<ConsoleIcon', '<ConsoleConfirmDialog',
      'type="checkbox" checked={includeArchived}', 'useConsoleToast',
      'role="alert"', 'role="status"', 'refetch()', 'StatusBadge',
      'canCreateWorkflow(user?.role)', 'canArchiveWorkflow(user?.role',
      'canPermanentlyDeleteWorkflow(user?.role', '<RevisionDrawer',
    ]) assert.ok(s.includes(term), term);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Table\b|<Pagination\b|<Switch\b|<Popconfirm\b|<Empty\b|<Button\b|message\./);
  });

  test('server authority still uses frozen expected revision and refreshes all list views', () => {
    const s = read('src/pages/Workflows/WorkflowList.tsx');
    for (const term of [
      'workflowApi.archiveWorkflow(workflow.id, workflow.current_revision)',
      'workflowApi.permanentlyDeleteWorkflow(workflow.id, workflow.current_revision)',
      'getAuthorizedWorkflowListTarget(confirmation, items, user?.role, false)',
      'mutationInFlight.current = true', 'archiveMutation.mutate(workflow)',
      'permanentDeleteMutation.mutate(workflow)',
      'setConfirmation(null)', 'mutationInFlight.current = false',
      "queryClient.invalidateQueries({ queryKey: ['workflowsList'] })",
      'setSelectedWorkflowForRevision(null)', 'toast.success', 'toast.error',
      'expectedRevision: workflow.current_revision', 'disabled={!confirmTarget}',
      'busy={busy || mutationInFlight.current}', 'onConfirm={handleConfirmAction}',
      'onRollbackSuccess={() =>',
    ]) assert.ok(s.includes(term), term);
  });

  test('light/dark, responsive tap targets, focus and reduced-motion are scoped', () => {
    const css = read('src/styles/console-v2-workflow-list.css');
    const main = read('src/main.tsx');
    for (const term of [
      '.nfc-v2-workflow-list-page', '.nfc-v2-workflow-table',
      '[data-theme=\'dark\']', '@media (max-width: 767px)',
      ':focus-visible', 'min-height: 44px',
      '@media (prefers-reduced-motion: reduce)',
    ]) assert.ok(css.includes(term), term);
    assert.ok(main.includes("import './styles/console-v2-workflow-list.css';"));
  });
});
