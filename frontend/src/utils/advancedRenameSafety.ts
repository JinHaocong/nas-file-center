import type { RenameProposal } from '../types';

export interface AdvancedRenameDraft {
  paths: string[];
  regex_pattern: string;
  regex_replacement: string;
  source_extension: string;
  target_extension: string;
  prefix: string;
  suffix: string;
  number_start: string;
  number_width: string;
  include_parent: boolean;
}
export interface AdvancedRenameRequest {
  paths: string[];
  regex_pattern: string | null;
  regex_replacement: string;
  prefix: string;
  suffix: string;
  number_start: number | null;
  number_width: number;
  include_parent: boolean;
  source_extension: string;
  target_extension: string;
}

export const DEFAULT_ADVANCED_RENAME_DRAFT: AdvancedRenameDraft = {
  paths: [], regex_pattern: '', regex_replacement: '',
  source_extension: '', target_extension: '',
  prefix: '', suffix: '', number_start: '', number_width: '3', include_parent: false,
};

/** Existing /api/rename/preview request, including 0 as a valid numbering start. */
export function buildAdvancedRenameRequest(draft: AdvancedRenameDraft): AdvancedRenameRequest | null {
  const paths = draft.paths.filter(path => typeof path === 'string' && path.trim().length > 0);
  if (paths.length === 0) return null;
  const parsedStart = draft.number_start.trim() === '' ? null : Number(draft.number_start);
  const parsedWidth = Number(draft.number_width);
  if (parsedStart !== null && (!Number.isSafeInteger(parsedStart) || parsedStart < 0)) return null;
  if (!Number.isSafeInteger(parsedWidth) || parsedWidth < 1 || parsedWidth > 10) return null;
  // Keep server-side extension validation authoritative: do not silently synthesize values.
  return {
    paths,
    regex_pattern: draft.regex_pattern || null,
    regex_replacement: draft.regex_replacement || '',
    prefix: draft.prefix || '',
    suffix: draft.suffix || '',
    number_start: parsedStart,
    number_width: parsedWidth,
    include_parent: Boolean(draft.include_parent),
    source_extension: draft.source_extension || '',
    target_extension: draft.target_extension || '',
  };
}

/** A Plan can only be created from the exact currently selected rule/path preview. */
export function canGenerateAdvancedRenamePlan(
  proposals: readonly RenameProposal[] | null, currentPreviewKey: string | null, busy: boolean,
): boolean {
  return !busy && Boolean(currentPreviewKey) && Boolean(proposals?.length) &&
    !proposals!.some(item => item.conflict || !item.source || !item.target ||
      item.source === item.target);
}
