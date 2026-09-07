export function canCreateWorkflow(role?: string, _isArchived: boolean = false): boolean {
  return role === 'admin';
}

export function canSaveRevision(role?: string, isArchived: boolean = false): boolean {
  if (isArchived) return false;
  return role === 'admin';
}

export function canArchiveWorkflow(role?: string, isArchived: boolean = false): boolean {
  if (isArchived) return false;
  return role === 'admin';
}

export function canRollbackWorkflow(role?: string, isArchived: boolean = false): boolean {
  if (isArchived) return false;
  return role === 'admin';
}

export function canPreviewWorkflow(isArchived: boolean = false): boolean {
  return !isArchived;
}

export function canGenerateDraft(isArchived: boolean = false): boolean {
  return !isArchived;
}

export interface WorkflowModeSwitchContext {
  isBuiltin?: boolean;
  isArchived?: boolean;
  isHistorical?: boolean;
}

export function canSwitchWorkflowMode(
  role?: string,
  context: WorkflowModeSwitchContext = {}
): boolean {
  if (role !== 'admin') return false;
  if (context.isBuiltin) return false;
  if (context.isArchived) return false;
  if (context.isHistorical) return false;
  return true;
}
