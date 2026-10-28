import type { QuarantineRecoveryDiagnostic } from '../../types';
import { getStructuredApiError } from '../../api/errors';

/** A preflight UI gate only. The server must re-check all evidence on DELETE. */
export function canOfferMissingPurgingRecordConfirmation(
  diagnostic: QuarantineRecoveryDiagnostic,
): boolean {
  return diagnostic.state === 'purging' &&
    diagnostic.reason === 'legacy_purge_requires_verification' &&
    diagnostic.tx_phase === null &&
    diagnostic.transaction_mode === null &&
    diagnostic.has_authoritative_anchor === false &&
    diagnostic.active_attempt_generation === 0 &&
    diagnostic.payload_path_observation === 'absent' &&
    diagnostic.transaction_evidence_observation === 'absent';
}

/** Translate the existing fail-closed 409 instead of exposing an English toast. */
export function isFrozenMissingRecordConflict(error: unknown): boolean {
  const parsed = getStructuredApiError(error);
  return parsed.status === 409 &&
    /transactional\/frozen evidence/i.test(parsed.message);
}
