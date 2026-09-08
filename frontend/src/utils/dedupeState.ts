export type DedupeStateMachineStatus =
  | 'INITIAL'
  | 'PREVIEW_RUNNING'
  | 'PREVIEW_READY'
  | 'PREVIEW_STALE'
  | 'GENERATING';

export interface DedupeState {
  status: DedupeStateMachineStatus;
  configGeneration: number;
  activeRequestGeneration: number | null;
  acceptedPreviewDigest: string | null;
  currentPreviewDigest: string | null;
  lastErrorMessage: string | null;
}

export type DedupeAction =
  | { type: 'CONFIG_EDITED' }
  | { type: 'PREVIEW_STARTED' }
  | { type: 'PREVIEW_SUCCESS'; digest: string; requestGeneration: number }
  | { type: 'PREVIEW_FAILED'; error?: string }
  | { type: 'PREVIEW_CHANGED_ERROR'; error?: string }
  | { type: 'GENERATE_STARTED' }
  | { type: 'GENERATE_FAILED'; error?: string }
  | { type: 'GENERATE_SUCCESS' }
  | { type: 'RESET' };

export const initialDedupeState: DedupeState = {
  status: 'INITIAL',
  configGeneration: 1,
  activeRequestGeneration: null,
  acceptedPreviewDigest: null,
  currentPreviewDigest: null,
  lastErrorMessage: null,
};

export function dedupeStateReducer(state: DedupeState, action: DedupeAction): DedupeState {
  switch (action.type) {
    case 'CONFIG_EDITED':
      return {
        ...state,
        configGeneration: state.configGeneration + 1,
        acceptedPreviewDigest: null,
        currentPreviewDigest: null,
        status: 'PREVIEW_STALE',
        lastErrorMessage: null,
      };
    case 'PREVIEW_STARTED':
      return {
        ...state,
        status: 'PREVIEW_RUNNING',
        activeRequestGeneration: state.configGeneration,
        lastErrorMessage: null,
      };
    case 'PREVIEW_SUCCESS':
      if (action.requestGeneration === state.configGeneration) {
        return {
          ...state,
          status: 'PREVIEW_READY',
          activeRequestGeneration: null,
          acceptedPreviewDigest: action.digest,
          currentPreviewDigest: action.digest,
          lastErrorMessage: null,
        };
      }
      return {
        ...state,
        activeRequestGeneration: null,
      };
    case 'PREVIEW_FAILED':
    case 'PREVIEW_CHANGED_ERROR':
      return {
        ...state,
        status: 'PREVIEW_STALE',
        activeRequestGeneration: null,
        acceptedPreviewDigest: null,
        currentPreviewDigest: null,
        lastErrorMessage: action.error || null,
      };
    case 'GENERATE_STARTED':
      return {
        ...state,
        status: 'GENERATING',
      };
    case 'GENERATE_FAILED':
      return {
        ...state,
        status: state.acceptedPreviewDigest ? 'PREVIEW_READY' : 'PREVIEW_STALE',
        lastErrorMessage: action.error || null,
      };
    case 'GENERATE_SUCCESS':
      return {
        ...state,
        status: 'PREVIEW_READY',
      };
    case 'RESET':
      return initialDedupeState;
    default:
      return state;
  }
}

export function canGeneratePlan(state: DedupeState): boolean {
  return (
    state.status === 'PREVIEW_READY' &&
    state.acceptedPreviewDigest !== null &&
    state.acceptedPreviewDigest === state.currentPreviewDigest &&
    state.activeRequestGeneration === null
  );
}
