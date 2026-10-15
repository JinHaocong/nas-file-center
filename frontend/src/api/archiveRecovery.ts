import { api } from './client';

export interface RecoveryItem {
  name: string;
  status: 'integrity_passed' | 'format_validated' | 'unverified' | 'incomplete' | 'unrecovered';
  path?: string;
  bytes?: number;
  reason?: string;
  provenance?: string;
}

export interface RecoveryReport {
  format?: string;
  source: string;
  output: string;
  recovery_status: string;
  known_total: number | null;
  items: RecoveryItem[];
  stats: Record<string, number>;
  error_code?: string | null;
  deep_capability?: string;
  aes_lzma2_deep?: {
    status: string;
    recovered: number;
    reason?: string;
    reset_points?: number;
    decoded_segments?: number;
    rejected_segments?: number;
    resync_scan?: { scan_bytes: number; probed: number; proven_files: number };
  } | null;
  warnings?: string[];
}

export interface RecoveryPreflight {
  format: string;
  source: string;
  source_bytes: number;
  free_bytes: number;
  can_write: boolean;
  dependency_available: boolean;
  /** Checks the API-side tmpfs only; Worker must share the volume. */
  password_channel_available: boolean;
  deep_strategy: string;
  warning: string;
}

export const archiveRecoveryApi = {
  check: (source: string) => api.post<RecoveryPreflight>('/api/archive-recovery/check', { source }),
  start: (source: string, password: string, deep: boolean) =>
    api.post<{ work_job_id: number; output: string; status: string }>(
      '/api/archive-recovery/start', { source, password: password || null, deep },
    ),
  report: (id: number) => api.get<RecoveryReport>(`/api/archive-recovery/${id}/report`),
};