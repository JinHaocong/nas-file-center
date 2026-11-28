import { api } from './client';

export type ArchiveKind = 'task_events' | 'operation_journal';

export interface DatabaseMaintenancePreview {
  database: {
    database_bytes: number;
    wal_bytes: number;
    reusable_bytes: number;
    estimated_reclaimable_bytes: number;
    wal_retained_limit_bytes: number;
    active_jobs: number;
  };
  task_events: { jobs: number; rows: number };
  operation_journal: { rows: number };
  policy: {
    automatic: boolean;
    task_event_retention_days: number;
    operation_journal_retention_days: number;
  };
}

export const databaseMaintenanceApi = {
  /** Read the database and archive preview without applying changes. */
  preview: () => api.get<DatabaseMaintenancePreview>('/api/database-maintenance'),

  /** Archive one batch under the current retention policy. */
  archive: (kind: ArchiveKind) => api.post<{ rows: number; files: string[] }>(
    '/api/database-maintenance/archive', { kind },
  ),
};
