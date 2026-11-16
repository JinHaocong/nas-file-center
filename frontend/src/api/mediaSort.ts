import { api } from './client';

export interface MediaSortRow {
  source: string;
  target: string;
  media_kind: 'image' | 'video';
  expected_size: number;
  conflict: boolean;
  conflict_reason: string | null;
}

export type MediaSortSkipReason = 'pure_images' | 'pure_videos' | 'no_media' | 'preclassified';

export interface MediaSortSkippedDirectory {
  path: string;
  reason: MediaSortSkipReason;
  image_count: number;
  video_count: number;
}

export interface MediaSortPreview {
  parent: string;
  recursive: boolean;
  smart_skip: boolean;
  scanned_directories: number;
  skipped_directory_count: number;
  skipped_directories: MediaSortSkippedDirectory[];
  count: number;
  image_count: number;
  video_count: number;
  ready_count: number;
  conflict_count: number;
  items: MediaSortRow[];
}

export type MediaSortItemFilter = 'all' | 'ready' | 'conflict';

export type MediaSortJobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'cancel_requested' | 'paused';

export interface MediaSortProgress {
  current: number;
  total: number;
  message: string | null;
  scanned_directories?: number;
  scanned_entries?: number;
  candidate_count?: number;
  skipped_directory_count?: number;
  current_directory?: string;
  pending_directories?: number;
}

export interface MediaSortSummary extends Omit<MediaSortPreview, 'items' | 'skipped_directories'> {
  scanned_entries: number;
}

export interface MediaSortPreviewPage {
  job_id: number;
  status: MediaSortJobStatus;
  error: string | null;
  progress: MediaSortProgress;
  parent: string;
  recursive: boolean;
  smart_skip: boolean;
  summary: MediaSortSummary | null;
  items: MediaSortRow[];
  skipped_directories: MediaSortSkippedDirectory[];
  item_filter: MediaSortItemFilter;
  item_total: number | null;
  page: number;
  page_size: number;
  skip_page: number;
  skip_page_size: number;
}

export interface MediaSortJobResult {
  job_id: number;
  status: MediaSortJobStatus;
  error?: string | null;
  stage?: 'freeze' | 'validate';
  plan_id?: number | null;
  progress?: MediaSortProgress;
}

export const mediaSortApi = {
  preview: (payload: { parent: string; recursive: boolean; smart_skip: boolean }) =>
    api.post<MediaSortPreview>('/api/media-sort/preview', payload),
  startPreview: (payload: { parent: string; recursive: boolean; smart_skip: boolean }) =>
    api.post<MediaSortJobResult>('/api/media-sort/previews', payload),
  getPreview: (
    jobId: number,
    page: number = 1, pageSize: number = 25,
    skipPage: number = 1, skipPageSize: number = 25,
    itemFilter: MediaSortItemFilter = 'all',
  ) => {
    const q = new URLSearchParams({
      page: String(page), page_size: String(pageSize),
      skip_page: String(skipPage), skip_page_size: String(skipPageSize),
      item_filter: itemFilter,
    });
    return api.get<MediaSortPreviewPage>(`/api/media-sort/previews/${jobId}?${q}`);
  },
  createPlanFromPreview: ({ jobId, skipConflicts }: { jobId: number; skipConflicts: boolean }) =>
    api.post<MediaSortJobResult>(`/api/media-sort/previews/${jobId}/plan`,
      { skip_conflicts: skipConflicts }),
  getPlanJob: (jobId: number) =>
    api.get<MediaSortJobResult>(`/api/media-sort/plan-jobs/${jobId}`),
  startPlanStage: (planId: number, stage: 'freeze' | 'validate') =>
    api.post<MediaSortJobResult>(`/api/plans/${planId}/stage-tasks/${stage}`),
  getPlanStage: (planId: number) =>
    api.get<{ job: MediaSortJobResult | null }>(`/api/plans/${planId}/stage-task`),
};
