import { api } from './client';

export type LuolcyJobStatus = 'queued' | 'running' | 'completed' | 'failed' |
  'cancelled' | 'cancel_requested' | 'paused';

export type LuolcyPackageStatus =
  'ready' | 'blocked' | 'skipped' | 'already_organized';

export interface LuolcyGroup {
  name: string;
  kind: 'P' | 'V' | 'Other';
  count: number;
  bytes: number;
  destination: string;
}

export interface LuolcySampleMove {
  source: string;
  target: string;
  bytes: number;
  kind: 'P' | 'V' | 'Other';
}

export interface LuolcyConflict {
  reason: string;
  directory?: string;
  source?: string;
  target?: string;
  detail?: string;
  existing?: string[];
  sources?: string[];
}

export interface LuolcyPackagePreview {
  package: string;
  status: LuolcyPackageStatus;
  reason: string | null;
  total_files: number;
  totals: { P: number; V: number; Other: number };
  groups: LuolcyGroup[];
  conflicts: LuolcyConflict[];
  sample_moves: LuolcySampleMove[];
  total_proposals: number;
  needed_moves: number;
  operation?: 'flatten_pure_media' | 'bucket_pure_media' | 'sort_mixed_media';
  truncated: boolean;
  read_only: true;
}

export interface LuolcyPreviewSummary {
  package_count: number;
  ready_count: number;
  blocked_count: number;
  skipped_count: number;
  already_organized_count: number;
  file_count: number;
  needed_moves: number;
  elapsed_seconds: number;
}

export interface LuolcyPreviewPage {
  job_id: number;
  status: LuolcyJobStatus;
  error: string | null;
  selection: string;
  progress: {
    current: number;
    total: number;
    message: string | null;
    current_package?: string;
  };
  summary: LuolcyPreviewSummary | null;
  packages: LuolcyPackagePreview[];
  page: number;
  page_size: number;
  read_only: true;
}

export interface LuolcyExecuteStatus {
  job_id: number;
  status: LuolcyJobStatus;
  error: string | null;
  preview_job_id: number;
  progress: {
    current: number;
    total: number;
    message: string | null;
    package?: string;
    package_file_progress?: number;
  };
}

export const luolcyApi = {
  startPreview: (selection: string) =>
    api.post<{ job_id: number; status: LuolcyJobStatus }>(
      '/api/luolcy/previews', { selection },
    ),
  startExecution: (previewJobId: number, confirmation: string) =>
    api.post<{ job_id: number; status: LuolcyJobStatus }>(
      `/api/luolcy/previews/${previewJobId}/execute`, { confirmation },
    ),
  getExecution: (jobId: number) =>
    api.get<LuolcyExecuteStatus>(`/api/luolcy/executions/${jobId}`),
  getPreview: (jobId: number, page: number = 1, pageSize: number = 25) => {
    const query = new URLSearchParams({
      page: String(page), page_size: String(pageSize),
    });
    return api.get<LuolcyPreviewPage>(`/api/luolcy/previews/${jobId}?${query}`);
  },
};
