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

export interface PlanDeleteConfirmationContent {
  title: string;
  description: string;
}

export function getPlanDeleteConfirmationContent(plan: {
  id: number;
  status?: string;
  name?: string;
}): PlanDeleteConfirmationContent {
  const { hasExecutionHistory } = getPlanDeleteAvailability(plan);
  const title = `确认删除计划 #${plan.id}？`;
  const description = hasExecutionHistory
    ? '该计划可能包含已经执行过的文件操作。删除仅清理计划及计划条目元数据，不会撤销已经执行的 NAS 文件操作（Delete ≠ Undo）。Audit 审计记录仍会保留。'
    : '仅删除该计划及其计划条目元数据，不会修改 NAS 上的任何真实文件。Audit 审计记录不会受到影响。';
  return { title, description };
}

export function invalidatePlanDeleteFailure(
  queryClient: { invalidateQueries: (filters: { queryKey: any[] }) => any },
  planId?: number
) {
  queryClient.invalidateQueries({ queryKey: ['plansList'] });
  if (planId !== undefined) {
    queryClient.invalidateQueries({ queryKey: ['planDetail', planId] });
  }
  queryClient.invalidateQueries({ queryKey: ['planDetail'] });
}

export function formatLegacyClearSuccessMessage(
  deletedCount: number,
  affectedScanCount: number
): string {
  return `已清理 ${deletedCount} 个旧版计划，并移除 ${affectedScanCount} 个扫描记录上的旧版计划依赖（若仍关联当前批处理计划，删除限制将继续保留）。`;
}

export function formatLegacyAlertDescription(summary: {
  plan_count: number;
  item_count: number;
  affected_scan_count: number;
}): string {
  return `发现 ${summary.plan_count} 个旧版计划，包含 ${summary.item_count} 个旧版计划项，涉及 ${summary.affected_scan_count} 个扫描记录。这些记录已不参与当前 Plan 执行链路，但仍可能作为旧版依赖阻止关联扫描记录删除。清理后会移除 legacy Plan / PlanItem 元数据；如果扫描仍关联当前 BatchPlan，其删除限制仍会继续保留。`;
}

export const LEGACY_CLEANUP_CONFIRM_DESCRIPTION =
  '该操作仅删除旧版 Plan / PlanItem 元数据。不会删除当前 BatchPlan / BatchPlanItem、Scan 记录、Task / WorkJob、Audit 审计记录或 NAS 上的真实文件。清理后会移除 legacy Plan 对 Scan 的依赖；如果 Scan 仍关联当前 BatchPlan，其删除限制不会解除。';

export function isPlanNotFoundError(error: unknown): boolean {
  if (!error || typeof error !== 'object') {
    return false;
  }
  const err = error as { status?: number; response?: { status?: number } };
  return err.status === 404 || err.response?.status === 404;
}

export type PlanDetailRenderState =
  | 'loading'
  | 'not-found'
  | 'error'
  | 'empty'
  | 'ready';

export function getPlanDetailRenderState(params: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  hasPlan: boolean;
}): PlanDetailRenderState {
  if (params.isLoading) {
    return 'loading';
  }
  if (params.isError && isPlanNotFoundError(params.error)) {
    return 'not-found';
  }
  if (params.isError) {
    return 'error';
  }
  if (!params.hasPlan) {
    return 'empty';
  }
  return 'ready';
}

export type PlanDetailView = 'loading' | 'not-found' | 'error' | 'ready';

export function getPlanDetailView(
  renderState: PlanDetailRenderState,
  hasPlan: boolean
): PlanDetailView {
  if (renderState === 'loading') {
    return 'loading';
  }
  if (renderState === 'not-found') {
    return 'not-found';
  }
  if (renderState === 'error') {
    return 'error';
  }
  if (renderState === 'empty' || !hasPlan) {
    return 'not-found';
  }
  return 'ready';
}


