export type ScheduleTargetType =
  | 'index_root'
  | 'fclones_scan'
  | 'media_analysis'
  | 'media_integrity_verification'
  | 'workflow';

export interface IndexRootScheduleTarget {
  type: 'index_root';
  root_id: number;
}

export interface FclonesScanScheduleTarget {
  type: 'fclones_scan';
  roots: string[];
  isolate: boolean;
  min_size?: string | null;
  name_patterns?: string[] | null;
  exclude_patterns?: string[] | null;
}

export interface MediaScheduleTarget {
  type: 'media_analysis' | 'media_integrity_verification';
  root_keys: string[];
}

export interface WorkflowScheduleTarget {
  type: 'workflow';
  workflow_id: number;
  workflow_revision: number;
  definition_sha256: string;
  action: 'preview' | 'draft';
  runtime_inputs?: {
    root_ids?: number[];
    scan_job_id?: number;
  } | null;
}

export type ScheduleTarget =
  | IndexRootScheduleTarget
  | FclonesScanScheduleTarget
  | MediaScheduleTarget
  | WorkflowScheduleTarget;

export interface ScheduleItem {
  id: number;
  name: string;
  description: string;
  enabled: boolean;
  target_type: ScheduleTargetType;
  target: ScheduleTarget;
  cron_expression: string;
  timezone: string;
  overlap_policy: 'skip_if_active';
  missed_run_policy: 'skip';
  created_by_user_id: number | null;
  revision: number;
  created_at: string;
  updated_at: string;
  last_scheduled_for_utc: string | null;
  next_scheduled_for_utc: string | null;
}

export interface ScheduleRun {
  id: number;
  schedule_id: number;
  schedule_revision: number;
  scheduled_for_utc: string;
  dispatched_at: string | null;
  status: 'pending' | 'dispatched' | 'skipped_overlap' | 'failed';
  work_job_id: number | null;
  work_job_status?: string | null;
  work_job_kind?: string | null;
  error_code: string | null;
  error_text: string | null;
  target_snapshot: ScheduleTarget;
  created_at: string;
}

export interface ScheduleCreatePayload {
  name: string;
  description?: string;
  enabled?: boolean;
  target: ScheduleTarget;
  cron_expression: string;
  timezone: string;
  overlap_policy?: 'skip_if_active';
  missed_run_policy?: 'skip';
}

export interface ScheduleUpdatePayload {
  expected_revision: number;
  name?: string;
  description?: string;
  enabled?: boolean;
  target?: ScheduleTarget;
  cron_expression?: string;
  timezone?: string;
  overlap_policy?: 'skip_if_active';
  missed_run_policy?: 'skip';
}

export interface RecurrencePreview {
  cron_expression: string;
  timezone: string;
  generated_at_utc: string;
  occurrences: string[];
}
