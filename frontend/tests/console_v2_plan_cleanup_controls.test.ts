import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  getPlanDeleteAvailability, getPlanDeleteConfirmationContent,
  LEGACY_CLEANUP_CONFIRM_DESCRIPTION, formatLegacyAlertDescription,
} from '../src/components/plans/plan_cleanup';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const deleteButton = () => read('src/components/plans/PlanDeleteButton.tsx');
const history = () => read('src/components/plans/PlanHistoryCleanupModal.tsx');
const legacy = () => read('src/components/plans/LegacyPlanCleanup.tsx');

describe('Console v2 native Plan cleanup controls', () => {
  test('delete availability still blocks active running jobs and unknown statuses', () => {
    assert.equal(getPlanDeleteAvailability({ status: 'validating' }).canDelete, false);
    assert.equal(getPlanDeleteAvailability({ status: 'executing', active_work_job_id: 7,
      active_work_job_status: 'running' }).canDelete, false);
    assert.equal(getPlanDeleteAvailability({ status: 'other' }).canDelete, false);
  });
  test('recovered idle jobs and orphaned execution retain existing safe cleanup rules', () => {
    assert.equal(getPlanDeleteAvailability({ status: 'executing' }).orphanedExecution, true);
    assert.equal(getPlanDeleteAvailability({
      status: 'executing', active_work_job_id: 7, active_work_job_status: 'queued',
      active_work_job_recovered_after_restart: true,
    }).willCancelIdleExecution, true);
    assert.match(getPlanDeleteConfirmationContent({ id: 2, status: 'executing' }).description, /Delete ≠ Undo/);
  });
  test('individual Plan delete is confirmation-gated and availability-locked', () => {
    const s = deleteButton();
    for (const token of [
      'getPlanDeleteAvailability(plan)', 'getPlanDeleteConfirmationContent(plan)',
      '!canDelete || busy', 'const busy = loading || submitting;', 'if (!canDelete || busy || singleFlight.current) return;',
      'await onDelete()', 'invalidatePlanDeleteFailure(queryClient, plan.id)',
      '<ConsoleConfirmDialog', 'confirmText="确认删除"', 'onClick={() => { if (canDelete && !busy) setOpen(true); }}',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Popconfirm\b|<Tooltip\b/);
  });
  test('individual Plan delete keeps legacy API-compatible component props', () => {
    const s = deleteButton();
    for (const token of [
      "size?: 'small' | 'middle' | 'large'", "type?: 'link' | 'text' | 'default' | 'primary'",
      'onDelete: () => void | Promise<void>', 'buttonText?: string',
    ]) assert.ok(s.includes(token), token);
  });
  test('legacy cleanup preserves exact old-only API and scan relationship semantics', () => {
    const s = legacy();
    assert.ok(s.includes('plansApi.getLegacySummary'));
    assert.ok(s.includes('plansApi.clearLegacyPlans'));
    for (const key of ['legacyPlanSummary', 'plansList', 'scansList', 'dashboardSummary']) {
      assert.ok(s.includes(key), key);
    }
    assert.match(LEGACY_CLEANUP_CONFIRM_DESCRIPTION, /BatchPlan/);
    assert.match(LEGACY_CLEANUP_CONFIRM_DESCRIPTION, /NAS 上的真实文件/);
    assert.match(formatLegacyAlertDescription({ plan_count: 1, item_count: 2, affected_scan_count: 3 }), /legacy Plan/);
  });
  test('legacy cleanup requires explicit guarded Radix confirmation', () => {
    const s = legacy();
    for (const token of [
      '!summary || summary.plan_count === 0', 'inFlight.current',
      '<ConsoleConfirmDialog', 'LEGACY_CLEANUP_CONFIRM_DESCRIPTION',
      'clearLegacyMutation.mutateAsync()', 'useConsoleToast',
      'onConfirm={() => { void handleConfirm(); }}',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Popconfirm\b/);
  });
  test('history cleanup only provides completed and failed checkboxes', () => {
    const s = history();
    for (const token of [
      "value: 'completed'", "value: 'failed'", 'selectedStatuses.includes(item.value)',
      'PLAN_HISTORY_OPTIONS.map(x => x.value)', 'selectedStatuses.length === 0',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /value:\s*['"](queued|running|draft|frozen|executing|ready)['"]/);
  });
  test('history cleanup creates an immutable whitelist snapshot before posting', () => {
    const s = history();
    for (const token of [
      'plansApi.clearHistory(statuses)', '.filter(x => selectedStatuses.includes(x))',
      'cleanupMutation.mutateAsync(selected)', 'if (submitting.current || selectedStatuses.length === 0) return',
      'queryClient.invalidateQueries', 'onCleaned?.()', 'setOpen(false)',
    ]) assert.ok(s.includes(token), token);
  });
  test('history cleanup truthfully discloses Delete != Undo and metadata-only impact', () => {
    const s = history();
    for (const token of [
      'Delete ≠ Undo', 'BatchPlan 及 BatchPlanItem', 'NAS 存储上的任何文件',
      'Audit 审计记录与关联的任务', '运行中 (validating / executing)',
      '选中的终态计划元数据',
    ]) assert.ok(s.includes(token), token);
  });
  test('Radix dialog cannot dismiss in-flight mutation or close through outside click', () => {
    const s = history();
    for (const token of [
      '@radix-ui/react-dialog',
      'cleanupMutation.isPending || submitting.current', 'event.preventDefault()',
      'onPointerDownOutside={event => event.preventDefault()}',
      'cleanupMutation.isPending', 'Dialog.Title', 'Dialog.Description',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|@ant-design\/icons|<Modal\b|<Checkbox\.Group/);
  });
  test('both Plan entry points await the deletion Promise before dismissing confirmation', () => {
    const ledger = read('src/pages/Plans/index.tsx');
    const detail = read('src/pages/Plans/PlanDetail.tsx');
    assert.equal(ledger.split('onDelete={() => deletePlanMutation.mutateAsync(plan.id)}').length - 1, 2);
    assert.ok(detail.includes('onDelete={() => deleteMutation.mutateAsync()}'));
    assert.ok(deleteButton().includes('await onDelete()'));
  });
  test('Plans ledger uses native toast without AntD message import', () => {
    const s = read('src/pages/Plans/index.tsx');
    for (const token of [
      'useConsoleToast()', 'toast.success(', 'toast.error(',
      'PlanDeleteButton', 'PlanHistoryCleanupModal', 'LegacyPlanCleanup',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /from ['"]antd['"]|message\.(success|error)/);
  });
  test('native CSS covers compact controls, modal, dark/mobile and focus', () => {
    const css = read('src/styles/console-v2-plan-cleanup-controls.css');
    for (const token of [
      '.nfc-v2-legacy-plan-cleanup', '.nfc-v2-plan-history-dialog',
      '.nfc-v2-plan-history-options', '.nfc-v2-plan-delete-subtle',
      "data-theme='dark'", 'focus-visible', 'max-width:767px',
      'prefers-reduced-motion:reduce', 'min-height:44px',
    ]) assert.ok(css.includes(token), token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-plan-cleanup-controls.css';"));
  });
});
