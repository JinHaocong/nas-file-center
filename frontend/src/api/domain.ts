import { api } from './client';
import {
  AuditEvent,
  DashboardSummary,
  DuplicateGroup,
  IndexRoot,
  PaginatedResponse,
  Plan,
  PlanItem,
  RenameProposal,
  ScanJob,
  SystemSettings,
  WorkJob,
} from '../types';

export const dashboardApi = {
  getSummary: () => api.get<DashboardSummary>('/api/dashboard/summary'),
};

export const scansApi = {
  listScans: (page = 1, pageSize = 20) =>
    api.get<PaginatedResponse<ScanJob>>(`/api/scans?page=${page}&page_size=${pageSize}`),
  getScanDetail: (id: number) => api.get<ScanJob>(`/api/scans/${id}`),
  getScanGroups: (id: number, page = 1, pageSize = 20) =>
    api.get<PaginatedResponse<DuplicateGroup>>(`/api/scans/${id}/groups?page=${page}&page_size=${pageSize}`),
  createScan: (payload: {
    name: string;
    roots: string[];
    isolate?: boolean;
    min_size?: string | null;
    name_patterns?: string[] | null;
    exclude_patterns?: string[] | null;
  }) => api.post<{ scan_job_id: number; work_job_id: number }>('/api/scans', payload),
  createDedupePlan: (
    scanId: number,
    payload: {
      policy: string;
      path_priority_patterns?: string[] | null;
      relative_path_priority_patterns?: string[] | null;
    }
  ) => api.post<{ id: number; status: string; expected_changes: number }>(`/api/scans/${scanId}/dedupe-plan`, payload),
};

export const indexesApi = {
  listIndexes: (page = 1, pageSize = 20) =>
    api.get<PaginatedResponse<IndexRoot>>(`/api/indexes?page=${page}&page_size=${pageSize}`),
  createIndex: (root: string) => api.post<{ work_job_id: number }>('/api/indexes', { root }),
  matchPreview: (payload: {
    root_keys: string[];
    mode?: string;
    normalize_pattern?: string | null;
    normalize_replacement?: string;
  }) => api.post<{ groups: any[]; count: number }>('/api/index-match/preview', payload),
};

export const plansApi = {
  listPlans: (page = 1, pageSize = 20) =>
    api.get<PaginatedResponse<Plan>>(`/api/plans?page=${page}&page_size=${pageSize}`),
  getPlanDetail: (id: number, page = 1, pageSize = 50) =>
    api.get<Plan>(`/api/plans/${id}?page=${page}&page_size=${pageSize}`),
  getPlanItems: (id: number, page = 1, pageSize = 50) =>
    api.get<PaginatedResponse<PlanItem>>(`/api/plans/${id}/items?page=${page}&page_size=${pageSize}`),
  createPlan: (payload: {
    name: string;
    kind: string;
    items: Array<{
      operation: string;
      source: string;
      target?: string | null;
      keep?: string | null;
      expected_size?: number;
      expected_hash?: string | null;
    }>;
  }) => api.post<{ id: number; status: string; expected_changes: number }>('/api/plans', payload),
  freezePlan: (id: number) => api.post<{ id: number; status: string }>(`/api/plans/${id}/freeze`),
  validatePlan: (id: number) => api.post<Plan>(`/api/plans/${id}/validate`),
  executePlan: (id: number) => api.post<{ id: number; status: string; items: any[] }>(`/api/plans/${id}/execute`),
};

export const batchApi = {
  previewRename: (payload: {
    paths: string[];
    regex_pattern?: string | null;
    regex_replacement?: string;
    prefix?: string;
    suffix?: string;
    number_start?: number | null;
    number_width?: number;
    include_parent?: boolean;
  }) => api.post<{ items: RenameProposal[] }>('/api/rename/preview', payload),
  previewPathMatch: (payload: {
    roots: string[];
    mode?: string;
    normalize_pattern?: string | null;
    normalize_replacement?: string;
  }) => api.post<{ groups: any[]; count: number }>('/api/path-match/preview', payload),
};

export const tasksApi = {
  listJobs: (page = 1, pageSize = 20) =>
    api.get<PaginatedResponse<WorkJob>>(`/api/work-jobs?page=${page}&page_size=${pageSize}`),
  getJobDetail: (id: number) => api.get<WorkJob>(`/api/work-jobs/${id}`),
};

export const auditApi = {
  listEvents: (page = 1, pageSize = 20, query?: string, operation?: string) => {
    const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (query) params.append('query', query);
    if (operation) params.append('operation', operation);
    return api.get<PaginatedResponse<AuditEvent>>(`/api/audit?${params.toString()}`);
  },
};

export const settingsApi = {
  getSettings: () => api.get<SystemSettings>('/api/settings'),
};
