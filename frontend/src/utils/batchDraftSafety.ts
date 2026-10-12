import { splitLines } from './format';

export type BatchOperation = 'quarantine' | 'touch' | 'move' | 'rename';
export type BatchItem =
  | { operation: 'quarantine' | 'touch'; source: string }
  | { operation: 'move' | 'rename'; source: string; target: string };
export interface BatchDraft {
  name: string;
  kind: string;
  items: BatchItem[];
}
export type BatchDraftResult = { draft: BatchDraft; error?: never } |
  { draft?: never; error: string };

export function isBatchOperation(value: string): value is BatchOperation {
  return value === 'quarantine' || value === 'touch' ||
    value === 'move' || value === 'rename';
}

/**
 * Exact Plan Draft wire contract. Validation is advisory: server remains the
 * authority for ALLOWED_ROOTS, quarantine fences and mutation lifecycles.
 * No filesystem operation occurs while building this payload.
 */
export function buildBatchDraft(
  name: string, op: string, paths: readonly string[], mappingsText: string,
): BatchDraftResult {
  if (!name.trim()) return { error: '请输入计划名称' };
  if (!isBatchOperation(op)) return { error: '不支持该操作类型' };
  const items: BatchItem[] = [];
  if (op === 'quarantine' || op === 'touch') {
    if (paths.length === 0) return { error: '请至少选择或输入一个文件或目录路径' };
    const seen = new Set<string>();
    for (const path of paths) {
      if (typeof path !== 'string' || !path.trim()) return { error: '路径清单包含空路径' };
      if (!path.startsWith('/')) return { error: '路径必须为绝对路径：' + path };
      if (seen.has(path)) return { error: '源路径重复：' + path };
      seen.add(path);
      items.push({ operation: op, source: path });
    }
  } else {
    const lines = splitLines(mappingsText);
    if (lines.length === 0) return { error: '请至少输入一行映射规则' };
    const sources = new Set<string>();
    const targets = new Set<string>();
    for (const line of lines) {
      if (!line.includes('->')) return { error: '映射缺少 "->" 分隔符: ' + line };
      // Reject ambiguous additional separators instead of silently truncating targets.
      const [source, target, extra] = line.split('->');
      const src = source.trim();
      const dst = target?.trim() || '';
      if (!src || !dst || extra !== undefined) return { error: '无效映射格式: ' + line };
      if (!src.startsWith('/') || !dst.startsWith('/')) {
        return { error: '映射必须使用绝对路径: ' + line };
      }
      if (src === dst) return { error: '源路径与目标路径不能相同: ' + src };
      if (sources.has(src)) return { error: '源路径重复: ' + src };
      if (targets.has(dst)) return { error: '目标路径重复: ' + dst };
      sources.add(src);
      targets.add(dst);
      items.push({ operation: op, source: src, target: dst });
    }
  }
  return { draft: { name: name.trim() || '批量处理计划', kind: 'batch-' + op, items } };
}
