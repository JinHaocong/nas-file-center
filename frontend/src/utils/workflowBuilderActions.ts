import type { WorkflowMode } from '../types/workflow';

/** Confirming a mode reset must revalidate current RBAC, save state and current mode. */
export function canConfirmWorkflowModeReset(
  canSwitchMode: boolean,
  saveBusy: boolean,
  currentMode: WorkflowMode,
  requestedMode: WorkflowMode,
): boolean {
  return canSwitchMode && !saveBusy && requestedMode !== currentMode;
}

export interface WorkflowRollbackConfirmation {
  canRollback: boolean;
  isHistoricalView: boolean;
  currentRevision?: number;
  selectedRevision: number | null;
  requestedRevision: number;
  expectedRevision: number;
  busy: boolean;
}

/** Prevent stale revision, role, archive and duplicate-submit rollback attempts. */
export function canConfirmWorkflowRollback(state: WorkflowRollbackConfirmation): boolean {
  return state.canRollback && state.isHistoricalView && !state.busy &&
    state.currentRevision !== undefined &&
    Number.isInteger(state.selectedRevision) &&
    state.selectedRevision !== null &&
    state.selectedRevision >= 1 &&
    state.selectedRevision === state.requestedRevision &&
    state.currentRevision === state.expectedRevision &&
    state.requestedRevision < state.currentRevision;
}
