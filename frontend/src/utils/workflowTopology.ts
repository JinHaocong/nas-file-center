import { WorkflowStep, WorkflowStepType } from '../types/workflow';

export interface ValidationResult {
  valid: boolean;
  error?: string;
}

export function validateWorkflowStepOrder(
  steps: WorkflowStep[],
  mode: 'file' | 'organizer'
): ValidationResult {
  if (!steps || steps.length === 0) {
    return { valid: false, error: '工作流至少需要包含一个扫描步骤 (Scan)' };
  }

  // Common: step 0 must be scan
  if (steps[0].type !== 'scan') {
    return { valid: false, error: '首个步骤必须是扫描步骤 (Scan)' };
  }

  const scanCount = steps.filter((s) => s.type === 'scan').length;
  if (scanCount !== 1) {
    return { valid: false, error: '工作流中只能包含一个扫描步骤 (Scan)' };
  }

  if (mode === 'organizer') {
    if (steps.length !== 2) {
      return { valid: false, error: '整理模式 (Organizer) 必须且只能包含两个步骤：Scan -> Organize' };
    }
    if (steps[1].type !== 'organize') {
      return { valid: false, error: '整理模式 (Organizer) 第二个步骤必须是 Organize' };
    }
    return { valid: true };
  }

  // File mode
  let seenAction = false;
  const quarantineIdx = steps.findIndex((s) => s.type === 'quarantine');

  if (quarantineIdx !== -1 && quarantineIdx !== steps.length - 1) {
    return { valid: false, error: '隔离步骤 (Quarantine) 必须是终端步骤，其后不能包含任何其他步骤' };
  }

  for (let i = 1; i < steps.length; i++) {
    const type = steps[i].type;
    if (type === 'organize') {
      return { valid: false, error: '文件模式下不允许包含 Organize 步骤' };
    }
    if (type === 'rename' || type === 'move' || type === 'touch') {
      seenAction = true;
    } else if (type === 'filter') {
      if (seenAction) {
        return { valid: false, error: '过滤器步骤 (Filter) 必须位于所有操作步骤 (Rename, Move, Touch, Quarantine) 之前' };
      }
    }
  }

  return { valid: true };
}

export function getAllowedInsertions(
  steps: WorkflowStep[],
  mode: 'file' | 'organizer'
): WorkflowStepType[] {
  if (mode === 'organizer') {
    // Organizer mode has fixed topology: Scan -> Organize. No further insertions allowed.
    return [];
  }

  // If quarantine is present (which must be terminal), no further steps can be added.
  const hasQuarantine = steps.some((s) => s.type === 'quarantine');
  if (hasQuarantine) {
    return [];
  }

  // Filter can only appear after Scan and before the first Action.
  // Once an action (rename, move, touch) exists, filter can no longer be appended.
  const hasAction = steps.some((s) => s.type === 'rename' || s.type === 'move' || s.type === 'touch');
  if (hasAction) {
    return ['rename', 'move', 'touch', 'quarantine'];
  }

  return ['filter', 'rename', 'move', 'touch', 'quarantine'];
}

export function canMoveStep(
  steps: WorkflowStep[],
  index: number,
  direction: 'up' | 'down',
  mode: 'file' | 'organizer'
): boolean {
  if (mode === 'organizer') {
    return false;
  }
  if (index === 0) {
    // Scan step can never move
    return false;
  }
  const targetIndex = direction === 'up' ? index - 1 : index + 1;
  if (targetIndex <= 0 || targetIndex >= steps.length) {
    return false;
  }

  // Simulate swap and validate
  const cloned = [...steps];
  const temp = cloned[index];
  cloned[index] = cloned[targetIndex];
  cloned[targetIndex] = temp;

  return validateWorkflowStepOrder(cloned, mode).valid;
}

export function canDeleteStep(
  steps: WorkflowStep[],
  index: number,
  mode: 'file' | 'organizer'
): boolean {
  if (index === 0) {
    // Scan step can never be deleted
    return false;
  }
  if (mode === 'organizer') {
    return false;
  }
  const remaining = steps.filter((_, i) => i !== index);
  return validateWorkflowStepOrder(remaining, mode).valid;
}
