import type { DedupeStorageAction } from '../../types/dedupe';

/** UI guard mirrors the backend role restriction; the server remains authoritative. */
export function canSelectStorageAction(
  action: DedupeStorageAction, isAdmin: boolean, disabled: boolean,
): boolean {
  return !disabled && (action === 'quarantine' || isAdmin);
}

/** Probe is explicitly requested, administrator-only, and requires a real preview pair. */
export function canRunCapabilityProbe(
  action: DedupeStorageAction, isAdmin: boolean,
  disabled: boolean, busy: boolean, hasDiagnosticPair: boolean,
): boolean {
  return !disabled && !busy && isAdmin && hasDiagnosticPair &&
    (action === 'hardlink' || action === 'reflink');
}
