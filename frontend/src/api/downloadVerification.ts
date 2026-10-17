import { api } from './client';

export interface DownloadVerificationRun {
  id: number;
  source_id: number | null;
  mode: 'metadata' | 'strict_sha256';
  work_job_id: number | null;
  remote_root: string;
  local_root: string;
  result: 'INCOMPLETE' | 'DIFFERENT' | 'STALE' | 'VERIFIED_IDENTICAL' | 'METADATA_IDENTICAL';
  job_status: string;
  can_delete: boolean;
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
export interface VerificationSource {
  id: number;
  name: string;
  provider: 'alist' | 'openlist';
  base_url: string;
  username: string;
  has_password: boolean;
  revision: number;
  active: boolean;
}
export interface SourceInput {
  name: string;
  provider: 'alist' | 'openlist';
  base_url: string;
  username: string;
  password?: string;
}
export interface RemoteDirectory {
  path: string;
  items: Array<{ name: string; kind: 'directory' | 'file'; size: number | null }>;
}
export const downloadVerificationApi = {
  sources: () => api.get<{ items: VerificationSource[] }>('/api/download-verifications/sources'),
  addSource: (input: SourceInput) => api.post<VerificationSource>('/api/download-verifications/sources', input),
  updateSource: (id: number, input: Partial<SourceInput>) =>
    api.put<VerificationSource>('/api/download-verifications/sources/' + id, input),
  deleteSource: (id: number) => api.delete<{ disabled: boolean }>('/api/download-verifications/sources/' + id),
  browse: (id: number, path: string) =>
    api.get<RemoteDirectory>('/api/download-verifications/sources/' + id + '/browse?path=' + encodeURIComponent(path)),
  configuration: () => api.get<{ configured: boolean; endpoint: string; mode: string; read_only: boolean }>('/api/download-verifications/configuration'),
  start: (remote_root: string, local_root: string, source_id?: number, mode: 'metadata' | 'strict_sha256' = 'metadata') =>
    api.post<{ id: number; work_job_id: number; job_status: string }>('/api/download-verifications',
      { remote_root, local_root, source_id, mode }),
  list: (page = 1) => api.get<Page<DownloadVerificationRun>>('/api/download-verifications?page=' + page + '&page_size=50'),
  removeReport: (id: number) => api.delete<Record<string, never>>('/api/download-verifications/' + id),
  items: (id: number, page: number, status?: string) =>
    api.get<Page<DownloadVerificationItem>>('/api/download-verifications/' + id + '/items?page=' + page + '&page_size=50' + (status ? '&status=' + encodeURIComponent(status) : '')),
};
