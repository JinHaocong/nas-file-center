import type { ScanJob } from '../types';

/** Reject floats, signs, exponent notation, unsafe integers and empty IDs. */
export function parseCompletedScanJobId(raw: string): number | null {
  if (!/^[1-9]\d*$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/** A fresh detail response must match the ID that was actually verified. */
export function verifiedCompletedScanId(
  requestedId: number,
  detail: Pick<ScanJob, 'id' | 'status'> | null | undefined,
): number | null {
  return Number.isSafeInteger(requestedId) && requestedId > 0 &&
    detail?.id === requestedId && detail.status === 'completed'
    ? requestedId : null;
}

/** Never display or apply non-completed records from a mixed server page. */
export function completedScanJobs(scans: ScanJob[]): ScanJob[] {
  return scans.filter(scan => scan.status === 'completed');
}
