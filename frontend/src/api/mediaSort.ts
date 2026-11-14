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

export const mediaSortApi = {
  preview: (payload: { parent: string; recursive: boolean; smart_skip: boolean }) =>
    api.post<MediaSortPreview>('/api/media-sort/preview', payload),
};
