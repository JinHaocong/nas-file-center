import type { DirectoryDiffResponse, DirectoryDiffRow } from '../api/domain';

export type DirectoryDiffFilterMode =
  | 'all' | 'differences' | 'unverified' | 'verified'
  | 'only_a' | 'only_b' | 'size_different' | 'type_mismatch';
export type DirectoryDiffRequest = { root_a: string; root_b: string };
export type DirectoryDiffVerifyRequest = DirectoryDiffRequest & { relative_path: string };
export type DirectoryDiffVerifyResponse = {
  relative_path: string; sha256_a: string; sha256_b: string; same_content: boolean;
};

/** Leave literal paths untouched: canonicalization, overlap and ALLOWED_ROOTS are backend authority. */
export function buildDirectoryDiffRequest(
  rootA: string, rootB: string,
): DirectoryDiffRequest | null {
  if (typeof rootA !== 'string' || typeof rootB !== 'string' ||
      !rootA.trim() || !rootB.trim() || rootA === rootB) return null;
  return { root_a: rootA, root_b: rootB };
}

export function directoryDiffRowLabel(row: DirectoryDiffRow): string {
  if (row.verification === 'content_same') return 'SHA256 相同';
  if (row.verification === 'content_different') return 'SHA256 不同';
  return {
    only_a: '仅 A 存在',
    only_b: '仅 B 存在',
    size_different: '大小不同',
    type_mismatch: '类型不同',
    same_size_unverified: '大小相同 · 待校验',
    both_directories: '双方均有目录',
  }[row.status];
}

export function directoryDiffTone(row: DirectoryDiffRow): 'neutral' | 'success' | 'danger' | 'warning' {
  if (row.verification === 'content_same') return 'success';
  if (row.verification === 'content_different') return 'danger';
  if (row.status === 'same_size_unverified' || row.status === 'both_directories') return 'neutral';
  return 'warning';
}

export function formatDirectoryDiffSize(value: number | null): string {
  if (value === null) return '—';
  if (value < 1024) return String(value) + ' B';
  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  let size = value;
  let unit = -1;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return size.toFixed(2) + ' ' + units[unit];
}

export function filterDirectoryDiffRows(
  rows: readonly DirectoryDiffRow[], filter: DirectoryDiffFilterMode,
): DirectoryDiffRow[] {
  if (filter === 'all') return [...rows];
  if (filter === 'differences') {
    return rows.filter(row =>
      row.verification === 'content_different' ||
      ['only_a', 'only_b', 'size_different', 'type_mismatch'].includes(row.status));
  }
  if (filter === 'verified') return rows.filter(row => row.verification !== undefined);
  if (filter === 'unverified') {
    return rows.filter(row => row.status === 'same_size_unverified' && !row.verification);
  }
  return rows.filter(row => row.status === filter);
}

/**
 * Verify only a currently displayed server-provided equal-size regular-file pair.
 * Never hash by constructing client paths or accepting an arbitrary input relative path.
 */
export function buildDirectoryDiffVerifyRequest(
  report: DirectoryDiffResponse | null, row: DirectoryDiffRow,
): DirectoryDiffVerifyRequest | null {
  if (!report) return null;
  const current = report.items.find(item => item.relative_path === row.relative_path);
  if (!current || current.status !== 'same_size_unverified' ||
      current.kind_a !== 'file' || current.kind_b !== 'file' ||
      current.size_a === null || current.size_b === null ||
      current.size_a !== current.size_b || !current.relative_path) return null;
  return { root_a: report.root_a, root_b: report.root_b, relative_path: current.relative_path };
}

/** Refuse response mismatches; SHA256 equality must agree with same_content. */
export function applyDirectoryDiffVerification(
  report: DirectoryDiffResponse,
  request: DirectoryDiffVerifyRequest,
  verification: DirectoryDiffVerifyResponse,
): DirectoryDiffResponse | null {
  if (request.root_a !== report.root_a || request.root_b !== report.root_b ||
      verification.relative_path !== request.relative_path ||
      !/^[a-f0-9]{64}$/i.test(verification.sha256_a) ||
      !/^[a-f0-9]{64}$/i.test(verification.sha256_b) ||
      (verification.sha256_a.toLowerCase() === verification.sha256_b.toLowerCase()) !== verification.same_content) {
    return null;
  }
  const current = report.items.find(row => row.relative_path === request.relative_path);
  if (!current || !buildDirectoryDiffVerifyRequest(report, current)) return null;
  return {
    ...report,
    items: report.items.map(row => row.relative_path === request.relative_path
      ? { ...row, verification: verification.same_content ? 'content_same' as const : 'content_different' as const }
      : row),
  };
}

function csvCell(value: string | number | null): string {
  let cell = String(value ?? '');
  // Spreadsheet formula injection can begin after whitespace. Do not trim literal paths.
  if (/^\s*[=+@-]/.test(cell)) cell = "'" + cell;
  return '"' + cell.replace(/"/g, '""') + '"';
}

/** Preserve the original CSV column order and export only the current filtered set. */
export function buildDirectoryDiffCsv(rows: readonly DirectoryDiffRow[]): string {
  const records = [
    ['relative_path', 'type_a', 'type_b', 'size_a_bytes', 'size_b_bytes', 'result'],
    ...rows.map(row => [
      row.relative_path, row.kind_a, row.kind_b, row.size_a, row.size_b, directoryDiffRowLabel(row),
    ]),
  ];
  return '\uFEFF' + records.map(record => record.map(csvCell).join(',')).join('\r\n');
}
