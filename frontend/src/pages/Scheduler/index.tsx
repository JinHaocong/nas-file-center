import React, { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { schedulerApi } from '../../api/scheduler';
import { getStructuredApiError } from '../../api/errors';
import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import type { ScheduleItem } from '../../types/scheduler';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { ScheduleEditorModal } from './ScheduleEditorModal';
import { ScheduleHistoryDrawer } from './ScheduleHistoryDrawer';
import { TARGET_LABELS, targetSummary } from './schedulerModel';
import '../../styles/pages/scheduler.css';

export const SchedulerPage: React.FC = () => {
  useTitle('计划任务');
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const toast = useConsoleToast();
  const queryClient = useQueryClient();
  const [editorSchedule, setEditorSchedule] = useState<ScheduleItem | null | undefined>(undefined);
  const [historySchedule, setHistorySchedule] = useState<ScheduleItem | null>(null);
  const [runTarget, setRunTarget] = useState<ScheduleItem | null>(null);
  const [runBusy, setRunBusy] = useState(false);
  const runInFlight = useRef(false);
  const enableInFlight = useRef(false);
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['schedules'],
    queryFn: () => schedulerApi.listSchedules(1, 200, true),
    refetchInterval: 15000,
  });

  const updateMutation = useMutation({
    mutationFn: ({ schedule, enabled }: { schedule: ScheduleItem; enabled: boolean }) =>
      schedulerApi.updateSchedule(schedule.id, {
        expected_revision: schedule.revision,
        enabled,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['schedules'] });
    },
    onError: (err: unknown) => toast.error(getStructuredApiError(err).message || '更新失败'),
  });
  const runMutation = useMutation({
    mutationFn: (schedule: ScheduleItem) => schedulerApi.runNow(schedule.id),
    onSuccess: async run => {
      if (run.status === 'dispatched') {
        toast.success('已派发 Task #' + run.work_job_id);
      } else if (run.status === 'skipped_overlap') {
        toast.info('已有同计划任务仍在运行，本次已按 overlap policy 跳过');
      } else {
        toast.info(run.error_text || '本次运行未派发');
      }
      await queryClient.invalidateQueries({ queryKey: ['schedules'] });
      await queryClient.invalidateQueries({ queryKey: ['schedule-runs'] });
    },
    onError: (err: unknown) => toast.error(getStructuredApiError(err).message || 'Run now 失败'),
  });

  const handleToggle = async (schedule: ScheduleItem, enabled: boolean) => {
    if (!isAdmin || enableInFlight.current || updateMutation.isPending) return;
    enableInFlight.current = true;
    try { await updateMutation.mutateAsync({ schedule, enabled }); }
    catch { /* Toast is displayed by the mutation callback. */ }
    finally { enableInFlight.current = false; }
  };
  const closeRunConfirm = (next: boolean) => {
    if (!next && !runInFlight.current && !runBusy) setRunTarget(null);
  };
  const handleRunNow = async () => {
    if (!isAdmin || !runTarget || runInFlight.current || runMutation.isPending) return;
    runInFlight.current = true;
    setRunBusy(true);
    try {
      await runMutation.mutateAsync(runTarget);
      setRunTarget(null);
    } catch {
      // Keep the confirmation open after a failed dispatch, for deliberate retry.
    } finally {
      runInFlight.current = false;
      setRunBusy(false);
    }
  };

  const renderEnabled = (row: ScheduleItem) => isAdmin ? (
    <label className="nfc-v2-scheduler-switch" title="切换计划任务启停状态">
      <input type="checkbox" role="switch"
        aria-label={'启用计划任务 #' + row.id}
        checked={row.enabled}
        disabled={updateMutation.isPending}
        onChange={event => { void handleToggle(row, event.target.checked); }} />
      <span>{row.enabled ? '启用' : '停用'}</span>
    </label>
  ) : (
    <span className={'nfc-v2-scheduler-state ' + (row.enabled ? 'is-enabled' : 'is-disabled')}>
      {row.enabled ? '启用' : '停用'}
    </span>
  );

  const renderActions = (row: ScheduleItem) => (
    <div className="nfc-row-actions nfc-v2-scheduler-actions">
      <ConsoleButton size="sm" variant="ghost"
        leadingIcon={<ConsoleIcon name="history" size={16} />}
        onClick={() => setHistorySchedule(row)}>历史</ConsoleButton>
      {isAdmin && (
        <>
          <ConsoleButton size="sm" variant="ghost"
            leadingIcon={<ConsoleIcon name="pencil" size={16} />}
            onClick={() => setEditorSchedule(row)}>编辑</ConsoleButton>
          <ConsoleButton size="sm" variant="ghost"
            leadingIcon={<ConsoleIcon name="play" size={16} />}
            loading={runMutation.isPending && runMutation.variables?.id === row.id}
            disabled={runBusy || runMutation.isPending}
            onClick={() => { if (!runInFlight.current) setRunTarget(row); }}>
            Run now
          </ConsoleButton>
        </>
      )}
    </div>
  );

  const items: ScheduleItem[] = data?.items || [];
  return (
    <div className="nfc-operations-page nfc-scheduler-page nfc-page-layout-ledger nfc-v2-scheduler-page">
      <PageHeader eyebrow="Automation" title="计划任务"
        description="用 Cron + IANA 时区定时派发索引、扫描、媒体任务与固定版本的 Workflow Preview/Draft。"
        actions={<ActionBar compact>
          {isAdmin && <ConsoleButton variant="primary" leadingIcon={<ConsoleIcon name="plus" size={17} />}
            onClick={() => setEditorSchedule(null)}>新建计划任务</ConsoleButton>}
          <ConsoleButton loading={isFetching} leadingIcon={<ConsoleIcon name="refresh" size={16} />}
            onClick={() => { void refetch(); }}>刷新</ConsoleButton>
        </ActionBar>}
      />

      {!isAdmin && <div className="nfc-v2-scheduler-note" role="note">
        <ConsoleIcon name="info" size={17} />
        <span><strong>只读模式。</strong>普通成员可以查看计划任务与运行历史；
          创建、编辑、启停和 Run now 仅限管理员。</span>
      </div>}
      {isError && <div className="nfc-v2-scheduler-note is-warning" role="alert">
        <ConsoleIcon name="info" size={17} />
        <div><strong>计划任务加载失败</strong>
          <p>{getStructuredApiError(error).message || '无法读取 Scheduler'}</p>
          <ConsoleButton size="sm" onClick={() => { void refetch(); }}>重试</ConsoleButton>
        </div>
      </div>}

      <DataPanel title="Scheduler ledger"
        description="Missed run = skip；同一 schedule 有活跃任务时 skip_if_active；Run now 同样写入 durable run history。"
        action={<span className="nfc-panel-count">{data?.total ?? 0} schedules</span>}
        className="nfc-panel-flush" variant="dense">
        {!isError && isLoading && <div role="status" className="nfc-v2-scheduler-list-state">
          正在读取计划任务…
        </div>}
        {!isError && !isLoading && items.length === 0 &&
          <ConsoleEmpty title="暂无计划任务" description="可以由管理员创建定时任务。" />}
        {!isError && !isLoading && items.length > 0 && (
          <ResponsiveDataView
            desktop={<div className="nfc-v2-scheduler-table-scroll">
              <table className="nfc-v2-scheduler-table">
                <thead><tr>
                  <th scope="col">计划任务</th><th scope="col">状态</th>
                  <th scope="col">目标</th><th scope="col">时间</th>
                  <th scope="col">下次运行</th><th scope="col">上次触发</th>
                  <th scope="col">操作</th>
                </tr></thead>
                <tbody>{items.map(row => (
                  <tr key={row.id}>
                    <td><div className="nfc-scheduler-name-cell">
                      <strong>{row.name}</strong>
                      <span>#{row.id} · revision {row.revision}</span>
                    </div></td>
                    <td>{renderEnabled(row)}</td>
                    <td><div className="nfc-scheduler-target-cell">
                      <span>{TARGET_LABELS[row.target_type]}</span>
                      <code>{targetSummary(row)}</code>
                    </div></td>
                    <td><div className="nfc-scheduler-time-cell">
                      <code>{row.cron_expression}</code><span>{row.timezone}</span>
                    </div></td>
                    <td className="nfc-table-meta">{formatDateTime(row.next_scheduled_for_utc)}</td>
                    <td className="nfc-table-meta">{formatDateTime(row.last_scheduled_for_utc)}</td>
                    <td>{renderActions(row)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>}
            mobile={<div className="nfc-mobile-record-list nfc-scheduler-mobile-list">
              {items.map(row => (
                <article key={row.id} className="nfc-scheduler-mobile-card">
                  <div className="nfc-mobile-record-heading">
                    <div><strong className="nfc-mobile-record-title">{row.name}</strong>
                      <span className="nfc-scheduler-mobile-id">#{row.id} · r{row.revision}</span>
                    </div>
                    {renderEnabled(row)}
                  </div>
                  <div className="nfc-scheduler-mobile-primary">
                    <span>{TARGET_LABELS[row.target_type]}</span>
                    <b>{targetSummary(row)}</b>
                  </div>
                  <div className="nfc-scheduler-mobile-cron">
                    <code>{row.cron_expression}</code><span>{row.timezone}</span>
                  </div>
                  <div className="nfc-mobile-record-facts">
                    <span>下次 <b>{formatDateTime(row.next_scheduled_for_utc)}</b></span>
                    <span>上次 <b>{formatDateTime(row.last_scheduled_for_utc)}</b></span>
                  </div>
                  <div className="nfc-mobile-record-actions">{renderActions(row)}</div>
                </article>
              ))}
            </div>}
          />
        )}
      </DataPanel>
      <ConsoleConfirmDialog open={runTarget !== null} onOpenChange={closeRunConfirm}
        title={runTarget ? '立即运行计划任务 #' + runTarget.id + '？' : '立即运行计划任务？'}
        description="会走与定时触发相同的 target 校验和 overlap policy。已存在活动任务时按 skip_if_active 跳过；仅能执行当前固定目标的 Preview 或 Draft，工作流 Draft 不会自动 Freeze、Validate 或 Execute。"
        confirmText="确认 Run now" danger={false} busy={runBusy}
        disabled={!isAdmin || !runTarget} onConfirm={() => { void handleRunNow(); }} />
      <ScheduleEditorModal open={editorSchedule !== undefined}
        schedule={editorSchedule ?? null} onClose={() => setEditorSchedule(undefined)} />
      <ScheduleHistoryDrawer schedule={historySchedule} onClose={() => setHistorySchedule(null)} />
    </div>
  );
};
