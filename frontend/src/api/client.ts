export interface ApiError {
  status: number;
  message: string;
  detail?: any;
}

export async function readApiErrorResponse(response: Response): Promise<ApiError> {
  // Response bodies are one-shot streams. Read exactly once, then decide
  // whether the payload is JSON or plain text. Calling json() and then text()
  // on the same response masks the real backend error with "body stream
  // already read".
  const rawBody = await response.text();
  let errorData: any = {};

  if (rawBody) {
    try {
      errorData = JSON.parse(rawBody);
    } catch {
      errorData = { detail: rawBody };
    }
  }

  const detail = errorData?.detail;
  const nestedMessage =
    detail &&
    typeof detail === 'object' &&
    !Array.isArray(detail) &&
    detail.error &&
    typeof detail.error.message === 'string'
      ? detail.error.message
      : undefined;

  const errorMsg =
    (typeof detail === 'string' && detail) ||
    nestedMessage ||
    (typeof errorData?.message === 'string' && errorData.message) ||
    (typeof errorData?.error?.message === 'string' && errorData.error.message) ||
    `请求失败 (${response.status})`;

  return {
    status: response.status,
    message: errorMsg,
    detail: errorData,
  };
}

class ApiClient {
  private onUnauthorizedCallback?: () => void;

  public setOnUnauthorized(cb: () => void) {
    this.onUnauthorizedCallback = cb;
  }

  private async request<T>(url: string, options: RequestInit = {}): Promise<T> {
    const defaultHeaders: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    const config: RequestInit = {
      ...options,
      credentials: 'include',
      headers: {
        ...defaultHeaders,
        ...(options.headers as Record<string, string> || {}),
      },
    };

    try {
      const response = await fetch(url, config);

      if (response.status === 401) {
        if (this.onUnauthorizedCallback && !window.location.pathname.startsWith('/login')) {
          this.onUnauthorizedCallback();
        }
        throw {
          status: 401,
          message: '未登录或登录已过期，请重新登录',
        } as ApiError;
      }

      if (!response.ok) {
        throw await readApiErrorResponse(response);
      }

      // Handle 204 No Content
      if (response.status === 204) {
        return {} as T;
      }

      return await response.json();
    } catch (err: any) {
      if (err.status) {
        throw err;
      }
      const networkError: ApiError = {
        status: 0,
        message: err.message || '网络连接异常，请检查 NAS 服务端状态',
      };
      throw networkError;
    }
  }

  public get<T>(url: string): Promise<T> {
    return this.request<T>(url, { method: 'GET' });
  }

  public post<T>(url: string, body?: any): Promise<T> {
    return this.request<T>(url, {
      method: 'POST',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  public put<T>(url: string, body?: any): Promise<T> {
    return this.request<T>(url, {
      method: 'PUT',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  }

  public delete<T>(url: string): Promise<T> {
    return this.request<T>(url, { method: 'DELETE' });
  }
}

export const api = new ApiClient();
