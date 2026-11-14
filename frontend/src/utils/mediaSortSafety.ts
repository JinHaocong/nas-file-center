import type { MediaSortPreview } from '../api/mediaSort';

export interface MediaSortPlanDraft {
  name: string;
  kind: 'media-sort';
  items: Array<{
    operation: 'move';
    source: string;
    target: string;
    expected_size: number;
  }>;
}

/** The frontend can only create a draft from a complete, conflict-free preview. */
export function buildMediaSortDraft(preview: MediaSortPreview | null): MediaSortPlanDraft | null {
  if (!preview || typeof preview.recursive !== 'boolean' ||
      preview.items.length === 0 || preview.conflict_count > 0 ||
      preview.count !== preview.items.length ||
      preview.items.some(item => item.conflict ||
        (item.media_kind !== 'image' && item.media_kind !== 'video') ||
        !item.source || !item.target || !Number.isSafeInteger(item.expected_size) ||
        item.expected_size < 0)) return null;

  return {
    name: preview.recursive ? '媒体文件递归分类（每目录 P / V）' : '媒体文件分类（P / V）',
    kind: 'media-sort',
    items: preview.items.map(item => ({
      operation: 'move',
      source: item.source,
      target: item.target,
      expected_size: item.expected_size,
    })),
  };
}
