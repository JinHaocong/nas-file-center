export interface PlanDeleteAvailability {
  canDelete: boolean;
  reason?: string;
  hasExecutionHistory?: boolean;
}

export const PLAN_SINGLE_DELETE_ALLOWED = new Set([
  'draft',
  'frozen',
  'ready',
  'partial',
  'completed',
  'failed',
]);

export const PLAN_DELETE_BLOCKED_ACTIVE = new Set([
  'validating',
  'executing',
]);

export const PLAN_EXECUTED_STATES = new Set([
  'partial',
  'completed',
  'failed',
]);

export function getPlanDeleteAvailability(plan?: {
  status?: string;
} | null): PlanDeleteAvailability {
  if (!plan || !plan.status) {
    return { canDelete: false, reason: '无效的计划状态' };
  }
  if (PLAN_DELETE_BLOCKED_ACTIVE.has(plan.status)) {
    return { canDelete: false, reason: '计划正在校验或执行中，禁止删除' };
  }
  if (!PLAN_SINGLE_DELETE_ALLOWED.has(plan.status)) {
    return { canDelete: false, reason: '未知或不允许删除的计划状态' };
  }
  return {
    canDelete: true,
    hasExecutionHistory: PLAN_EXECUTED_STATES.has(plan.status),
  };
}
