import { api } from './client';

export interface MediaSortRow {
  source: string;
  target: string;
  media_kind: 'image' | 'video';
  expected_size: number;
  conflict: boolean;
  conflict_reason: string | null;
}

export interface MediaSortPreview {
  parent: string;
  count: number;
  image_count: number;
  video_count: number;
  ready_count: number;
  conflict_count: number;
  items: MediaSortRow[];
}

export const mediaSortApi = {
  preview: (parent: string) =>
    api.post<MediaSortPreview>('/api/media-sort/preview', { parent }),
};
