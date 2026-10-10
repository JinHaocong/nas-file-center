export interface ScanCreateValues {
  name: string;
  roots: string[];
  isolate: boolean;
  minSize: string;
  namePatternsText: string;
  excludePatternsText: string;
}

export interface ScanCreatePayload {
  name: string;
  roots: string[];
  isolate: boolean;
  min_size: string | null;
  name_patterns: string[] | null;
  exclude_patterns: string[] | null;
}

export const splitScanLines = (text: string): string[] =>
  text.split('\n').map(value => value.trim()).filter(Boolean);

export function validateScanCreateValues(values: ScanCreateValues): string | null {
  if (!values.name.trim()) return '请输入任务名称';
  if (!Array.isArray(values.roots) || !values.roots.some(root => root.trim())) {
    return '请至少选择或输入一个待扫描路径';
  }
  return null;
}

/** Form normalization only. The backend remains the ALLOWED_ROOTS/path authority. */
export function toScanCreatePayload(values: ScanCreateValues): ScanCreatePayload {
  const patterns = splitScanLines(values.namePatternsText);
  const excludes = splitScanLines(values.excludePatternsText);
  return {
    name: values.name.trim(),
    roots: values.roots.map(root => root.trim()).filter(Boolean),
    isolate: values.isolate,
    min_size: values.minSize.trim() || null,
    name_patterns: patterns.length ? patterns : null,
    exclude_patterns: excludes.length ? excludes : null,
  };
}
