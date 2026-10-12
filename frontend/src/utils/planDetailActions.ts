import type { Plan } from '../types';

export type PlanLifecycleAction = 'freeze' | 'validate' | 'execute' | 'undo';

export interface PlanActionContext {
  plan: Pick<Plan, 'id' | 'status' | 'active_work_job_id'> | null;
  allowMutation: boolean;
  journalTotal: number;
  journalReady: boolean;
  pending: boolean;
}

export function canPlanLifecycleAction(
  action: PlanLifecycleAction, context: PlanActionContext,
): boolean {
  const { plan, allowMutation, journalTotal, journalReady, pending } = context;
  if (!plan || !Number.isSafeInteger(plan.id) || plan.id <= 0 ||
      pending || Boolean(plan.active_work_job_id)) return false;
  switch (action) {
    case 'freeze': return plan.status === 'draft';
    case 'validate': return ['frozen', 'ready', 'partial', 'stale'].includes(plan.status);
    case 'execute':
      return allowMutation && ['ready', 'partial'].includes(plan.status);
    case 'undo':
      return ['completed', 'partial'].includes(plan.status) &&
        journalReady && Number.isSafeInteger(journalTotal) && journalTotal > 0;
    default: return false;
  }
}

/** Snapshot of the facts that were visible when the user requested confirmation. */
export interface PlanConfirmationSnapshot {
  action: 'execute' | 'undo';
  id: number;
  status: string;
  activeWorkJobId: number | null;
  allowMutation: boolean;
  journalTotal: number;
}

export function planConfirmationSnapshot(
  action: 'execute' | 'undo',
  context: PlanActionContext,
): PlanConfirmationSnapshot | null {
  if (!canPlanLifecycleAction(action, context) || !context.plan) return null;
  return {
    action,
    id: context.plan.id,
    status: context.plan.status,
    activeWorkJobId: context.plan.active_work_job_id ?? null,
    allowMutation: context.allowMutation,
    journalTotal: context.journalTotal,
  };
}

/** The submit handler must re-check the latest plan, settings and journal authority. */
export function samePlanConfirmation(
  initial: PlanConfirmationSnapshot | null,
  now: PlanConfirmationSnapshot | null,
): boolean {
  return Boolean(initial && now &&
    initial.action === now.action &&
    initial.id === now.id && initial.status === now.status &&
    initial.activeWorkJobId === now.activeWorkJobId &&
    initial.allowMutation === now.allowMutation &&
    initial.journalTotal === now.journalTotal);
}
