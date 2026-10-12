import type { WorkflowGeneratePlanRequest, WorkflowMode, WorkflowPreviewResponse } from '../types/workflow';

interface LegacyDraftContext {
  preview: WorkflowPreviewResponse | null;
  workflowId: number;
  revision: number;
  mode: WorkflowMode;
  selectedRoots?: readonly number[];
  selectedScanJobId?: number;
  planName: string;
  ready: boolean;
}

/** Prepare only a Draft request from the currently accepted, immutable Preview identity. */
export function buildLegacyDraftRequest(input: LegacyDraftContext): WorkflowGeneratePlanRequest | null {
  const { preview, workflowId, revision, mode, ready, selectedRoots, selectedScanJobId, planName } = input;
  if (!ready || !preview?.compile_digest ||
      preview.workflow_id !== workflowId ||
      (preview.workflow_revision ?? preview.revision) !== revision) return null;

  if (mode === 'dedupe') {
    if (!Number.isSafeInteger(selectedScanJobId) || !selectedScanJobId || selectedScanJobId <= 0 ||
        !preview.dedupe_summary) return null;
    return {
      expected_compile_digest: preview.compile_digest,
      revision, runtime_inputs: { scan_job_id: selectedScanJobId },
      plan_name: planName.trim() || undefined,
    };
  }

  const summary = mode === 'organizer' ? preview.organizer_summary : null;
  if (summary?.advanced_enabled &&
      (!summary.preview_digest || Number(summary.summary?.conflicts ?? 0) > 0)) return null;
  const roots = selectedRoots ? [...selectedRoots] : [];
  if (roots.length > (mode === 'organizer' ? 1 : 16) ||
      roots.some(id => !Number.isSafeInteger(id) || id <= 0) ||
      new Set(roots).size !== roots.length) return null;
  return {
    expected_compile_digest: preview.compile_digest,
    expected_preview_digest: summary?.advanced_enabled ? summary.preview_digest || undefined : undefined,
    revision, runtime_inputs: roots.length ? { root_ids: roots } : undefined,
    plan_name: planName.trim() || undefined,
  };
}

/** A confirmation must remain tied to the exact Preview digest, inputs and revision. */
export function sameLegacyDraftRequest(
  a: WorkflowGeneratePlanRequest | null,
  b: WorkflowGeneratePlanRequest | null,
): boolean {
  return Boolean(a && b && JSON.stringify(a) === JSON.stringify(b));
}
