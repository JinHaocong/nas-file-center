import { api } from './client';

export interface CloudCopyConfiguration {
  configured: boolean;
  source_id: string | null;
  local_root: string | null;
}

export interface CloudCopyRequest {
  source_id: string;
  remote_root: string;
  local_parent: string;
  folder_name: string;
}

/** Queue a one-way copy from the OpenList source enabled by this deployment. */
export const cloudCopyApi = {
  configuration: () => api.get<CloudCopyConfiguration>('/api/cloud-copy/configuration'),
  start: (body: CloudCopyRequest) => api.post<{ job_id: string; status: 'queued' }>('/api/cloud-copy', body),
};
