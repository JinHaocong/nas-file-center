import { DedupeScorerConfig } from './dedupe';

export type FilterLeafField =
  | 'path'
  | 'name'
  | 'extension'
  | 'size'
  | 'mtime'
  | 'media_type';

export type FilterLeafOperator =
  | 'eq'
  | 'neq'
  | 'contains'
  | 'startswith'
  | 'endswith'
  | 'in'
  | 'nin'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte';

export interface FilterLeafNode {
  field: FilterLeafField;
  operator: FilterLeafOperator;
  value: string | number | string[];
  case_sensitive?: boolean;
}

export interface FilterAndOrNode {
  op: 'and' | 'or';
  children: FilterNode[];
}

export interface FilterNotNode {
  op: 'not';
  child: FilterNode;
}

export type FilterNode = FilterLeafNode | FilterAndOrNode | FilterNotNode;

export function isFilterLeafNode(node: FilterNode): node is FilterLeafNode {
  return typeof node === 'object' && node !== null && 'field' in node && 'operator' in node;
}

export function isFilterAndOrNode(node: FilterNode): node is FilterAndOrNode {
  return (
    typeof node === 'object' &&
    node !== null &&
    'op' in node &&
    ((node as any).op === 'and' || (node as any).op === 'or') &&
    Array.isArray((node as any).children)
  );
}

export function isFilterNotNode(node: FilterNode): node is FilterNotNode {
  return (
    typeof node === 'object' &&
    node !== null &&
    'op' in node &&
    (node as any).op === 'not' &&
    'child' in node
  );
}

export interface ScanStep {
  id: string;
  type: 'scan';
  root_ids: number[];
  subpath?: string;
}

export interface FilterStep {
  id: string;
  type: 'filter';
  filter: FilterNode;
}

export interface RenameStep {
  id: string;
  type: 'rename';
  pattern: string;
  replacement: string;
}

export interface MoveStep {
  id: string;
  type: 'move';
  destination_root_id: number;
  destination_subpath?: string;
}

export interface TouchStep {
  id: string;
  type: 'touch';
  mtime_ns: number | null;
  touch_now: boolean;
}

export interface QuarantineStep {
  id: string;
  type: 'quarantine';
  reason: string;
}

export interface OrganizerProfileSnapshot {
  name: string;
  description?: string | null;
  root?: string | null;
  recursive?: boolean;
  image_extensions?: string[];
  video_extensions?: string[];
  rename_template?: string;
  statistics_template?: string;
  preserve_tags?: string[];
  cleanup_patterns?: string[];
  numbering_mode?: 'none' | 'sequential';
  numbering_start?: number;
  numbering_padding?: number;
  mtime_mode?: 'none' | 'ordered';
  mtime_delay_seconds?: number;
}

export const CANONICAL_ORGANIZER_SNAPSHOT_DEFAULTS: OrganizerProfileSnapshot = {
  name: '',
  description: '',
  root: '',
  recursive: false,
  image_extensions: ['jpg', 'jpeg', 'png', 'webp'],
  video_extensions: ['mp4', 'mov', 'mkv'],
  rename_template: '{name}',
  statistics_template: '[{images}P {videos}V {size}]',
  preserve_tags: [],
  cleanup_patterns: [],
  numbering_mode: 'none',
  numbering_start: 1,
  numbering_padding: 3,
  mtime_mode: 'none',
  mtime_delay_seconds: 2.0,
};

export interface OrganizeStep {
  id: string;
  type: 'organize';
  profile_snapshot: OrganizerProfileSnapshot;
}

export interface DedupeStep {
  id: string;
  type: 'dedupe';
  scorer_config: DedupeScorerConfig;
}

export type WorkflowStep =
  | ScanStep
  | FilterStep
  | RenameStep
  | MoveStep
  | TouchStep
  | QuarantineStep
  | OrganizeStep
  | DedupeStep;

export type WorkflowStepType =
  | 'scan'
  | 'filter'
  | 'rename'
  | 'move'
  | 'touch'
  | 'quarantine'
  | 'organize'
  | 'dedupe';

export type WorkflowMode = 'file' | 'organizer' | 'dedupe';

export interface WorkflowDefinition {
  schema_version: 1;
  mode: WorkflowMode;
  steps: WorkflowStep[];
}

export interface WorkflowListItem {
  id: number;
  name: string;
  description: string;
  current_revision: number;
  is_builtin: boolean;
  mode: WorkflowMode;
  created_by_user_id: number | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowResponse {
  id: number;
  name: string;
  description: string;
  current_revision: number;
  is_builtin: boolean;
  created_by_user_id: number | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  definition?: WorkflowDefinition;
  definition_sha256?: string;
}

export interface WorkflowRevisionResponse {
  revision: number;
  definition_sha256: string;
  definition: WorkflowDefinition;
  created_at: string;
  created_by_user_id: number | null;
}

export interface WorkflowCreateRequest {
  name: string;
  description?: string;
  definition: WorkflowDefinition;
}

export interface WorkflowUpdateRequest {
  expected_current_revision: number;
  name?: string;
  description?: string;
  definition?: WorkflowDefinition;
}

export interface WorkflowRollbackRequest {
  target_revision: number;
  expected_current_revision: number;
}

export interface WorkflowPreviewItem {
  source_path: string;
  target_path?: string | null;
  operation: string;
  mtime_ns?: number | null;
  changed: boolean;
  metadata: Record<string, any>;
}

export interface WorkflowPreviewRequest {
  revision?: number;
  runtime_inputs?: {
    root_ids?: number[];
    scan_job_id?: number;
    [key: string]: any;
  };
  root_ids?: number[];
  page?: number;
  page_size?: number;
  only_changed?: boolean;
}

export interface WorkflowPreviewResponse {
  workflow_id: number;
  revision: number;
  workflow_revision: number;
  definition_sha256: string;
  preview_source: 'index' | 'organizer-live-readonly';
  live_filesystem_verified: boolean;
  compile_digest: string;
  matched_count: number;
  matched_bytes: number;
  planned_operations_count: number;
  page: number;
  page_size: number;
  total_pages: number;
  items: WorkflowPreviewItem[];
}

export interface WorkflowGeneratePlanRequest {
  expected_compile_digest: string;
  revision?: number;
  runtime_inputs?: {
    root_ids?: number[];
    scan_job_id?: number;
    [key: string]: any;
  };
  root_ids?: number[];
  plan_name?: string;
}

export interface WorkflowGeneratePlanResponse {
  plan_id: number;
  plan_name: string;
  status: string;
  expected_changes: number;
  compile_digest: string;
}

export interface PlanRebuildPreviewRequest {
  page?: number;
  page_size?: number;
  only_changed?: boolean;
}

export interface PlanRebuildPreviewResponse {
  source_plan_id: number;
  workflow_id: number;
  workflow_revision: number;
  definition_sha256: string;
  runtime_inputs: {
    root_ids: number[];
    [key: string]: any;
  };
  preview_source: 'index' | 'organizer-live-readonly';
  live_filesystem_verified: boolean;
  compile_digest: string;
  matched_count: number;
  matched_bytes: number;
  planned_operations_count: number;
  page: number;
  page_size: number;
  total_pages: number;
  items: WorkflowPreviewItem[];
}

export interface PlanRebuildRequest {
  expected_compile_digest: string;
  plan_name?: string;
}

export interface PlanRebuildResponse {
  id: number;
  plan_id: number;
  name: string;
  status: string;
  rebuild_of_plan_id: number;
  expected_changes: number;
  compile_digest: string;
}

export interface WorkflowPlanMetadata {
  source: 'workflow';
  workflow_id: number;
  workflow_name?: string;
  workflow_revision: number;
  workflow_mode?: WorkflowMode;
  scan_job_id?: number;
  definition_sha256: string;
  compile_digest: string;
  runtime_inputs: {
    root_ids?: number[];
    scan_job_id?: number;
    [key: string]: any;
  };
  compile_context?: Record<string, any>;
  matched_count?: number;
  matched_bytes?: number;
  rebuild_of_plan_id?: number;
  rebuild_source_status?: string;
  created_by_user_id?: number | null;
}

export function isWorkflowPlanMetadata(metadata: unknown): metadata is WorkflowPlanMetadata {
  if (!metadata) return false;
  let m = metadata;
  if (typeof m === 'string') {
    try {
      m = JSON.parse(m);
    } catch {
      return false;
    }
  }
  if (!m || typeof m !== 'object' || Array.isArray(m)) {
    return false;
  }
  const obj = m as Record<string, any>;
  if (obj.source !== 'workflow') return false;

  if (typeof obj.workflow_id !== 'number' || !Number.isInteger(obj.workflow_id) || obj.workflow_id <= 0) {
    return false;
  }
  if (
    typeof obj.workflow_revision !== 'number' ||
    !Number.isInteger(obj.workflow_revision) ||
    obj.workflow_revision <= 0
  ) {
    return false;
  }

  const hex64Regex = /^[0-9a-fA-F]{64}$/;
  if (typeof obj.definition_sha256 !== 'string' || !hex64Regex.test(obj.definition_sha256)) {
    return false;
  }
  if (typeof obj.compile_digest !== 'string' || !hex64Regex.test(obj.compile_digest)) {
    return false;
  }

  if (
    !obj.runtime_inputs ||
    typeof obj.runtime_inputs !== 'object' ||
    Array.isArray(obj.runtime_inputs)
  ) {
    return false;
  }

  const isDedupe =
    obj.workflow_mode === 'dedupe' ||
    typeof obj.runtime_inputs.scan_job_id === 'number' ||
    typeof obj.scan_job_id === 'number';

  if (isDedupe) {
    const scanJobId = obj.runtime_inputs.scan_job_id ?? obj.scan_job_id;
    if (typeof scanJobId !== 'number' || !Number.isInteger(scanJobId) || scanJobId <= 0) {
      return false;
    }
    if (
      typeof obj.scan_job_id === 'number' &&
      typeof obj.runtime_inputs.scan_job_id === 'number' &&
      obj.scan_job_id !== obj.runtime_inputs.scan_job_id
    ) {
      return false;
    }
    return true;
  }

  if (
    !Array.isArray(obj.runtime_inputs.root_ids) ||
    obj.runtime_inputs.root_ids.length === 0 ||
    !obj.runtime_inputs.root_ids.every((id: any) => typeof id === 'number' && Number.isInteger(id) && id > 0)
  ) {
    return false;
  }
  return true;
}
