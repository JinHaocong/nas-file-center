import type { WorkflowListItem } from '../types/workflow';
import { canArchiveWorkflow, canPermanentlyDeleteWorkflow } from './workflowRbac';

export type WorkflowListAction = 'archive' | 'delete';
export interface WorkflowListIntent {
  kind: WorkflowListAction;
  workflowId: number;
  expectedRevision: number;
}

/** Confirm against current list data, not just the snapshot that opened the dialog. */
export function getAuthorizedWorkflowListTarget(
  intent: WorkflowListIntent | null,
  workflows: readonly WorkflowListItem[],
  role: string | undefined,
  busy: boolean,
): WorkflowListItem | null {
  if (!intent || busy || !Number.isSafeInteger(intent.workflowId) || intent.workflowId < 1
    || !Number.isSafeInteger(intent.expectedRevision) || intent.expectedRevision < 1) return null;
  const workflow = workflows.find(item => item.id === intent.workflowId);
  if (!workflow || workflow.current_revision !== intent.expectedRevision || workflow.is_builtin) return null;
  const archived = Boolean(workflow.archived_at);
  if (intent.kind === 'archive') {
    return canArchiveWorkflow(role, archived) ? workflow : null;
  }
  if (intent.kind === 'delete') {
    return canPermanentlyDeleteWorkflow(role, archived, workflow.is_builtin) ? workflow : null;
  }
  return null;
}
