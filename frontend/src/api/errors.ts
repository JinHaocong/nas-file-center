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
    case 'DEDUPE_SCAN_NOT_FOUND':
      return `指定的扫描任务不存在 (DEDUPE_SCAN_NOT_FOUND)：${msg}`;
    case 'DEDUPE_SCAN_NOT_COMPLETED':
      return `指定的扫描任务尚未完成 (DEDUPE_SCAN_NOT_COMPLETED)：${msg}`;
    case 'SCAN_JOB_ID_REQUIRED':
      return `去重模式必须提供扫描任务 ID (SCAN_JOB_ID_REQUIRED)：${msg}`;
    case 'SCAN_JOB_ID_FORBIDDEN':
      return `非去重工作流禁止传入扫描任务 ID (SCAN_JOB_ID_FORBIDDEN)：${msg}`;
    case 'ROOT_IDS_FORBIDDEN':
      return `去重工作流禁止传入 root_ids 参数 (ROOT_IDS_FORBIDDEN)：${msg}`;
    case 'AMBIGUOUS_RUNTIME_INPUTS':
      return `运行时输入参数冲突或不明确 (AMBIGUOUS_RUNTIME_INPUTS)：${msg}`;
    case 'WORKFLOW_ARCHIVED':
      return `工作流已被归档 (WORKFLOW_ARCHIVED)：已被归档的工作流禁止生成计划或执行操作。${msg ? ` (${msg})` : ''}`;
    case 'DEDUPE_RESCAN_REQUIRED':
      return `重新扫描已失效 (DEDUPE_RESCAN_REQUIRED)：检测到扫描快照数据过时，请按标准流程恢复：new scan → completed → return Workflow → select new Scan Job → Preview → Generate new Draft。${msg ? ` (${msg})` : ''}`;
    // Legacy compatibility codes
    case 'DEDUPE_SNAPSHOT_EMPTY':
      return `扫描任务快照为空 (DEDUPE_SNAPSHOT_EMPTY)：${msg}`;
    case 'DEDUPE_ROOT_MISMATCH':
      return `扫描根路径不匹配 (DEDUPE_ROOT_MISMATCH)：${msg}`;
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
