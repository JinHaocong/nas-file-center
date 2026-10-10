import type { OrganizerPreviewSummary, OrganizerProposal } from '../types';

export type OrganizerPreviewFilter = 'all' | 'changed' | 'conflicts';
export interface OrganizerPreviewPlanState {
  summary: OrganizerPreviewSummary | null;
  advancedEnabled: boolean;
  structuralRequired: boolean;
  previewDigest?: string;
  previewRoot: string;
  selectedRoot: string;
  busy: boolean;
}

export function organizerActionableChanges(summary: OrganizerPreviewSummary | null): number {
  return summary ? Math.max(summary.advanced_changes ?? 0, summary.changed_directories ?? 0) : 0;
}

export function organizerStageActionCount(summary: OrganizerPreviewSummary | null, structuralRequired: boolean): number {
  return structuralRequired ? summary?.wrapper_candidates ?? 0 : organizerActionableChanges(summary);
}
export function organizerPreviewStageLabel(advancedEnabled: boolean, structuralRequired: boolean): string {
  return structuralRequired ? 'Stage A · Structural' : advancedEnabled ? 'Stage B · Rename' : 'Standard';
}
export function organizerProposalStageLabel(proposal: OrganizerProposal, advancedEnabled: boolean): string {
  if (!advancedEnabled) return 'Standard';
  return proposal.proposal_type === 'wrapper_collapse' ? 'Stage A' : 'Stage B';
}
export function organizerProposalRuleLabel(proposal: OrganizerProposal): string {
  const names: Record<string, string> = {
    wrapper_collapse: 'Wrapper collapse',
    directory_rename: 'Directory rename',
    file_rename: 'File numbering',
    latest_child_prefix: 'Latest prefix',
    touch: 'mtime',
  };
  return names[proposal.proposal_type] || proposal.proposal_type || 'Legacy';
}
/** Preview is read-only. A Plan is only offered for the exact current root and live digest. */
export function canGenerateOrganizerPlan(state: OrganizerPreviewPlanState, mtimeMode: 'none' | 'ordered'): boolean {
  const { summary, advancedEnabled, structuralRequired, previewDigest, previewRoot, selectedRoot, busy } = state;
  if (!summary || busy || !selectedRoot.trim() || previewRoot !== selectedRoot.trim() ||
      summary.conflicts !== 0 || (advancedEnabled && !previewDigest)) return false;
  return structuralRequired ||
    organizerActionableChanges(summary) > 0 ||
    (mtimeMode === 'ordered' && summary.total_directories > 0);
}
