export type WorkflowPreviewState =
  | 'CLEAN_SAVED'
  | 'EDITING_DIRTY'
  | 'SAVED_PREVIEW_REQUIRED'
  | 'PREVIEWING'
  | 'PREVIEW_READY'
  | 'PREVIEW_STALE';

export type PreviewEvent =
  | { type: 'DIRTY_CHANGE'; isDirty: boolean }
  | { type: 'START_PREVIEW' }
  | { type: 'PREVIEW_SUCCESS'; compileDigest: string }
  | { type: 'PREVIEW_ERROR'; message?: string }
  | { type: 'ROOTS_CHANGE' }
  | { type: 'ONLY_CHANGED_TOGGLE' }
  | { type: 'PREVIEW_CHANGED_ERROR' };

export function transitionPreviewState(
  currentState: WorkflowPreviewState,
  event: PreviewEvent
): WorkflowPreviewState {
  switch (event.type) {
    case 'DIRTY_CHANGE':
      return event.isDirty ? 'EDITING_DIRTY' : 'SAVED_PREVIEW_REQUIRED';

    case 'START_PREVIEW':
      return 'PREVIEWING';

    case 'PREVIEW_SUCCESS':
      return 'PREVIEW_READY';

    case 'PREVIEW_ERROR':
    case 'ROOTS_CHANGE':
    case 'ONLY_CHANGED_TOGGLE':
    case 'PREVIEW_CHANGED_ERROR':
      return 'PREVIEW_STALE';

    default:
      return currentState;
  }
}
