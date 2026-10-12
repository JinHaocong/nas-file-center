import test, { describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import type { ResourcePolicyUpdate } from '../src/types';
import {
  formatAuditRetention, getAuditRetentionApplyAvailability,
  getAuditRetentionSaveAvailability, getQuarantineRetentionSaveAvailability,
  validateRetentionDaysInput,
} from '../src/components/settings/data_lifecycle';
import {
  COMMON_TIMEZONES, validateResourcePolicyUpdate, getProfileDisplay,
} from '../src/components/settings/resource_policy';

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');
const page = () => read('src/pages/Settings/index.tsx');
const base: ResourcePolicyUpdate = {
  scan_threads: 2, hash_threads: 2, io_limit: 'normal', job_priority: 'normal',
  active_window_enabled: false, active_window_start: null, active_window_end: null,
  active_window_timezone: null, outside_window_mode: 'limited',
};

describe('Console v2 Settings native RBAC and destructive action security', () => {
  test('runtime flags stay read-only and cannot be changed by a web action', () => {
    const s = page();
    for (const flag of ['ALLOW_MUTATION', 'ALLOW_DELETE', 'PROTECT_LAST_FILE', 'ALLOWED_ROOTS', 'QUARANTINE_ROOT']) {
      assert.ok(s.includes(flag), flag);
    }
    assert.ok(s.includes('Docker Compose 环境变量配置'));
    assert.ok(s.includes('settingsApi.getSettings'));
    assert.doesNotMatch(s, /settingsApi\.updateSettings|allow_mutation:\s*|allow_delete:\s*/);
    assert.doesNotMatch(s, /<Switch\b|<Form\b|<Table\b|@ant-design\/icons|from ['"]antd['"]/);
  });

  test('all legacy policy and audit mutations preserve exact endpoints', () => {
    const s = page();
    for (const token of [
      'dataLifecycleApi.updatePolicy(days)', 'quarantineApi.updateRetentionPolicy(days)',
      'resourcePolicyApi.updatePolicy(payload)', 'auditApi.applyRetention()',
      'auditApi.clearHistory()', 'authApi.revokeSession(sessionId)',
      "queryKey: ['auditRetentionPreview']", "queryKey: ['resourcePolicy']",
      "queryKey: ['activeSessions']",
    ]) assert.ok(s.includes(token), token);
  });

  test('preserves lifecycle retention limits and permanent-retain semantics', () => {
    assert.equal(formatAuditRetention(0), '永久保留');
    assert.equal(formatAuditRetention(7), '保留最近 7 天');
    assert.equal(validateRetentionDaysInput(0).valid, true);
    assert.equal(validateRetentionDaysInput(3650).valid, true);
    for (const invalid of [-1, 3651, 3.14, null, '', undefined]) {
      assert.equal(validateRetentionDaysInput(invalid).valid, false, String(invalid));
    }
    assert.equal(getAuditRetentionSaveAvailability(false).canSave, false);
    assert.equal(getQuarantineRetentionSaveAvailability(false).canSave, false);
  });

  test('retention apply requires saved nonzero policy, admin and no pending work', () => {
    const policy = { audit_retention_days: 30 };
    const preview = { enabled: true, delete_count: 10 };
    assert.equal(getAuditRetentionApplyAvailability(policy, preview, { isAdmin: true }).canApply, true);
    assert.equal(getAuditRetentionApplyAvailability({ audit_retention_days: 0 }, preview, { isAdmin: true }).canApply, false);
    assert.equal(getAuditRetentionApplyAvailability(policy, preview, { isAdmin: false }).canApply, false);
    for (const key of ['isSavingPolicy', 'isPreparingApply', 'isApplying', 'isQueryError'] as const) {
      assert.equal(getAuditRetentionApplyAvailability(policy, preview,
        { isAdmin: true, [key]: true }).canApply, false, key);
    }
  });

  test('destructive audit action can only open through a fresh dual refetch and confirmation', () => {
    const s = page();
    for (const token of [
      'handlePrepareApply', 'refetchPolicy()', 'refetchPreview()',
      'Promise.all([refetchPolicy(), refetchPreview()])',
      "setConfirmation({ kind: 'retention'",
      'ticket !== prepareTicket.current',
      'freshPolicy.audit_retention_days === 0',
      'freshPreview.delete_count',
      'getAuditRetentionApplyAvailability', '<ConsoleConfirmDialog',
      'lifecyclePolicy?.audit_retention_days !== captured.days',
    ]) assert.ok(s.includes(token), token);
    assert.ok(s.includes('审计历史清理不可撤销'));
    assert.ok(s.includes('不会') || s.includes('不删除 NAS'));
  });

  test('immediate audit clear remains admin-only, separate and self-audited', () => {
    const s = page();
    for (const token of [
      'handleClearAuditHistory', "setConfirmation({ kind: 'clear' })",
      'rejectNonAdmin(', 'auditApi.clearHistory()', 'audit.clear',
      'clearAuditMutation.mutateAsync()', "runOnce('audit-action'",
      '立即清空', '无法撤销',
    ]) assert.ok(s.includes(token), token);
  });

  test('sessions are read-only until confirming a different non-current device', () => {
    const s = page();
    for (const token of [
      'session.is_current', "confirmation.kind === 'revoke'",
      'active.is_current', 'authApi.revokeSession(sessionId)',
      "runOnce('session-revoke'", 'sessionActions(session)',
      '<ResponsiveDataView', 'nfc-session-mobile-card', 'nfc-v2-settings-table',
      'sessionsError', 'sessionsLoading',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /session\.is_current\s*\?\s*<ConsoleButton/);
  });

  test('resource policy permits valid threads and rejects fractional, NaN or unsafe limits', () => {
    assert.equal(validateResourcePolicyUpdate(base).valid, true);
    for (const invalid of [0, 33, 1.1, 2.5, NaN, Infinity]) {
      assert.equal(validateResourcePolicyUpdate({ ...base, scan_threads: invalid }).valid, false, 'scan ' + invalid);
      assert.equal(validateResourcePolicyUpdate({ ...base, hash_threads: invalid }).valid, false, 'hash ' + invalid);
    }
    assert.equal(validateResourcePolicyUpdate({ ...base, io_limit: 'unknown' as any }).valid, false);
    assert.equal(validateResourcePolicyUpdate({ ...base, outside_window_mode: 'unknown' as any }).valid, false);
  });

  test('active window validates exact HH:MM, non-identical bounds and timezone', () => {
    const enabled: ResourcePolicyUpdate = {
      ...base, active_window_enabled: true, active_window_start: '01:00',
      active_window_end: '07:00', active_window_timezone: 'UTC',
    };
    assert.equal(validateResourcePolicyUpdate(enabled).valid, true);
    for (const fields of [
      { active_window_start: '25:00' }, { active_window_start: '' },
      { active_window_end: '07:99' }, { active_window_end: '01:00' },
      { active_window_timezone: '' },
    ]) assert.equal(validateResourcePolicyUpdate({ ...enabled, ...fields }).valid, false);
    assert.ok(COMMON_TIMEZONES.includes('America/Los_Angeles'));
    assert.ok(COMMON_TIMEZONES.includes('Asia/Shanghai'));
  });

  test('running profile data retains existing labels and no mock values', () => {
    assert.equal(getProfileDisplay('full').color, 'success');
    assert.equal(getProfileDisplay('limited').color, 'warning');
    assert.equal(getProfileDisplay('pause').color, 'error');
    const s = page();
    assert.ok(s.includes('resourcePolicy.effective_now.profile'));
    assert.ok(s.includes('resourcePolicy.effective_now.resource_jobs_admitted'));
    assert.ok(s.includes('resourcePolicy.effective_now.effective_thread_cap'));
    assert.ok(s.includes('resourcePolicy.revision'));
  });

  test('single-flight mutation and focus-safe Radix dialogs replace unsafe inline confirmation', () => {
    const s = page();
    for (const token of [
      'pendingActions.current.has(key)', 'pendingActions.current.add(key)',
      'pendingActions.current.delete(key)', "runOnce('audit-save'",
      "runOnce('quarantine-save'", "runOnce('resource-save'",
      'useConsoleToast()', 'confirmBusy', 'onOpenChange=',
      'disabled={!isAdmin}', 'onConfirm={handleConfirm}',
    ]) assert.ok(s.includes(token), token);
    assert.doesNotMatch(s, /Modal\.confirm|<Popconfirm\b|message\.(success|error|info)/);
    const primitive = read('src/components/ui/ConsoleConfirmDialog.tsx');
    assert.ok(primitive.includes('@radix-ui/react-dialog'));
    assert.ok(primitive.includes('if (!busy) onOpenChange(next)'));
    assert.ok(primitive.includes('onPointerDownOutside={event => event.preventDefault()}'));
  });

  test('semantic desktop session table, mobile cards, status and native controls', () => {
    const s = page();
    for (const token of [
      '<table', '<caption', '<th scope="col">', '<tbody>',
      'nfc-settings-control-grid', 'type="number"', '<select',
      'type="checkbox"', 'role="switch"', 'aria-checked=',
      'nfc-settings-panel-runtime', 'nfc-settings-panel-lifecycle',
      'nfc-settings-panel-resource', 'nfc-settings-panel-sessions',
      'ResponsiveDescriptions', 'CodePath', 'ConsoleButton', 'ConsoleEmpty',
    ]) assert.ok(s.includes(token), token);
  });

  test('scoped CSS covers controls, mobile, dark, focus and reduced motion', () => {
    const css = read('src/styles/console-v2-settings.css');
    for (const token of [
      '.nfc-v2-settings', '.nfc-v2-settings-notice', '.nfc-v2-settings-table',
      '.nfc-v2-settings-switch', '.nfc-v2-settings-mobile',
      "[data-theme='dark']", ':focus-visible', 'max-width:767px',
      'prefers-reduced-motion:reduce', 'min-height:44px',
    ]) assert.ok(css.includes(token), token);
    assert.ok(read('src/main.tsx').includes("import './styles/console-v2-settings.css';"));
  });
});
