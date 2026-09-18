import { api } from './client';
import {
  QuarantineEntry,
  QuarantineListResponse,
  QuarantineRestoreRequest,
  QuarantineRestoreResponse,
  QuarantinePurgeRequest,
  QuarantinePurgeResponse,
  QuarantineBulkPreviewRequest,
  QuarantineBulkPreviewResponse,
  QuarantineBulkPlanRequest,
  QuarantineBulkPlanResponse,
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

  resolveBulkFilteredEntryIds: async (params?: { state?: string; search?: string; query?: string }) => {
    const pageSize = 500;
    const entryIds: number[] = [];
    let page = 1;
    let total = 0;

    do {
      const response = await quarantineApi.list({ ...params, page, pageSize });
      total = response.total;
      entryIds.push(...response.items.filter((entry) => entry.state === 'active').map((entry) => entry.id));
      if (entryIds.length > 5000) {
        throw new Error('Gate6-A bulk selection exceeds maximum of 5000 active entries');
      }
      page += 1;
    } while ((page - 1) * pageSize < total);

    return entryIds;
  },

  resolveTerminalCleanupFilteredEntryIds: async (params?: { state?: string; search?: string; query?: string }) => {
    const pageSize = 500;
    const entryIds: number[] = [];
    let page = 1;
    let total = 0;

    do {
      const response = await quarantineApi.list({ ...params, page, pageSize });
      total = response.total;
      entryIds.push(...response.items.filter((entry) => ['purged', 'abandoned', 'conflict'].includes(entry.state)).map((entry) => entry.id));
      if (entryIds.length > 5000) {
        throw new Error('批量删除隔离记录最多支持 5000 条');
      }
      page += 1;
    } while ((page - 1) * pageSize < total);

    return entryIds;
  },

  get: (id: number) => api.get<QuarantineEntry>(`/api/quarantine/${id}`),

  restore: (id: number, payload: QuarantineRestoreRequest = {}) =>
    api.post<QuarantineRestoreResponse>(`/api/quarantine/${id}/restore`, payload),

  purge: (id: number, payload: QuarantinePurgeRequest) =>
    api.post<QuarantinePurgeResponse>(`/api/quarantine/${id}/purge`, payload),

  bulkPreview: (payload: QuarantineBulkPreviewRequest) =>
    api.post<QuarantineBulkPreviewResponse>('/api/quarantine/bulk-preview', payload),

  bulkPlan: (payload: QuarantineBulkPlanRequest) =>
    api.post<QuarantineBulkPlanResponse>('/api/quarantine/bulk-plan', payload),

  deleteRecord: (id: number) =>
    api.delete<{ status: string; deleted: boolean; id: number }>(
      `/api/quarantine/${id}/record?confirmation=DELETE_RECORD`
    ),

  bulkDeleteRecords: (entryIds: number[]) =>
    api.post<{ status: string; deleted_count: number; deleted_ids: number[] }>(
      '/api/quarantine/records/bulk-delete',
      { entry_ids: entryIds, confirmation: 'DELETE_RECORDS' }
    ),

  getRetentionPolicy: () => api.get<QuarantineRetentionPolicy>('/api/quarantine/retention-policy'),

  updateRetentionPolicy: (days: number) =>
    api.put<QuarantineRetentionPolicy>('/api/quarantine/retention-policy', {
      quarantine_retention_days: days,
    }),
};
