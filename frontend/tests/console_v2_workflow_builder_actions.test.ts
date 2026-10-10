import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  canConfirmWorkflowModeReset, canConfirmWorkflowRollback,
} from '../src/utils/workflowBuilderActions';
const read = (p: string) => readFileSync(resolve(process.cwd(), p), 'utf8');

describe('Console v2 workflow builder action shell and safety', () => {
  test('mode reset requires current role, changed mode and idle save', () => {
    assert.equal(canConfirmWorkflowModeReset(true, false, 'file', 'dedupe'), true);
    assert.equal(canConfirmWorkflowModeReset(true, false, 'file', 'organizer'), true);
    assert.equal(canConfirmWorkflowModeReset(false, false, 'file', 'dedupe'), false);
    assert.equal(canConfirmWorkflowModeReset(true, true, 'file', 'dedupe'), false);
    assert.equal(canConfirmWorkflowModeReset(true, false, 'file', 'file'), false);
  });

  test('rollback rejects stale, unprivileged, active and invalid revision intents', () => {
    const valid = {
      canRollback: true, isHistoricalView: true,
      currentRevision: 9, selectedRevision: 4, requestedRevision: 4,
      expectedRevision: 9, busy: false,
    };
    assert.equal(canConfirmWorkflowRollback(valid), true);
    assert.equal(canConfirmWorkflowRollback({...valid, canRollback: false}), false);
    assert.equal(canConfirmWorkflowRollback({...valid, isHistoricalView: false}), false);
    assert.equal(canConfirmWorkflowRollback({...valid, currentRevision: 10}), false);
    assert.equal(canConfirmWorkflowRollback({...valid, expectedRevision: 8}), false);
    assert.equal(canConfirmWorkflowRollback({...valid, selectedRevision: 5}), false);
    assert.equal(canConfirmWorkflowRollback({...valid, selectedRevision: null}), false);
    assert.equal(canConfirmWorkflowRollback({...valid, selectedRevision: 0, requestedRevision: 0}), false);
    assert.equal(canConfirmWorkflowRollback({...valid, selectedRevision: 9, requestedRevision: 9}), false);
    assert.equal(canConfirmWorkflowRollback({...valid, busy: true}), false);
    assert.equal(canConfirmWorkflowRollback({...valid, currentRevision: undefined}), false);
  });

  test('three distinct Radix confirmations preserve dirty exit, topology reset and rollback', () => {
    const s=read('src/pages/Workflows/WorkflowBuilder.tsx');
    for(const term of [
      'type PendingWorkflowConfirmation', "kind: 'mode'", "kind: 'back'",
      "kind: 'rollback'", 'setConfirmation(', 'confirmWorkflowAction',
      'canConfirmWorkflowModeReset(', 'canConfirmWorkflowRollback({',
      "setSteps(defaultStepsForMode(confirmation.targetMode))",
      'canSwitchMode', 'saveMutation.isPending',
      'rollbackInFlight.current', 'rollbackMutation.isPending', 'workflow.current_revision',
      'expectedRevision', 'targetRevision', 'canRollback',
      '确认重置并切换', '当前工作流存在未保存的修改', '确认回滚',
      '<ConsoleConfirmDialog', 'onConfirm={confirmWorkflowAction}',
      'busy={rollbackMutation.isPending', 'disabled={confirmation?.kind',
    ])assert.ok(s.includes(term),term);
    assert.doesNotMatch(s, /Modal\.confirm|<Popconfirm\b|from ['"]@ant-design\/icons['"]/);
  });

  test('RBAC, revision identity and save validation remain authoritative', () => {
    const s=read('src/pages/Workflows/WorkflowBuilder.tsx');
    for(const term of [
      'parseWorkflowRevisionQuery', 'expected_current_revision: workflow.current_revision',
      'canCreateWorkflow(user?.role)', 'canSaveRevision(user?.role, isArchived)',
      'canSwitchWorkflowMode(user?.role', 'canRollbackWorkflow(user?.role, isArchived)',
      'isHistoricalView', 'isArchived', 'isBuiltin',
      'validateWorkflowBasicFields(name, description)', 'name: values.name',
      'description: values.description', 'schema_version: 1',
      'StepList', 'WorkflowPreviewPanel', 'RevisionDrawer',
      'createDefaultDedupeScorerConfig', 'createDefaultOrganizerSnapshot',
      'isDirty={isDirty}', 'isArchived={isArchived}', 'onGeneratePlanSuccess',
    ])assert.ok(s.includes(term),term);
    assert.doesNotMatch(s, /from ['"]antd['"]|Form\.useForm\(|form\.validateFields\(/);
  });

  test('native status, history, back, save and toast controls remain accessible', () => {
    const s=read('src/pages/Workflows/WorkflowBuilder.tsx');
    for(const term of [
      '<ConsoleButton', '<ConsoleIcon', 'useConsoleToast()', 'toast.success',
      'toast.error', 'role="alert"', 'role="status"', 'role="note"',
      'nfc-v2-workflow-state', 'nfc-v2-workflow-notice',
      '历史版本只读', '工作流已被归档封存', '普通成员权限提示',
      '返回当前最新版', '回滚至此版本', '保存新版本', '版本历史',
      'nfc-workflow-mode-grid',
    ]) assert.ok(s.includes(term),term);
    assert.doesNotMatch(s, /<Alert\b|<Button\b|<Spin\b|message\.error|message\.success/);
  });

  test('theme/focus/mobile/reduced-motion and shared confirmation styles are loaded', () => {
    const css=read('src/styles/console-v2-workflow-builder.css');
    const main=read('src/main.tsx');
    for (const term of [
      '.nfc-v2-workflow-state', '.nfc-v2-workflow-notice',
      '.nfc-workflow-builder-page', "[data-theme='dark']", ':focus-visible',
      '@media (max-width: 767px)', 'min-height: 44px',
      'prefers-reduced-motion: reduce',
    ])assert.ok(css.includes(term),term);
    assert.ok(main.includes("import './styles/console-v2-workflow-builder.css';"));
    assert.ok(main.includes("import './styles/console-v2-task-overlays.css';"));
    const dialog=read('src/components/ui/ConsoleConfirmDialog.tsx');
    assert.ok(dialog.includes('<Dialog.Root'));
    assert.ok(dialog.includes('onEscapeKeyDown'));
    assert.ok(dialog.includes('onPointerDownOutside'));
  });
});
