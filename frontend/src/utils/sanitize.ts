const SENSITIVE_KEY_PATTERNS = [
  'password',
  'passwd',
  'secret',
  'token',
  'api_key',
  'authorization',
  'auth',
  'cookie',
  'session',
];

export function isSensitiveKey(key: string): boolean {
  const lower = key.toLowerCase();
  return SENSITIVE_KEY_PATTERNS.some((pattern) => lower.includes(pattern));
}

export function sanitizeContext<T>(data: T): T {
  if (data === null || data === undefined) {
    return data;
  }

  if (Array.isArray(data)) {
    return data.map((item) => sanitizeContext(item)) as unknown as T;
  }

  if (typeof data === 'object') {
    const sanitized: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(data as Record<string, unknown>)) {
      if (isSensitiveKey(k)) {
        sanitized[k] = '***REDACTED***';
      } else if (typeof v === 'object' && v !== null) {
        sanitized[k] = sanitizeContext(v);
      } else {
        sanitized[k] = v;
      }
    }
    return sanitized as T;
  }

  return data;
}
