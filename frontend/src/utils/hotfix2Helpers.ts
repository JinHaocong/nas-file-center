import { WorkflowMode } from '../types/workflow';

export function computeWorkflowDedupeTableTotal(
  previewData: { matched_count: number; planned_operations_count: number },
  onlyChanged: boolean
): number {
  return onlyChanged ? previewData.planned_operations_count : previewData.matched_count;
}

export function shouldAcceptDirectResponse(params: {
  responseGeneration: number;
  currentGeneration: number;
}): boolean {
  return params.responseGeneration === params.currentGeneration;
}

export interface WorkflowResponseCorrelationParams {
  snapshot: {
    workflowId: number;
    revision: number;
    mode: WorkflowMode;
    requestId: number;
    page: number;
    pageSize: number;
    onlyChanged: boolean;
  };
  currentWorkflowId: number;
  currentRevision: number;
  currentMode: WorkflowMode;
  currentRequestId: number;
}

export function shouldAcceptWorkflowResponse(params: WorkflowResponseCorrelationParams): boolean {
  return (
    params.snapshot.requestId === params.currentRequestId &&
    params.snapshot.workflowId === params.currentWorkflowId &&
    params.snapshot.revision === params.currentRevision &&
    params.snapshot.mode === params.currentMode
  );
}

export interface CanDraftOptions {
  isArchived?: boolean;
  isDirty?: boolean;
  previewState?: string;
  compileDigest?: string | null;
  previewPending?: boolean;
  generatePending?: boolean;
  isDedupe?: boolean;
  selectedScanJobId?: number;
  hasDedupeSummary?: boolean;
}

export function computeCanDraft(opts: CanDraftOptions): boolean {
  if (opts.isArchived || opts.isDirty) return false;
  if (opts.previewState !== 'PREVIEW_READY') return false;
  if (!opts.compileDigest) return false;
  if (opts.previewPending || opts.generatePending) return false;
  if (opts.isDedupe) {
    if (!opts.selectedScanJobId || !opts.hasDedupeSummary) return false;
  }
  return true;
}

export function resolveDirectSafetyPolicy(params: {
  summary?: { effective_safety_policy?: { protect_last_file?: boolean; [key: string]: any } };
  topLevelSafetyPolicy?: { protect_last_file?: boolean; [key: string]: any };
}): { protect_last_file?: boolean; [key: string]: any } {
  if (
    params.summary?.effective_safety_policy &&
    params.summary.effective_safety_policy.protect_last_file !== undefined
  ) {
    return params.summary.effective_safety_policy;
  }
  if (params.topLevelSafetyPolicy && params.topLevelSafetyPolicy.protect_last_file !== undefined) {
    return params.topLevelSafetyPolicy;
  }
  return params.summary?.effective_safety_policy || params.topLevelSafetyPolicy || {};
}
