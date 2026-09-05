import { QuarantineConflictPolicy, Plan } from '../../types';

export function canCreateUndoPlan(
  plan: Plan | { status: string; kind?: string; expected_changes?: number } | null | undefined,
  journalCount: number
): boolean {
  if (!plan || !plan.status) return false;
  if (plan.status !== 'completed' && plan.status !== 'partial') return false;
  return journalCount > 0 || (plan.expected_changes ?? 0) > 0;
}

export function getQuarantinePurgeAvailability(
  isAdmin: boolean,
  allowDelete: boolean,
  confirmationInput: string
): { canPurge: boolean; reason?: string } {
  if (!isAdmin) {
    return { canPurge: false, reason: '只有系统管理员允许执行隔离文件的永久清除操作' };
  }
  if (!allowDelete) {
    return { canPurge: false, reason: '服务端配置已禁用永久文件删除 (ALLOW_DELETE=false)' };
  }
  if (confirmationInput.trim() !== 'DELETE') {
    return { canPurge: false, reason: '必须严格输入全大写字母 "DELETE"' };
  }
  return { canPurge: true };
}

export function getQuarantineRestoreAvailability(
  isSafeMode: boolean,
  policy: QuarantineConflictPolicy,
  customTarget?: string
): { canRestore: boolean; reason?: string } {
  if (isSafeMode) {
    return { canRestore: false, reason: '只读安全模式生效中，禁止执行恢复操作' };
  }
  if (!['skip', 'rename', 'manual'].includes(policy)) {
    return { canRestore: false, reason: '无效的冲突处理策略' };
  }
  if (policy === 'manual') {
    if (!customTarget || !customTarget.trim()) {
      return { canRestore: false, reason: '请输入自定义恢复目标路径' };
    }
    if (!customTarget.trim().startsWith('/')) {
      return { canRestore: false, reason: '路径必须为以 / 开头的绝对路径' };
    }
  }
  return { canRestore: true };
}

export function validateQuarantineRetentionDays(days: any): { valid: boolean; error?: string } {
  if (typeof days !== 'number' || isNaN(days) || typeof days === 'boolean') {
    return { valid: false, error: '保留天数必须为数字' };
  }
  if (![0, 7, 30, 90].includes(days)) {
    return { valid: false, error: '隔离区保留天数仅支持 0（永久保留）、7 天、30 天、90 天' };
  }
  return { valid: true };
}

export function formatQuarantineRetention(days: number | null | undefined): string {
  if (days === 0 || days === null || days === undefined) {
    return '永久保留 (0 天)';
  }
  if (days === 7) return '7 天 (7 days)';
  if (days === 30) return '30 天 (30 days)';
  if (days === 90) return '90 天 (90 days)';
  return `${days} 天`;
}
