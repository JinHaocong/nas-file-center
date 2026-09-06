import { FilterLeafField, FilterLeafOperator } from '../types/workflow';

export const ALLOWED_OPERATORS_BY_FIELD: Record<FilterLeafField, FilterLeafOperator[]> = {
  path: ['eq', 'neq', 'contains', 'startswith', 'endswith', 'in', 'nin'],
  name: ['eq', 'neq', 'contains', 'startswith', 'endswith', 'in', 'nin'],
  extension: ['eq', 'neq', 'in', 'nin'],
  size: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte'],
  mtime: ['eq', 'neq', 'gt', 'gte', 'lt', 'lte'],
  media_type: ['eq', 'neq', 'in', 'nin'],
};

export const MEDIA_TYPE_OPTIONS = [
  { label: '图片 (image)', value: 'image' },
  { label: '视频 (video)', value: 'video' },
  { label: '音频 (audio)', value: 'audio' },
  { label: '文档 (document)', value: 'document' },
  { label: '归档 (archive)', value: 'archive' },
  { label: '其他 (other)', value: 'other' },
];

export const MAX_FILTER_DEPTH = 5;
export const MAX_FILTER_CHILDREN = 50;
export const MAX_FILTER_LEAVES = 200;

export function normalizeExtension(ext: string): string {
  if (!ext) return '';
  return ext.trim().replace(/^\.+/, '').toLowerCase();
}

export function validateFilterLimits(stats: {
  depth: number;
  children: number;
  leaves: number;
}): boolean {
  if (stats.depth > MAX_FILTER_DEPTH) return false;
  if (stats.children > MAX_FILTER_CHILDREN) return false;
  if (stats.leaves > MAX_FILTER_LEAVES) return false;
  return true;
}
