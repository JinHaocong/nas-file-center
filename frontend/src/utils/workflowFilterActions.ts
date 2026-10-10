import {
  type FilterNode, type FilterLeafNode, type FilterLeafField, type FilterLeafOperator,
  type FilterAndOrNode, isFilterLeafNode, isFilterAndOrNode, isFilterNotNode,
} from '../types/workflow';
import {
  ALLOWED_OPERATORS_BY_FIELD, MAX_FILTER_CHILDREN, MAX_FILTER_DEPTH,
  MAX_FILTER_LEAVES, normalizeExtension,
} from './filterMatrix';

export type FilterNodeKind = 'leaf' | 'and' | 'or' | 'not';
export const DEFAULT_CHILD: FilterLeafNode = {
  field: 'extension', operator: 'eq', value: 'png', case_sensitive: false,
};

export function countFilterLeaves(node: FilterNode): number {
  if (isFilterLeafNode(node)) return 1;
  if (isFilterAndOrNode(node)) return node.children.reduce((count, child) => count + countFilterLeaves(child), 0);
  if (isFilterNotNode(node)) return countFilterLeaves(node.child);
  return 1;
}

export function createFilterNode(kind: FilterNodeKind, depth: number): FilterNode | null {
  if (kind !== 'leaf' && depth >= MAX_FILTER_DEPTH) return null;
  if (kind === 'leaf') return { field: 'extension', operator: 'eq', value: 'txt', case_sensitive: false };
  if (kind === 'and' || kind === 'or') return {
    op: kind, children: [{ field: 'extension', operator: 'eq', value: 'jpg', case_sensitive: false }],
  };
  return { op: 'not', child: { field: 'name', operator: 'startswith', value: '.', case_sensitive: false } };
}

export function changeFilterField(leaf: FilterLeafNode, field: FilterLeafField): FilterLeafNode {
  const allowed = ALLOWED_OPERATORS_BY_FIELD[field];
  const operator = allowed.includes(leaf.operator) ? leaf.operator : allowed[0];
  const list = operator === 'in' || operator === 'nin';
  const value: FilterLeafNode['value'] = field === 'size' ? 0 :
    field === 'mtime' ? new Date().toISOString() :
    field === 'extension' ? (list ? ['jpg'] : 'jpg') :
    field === 'media_type' ? (list ? ['image'] : 'image') :
    list ? ['sample'] : '';
  return { ...leaf, field, operator, value };
}

export function changeFilterOperator(leaf: FilterLeafNode, operator: FilterLeafOperator): FilterLeafNode {
  if (!ALLOWED_OPERATORS_BY_FIELD[leaf.field].includes(operator)) return leaf;
  const list = operator === 'in' || operator === 'nin';
  const wasList = leaf.operator === 'in' || leaf.operator === 'nin';
  let value = leaf.value;
  if (list && !wasList) value = typeof value === 'string' && value ? [value] : [];
  else if (!list && wasList) value = Array.isArray(value) && value.length ? value[0] : '';
  return { ...leaf, operator, value };
}

export function canAppendFilterChild(group: FilterAndOrNode): boolean {
  return group.children.length < MAX_FILTER_CHILDREN && countFilterLeaves(group) < MAX_FILTER_LEAVES;
}

export function addFilterTag(leaf: FilterLeafNode, raw: string): FilterLeafNode {
  const tag = leaf.field === 'extension' ? normalizeExtension(raw) : raw.trim();
  if (!tag) return leaf;
  const previous = Array.isArray(leaf.value) ? leaf.value : [];
  return previous.includes(tag) ? leaf : { ...leaf, value: [...previous, tag] };
}

export function formatFilterMtimeLocal(value: FilterLeafNode['value']): string {
  if (typeof value !== 'string' || !value) return '';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number, length = 2) => String(n).padStart(length, '0');
  return pad(d.getFullYear(), 4) + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
    'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()) +
    '.' + pad(d.getMilliseconds(), 3);
}
/** The old Ant DatePicker serializes selected local wall time to an ISO instant. */
export function parseFilterMtimeLocal(value: string): string | null {
  if (!value) return '';
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/.exec(value);
  if (!match) return null;
  const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
  const hour = Number(match[4]), minute = Number(match[5]), second = Number(match[6] || 0);
  const ms = Number((match[7] || '').padEnd(3, '0'));
  if (year < 100 || month < 1 || month > 12 || day < 1 || day > 31 ||
    hour > 23 || minute > 59 || second > 59) return null;
  const d = new Date(year, month - 1, day, hour, minute, second, ms);
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day ||
    d.getHours() !== hour || d.getMinutes() !== minute ||
    d.getSeconds() !== second || d.getMilliseconds() !== ms) return null;
  return d.toISOString();
}
