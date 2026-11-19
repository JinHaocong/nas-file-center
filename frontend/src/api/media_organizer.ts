import { api } from './client';
import type { TaskDetail } from '../types/task';

export type SemanticPreviewStatus = 'queued' | 'running' | 'completed' | 'failed' |
  'cancelled' | 'cancel_requested' | 'paused';
export type SemanticUnitStatus = 'ready' | 'blocked' | 'skipped' | 'already_organized';

export interface SemanticExecutionAssurance {
  execution_mode?: 'strict' | 'maintenance_window';
  assurance_level?: 'strict' | 'maintenance_window';
  requires_maintenance_window?: boolean;
  namespace_exclusive_custody_proven?: boolean;
}

export interface SemanticMediaGroup {
  name: string;
  kind: 'P' | 'V' | 'Other';
  count: number;
  bytes: number;
  destination: string;
}

export interface SemanticMovePreview {
  source: string;
  target: string;
  target_name: string;
  kind: 'P' | 'V' | 'Other';
  bytes: number;
}

export interface SemanticUnitPreview {
  unit: string;
  status: SemanticUnitStatus;
  reason: string | null;
  operation: 'flatten_pure_media' | 'bucket_pure_media' | 'sort_mixed_media' | null;
  totals: { P: number; V: number; Other: number };
  groups: SemanticMediaGroup[];
  needed_moves: number;
  renamed_count: number;
  total_files: number;
  total_proposals: number;
  sample_moves: SemanticMovePreview[];
  mapping_id: string | null;
  truncated: boolean;
  input_fingerprint?: string | null;
  conflicts: string[];
  read_only: true;
}

export interface SemanticPreviewSummary {
  unit_count: number;
  ready_count: number;
  blocked_count: number;
  already_organized_count: number;
  skipped_count: number;
  file_count: number;
  needed_moves: number;
  renamed_count: number;
  elapsed_seconds: number;
  read_only: true;
}

export interface SemanticPreviewPage extends SemanticExecutionAssurance {
  job_id: number;
  status: SemanticPreviewStatus;
  error: string | null;
  selection: string;
  progress: { current: number; total: number; message: string | null };
  summary: SemanticPreviewSummary | null;
  units: SemanticUnitPreview[];
  page: number;
  page_size: number;
  filtered_total: number;
  read_only: true;
  execution_enabled: boolean;
  confirmation_tokens: Record<string, string>;
}

export interface SemanticMappingPage {
  job_id: number;
  mapping_id: string;
  page: number;
  page_size: number;
  total_moves: number;
  moves: SemanticMovePreview[];
  read_only: true;
}

export interface SemanticExecutionStatus extends SemanticExecutionAssurance {
  job_id: number;
  status: SemanticPreviewStatus;
  error: string | null;
  preview_job_id: number;
  unit: string;
  recovery_of_job_id: number | null;
  manual_cleanup_required: boolean;
  finalized: boolean;
  publication_complete: boolean;
  deferred_publication_count: number;
  execution_enabled: boolean;
  cleanup: SemanticCleanupStatus | null;
  progress: {
    current: number;
    total: number;
    message: string | null;
    phase?: string;
  };
}

export interface SemanticCleanupStatus {
  job_id: number;
  status: SemanticPreviewStatus;
  error: string | null;
  recovery_confirmation: string | null;
}

export interface SemanticCleanupLink {
  path: string;
  published_path: string;
  identity: [number, number, number, number];
}

export interface SemanticDeferredPublication {
  path: string;
  stage_path: string;
  source_path: string;
  identity: [number, number, number, number];
}

export interface SemanticReleasedOriginalLink extends SemanticCleanupLink {
  stage_path: string;
}

export interface SemanticCleanupPlan extends SemanticExecutionAssurance {
  verification_scope?: 'worker_handoff_snapshot' | 'live_frozen_inventory';
  live_inventory_verified?: boolean;
  job_id: number;
  reviewed_execution_job_id: number;
  unit: string;
  plan_sha256: string;
  manifest_checksum: string;
  plan_kind: 'review_only';
  page: number;
  page_size: number;
  total_original_links: number;
  total_staged_links: number;
  total_deferred_publications: number;
  total_released_original_links: number;
  total_retained_original_links: number;
  original_links: SemanticCleanupLink[];
  staged_links: SemanticCleanupLink[];
  deferred_publications: SemanticDeferredPublication[];
  released_original_links: SemanticReleasedOriginalLink[];
  retained_original_links: SemanticCleanupLink[];
  wrapper_directories: { path: string; identity: [number, number] }[];
  retained_wrapper_directories: { path: string; identity: [number, number] }[];
  stage: { path: string; identity: [number, number] };
  cleanup_authorized: false;
  finalized: false;
  zero_change_rescan_verified: false;
  namespace_exclusive_custody_proven: false;
  read_only: true;
  confirmation: string;
}

const taskIsActive = (status: SemanticPreviewStatus | undefined) =>
  status === 'queued' || status === 'running' ||
  status === 'cancel_requested' || status === 'paused';

const positiveJobId = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value > 0;

export function requiresSemanticMaintenanceWindow(response: SemanticExecutionAssurance | undefined): boolean {
  return response?.execution_mode === 'maintenance_window' ||
    response?.assurance_level === 'maintenance_window' || response?.requires_maintenance_window === true;
}

export function hasMaintenanceConfirmation(
  response: SemanticExecutionAssurance | undefined, confirmed: boolean,
): boolean {
  return !requiresSemanticMaintenanceWindow(response) || confirmed === true;
}

const maintenanceConfirmationBody = (confirmed: boolean) =>
  confirmed === true ? { maintenance_window_confirmed: true } : {};

export function semanticExecutionIdFromSearch(search: URLSearchParams): number | null {
  const values = search.getAll('execution');
  if (values.length !== 1 || !/^[1-9]\d*$/.test(values[0])) return null;
  const id = Number(values[0]);
  return positiveJobId(id) ? id : null;
}

export function withSemanticExecutionId(search: URLSearchParams, id: number | null): URLSearchParams {
  const next = new URLSearchParams(search);
  next.set('operation', 'semantic-media-organize');
  if (id === null) next.delete('execution');
  else {
    if (!positiveJobId(id)) throw new Error('Invalid semantic execution ID');
    next.set('execution', String(id));
  }
  return next;
}

export function semanticOrganizerTaskHref(
  task: Pick<TaskDetail, 'id' | 'job_type' | 'payload'>,
): string | null {
  const id = task.job_type === 'media-organizer-execute' ? task.id :
    task.job_type === 'media-organizer-cleanup' ? task.payload?.execution_job_id : null;
  return positiveJobId(id) ? `/batch?${withSemanticExecutionId(new URLSearchParams(), id)}` : null;
}

export function executableSemanticUnits(page: SemanticPreviewPage | undefined): SemanticUnitPreview[] {
  if (!page?.execution_enabled || page.status !== 'completed' ||
    !page.summary || page.summary.blocked_count !== 0) return [];
  return page.units.filter(unit => unit.status === 'ready' &&
    Boolean(page.confirmation_tokens[unit.unit]));
}

/** Keep the original execution observable while its separate cleanup runs. */
export function semanticExecutionNeedsPolling(
  execution: SemanticExecutionStatus | undefined,
  expectedCleanupJobId: number | null = null,
): boolean {
  return execution === undefined || taskIsActive(execution.status) ||
    taskIsActive(execution.cleanup?.status) ||
    (expectedCleanupJobId !== null && execution.cleanup?.job_id !== expectedCleanupJobId);
}

export function canConfirmSemanticCleanup(
  execution: SemanticExecutionStatus | undefined,
  plan: SemanticCleanupPlan | undefined,
  confirmation: string,
  maintenanceWindowConfirmed = false,
): boolean {
  return Boolean(execution?.execution_enabled && execution.status === 'completed' && execution.manual_cleanup_required &&
    hasMaintenanceConfirmation(execution, maintenanceWindowConfirmed) &&
    hasMaintenanceConfirmation(plan, maintenanceWindowConfirmed) &&
    !execution.finalized && !execution.cleanup && plan?.read_only &&
    plan.plan_kind === 'review_only' && !plan.cleanup_authorized &&
    plan.reviewed_execution_job_id === execution.job_id && plan.unit === execution.unit &&
    plan.confirmation && confirmation === plan.confirmation);
}

export function canRecoverSemanticCleanup(
  execution: SemanticExecutionStatus | undefined,
  confirmation: string,
  maintenanceWindowConfirmed = false,
): boolean {
  const cleanup = execution?.cleanup;
  return Boolean(execution?.execution_enabled && cleanup?.status === 'failed' && cleanup.recovery_confirmation &&
    hasMaintenanceConfirmation(execution, maintenanceWindowConfirmed) &&
    confirmation === cleanup.recovery_confirmation);
}

export const mediaOrganizerApi = {
  startExecution: (previewJobId: number, unit: string, confirmation: string, maintenanceWindowConfirmed = false) =>
    api.post<{ job_id: number; status: SemanticPreviewStatus }>(
      `/api/media-organizer/previews/${previewJobId}/execute`,
      { unit, confirmation, ...maintenanceConfirmationBody(maintenanceWindowConfirmed) },
    ),
  getExecution: (jobId: number) =>
    api.get<SemanticExecutionStatus>(`/api/media-organizer/executions/${jobId}`),
  getCleanupPlan: (jobId: number, page = 1, pageSize = 25) => {
    const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    return api.get<SemanticCleanupPlan>(
      `/api/media-organizer/executions/${jobId}/cleanup-plan?${query}`,
    );
  },
  startCleanup: (jobId: number, confirmation: string, maintenanceWindowConfirmed = false) =>
    api.post<{ job_id: number; status: SemanticPreviewStatus; execution_job_id: number }>(
      `/api/media-organizer/executions/${jobId}/cleanup`,
      { confirmation, ...maintenanceConfirmationBody(maintenanceWindowConfirmed) },
    ),
  recoverCleanup: (cleanupJobId: number, confirmation: string, maintenanceWindowConfirmed = false) =>
    api.post<{ job_id: number; status: SemanticPreviewStatus; execution_job_id: number }>(
      `/api/media-organizer/cleanups/${cleanupJobId}/recover`,
      { confirmation, ...maintenanceConfirmationBody(maintenanceWindowConfirmed) },
    ),
  recoverExecution: (jobId: number, confirmation: string, maintenanceWindowConfirmed = false) =>
    api.post<{ job_id: number; status: SemanticPreviewStatus; recovery_of_job_id: number }>(
      `/api/media-organizer/executions/${jobId}/recover`,
      { confirmation, ...maintenanceConfirmationBody(maintenanceWindowConfirmed) },
    ),
  startPreview: (selection: string) =>
    api.post<{ job_id: number; status: SemanticPreviewStatus }>(
      '/api/media-organizer/previews', { selection },
    ),
  getPreview: (jobId: number, page = 1, pageSize = 25, statusFilter = 'all') => {
    const query = new URLSearchParams({
      page: String(page), page_size: String(pageSize), status_filter: statusFilter,
    });
    return api.get<SemanticPreviewPage>(`/api/media-organizer/previews/${jobId}?${query}`);
  },
  getMapping: (jobId: number, mappingId: string, page = 1, pageSize = 50) => {
    const query = new URLSearchParams({
      page: String(page), page_size: String(pageSize),
    });
    return api.get<SemanticMappingPage>(
      `/api/media-organizer/previews/${jobId}/mappings/${encodeURIComponent(mappingId)}?${query}`,
    );
  },
};
