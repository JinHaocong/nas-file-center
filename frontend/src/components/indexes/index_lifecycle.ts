import { IndexRoot } from '../../types';

export interface IndexRemoveAvailability {
  canRemove: boolean;
  reason?: string;
}

export function getIndexRemoveAvailability(
  root?: Partial<IndexRoot> | null
): IndexRemoveAvailability {
  if (!root) {
    return { canRemove: false, reason: '无效的索引根目录' };
  }
  if (root.has_active_job || root.can_remove === false) {
    return {
      canRemove: false,
      reason: '该根目录仍存在未结束的索引任务，请先等待任务结束。',
    };
  }
  return { canRemove: true };
}

export interface PathStatePresentation {
  label: string;
  color: 'success' | 'error' | 'warning' | 'default';
  tooltip?: string;
}

export function getIndexPathStatePresentation(
  state?: 'available' | 'missing' | 'blocked' | string
): PathStatePresentation {
  switch (state) {
    case 'available':
      return {
        label: '可用',
        color: 'success',
      };
    case 'missing':
      return {
        label: '目录不存在',
        color: 'error',
        tooltip:
          '该 Root 当前已不存在或已不是目录。下方文件/目录数量是 NAS File Center 保存的索引 metadata，不是实时文件系统结果。',
      };
    case 'blocked':
      return {
        label: '访问已阻止',
        color: 'warning',
        tooltip:
          '该路径当前不在 ALLOWED_ROOTS 范围内，或解析后违反路径安全规则。',
      };
    default:
      return {
        label: state || '未知',
        color: 'default',
      };
  }
}
