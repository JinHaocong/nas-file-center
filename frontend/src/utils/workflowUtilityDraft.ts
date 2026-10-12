import type {
  WorkflowPreviewResponse, WorkflowUtilityCandidate, WorkflowUtilitySummary,
  WorkflowGeneratePlanRequest,
} from '../types/workflow';

/** Only READY and explicitly selectable candidates can enter a utility Draft. */
export function selectableUtilityCandidateIds(
  candidates: readonly WorkflowUtilityCandidate[],
): string[] {
  return candidates.filter(item =>
    item.state === 'READY' && item.selectable && !!item.candidate_id
  ).map(item => item.candidate_id);
}

/** The server's default selection is advisory, never an authority to select blocked items. */
export function initialUtilityCandidateIds(
  summary: WorkflowUtilitySummary | null | undefined,
): string[] {
  if (!summary) return [];
  const proposed = summary.selected_candidate_ids ??
    summary.candidates.filter(candidate => candidate.selected).map(candidate => candidate.candidate_id);
  return sanitizeUtilityCandidateIds(summary.candidates, proposed);
}

export function sanitizeUtilityCandidateIds(
  candidates: readonly WorkflowUtilityCandidate[],
  selected: readonly string[],
): string[] {
  const valid = new Set(selectableUtilityCandidateIds(candidates));
  return [...new Set(selected.filter(id => valid.has(id)))];
}

interface DraftReadiness {
  preview: WorkflowPreviewResponse | null;
  workflowId: number;
  revision: number;
  contextValid: boolean;
  isDirty: boolean;
  isArchived: boolean;
  previewPending: boolean;
  generatePending: boolean;
  selectedCandidateIds: readonly string[];
}

export function utilityDraftRequest(
  state: DraftReadiness,
  customPlanName: string,
): WorkflowGeneratePlanRequest | null {
  const {
    preview, workflowId, revision, contextValid, isDirty, isArchived,
    previewPending, generatePending, selectedCandidateIds,
  } = state;
  if (!preview || !contextValid || isDirty || isArchived ||
      previewPending || generatePending || !preview.compile_digest ||
      preview.workflow_id !== workflowId ||
      (preview.workflow_revision ?? preview.revision) !== revision) return null;
  const candidates = preview.utility_summary?.candidates || [];
  const selected = sanitizeUtilityCandidateIds(candidates, selectedCandidateIds);
  if (selected.length === 0 || selected.length !== selectedCandidateIds.length) return null;
  return {
    expected_compile_digest: preview.compile_digest,
    revision,
    selected_candidate_ids: selected,
    plan_name: customPlanName.trim() || undefined,
  };
}

/** Detect a changed confirmation snapshot before network submission. */
export function sameUtilityDraftRequest(
  previous: WorkflowGeneratePlanRequest | null,
  current: WorkflowGeneratePlanRequest | null,
): boolean {
  if (!previous || !current) return false;
  return previous.expected_compile_digest === current.expected_compile_digest &&
    previous.revision === current.revision &&
    previous.plan_name === current.plan_name &&
    JSON.stringify(previous.selected_candidate_ids) === JSON.stringify(current.selected_candidate_ids);
}
