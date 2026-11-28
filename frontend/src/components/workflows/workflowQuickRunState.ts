import type { WorkflowPreviewResponse, WorkflowQuickRunRequest } from '../../types/workflow';
import { isSqliteId, sqliteIdText } from '../../utils/sqliteId';

export interface QuickRunSelection {
  workflowId: string;
  revision: number;
  directory: string;
}

const digestPattern = /^[0-9a-f]{64}$/;
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const pending = new Map<string, WorkflowQuickRunRequest>();

/** Accept a review only if it describes the requested version, directory and usable plan. */
export function getReviewedQuickRun(selection: QuickRunSelection | null, preview?: WorkflowPreviewResponse) {
  if (!selection || !preview || preview.workflow_mode !== 'file' ||
      sqliteIdText(preview.workflow_id) !== selection.workflowId ||
      preview.workflow_revision !== selection.revision ||
      preview.file_summary?.directory !== selection.directory ||
      !Number.isSafeInteger(preview.planned_operations_count) || preview.planned_operations_count < 0 ||
      !Array.isArray(preview.items) ||
      !digestPattern.test(preview.compile_digest || '')) return null;
  const counts = preview.file_summary?.operation_counts;
  if (!counts || typeof counts !== 'object' || Array.isArray(counts) ||
      Object.values(counts).some(count => !Number.isSafeInteger(count) || count < 0)) return null;
  return preview;
}

/** Keep unresolved receipts scoped to this account, saved version and directory. */
function pendingKey(account: string, selection: QuickRunSelection) {
  return 'nfc:workflow-quick-run:' + JSON.stringify([account, selection.workflowId, selection.revision, selection.directory]);
}

/** Restore an unresolved request in this tab so a retry always reuses its original token. */
export function readPendingQuickRun(account: string, selection: QuickRunSelection): WorkflowQuickRunRequest | null {
  const key = pendingKey(account, selection);
  const remembered = pending.get(key);
  if (remembered) return remembered;
  try {
    const value: Partial<WorkflowQuickRunRequest> | null = JSON.parse(sessionStorage.getItem(key) ?? 'null');
    if (value?.directory === selection.directory && value.revision === selection.revision &&
        typeof value.request_id === 'string' && uuidPattern.test(value.request_id) &&
        typeof value.expected_compile_digest === 'string' && digestPattern.test(value.expected_compile_digest)) {
      return value as WorkflowQuickRunRequest;
    }
  } catch { /* An unavailable browser store still permits retries in memory. */ }
  return null;
}

/** Record the token before sending an execution request. */
export function rememberPendingQuickRun(account: string, selection: QuickRunSelection, request: WorkflowQuickRunRequest) {
  const key = pendingKey(account, selection);
  pending.set(key, request);
  try { sessionStorage.setItem(key, JSON.stringify(request)); }
  catch { /* The in-memory record still covers close and reopen in this tab. */ }
}

/** Clear the retry token after a receipt or a definitive rejection. */
export function clearPendingQuickRun(account: string, selection: QuickRunSelection) {
  const key = pendingKey(account, selection);
  pending.delete(key);
  try { sessionStorage.removeItem(key); }
  catch { /* The browser store may be unavailable. */ }
}

/** A lost response does not establish whether the worker received the request. */
export function quickRunSubmissionUnknown(status?: number): boolean {
  return status === undefined || status === 0 || status === 408 || status >= 500;
}

/** Use the worker's exact child-task ID, including IDs beyond JS numeric precision. */
export function quickRunExecutionId(checkpoint?: Record<string, unknown> | null): string | null {
  const id = checkpoint?.execution_job_id;
  return typeof id === 'string' && isSqliteId(id) ? id : null;
}

/** Construct a UUID using secure randomness, including on HTTP origins without randomUUID. */
export function createQuickRunRequestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
}
