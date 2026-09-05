import { api } from './client';
import {
  QuarantineEntry,
  QuarantineListResponse,
  QuarantineRestoreRequest,
  QuarantineRestoreResponse,
  QuarantinePurgeRequest,
  QuarantinePurgeResponse,
  QuarantineRetentionPolicy,
} from '../types';

export const quarantineApi = {
  list: (params?: { page?: number; pageSize?: number; state?: string; search?: string }) => {
    const query = new URLSearchParams();
    if (params?.page) query.append('page', String(params.page));
    if (params?.pageSize) query.append('page_size', String(params.pageSize));
    if (params?.state && params.state !== 'all') query.append('state', params.state);
    if (params?.search && params.search.trim()) query.append('search', params.search.trim());
    const qs = query.toString();
    return api.get<QuarantineListResponse>(`/api/quarantine${qs ? `?${qs}` : ''}`);
  },

  get: (id: number) => api.get<QuarantineEntry>(`/api/quarantine/${id}`),

  restore: (id: number, payload: QuarantineRestoreRequest = {}) =>
    api.post<QuarantineRestoreResponse>(`/api/quarantine/${id}/restore`, payload),

  purge: (id: number, payload: QuarantinePurgeRequest) =>
    api.post<QuarantinePurgeResponse>(`/api/quarantine/${id}/purge`, payload),

  getRetentionPolicy: () => api.get<QuarantineRetentionPolicy>('/api/quarantine/retention-policy'),

  updateRetentionPolicy: (days: number) =>
    api.put<QuarantineRetentionPolicy>('/api/quarantine/retention-policy', {
      quarantine_retention_days: days,
    }),
};
