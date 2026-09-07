import { ScanStep } from '../types/workflow';

export interface ParsedRevisionResult {
  isValid: boolean;
  isHistorical: boolean;
  revision: number | null;
  errorMessage?: string;
}

/**
 * Strictly parses and validates the workflow revision query parameter.
 * Fail-closed: invalid formats, non-integers, non-positive or overflow numbers
 * will return isValid: false with an error message, preventing fallback to current revision.
 */
export function parseWorkflowRevisionQuery(
  rawQuery: string | null | undefined,
  currentRevision?: number
): ParsedRevisionResult {
  if (rawQuery === null || rawQuery === undefined || rawQuery.trim() === '') {
    return {
      isValid: true,
      isHistorical: false,
      revision: null,
    };
  }

  // Strict check: must only contain digits starting with 1-9 (no leading 0, no spaces, no newlines)
  if (!/^[1-9]\d*$/.test(rawQuery)) {
    return {
      isValid: false,
      isHistorical: false,
      revision: null,
      errorMessage: `无效的历史版本号: "${rawQuery}"。版本号必须为大于0的正整数。`,
    };
  }

  const num = Number(rawQuery);
  if (!Number.isSafeInteger(num) || num <= 0) {
    return {
      isValid: false,
      isHistorical: false,
      revision: null,
      errorMessage: `无效的历史版本号: "${rawQuery}"。版本号超出安全整数范围。`,
    };
  }

  // If revision equals current_revision, normalize to current view
  if (currentRevision !== undefined && num === currentRevision) {
    return {
      isValid: true,
      isHistorical: false,
      revision: num,
    };
  }

  return {
    isValid: true,
    isHistorical: true,
    revision: num,
  };
}

/**
 * Computes 1-based sequential row index for paginated tables.
 */
export function computePreviewRowIndex(page: number, pageSize: number, index: number): number {
  return (page - 1) * pageSize + index + 1;
}

/**
 * Creates standard initial scan step with empty root_ids skeleton.
 */
export function createInitialScanStep(id: string = 'step_scan_1'): ScanStep {
  return {
    id,
    type: 'scan',
    root_ids: [],
  };
}
