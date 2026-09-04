export interface ScanDeleteAvailability {
  canDelete: boolean;
  reason?: string;
}

export const TERMINAL_SCAN_STATUSES = new Set(['completed', 'failed', 'cancelled']);

export function getScanDeleteAvailability(scan?: {
  status?: string;
  has_dependent_plan?: boolean;
} | null): ScanDeleteAvailability {
  if (!scan || !scan.status) {
    return { canDelete: false, reason: '无效扫描状态' };
  }
  if (!TERMINAL_SCAN_STATUSES.has(scan.status)) {
    return { canDelete: false, reason: '仅终态扫描可删除' };
  }
  if (scan.has_dependent_plan) {
    return { canDelete: false, reason: '该扫描已生成关联计划，无法删除' };
  }
  return { canDelete: true };
}
