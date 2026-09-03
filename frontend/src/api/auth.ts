import { api } from './client';
import { SessionInfo, User } from '../types';

export interface LoginPayload {
  username: string;
  password: string;
}

export interface ChangePasswordPayload {
  old_password: string;
  new_password: string;
}

export const authApi = {
  login: (payload: LoginPayload) => api.post<User>('/api/auth/login', payload),
  logout: () => api.post<{ status: string }>('/api/auth/logout'),
  getMe: () => api.get<User>('/api/auth/me'),
  changePassword: (payload: ChangePasswordPayload) =>
    api.post<{ status: string; message: string }>('/api/auth/change-password', payload),
  listSessions: () => api.get<{ sessions: SessionInfo[] }>('/api/auth/sessions'),
  revokeSession: (sessionId: number) => api.delete<{ status: string }>(`/api/auth/sessions/${sessionId}`),
};
