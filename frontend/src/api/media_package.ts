import { api } from './client';

export type MediaPackageJobStatus = 'queued' | 'running' | 'completed' | 'failed' |
  'cancelled' | 'cancel_requested' | 'paused';

export type MediaPackageStatus =
  'ready' | 'blocked' | 'skipped' | 'already_organized';

export interface MediaPackageGroup {
  name: string;
  kind: 'P' | 'V' | 'Other';
  count: number;
  bytes: number;
  destination: string;
}

export interface MediaPackageSampleMove {
  source: string;
  target: string;
  bytes: number;
  kind: 'P' | 'V' | 'Other';
  source_name?: string;
  target_name?: string;
  original_relative_path?: string;
}

export interface MediaPackageConflict {
  reason: string;
  directory?: string;
  source?: string;
  target?: string;
  detail?: string;
  existing?: string[];
  sources?: string[];
}

export interface MediaPackagePreview {
  package: string;
  status: MediaPackageStatus;
  reason: string | null;
  total_files: number;
  totals: { P: number; V: number; Other: number };
  groups: MediaPackageGroup[];
  conflicts: MediaPackageConflict[];
  sample_moves: MediaPackageSampleMove[];
  total_proposals: number;
  needed_moves: number;
  renamed_count?: number;
  resolved_collision_count?: number;
  operation?: 'flatten_pure_media' | 'bucket_pure_media' | 'sort_mixed_media';
  truncated: boolean;
  read_only: true;
}

export interface MediaPackagePreviewSummary {
  package_count: number;
  ready_count: number;
  blocked_count: number;
  skipped_count: number;
  already_organized_count: number;
  file_count: number;
  needed_moves: number;
  renamed_count?: number;
  resolved_collision_count?: number;
  elapsed_seconds: number;
}

export interface MediaPackagePreviewPage {
  job_id: number;
  status: MediaPackageJobStatus;
  error: string | null;
  selection: string;
  progress: {
    current: number;
    total: number;
    message: string | null;
    current_package?: string;
  };
  summary: MediaPackagePreviewSummary | null;
  packages: MediaPackagePreview[];
  page: number;
  page_size: number;
  read_only: true;
}

export interface MediaPackageExecuteStatus {
  job_id: number;
  status: MediaPackageJobStatus;
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

export const media_packageApi = {
  startPreview: (selection: string) =>
    api.post<{ job_id: number; status: MediaPackageJobStatus }>(
      '/api/media_package/previews', { selection },
    ),
  startExecution: (previewJobId: number, confirmation: string) =>
    api.post<{ job_id: number; status: MediaPackageJobStatus }>(
      `/api/media_package/previews/${previewJobId}/execute`, { confirmation },
    ),
  getExecution: (jobId: number) =>
    api.get<MediaPackageExecuteStatus>(`/api/media_package/executions/${jobId}`),
  recoverExecution: (failedJobId: number, confirmation: string) =>
    api.post<{ job_id: number; status: MediaPackageJobStatus; recovery_of_job_id: number }>(
      `/api/media_package/executions/${failedJobId}/recover`, { confirmation },
    ),
  getPreview: (jobId: number, page: number = 1, pageSize: number = 25) => {
    const query = new URLSearchParams({
      page: String(page), page_size: String(pageSize),
    });
    return api.get<MediaPackagePreviewPage>(`/api/media_package/previews/${jobId}?${query}`);
  },
};
