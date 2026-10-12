import type { ScheduleCreatePayload, ScheduleItem, ScheduleTarget, ScheduleTargetType } from '../../types/scheduler';
import type { WorkflowListItem } from '../../types/workflow';

export const TARGET_LABELS: Record<ScheduleTargetType, string> = {
  index_root: '文件索引',
  fclones_scan: '重复扫描',
  media_analysis: '媒体分析',
  media_integrity_verification: '媒体完整性校验',
  workflow: '工作流',
};

export const COMMON_TIMEZONES = [
  'UTC', 'Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Tokyo',
  'America/New_York', 'America/Chicago', 'America/Denver',
  'America/Los_Angeles', 'Europe/London', 'Europe/Berlin',
];

export interface ScheduleDraft {
  name: string;
  description: string;
  enabled: boolean;
  targetType: ScheduleTargetType;
  cron: string;
  timezone: string;
  indexRootId: string;
  scanRoots: string[];
  scanIsolate: boolean;
  scanMinSize: string;
  scanNamePatterns: string;
  scanExcludePatterns: string;
  mediaRootKeys: string[];
  workflowId: string;
  workflowRevision: number | null;
  workflowSha: string;
  workflowAction: 'preview' | 'draft';
  workflowRootIds: string[];
  workflowScanJobId: string;
}

const joinPatterns = (items?: string[] | null) => (items || []).join(', ');
export const splitPatterns = (raw: string): string[] =>
  raw.split(/[,\n]/).map(x => x.trim()).filter(Boolean);

export const createDefaultScheduleDraft = (timezone = 'UTC'): ScheduleDraft => ({
  name: '', description: '', enabled: true, targetType: 'index_root',
  cron: '0 2 * * *', timezone, indexRootId: '', scanRoots: [], scanIsolate: false,
  scanMinSize: '', scanNamePatterns: '', scanExcludePatterns: '',
  mediaRootKeys: [], workflowId: '', workflowRevision: null, workflowSha: '',
  workflowAction: 'preview', workflowRootIds: [], workflowScanJobId: '',
});

export function draftFromSchedule(schedule: ScheduleItem): ScheduleDraft {
  const draft = createDefaultScheduleDraft(schedule.timezone);
  draft.name = schedule.name;
  draft.description = schedule.description || '';
  draft.enabled = schedule.enabled;
  draft.targetType = schedule.target.type;
  draft.cron = schedule.cron_expression;
  const target = schedule.target;
  if (target.type === 'index_root') {
    draft.indexRootId = String(target.root_id);
  } else if (target.type === 'fclones_scan') {
    draft.scanRoots = [...target.roots];
    draft.scanIsolate = target.isolate;
    draft.scanMinSize = target.min_size || '';
    draft.scanNamePatterns = joinPatterns(target.name_patterns);
    draft.scanExcludePatterns = joinPatterns(target.exclude_patterns);
  } else if (target.type === 'media_analysis' || target.type === 'media_integrity_verification') {
    draft.mediaRootKeys = [...target.root_keys];
  } else if (target.type === 'workflow') {
    draft.workflowId = String(target.workflow_id);
    draft.workflowRevision = target.workflow_revision;
    draft.workflowSha = target.definition_sha256;
    draft.workflowAction = target.action;
    draft.workflowRootIds = (target.runtime_inputs?.root_ids || []).map(String);
    draft.workflowScanJobId = target.runtime_inputs?.scan_job_id
      ? String(target.runtime_inputs.scan_job_id) : '';
  }
  return draft;
}

function positiveId(value: string, label: string): number {
  const id = Number(value);
  if (!Number.isSafeInteger(id) || id <= 0) throw new Error('请选择有效的' + label);
  return id;
}

export function buildScheduleTarget(
  draft: ScheduleDraft, workflowMode: WorkflowListItem['mode'] | null,
): ScheduleTarget {
  switch (draft.targetType) {
    case 'index_root':
      return { type: 'index_root', root_id: positiveId(draft.indexRootId, '索引根目录') };
    case 'fclones_scan':
      if (!draft.scanRoots.length) throw new Error('至少选择一个扫描目录');
      return {
        type: 'fclones_scan', roots: [...draft.scanRoots],
        isolate: draft.scanIsolate, min_size: draft.scanMinSize.trim() || null,
        name_patterns: splitPatterns(draft.scanNamePatterns).length
          ? splitPatterns(draft.scanNamePatterns) : null,
        exclude_patterns: splitPatterns(draft.scanExcludePatterns).length
          ? splitPatterns(draft.scanExcludePatterns) : null,
      };
    case 'media_analysis':
    case 'media_integrity_verification':
      if (!draft.mediaRootKeys.length) throw new Error('至少选择一个媒体根目录');
      return { type: draft.targetType, root_keys: [...draft.mediaRootKeys] };
    case 'workflow': {
      const workflowId = positiveId(draft.workflowId, '工作流');
      const revision = draft.workflowRevision;
      if (!Number.isSafeInteger(revision) || !revision || revision <= 0 || !draft.workflowSha.trim()) {
        throw new Error('必须先固定工作流 revision 和 Definition SHA');
      }
      if (!workflowMode) throw new Error('尚未验证固定工作流版本的模式');
      if (workflowMode === 'utility' && draft.workflowAction !== 'preview') {
        throw new Error('Utility 工作流仅允许 Preview，禁止 Draft');
      }
      let runtimeInputs: { root_ids?: number[]; scan_job_id?: number } | null = null;
      if (workflowMode === 'dedupe') {
        runtimeInputs = { scan_job_id: positiveId(draft.workflowScanJobId, '已完成扫描') };
      } else if ((workflowMode === 'file' || workflowMode === 'organizer') &&
                 draft.workflowRootIds.length) {
        runtimeInputs = { root_ids: draft.workflowRootIds.map(id => positiveId(id, '运行时根目录')) };
      }
      return {
        type: 'workflow', workflow_id: workflowId,
        workflow_revision: revision, definition_sha256: draft.workflowSha.trim(),
        action: draft.workflowAction, runtime_inputs: runtimeInputs,
      };
    }
    default:
      throw new Error('未知 Scheduler target');
  }
}

export function buildSchedulePayload(
  draft: ScheduleDraft, workflowMode: WorkflowListItem['mode'] | null,
): ScheduleCreatePayload {
  const name = draft.name.trim();
  if (!name) throw new Error('请输入名称');
  if (name.length > 128) throw new Error('名称不得超过 128 字符');
  if (!draft.cron.trim() || !draft.timezone.trim()) throw new Error('请输入 5-field Cron 和 IANA 时区');
  return {
    name, description: draft.description.trim(), enabled: draft.enabled,
    target: buildScheduleTarget(draft, workflowMode),
    cron_expression: draft.cron.trim(), timezone: draft.timezone.trim(),
  };
}

export function targetSummary(schedule: ScheduleItem): string {
  const target = schedule.target;
  switch (target.type) {
    case 'index_root': return 'IndexRoot #' + target.root_id;
    case 'fclones_scan': return target.roots.length + ' roots' + (target.isolate ? ' · isolate' : '');
    case 'media_analysis':
    case 'media_integrity_verification': return target.root_keys.length + ' roots';
    case 'workflow': return 'Workflow #' + target.workflow_id + ' · r' +
      target.workflow_revision + ' · ' + target.action;
    default: return '—';
  }
}
