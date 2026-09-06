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
