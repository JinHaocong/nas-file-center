import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { schedulerApi } from '../../api/scheduler';
import { indexesApi, scansApi } from '../../api/domain';
import { workflowApi } from '../../api/workflows';
import type { ScheduleItem, ScheduleTargetType } from '../../types/scheduler';
import type { WorkflowListItem } from '../../types/workflow';
import { getStructuredApiError } from '../../api/errors';
import { formatDateTime } from '../../utils/format';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import {
  buildSchedulePayload, COMMON_TIMEZONES, createDefaultScheduleDraft,
  draftFromSchedule, TARGET_LABELS,
} from './schedulerModel';
import type { ScheduleDraft } from './schedulerModel';

interface Props { open: boolean; schedule: ScheduleItem | null; onClose: () => void; }

const MultiOptions: React.FC<{
  label: string;
  value: string[];
  options: { value: string; label: string }[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
}> = ({ label, value, options, onChange, disabled = false }) => (
  <fieldset className="nfc-v2-scheduler-multi" disabled={disabled}>
    <legend>{label}</legend>
    {options.length ? options.map(option => (
      <label key={option.value}>
        <input type="checkbox" checked={value.includes(option.value)}
          onChange={event => onChange(event.target.checked
            ? Array.from(new Set([...value, option.value]))
            : value.filter(item => item !== option.value))} />
        <span>{option.label}</span>
      </label>
    )) : <p>暂无可选条目</p>}
  </fieldset>
);

export const ScheduleEditorModal: React.FC<Props> = ({ open, schedule, onClose }) => {
  const toast = useConsoleToast();
  const queryClient = useQueryClient();
  const inFlight = useRef(false);
  const workflowEpoch = useRef(0);
  const previewEpoch = useRef(0);
  const live = useRef({ open, workflowId: '' });
  const [draft, setDraft] = useState<ScheduleDraft>(() => createDefaultScheduleDraft());
  live.current = { open, workflowId: draft.workflowId };
  const [workflowMode, setWorkflowMode] = useState<WorkflowListItem['mode'] | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [previewTimes, setPreviewTimes] = useState<string[]>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const { data: indexes } = useQuery({
    queryKey: ['scheduler-index-roots'], queryFn: () => indexesApi.listIndexes(1, 200), enabled: open,
  });
  const { data: scans } = useQuery({
    queryKey: ['scheduler-scans'], queryFn: () => scansApi.listScans(1, 200), enabled: open,
  });
  const { data: workflows } = useQuery({
    queryKey: ['scheduler-workflows'], queryFn: () => workflowApi.listWorkflows(false), enabled: open,
  });
  const completedScans = useMemo(
    () => (scans?.items || []).filter(item => item.status === 'completed'), [scans?.items],
  );

  useEffect(() => {
    workflowEpoch.current += 1;
    previewEpoch.current += 1;
    setPreviewTimes([]);
    setPreviewError(null);
    if (!open) return;
    setWorkflowMode(null);
    setWorkflowLoading(false);
    const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    setDraft(schedule ? draftFromSchedule(schedule) : createDefaultScheduleDraft(browserTimezone));
    if (!schedule || schedule.target.type !== 'workflow') return;
    const target = schedule.target;
    const ticket = ++workflowEpoch.current;
    setWorkflowLoading(true);
    void workflowApi.getWorkflowRevision(target.workflow_id, target.workflow_revision)
      .then(revision => {
        if (workflowEpoch.current === ticket) setWorkflowMode(revision.definition.mode);
      })
      .catch(() => {
        if (workflowEpoch.current === ticket) {
          setWorkflowMode(null);
          toast.error('无法核验固定工作流版本；保存已锁定');
        }
      })
      .finally(() => { if (workflowEpoch.current === ticket) setWorkflowLoading(false); });
  }, [open, schedule, toast]);

  const update = <K extends keyof ScheduleDraft>(key: K, value: ScheduleDraft[K]) =>
    setDraft(previous => ({ ...previous, [key]: value }));
  const invalidatePreview = () => {
    previewEpoch.current += 1;
    setPreviewTimes([]);
    setPreviewError(null);
  };
  const bindWorkflowCurrent = async (id: string) => {
    const ticket = ++workflowEpoch.current;
    setWorkflowMode(null);
    setWorkflowLoading(Boolean(id));
    setDraft(previous => ({
      ...previous, workflowId: id, workflowRevision: null, workflowSha: '',
      workflowAction: 'preview', workflowRootIds: [], workflowScanJobId: '',
    }));
    if (!id) return;
    try {
      const detail = await workflowApi.getWorkflow(Number(id));
      if (workflowEpoch.current !== ticket || !live.current.open || live.current.workflowId !== id) return;
      const selected = workflows?.find(item => item.id === Number(id));
      const mode = selected?.mode || detail.definition?.mode || null;
      setWorkflowMode(mode);
      setDraft(previous => previous.workflowId === id ? {
        ...previous, workflowRevision: detail.current_revision,
        workflowSha: detail.definition_sha256 || '',
      } : previous);
    } catch (err: unknown) {
      if (workflowEpoch.current === ticket) {
        setWorkflowMode(null);
        toast.error(getStructuredApiError(err).message || '读取工作流版本失败');
      }
    } finally {
      if (workflowEpoch.current === ticket) setWorkflowLoading(false);
    }
  };

  const previewRecurrence = async () => {
    if (previewLoading || inFlight.current) return;
    const cron = draft.cron.trim(), timezone = draft.timezone.trim();
    if (!cron || !timezone) {
      setPreviewError('请先填写 Cron 和时区');
      setPreviewTimes([]);
      return;
    }
    const ticket = ++previewEpoch.current;
    setPreviewLoading(true);
    setPreviewError(null);
    setPreviewTimes([]);
    try {
      const result = await schedulerApi.previewRecurrence(cron, timezone, 5);
      if (previewEpoch.current === ticket && live.current.open) setPreviewTimes(result.occurrences);
    } catch (err: unknown) {
      if (previewEpoch.current === ticket && live.current.open) {
        setPreviewError(getStructuredApiError(err).message || '时间表达式无效');
      }
    } finally {
      if (previewEpoch.current === ticket) setPreviewLoading(false);
    }
  };

  const saveMutation = useMutation({
    mutationFn: (values: ScheduleDraft) => {
      const payload = buildSchedulePayload(values, workflowMode);
      return schedule
        ? schedulerApi.updateSchedule(schedule.id, { ...payload, expected_revision: schedule.revision })
        : schedulerApi.createSchedule(payload);
    },
    onSuccess: async () => {
      toast.success(schedule ? '计划任务已更新' : '计划任务已创建');
      await queryClient.invalidateQueries({ queryKey: ['schedules'] });
      onClose();
    },
    onError: (err: unknown) => toast.error(getStructuredApiError(err).message || '保存失败'),
  });
  const busy = saveMutation.isPending;
  const closeSafely = () => { if (!busy && !inFlight.current) onClose(); };
  const onSubmit = async () => {
    if (!open || busy || inFlight.current || workflowLoading || previewLoading) return;
    inFlight.current = true;
    try {
      await saveMutation.mutateAsync({ ...draft });
    } catch {
      // Validation and server errors shown below; explicit retry stays available.
    } finally { inFlight.current = false; }
  };

  const rootOptions = (indexes?.items || []).map(root => ({
    value: root.root, label: root.root,
  }));
  const rootIdOptions = (indexes?.items || []).map(root => ({
    value: String(root.id), label: '#' + root.id + ' · ' + root.root,
  }));

  return (
    <Dialog.Root open={open} onOpenChange={next => { if (!next) closeSafely(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-confirm-overlay" />
        <Dialog.Content className="nfc-v2-dialog nfc-overlay-modal nfc-scheduler-editor nfc-v2-scheduler-editor"
          onEscapeKeyDown={event => { if (busy || inFlight.current) event.preventDefault(); }}
          onPointerDownOutside={event => event.preventDefault()}>
          <header className="nfc-v2-dialog-heading">
            <span className="nfc-v2-dialog-icon"><ConsoleIcon name="calendar" size={20} /></span>
            <div>
              <Dialog.Title>{schedule ? '编辑计划任务 #' + schedule.id : '新建计划任务'}</Dialog.Title>
              <Dialog.Description>编辑 Cron、IANA 时区与固定目标；权限和有效性由服务端最终裁决。</Dialog.Description>
            </div>
            <button type="button" className="nfc-v2-dialog-close" disabled={busy}
              aria-label="关闭编辑窗口" onClick={closeSafely}><ConsoleIcon name="x" size={18} /></button>
          </header>
          <form className="nfc-v2-scheduler-form" onSubmit={event => { event.preventDefault(); void onSubmit(); }}>
            <div className="nfc-scheduler-form-grid">
              <label className="nfc-v2-scheduler-field">名称
                <input value={draft.name} onChange={event => update('name', event.target.value)}
                  maxLength={128} required placeholder="例如：每天凌晨重新索引照片库" />
              </label>
              <label className="nfc-v2-scheduler-toggle">启用
                <input type="checkbox" checked={draft.enabled}
                  onChange={event => update('enabled', event.target.checked)} />
              </label>
            </div>
            <label className="nfc-v2-scheduler-field">说明
              <textarea rows={2} maxLength={2000} value={draft.description}
                onChange={event => update('description', event.target.value)} />
            </label>

            <div className="nfc-v2-scheduler-section-label">目标</div>
            <label className="nfc-v2-scheduler-field">任务类型
              <select value={draft.targetType} onChange={event => {
                const next = event.target.value as ScheduleTargetType;
                workflowEpoch.current += 1;
                setWorkflowMode(null);
                setWorkflowLoading(false);
                update('targetType', next);
              }}>
                {Object.entries(TARGET_LABELS).map(([value, label]) =>
                  <option key={value} value={value}>{label}</option>)}
              </select>
            </label>

            {draft.targetType === 'index_root' && (
              <label className="nfc-v2-scheduler-field">索引根目录
                <select required value={draft.indexRootId}
                  onChange={event => update('indexRootId', event.target.value)}>
                  <option value="">请选择索引根目录</option>
                  {rootIdOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
            )}
            {draft.targetType === 'fclones_scan' && (
              <>
                <MultiOptions label="扫描目录（至少一个）" value={draft.scanRoots}
                  options={rootOptions} onChange={value => update('scanRoots', value)} />
                <div className="nfc-scheduler-form-grid">
                  <label className="nfc-v2-scheduler-toggle">隔离扫描
                    <input type="checkbox" checked={draft.scanIsolate}
                      onChange={event => update('scanIsolate', event.target.checked)} />
                  </label>
                  <label className="nfc-v2-scheduler-field">最小文件大小
                    <input value={draft.scanMinSize} placeholder="例如 10M；留空表示不限制"
                      onChange={event => update('scanMinSize', event.target.value)} />
                  </label>
                </div>
                <div className="nfc-scheduler-form-grid">
                  <label className="nfc-v2-scheduler-field">文件名模式（逗号或换行分隔）
                    <textarea rows={2} value={draft.scanNamePatterns} placeholder="例如 *.mkv"
                      onChange={event => update('scanNamePatterns', event.target.value)} />
                  </label>
                  <label className="nfc-v2-scheduler-field">排除模式（逗号或换行分隔）
                    <textarea rows={2} value={draft.scanExcludePatterns} placeholder="例如 sample*"
                      onChange={event => update('scanExcludePatterns', event.target.value)} />
                  </label>
                </div>
              </>
            )}
            {(draft.targetType === 'media_analysis' ||
              draft.targetType === 'media_integrity_verification') && (
              <MultiOptions label="媒体根目录（至少一个）" value={draft.mediaRootKeys}
                options={rootOptions} onChange={value => update('mediaRootKeys', value)} />
            )}
            {draft.targetType === 'workflow' && (
              <>
                <label className="nfc-v2-scheduler-field">工作流
                  <select required value={draft.workflowId}
                    onChange={event => { void bindWorkflowCurrent(event.target.value); }}>
                    <option value="">请选择工作流</option>
                    {(workflows || []).map(item => (
                      <option key={item.id} value={String(item.id)}>
                        #{item.id} · {item.name} · {item.mode}
                      </option>
                    ))}
                    {draft.workflowId && !(workflows || []).some(item => String(item.id) === draft.workflowId) &&
                      <option value={draft.workflowId}>已固定工作流 #{draft.workflowId}</option>}
                  </select>
                </label>
                <div className="nfc-scheduler-pin-panel" aria-live="polite">
                  <div><span>固定版本</span><b>r{draft.workflowRevision || '—'}</b></div>
                  <div><span>Definition SHA</span><code>{draft.workflowSha || '—'}</code></div>
                </div>
                {workflowLoading && <p role="status">正在核验工作流固定版本…</p>}
                <label className="nfc-v2-scheduler-field">动作
                  <select value={draft.workflowAction} disabled={workflowLoading}
                    onChange={event => update('workflowAction', event.target.value as 'preview' | 'draft')}>
                    <option value="preview">Preview（只读预览）</option>
                    <option value="draft" disabled={workflowMode === 'utility'}>
                      Draft（生成草稿 Plan）
                    </option>
                  </select>
                  <small>{workflowMode === 'utility'
                    ? 'Utility 工作流在 Scheduler S3/S4 中仅允许 Preview。'
                    : 'Draft 只生成草稿 Plan，不会自动 Freeze / Validate / Execute。'}</small>
                </label>
                {workflowMode === 'dedupe' && (
                  <label className="nfc-v2-scheduler-field">固定完成扫描
                    <select required value={draft.workflowScanJobId}
                      onChange={event => update('workflowScanJobId', event.target.value)}>
                      <option value="">请选择 completed ScanJob</option>
                      {completedScans.map(scan => <option key={scan.id} value={String(scan.id)}>
                        #{scan.id} · {scan.name}
                      </option>)}
                    </select>
                  </label>
                )}
                {(workflowMode === 'file' || workflowMode === 'organizer') && (
                  <MultiOptions label="运行时根目录覆盖（可选）" value={draft.workflowRootIds}
                    options={rootIdOptions} onChange={value => update('workflowRootIds', value)} />
                )}
                {draft.workflowAction === 'draft' &&
                  <div className="nfc-scheduler-boundary-alert nfc-v2-scheduler-note" role="note">
                    <ConsoleIcon name="info" size={17} />
                    <span><strong>Draft 权限边界。</strong>定时执行只会完成 Preview → Generate Draft。
                      不会自动 Freeze、Validate 或 Execute。</span>
                  </div>}
              </>
            )}

            <div className="nfc-v2-scheduler-section-label">时间</div>
            <div className="nfc-scheduler-form-grid">
              <label className="nfc-v2-scheduler-field">Cron
                <input required value={draft.cron} placeholder="0 2 * * *"
                  onChange={event => { update('cron', event.target.value); invalidatePreview(); }} />
                <small>格式：minute hour day-of-month month day-of-week</small>
              </label>
              <label className="nfc-v2-scheduler-field">IANA 时区
                <input required value={draft.timezone} list="scheduler-common-timezones"
                  onChange={event => { update('timezone', event.target.value); invalidatePreview(); }}
                  placeholder="例如 Asia/Shanghai" />
                <datalist id="scheduler-common-timezones">
                  {COMMON_TIMEZONES.map(zone => <option value={zone} key={zone} />)}
                </datalist>
              </label>
            </div>
            <div className="nfc-scheduler-time-preview">
              <ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="clock" size={15} />}
                disabled={!draft.cron.trim() || !draft.timezone.trim()}
                loading={previewLoading} onClick={() => { void previewRecurrence(); }}>
                验证并预览未来 5 次
              </ConsoleButton>
              {previewError && <span role="alert" className="nfc-scheduler-preview-error">{previewError}</span>}
              {previewTimes.length > 0 && <div className="nfc-scheduler-occurrences">
                {previewTimes.map((time, i) => <code key={time + i}>{formatDateTime(time)}</code>)}
              </div>}
            </div>
            <div className="nfc-v2-confirm-actions">
              <ConsoleButton disabled={busy} onClick={closeSafely}>取消</ConsoleButton>
              <ConsoleButton type="submit" variant="primary" loading={busy}
                disabled={workflowLoading || previewLoading ||
                  (draft.targetType === 'workflow' && (!draft.workflowRevision || !draft.workflowSha || !workflowMode))}>
                保存
              </ConsoleButton>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};
