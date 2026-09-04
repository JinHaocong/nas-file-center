export interface RetentionApplyAvailability {
  canApply: boolean;
  disabledReason?: string;
  isZeroCandidates?: boolean;
}

/**
 * 格式化审计保留天数描述
 */
export function formatAuditRetention(days: number | undefined | null): string {
  if (days === undefined || days === null) {
    return '未配置';
  }
  if (days === 0) {
    return '永久保留';
  }
  if (days > 0) {
    return `保留最近 ${days} 天`;
  }
  return '非法配置';
}

/**
 * 校验保留天数输入
 */
export function validateRetentionDaysInput(value: unknown): { valid: boolean; error?: string } {
  if (value === null || value === undefined || value === '') {
    return { valid: false, error: '保留天数不能为空' };
  }
  const num = Number(value);
  if (!Number.isInteger(num)) {
    return { valid: false, error: '保留天数必须为整数' };
  }
  if (num < 0 || num > 3650) {
    return { valid: false, error: '保留天数必须在 0 到 3650 之间' };
  }
  return { valid: true };
}

/**
 * 获取执行审计清理按钮的可用性状态
 */
export function getAuditRetentionApplyAvailability(
  policy?: { audit_retention_days: number } | null,
  preview?: { enabled: boolean; delete_count: number } | null,
): RetentionApplyAvailability {
  if (!policy || policy.audit_retention_days === 0) {
    return {
      canApply: false,
      disabledReason: '当前保留策略为永久保留（0 天），不可执行清理',
    };
  }

  if (preview && preview.delete_count === 0) {
    return {
      canApply: true,
      isZeroCandidates: true,
    };
  }

  return {
    canApply: true,
  };
}
