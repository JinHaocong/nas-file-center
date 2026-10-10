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
    state.selectedRevision !== null &&
    Number.isInteger(state.selectedRevision) &&
    state.selectedRevision >= 1 &&
    state.selectedRevision === state.requestedRevision &&
    state.currentRevision === state.expectedRevision &&
    state.requestedRevision < state.currentRevision;
}

/** Normalizes both editable fields before submission, rejecting blank trimmed names. */
export function validateWorkflowBasicFields(name: string, description: string): {
  name: string;
  description: string;
  nameError: string;
} {
  const normalizedName = name.trim();
  return {
    name: normalizedName,
    description: description.trim(),
    nameError: normalizedName ? '' : '请输入工作流名称',
  };
}
