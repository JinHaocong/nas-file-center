import { canRollbackWorkflow } from './workflowRbac';

export interface RevisionRollbackGuard {
  role?: string;
  isBuiltin: boolean;
  isArchived: boolean;
  currentRevision: number;
  selectedRevision: number;
  expectedRevision: number;
  availableRevisions: readonly number[];
  busy: boolean;
}

/** Fail closed on role/archive/builtin, stale current revision or invalid history. */
export function canConfirmRevisionDrawerRollback(state: RevisionRollbackGuard): boolean {
  return canRollbackWorkflow(state.role, state.isArchived) &&
    !state.isBuiltin &&
    !state.busy &&
    Number.isSafeInteger(state.currentRevision) &&
    Number.isSafeInteger(state.expectedRevision) &&
    Number.isSafeInteger(state.selectedRevision) &&
    state.selectedRevision >= 1 &&
    state.selectedRevision < state.currentRevision &&
    state.expectedRevision === state.currentRevision &&
    state.availableRevisions.includes(state.selectedRevision);
}
