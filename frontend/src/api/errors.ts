export interface StructuredApiError {
  code?: string;
  message: string;
  details?: any;
  status?: number;
}

export function getStructuredApiError(err: unknown): StructuredApiError {
  if (!err || typeof err !== 'object') {
    return { message: String(err || '未知错误') };
  }
  const e = err as any;
  const status = typeof e.status === 'number' ? e.status : undefined;

  if (e.detail && typeof e.detail === 'object' && e.detail.error) {
    const errorObj = e.detail.error;
    return {
      code: errorObj.code,
      message: errorObj.message || e.message || '请求处理失败',
      details: errorObj.details,
      status,
    };
  }

  if (e.error && typeof e.error === 'object') {
    return {
      code: e.error.code,
      message: e.error.message || e.message || '请求处理失败',
      details: e.error.details,
      status,
    };
  }

  if (typeof e.detail === 'string') {
    return {
      message: e.detail,
      status,
    };
  }

  if (Array.isArray(e.detail)) {
    const msg = e.detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ');
    return {
      code: 'VALIDATION_ERROR',
      message: msg || '参数校验失败',
      details: e.detail,
      status,
    };
  }

  return {
    code: e.code,
    message: e.message || '未知错误',
    details: e.details,
    status,
  };
}

export function formatDedupeErrorMessage(err: unknown): string {
  const structured = getStructuredApiError(err);
  if (structured.code === 'PREVIEW_CHANGED' || structured.code === 'DEDUPE_PREVIEW_CHANGED') {
    return '预览已失效 (PREVIEW_CHANGED)：底层文件或打分配置已改变，请重新运行预览。';
  }
  if (structured.code === 'DEDUPE_FACTOR_UNAVAILABLE') {
    return `打分因子不可用 (DEDUPE_FACTOR_UNAVAILABLE)：${structured.message}`;
  }
  if (structured.code === 'DEDUPE_LIMIT_EXCEEDED') {
    return `超出去重配置限制 (DEDUPE_LIMIT_EXCEEDED)：${structured.message}`;
  }
  if (structured.code === 'DEDUPE_INVALID_CONFIG') {
    return `去重配置无效 (DEDUPE_INVALID_CONFIG)：${structured.message}`;
  }
  if (structured.code === 'SCAN_NOT_COMPLETED') {
    return '指定的扫描任务尚未完成，无法进行去重分析。';
  }
  return structured.message || '去重操作失败';
}
