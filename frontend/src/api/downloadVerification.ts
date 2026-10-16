import { api } from './client';

export interface DownloadVerificationRun {
  id: number;
  work_job_id: number;
  remote_root: string;
  local_root: string;
  result: 'INCOMPLETE' | 'DIFFERENT' | 'STALE' | 'VERIFIED_IDENTICAL';
  job_status: string;
  checked: number;
  total: number;
  bytes_checked: number;
  error_code: string | null;
  created_at: string;
  finished_at: string | null;
}
export interface DownloadVerificationItem {
  relative_path: string;
  kind: string;
  status: string;
  remote_size: number | null;
  local_size: number | null;
  remote_sha256: string | null;
  local_sha256: string | null;
  reason_code: string | null;
}
export interface Page<T> { items: T[]; page: number; page_size: number; total: number }
export const downloadVerificationApi = {
  configuration: () => api.get<{ configured: boolean; endpoint: string; mode: string; read_only: boolean }>('/api/download-verifications/configuration'),
  start: (remote_root: string, local_root: string) =>
    api.post<{ id: number; work_job_id: number; job_status: string }>('/api/download-verifications', { remote_root, local_root }),
  list: () => api.get<Page<DownloadVerificationRun>>('/api/download-verifications?page=1&page_size=50'),
  items: (id: number, page: number, status?: string) =>
    api.get<Page<DownloadVerificationItem>>('/api/download-verifications/' + id + '/items?page=' + page + '&page_size=50' + (status ? '&status=' + encodeURIComponent(status) : '')),
};
