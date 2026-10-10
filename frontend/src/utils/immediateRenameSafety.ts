import type { RenameProposal } from '../types';

export type ImmediateRenameKind = 'directory' | 'file';
export type ImmediateRenameModule = 'replace' | 'add';
export type ImmediateRenameMode = 'replace_name' | 'replace_suffix' | 'add_prefix' | 'add_suffix';
export interface ImmediateRenameDraft {
  parent: string;
  module: ImmediateRenameModule;
  replaceTarget: 'name' | 'suffix';
  addPosition: 'prefix' | 'suffix';
  find: string;
  value: string;
  preserveExtension: boolean;
}
export interface ImmediateRenameRequest {
  parent: string;
  mode: ImmediateRenameMode;
  find: string;
  value: string;
  preserve_extension?: boolean;
}
export const DEFAULT_IMMEDIATE_RENAME_DRAFT: ImmediateRenameDraft = {
  parent: '', module: 'replace', replaceTarget: 'name', addPosition: 'prefix',
  find: '', value: '', preserveExtension: true,
};
/** Preserve literal find/replacement bytes; the backend enforces paths and filename safety. */
export function buildImmediateRenameRequest(kind: ImmediateRenameKind, draft: ImmediateRenameDraft): ImmediateRenameRequest | null {
  if (!draft.parent.trim()) return null;
  if (draft.module === 'replace' && !draft.find) return null;
  if (draft.module === 'add' && !draft.value) return null;
  const mode: ImmediateRenameMode = draft.module === 'replace'
    ? (draft.replaceTarget === 'name' ? 'replace_name' : 'replace_suffix')
    : (draft.addPosition === 'prefix' ? 'add_prefix' : 'add_suffix');
  const result: ImmediateRenameRequest = {
    parent: draft.parent, mode, find: draft.find, value: draft.value,
  };
  if (kind === 'file') result.preserve_extension = draft.preserveExtension;
  return result;
}
export function canCreateImmediateRenamePlan(
  proposals: readonly RenameProposal[] | null,
  activePreviewKey: string | null,
  busy: boolean,
): boolean {
  return !busy && Boolean(activePreviewKey) && Boolean(proposals?.length) &&
    !proposals!.some(item => item.conflict || !item.source || !item.target || item.source === item.target);
}
