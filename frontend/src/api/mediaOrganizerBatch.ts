import { api } from './client';
import type { TaskProgress, TaskStatus } from '../types/task';
import { isSqliteId } from '../utils/sqliteId';

export type OrganizerJobId = string;
type MediaKind = 'P' | 'V' | 'Other';
type MediaUnitStatus = 'ready' | 'blocked' | 'already_organized' | 'skipped' | 'needs_assignment';
export type MediaPreviewFilter = MediaUnitStatus | 'all';
export type MediaBatchOutcome = 'success' | 'skipped' | 'conflict' | 'failed';
export type MediaBatchResultFilter = MediaBatchOutcome | 'all';

interface OrganizerJobReceipt {
  job_id: OrganizerJobId;
  status: TaskStatus;
}

interface OrganizerJob extends OrganizerJobReceipt {
  selection: string;
  error: string | null;
  progress: Omit<TaskProgress, 'percent'>;
}

interface Page {
  page: number;
  page_size: number;
}

interface OrganizerReportPage extends Page {
  filtered_total: number;
}

interface MediaPreviewConflict {
  reason: string;
  target?: string;
  directory?: string;
  existing?: string[];
}

type OrganizerMappingKind = MediaKind | 'Directory';

export interface MediaBatchPreviewUnit {
  unit: string;
  status: MediaUnitStatus;
  reason: string | null;
  operation?: string | null;
  totals: Record<MediaKind, number>;
  total_bytes?: number;
  groups: Array<{ name: string; destination: string; count: number; bytes: number }>;
  sample_moves?: Array<{ source: string; target: string; kind: OrganizerMappingKind; bytes: number }>;
  needed_moves: number;
  renamed_count: number;
  wrapper_cleanup_count?: number;
  wrapper_cleanup_paths?: string[];
  preserved_directory_paths?: string[];
  recycle_reason?: 'url_shortcut' | 'links_only' | 'promotion' | 'text_file';
  total_proposals: number;
  mapping_id: string | null;
  loose_id?: string;
  conflicts: MediaPreviewConflict[];
}

export interface MediaBatchPreview extends OrganizerJob, OrganizerReportPage {
  batch_job_id?: OrganizerJobId | null;
  execution_enabled: boolean;
  units: MediaBatchPreviewUnit[];
  summary: {
    unit_count: number;
    ready_count: number;
    blocked_count: number;
    already_organized_count: number;
    skipped_count: number;
    needs_assignment_count?: number;
    file_count: number;
    totals?: Record<MediaKind, number>;
    total_bytes?: number;
    needed_moves: number;
    renamed_count: number;
    wrapper_cleanup_count?: number;
    recycle_count?: number;
  } | null;
}

interface MediaMappingPage extends Page {
  total_moves: number;
  moves: Array<{ source: string; target: string; kind: OrganizerMappingKind; bytes: number }>;
}

interface MediaLooseFilesPage extends Page {
  job_id: OrganizerJobId;
  loose_id: string;
  author: string;
  total_files: number;
  packages: string[];
  files: Array<{ source: string; kind: MediaKind; bytes: number }>;
  read_only: true;
}

interface MediaLooseAssignmentRequest {
  sources: string[];
  package_name: string;
  new_package: boolean;
}

interface MediaLooseAssignmentDraft {
  plan_id: string;
  status: 'draft';
  expected_changes: number;
}

export interface MediaBatchResult extends OrganizerJob, OrganizerReportPage {
  results_archived?: boolean;
  preview_job_id: OrganizerJobId;
  report_cleanup_status?: 'pending' | 'released' | 'missing';
  summary: Record<`${MediaBatchOutcome}_count`, number>;
  items: Array<{ unit: string; status: MediaBatchOutcome; reason?: string | null; operation?: string }>;
}

const base = '/api/media-organizer';

/** Accept one exact, positive SQLite WorkJob ID without a numeric conversion. */
export function organizerJobId(params: URLSearchParams, key: string): OrganizerJobId | null {
  const values = params.getAll(key);
  if (values.length !== 1) return null;
  const [id] = values;
  return isSqliteId(id) ? id : null;
}

/** Keep pagination parameters consistent across preview, mapping, and result reads. */
function pagination(page: number, pageSize: number) {
  return new URLSearchParams({ page: String(page), page_size: String(pageSize) });
}

export const mediaOrganizerBatchApi = {
  /** Queue a read-only recursive scan of the selected directory. */
  startPreview: (selection: string) =>
    api.post<OrganizerJobReceipt>(`${base}/previews`, { selection, batch_flow: true }),
  /** Read one page of the scope preview. */
  getPreview: (id: OrganizerJobId, page: number, pageSize: number, status: MediaPreviewFilter) => {
    const query = pagination(page, pageSize);
    query.set('status_filter', status);
    return api.get<MediaBatchPreview>(`${base}/previews/${id}?${query}`);
  },
  /** Read a complete per-unit mapping, one page at a time. */
  getMapping: (id: OrganizerJobId, mappingId: string, page: number, pageSize: number) =>
    api.get<MediaMappingPage>(
      `${base}/previews/${id}/mappings/${encodeURIComponent(mappingId)}?${pagination(page, pageSize)}`,
    ),
  /** Read the files directly inside one author directory and its existing package choices. */
  getLooseFiles: (id: OrganizerJobId, looseId: string, page: number, pageSize: number) =>
    api.get<MediaLooseFilesPage>(
      `${base}/previews/${id}/loose-files/${encodeURIComponent(looseId)}?${pagination(page, pageSize)}`,
    ),
  /** Create a plan draft for exactly the selected sources and one same-author package. */
  createAssignmentDraft: (id: OrganizerJobId, looseId: string, payload: MediaLooseAssignmentRequest) =>
    api.post<MediaLooseAssignmentDraft>(
      `${base}/previews/${id}/loose-files/${encodeURIComponent(looseId)}/assignments`, payload,
    ),
  /** Confirm all ready units bound to the reviewed preview. */
  startBatch: (previewId: OrganizerJobId) =>
    api.post<OrganizerJobReceipt>(`${base}/previews/${previewId}/batches`, {}),
  /** Read the durable progress and paginated outcomes of one batch. */
  getBatch: (id: OrganizerJobId, page: number, pageSize: number, status: MediaBatchResultFilter = 'all') => {
    const query = pagination(page, pageSize);
    if (status !== 'all') query.set('status_filter', status);
    return api.get<MediaBatchResult>(`${base}/batches/${id}?${query}`);
  },
};
