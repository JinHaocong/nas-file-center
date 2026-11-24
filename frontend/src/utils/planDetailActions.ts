import type { Plan, PlanId, PlanStatus } from '../types';
import { isSqliteId } from './sqliteId';

export type PlanLifecycleAction = 'freeze' | 'validate' | 'execute' | 'undo';
type PlanRecoveryAction = 'rebuild' | 'workflow' | 'scan';

/** Pick the primary control, leaving lifecycle authorization to canPlanLifecycleAction. */
export function getPlanPrimaryAction(status: PlanStatus, {
  allowMutation, hasBackgroundTask, recovery,
}: { allowMutation: boolean; hasBackgroundTask?: boolean; recovery?: PlanRecoveryAction }) {
  if (hasBackgroundTask) return 'background';
  switch (status) {
    case 'draft': return 'freeze';
    case 'frozen': return 'validate';
    case 'ready': return allowMutation ? 'execute' : 'validate';
    case 'partial': return allowMutation ? 'execute' : 'journal';
    case 'stale': return recovery ?? 'journal';
    default: return 'journal';
  }
}

export interface PlanActionContext {
  plan: (Pick<Plan, 'status' | 'active_work_job_id'> & { id: PlanId }) | null;
  allowMutation: boolean;
  journalTotal: number;
  journalReady: boolean;
  pending: boolean;
}

/** Enforce the status, identity and permission gates for a lifecycle action. */
export function canPlanLifecycleAction(
  action: PlanLifecycleAction, context: PlanActionContext,
): boolean {
  const { plan, allowMutation, journalTotal, journalReady, pending } = context;
  if (!plan || pending || Boolean(plan.active_work_job_id)) return false;
  const validId = typeof plan.id === 'string'
    ? isSqliteId(plan.id)
    : Number.isSafeInteger(plan.id) && plan.id > 0;
  if (!validId) return false;
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
  id: PlanId;
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
