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
  const code = structured.code;
  const msg = structured.message;

  switch (code) {
    case 'DEDUPE_SCAN_NOT_COMPLETED':
      return `指定的扫描任务尚未完成 (DEDUPE_SCAN_NOT_COMPLETED)：${msg}`;
    case 'DEDUPE_SNAPSHOT_EMPTY':
      return `扫描任务快照为空 (DEDUPE_SNAPSHOT_EMPTY)：${msg}`;
    case 'DEDUPE_ROOT_MISMATCH':
      return `扫描根路径不匹配 (DEDUPE_ROOT_MISMATCH)：${msg}`;
    case 'DEDUPE_INVALID_CONFIG':
      return `去重配置无效 (DEDUPE_INVALID_CONFIG)：${msg}`;
    case 'DEDUPE_FACTOR_UNAVAILABLE':
      return `打分因子不可用 (DEDUPE_FACTOR_UNAVAILABLE)：${msg}`;
    case 'DEDUPE_LIMIT_EXCEEDED':
      return `超出去重配置限制 (DEDUPE_LIMIT_EXCEEDED)：${msg}`;
    case 'DEDUPE_EMPTY_PLAN':
      return `未生成任何去重操作 (DEDUPE_EMPTY_PLAN)：${msg}`;
    case 'PREVIEW_CHANGED':
    case 'DEDUPE_PREVIEW_CHANGED':
      return `预览已失效 (PREVIEW_CHANGED)：底层文件或打分配置已改变，请重新运行预览。${msg ? ` (${msg})` : ''}`;
    case 'DEDUPE_QUARANTINE_CONFLICT':
      return `隔离区路径冲突 (DEDUPE_QUARANTINE_CONFLICT)：${msg}`;
    case 'DEDUPE_STEP_NOT_FOUND':
      return `未找到去重步骤定义 (DEDUPE_STEP_NOT_FOUND)：${msg}`;
    case 'DEDUPE_MULTIPLE_STEPS_UNSUPPORTED':
      return `不支持多个去重步骤 (DEDUPE_MULTIPLE_STEPS_UNSUPPORTED)：${msg}`;
    case 'DEDUPE_WORKFLOW_INPUT_MISMATCH':
      return `工作流输入参数与去重配置不匹配 (DEDUPE_WORKFLOW_INPUT_MISMATCH)：${msg}`;
    default:
      return msg || '去重操作失败';
  }
}
