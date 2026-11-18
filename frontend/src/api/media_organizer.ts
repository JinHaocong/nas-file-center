import { api } from './client';

export type SemanticPreviewStatus = 'queued' | 'running' | 'completed' | 'failed' |
  'cancelled' | 'cancel_requested' | 'paused';
export type SemanticUnitStatus = 'ready' | 'blocked' | 'skipped' | 'already_organized';

export interface SemanticMediaGroup {
  name: string;
  kind: 'P' | 'V' | 'Other';
  count: number;
  bytes: number;
  destination: string;
}

export interface SemanticMovePreview {
  source: string;
  target: string;
  target_name: string;
  kind: 'P' | 'V' | 'Other';
  bytes: number;
}

export interface SemanticUnitPreview {
  unit: string;
  status: SemanticUnitStatus;
  reason: string | null;
  operation: 'flatten_pure_media' | 'bucket_pure_media' | 'sort_mixed_media' | null;
  totals: { P: number; V: number; Other: number };
  groups: SemanticMediaGroup[];
  needed_moves: number;
  renamed_count: number;
  total_files: number;
  total_proposals: number;
  sample_moves: SemanticMovePreview[];
  truncated: boolean;
  input_fingerprint?: string | null;
  conflicts: string[];
  read_only: true;
}

export interface SemanticPreviewSummary {
  unit_count: number;
  ready_count: number;
  blocked_count: number;
  already_organized_count: number;
  skipped_count: number;
  file_count: number;
  needed_moves: number;
  renamed_count: number;
  elapsed_seconds: number;
  read_only: true;
}

export interface SemanticPreviewPage {
  job_id: number;
  status: SemanticPreviewStatus;
  error: string | null;
  selection: string;
  progress: { current: number; total: number; message: string | null };
  summary: SemanticPreviewSummary | null;
  units: SemanticUnitPreview[];
  page: number;
  page_size: number;
  filtered_total: number;
  read_only: true;
  execution_enabled: boolean;
  confirmation_tokens: Record<string, string>;
}

export interface SemanticExecutionStatus {
  job_id: number;
  status: SemanticPreviewStatus;
  error: string | null;
  preview_job_id: number;
  unit: string;
  recovery_of_job_id: number | null;
  manual_cleanup_required: boolean;
  finalized: boolean;
  progress: {
    current: number;
    total: number;
    message: string | null;
    phase?: string;
  };
}

export const mediaOrganizerApi = {
  startExecution: (previewJobId: number, unit: string, confirmation: string) =>
    api.post<{ job_id: number; status: SemanticPreviewStatus }>(
      `/api/media-organizer/previews/${previewJobId}/execute`,
      { unit, confirmation },
    ),
  getExecution: (jobId: number) =>
    api.get<SemanticExecutionStatus>(`/api/media-organizer/executions/${jobId}`),
  recoverExecution: (jobId: number, confirmation: string) =>
    api.post<{ job_id: number; status: SemanticPreviewStatus; recovery_of_job_id: number }>(
      `/api/media-organizer/executions/${jobId}/recover`,
      { confirmation },
    ),
  startPreview: (selection: string) =>
    api.post<{ job_id: number; status: SemanticPreviewStatus }>(
      '/api/media-organizer/previews', { selection },
    ),
  getPreview: (jobId: number, page = 1, pageSize = 25, statusFilter = 'all') => {
    const query = new URLSearchParams({
      page: String(page), page_size: String(pageSize), status_filter: statusFilter,
    });
    return api.get<SemanticPreviewPage>(`/api/media-organizer/previews/${jobId}?${query}`);
  },
};
