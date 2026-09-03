export interface ApiError {
  status: number;
  message: string;
  detail?: any;
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
        let errorData: any = {};
        try {
          errorData = await response.json();
        } catch {
          errorData = { detail: await response.text() };
        }
        const errorMsg = errorData.detail || errorData.message || `请求失败 (${response.status})`;
        throw {
          status: response.status,
          message: errorMsg,
          detail: errorData,
        } as ApiError;
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
