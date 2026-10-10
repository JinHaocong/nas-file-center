export interface DedupePairValues {
  pathA: string;
  pathB: string;
}

/** UI validation only. ALLOWED_ROOTS, symlink, quarantine and SHA256 checks live on the backend. */
export function validateDedupePair(values: DedupePairValues): string | null {
  if (!values.pathA.trim()) return '请输入第一个完整文件路径';
  if (!values.pathB.trim()) return '请输入第二个完整文件路径';
  return null;
}

export function toDedupePairPayload(values: DedupePairValues, scanJobId?: number | null) {
  return {
    path_a: values.pathA.trim(),
    path_b: values.pathB.trim(),
    scan_job_id: scanJobId ?? null,
  };
}
