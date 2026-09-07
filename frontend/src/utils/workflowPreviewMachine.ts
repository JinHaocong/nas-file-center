export type WorkflowPreviewState =
  | 'CLEAN_SAVED'
  | 'EDITING_DIRTY'
  | 'SAVING'
  | 'SAVED_PREVIEW_REQUIRED'
  | 'PREVIEWING'
  | 'PREVIEW_READY'
  | 'PREVIEW_STALE'
  | 'GENERATING';

export type PreviewEvent =
  | { type: 'DIRTY_CHANGE'; isDirty: boolean }
  | { type: 'START_SAVE' }
  | { type: 'SAVE_SUCCESS' }
  | { type: 'SAVE_ERROR' }
  | { type: 'START_PREVIEW' }
  | { type: 'PREVIEW_SUCCESS'; compileDigest?: string }
  | { type: 'PREVIEW_ERROR'; message?: string }
  | { type: 'ROOTS_CHANGE' }
  | { type: 'ONLY_CHANGED_TOGGLE' }
  | { type: 'START_GENERATE' }
  | { type: 'GENERATE_SUCCESS' }
  | { type: 'GENERATE_ERROR' }
  | { type: 'PREVIEW_CHANGED_ERROR' };

export function transitionPreviewState(
  currentState: WorkflowPreviewState,
  event: PreviewEvent
): WorkflowPreviewState {
  switch (event.type) {
    case 'DIRTY_CHANGE':
      return event.isDirty ? 'EDITING_DIRTY' : 'SAVED_PREVIEW_REQUIRED';

    case 'START_SAVE':
      return 'SAVING';

    case 'SAVE_SUCCESS':
      return 'SAVED_PREVIEW_REQUIRED';

    case 'SAVE_ERROR':
      return 'EDITING_DIRTY';

    case 'START_PREVIEW':
      return 'PREVIEWING';

    case 'PREVIEW_SUCCESS':
      return 'PREVIEW_READY';

    case 'PREVIEW_ERROR':
    case 'ROOTS_CHANGE':
    case 'ONLY_CHANGED_TOGGLE':
    case 'PREVIEW_CHANGED_ERROR':
      return 'PREVIEW_STALE';

    case 'START_GENERATE':
      return 'GENERATING';

    case 'GENERATE_SUCCESS':
      return 'CLEAN_SAVED';

    case 'GENERATE_ERROR':
      return 'PREVIEW_READY';

    default:
      return currentState;
  }
}
