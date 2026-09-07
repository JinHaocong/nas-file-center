export interface RebuildReadinessInput {
  hasPreview: boolean;
  previewInvalidated: boolean;
  acceptedDigest: string | null;
  isLoading: boolean;
  isFetching: boolean;
}

export interface RebuildReadinessResult {
  canSubmit: boolean;
  submitDigest: string | null;
}

export function computeRebuildReadiness(input: RebuildReadinessInput): RebuildReadinessResult {
  const { hasPreview, previewInvalidated, acceptedDigest, isLoading, isFetching } = input;
  if (!hasPreview || previewInvalidated || isLoading || isFetching || !acceptedDigest) {
    return {
      canSubmit: false,
      submitDigest: null,
    };
  }
  return {
    canSubmit: true,
    submitDigest: acceptedDigest,
  };
}
