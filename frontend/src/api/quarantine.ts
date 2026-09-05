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
  list: (params?: { page?: number; pageSize?: number; state?: string; search?: string; query?: string }) => {
    const urlParams = new URLSearchParams();
    if (params?.page) urlParams.append('page', String(params.page));
    if (params?.pageSize) urlParams.append('page_size', String(params.pageSize));
    if (params?.state && params.state !== 'all') urlParams.append('state', params.state);
    const searchVal = (params?.query ?? params?.search)?.trim();
    if (searchVal) {
      urlParams.append('query', searchVal);
    }
    const qs = urlParams.toString();
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
