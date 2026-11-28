import { api } from './client';

export type CloudFileProvider = 'openlist' | 'rclone';
export type CloudTransferStatus = 'submitting' | 'queued' | 'running' | 'cancel_requested' |
  'cancelled' | 'completed' | 'failed' | 'unknown';

export interface CloudFileService {
  enabled: boolean;
  name?: string | null;
  web_url?: string | null;
}

export interface CloudFilesConfiguration {
  enabled: boolean;
  writable: boolean;
  local_root: string | null;
  openlist: CloudFileService;
  rclone: CloudFileService;
}

export interface CloudEntry {
  name: string;
  kind: 'directory' | 'file';
  size: number | null;
}

export interface CloudTransferFile {
  name: string;
  status: CloudTransferStatus;
  progress: number | null;
  bytes: number | null;
  total_bytes: number | null;
  speed: number | null;
  speed_estimated?: boolean;
}

export interface NewCloudTransfer {
  provider: CloudFileProvider;
  remote?: string;
  path: string;
  names: string[];
  destination: string;
}

export interface CloudTransfer extends Omit<NewCloudTransfer, 'remote'> {
  id: string;
  remote: string | null;
  status: CloudTransferStatus;
  progress: number | null;
  speed: number | null;
  speed_estimated?: boolean;
  error: string | null;
  created_at: string;
  native_ids: string[];
  files: CloudTransferFile[];
  can_cancel: boolean;
  can_delete: boolean;
  verification?: {
    source_id: string;
    remote_root: string;
    local_root: string;
  } | null;
}

export interface CloudTransfers {
  items: CloudTransfer[];
  errors?: Partial<Record<CloudFileProvider, string>>;
}

const endpoint = '/api/cloud-files';
const transfers = endpoint + '/transfers';

/** Browse and manage native transfers through the File Center session. */
export const cloudFilesApi = {
  configuration: () => api.get<CloudFilesConfiguration>(endpoint + '/configuration'),
  remotes: () => api.get<{ items: { name: string }[] }>(endpoint + '/rclone/remotes'),
  entries: (provider: CloudFileProvider, remote: string | undefined, path: string) => {
    const query = new URLSearchParams({ provider, path });
    if (remote !== undefined) query.set('remote', remote);
    return api.get<{ items: CloudEntry[] }>(endpoint + '/entries?' + query);
  },
  start: (request: NewCloudTransfer) => api.post<CloudTransfer>(transfers, request),
  list: () => api.get<CloudTransfers>(transfers),
  detail: (id: string) => api.get<CloudTransfer>(transfers + '/' + encodeURIComponent(id)),
  cancel: (id: string) => api.post<CloudTransfer>(transfers + '/' + encodeURIComponent(id) + '/cancel'),
  remove: (id: string) => api.delete<{ deleted: true }>(transfers + '/' + encodeURIComponent(id)),
};
