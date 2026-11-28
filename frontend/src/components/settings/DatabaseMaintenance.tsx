import { useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { ActionBar } from '../ui/ActionBar';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../ui/ConsoleConfirmDialog';
import { ResponsiveDescriptions } from '../ui/ResponsiveDescriptions';

import { databaseMaintenanceApi, type ArchiveKind } from '../../api/databaseMaintenance';
import { getStructuredApiError } from '../../api/errors';

import { formatBytes } from '../../utils/format';

const archiveNames = { task_events: '整理明细', operation_journal: '操作流水' } as const;
const number = (count: number) => count.toLocaleString('zh-CN');

/** Preview physical database usage and let an administrator archive one batch. */
export function DatabaseMaintenance() {
  const preview = useQuery({
    queryKey: ['settings', 'database-maintenance'],
    queryFn: databaseMaintenanceApi.preview,
    retry: false,
  });
  const archive = useMutation({ mutationFn: databaseMaintenanceApi.archive });
  const [confirmation, setConfirmation] = useState<ArchiveKind | null>(null);
  const [message, setMessage] = useState('');
  const running = useRef(false);

  /** Fold a confirmed archive into the refreshed preview and surface its actual result. */
  async function applyArchive() {
    if (confirmation === null || running.current) return;
    running.current = true;
    setMessage('');
    try {
      const result = await archive.mutateAsync(confirmation);
      setMessage(result.rows ? `已归档 ${number(result.rows)} 条记录。` : '当前没有符合条件的记录。');
    } catch {
      // The mutation error is displayed below the controls after the dialog closes.
    } finally {
      setConfirmation(null);
      await preview.refetch();
      running.current = false;
    }
  }

  const data = preview.data;
  const disabled = preview.isFetching || preview.isError || archive.isPending || confirmation !== null;
  return (
    <section className="nfc-settings-subpanel nfc-settings-policy-card" aria-labelledby="database-maintenance-title">
      <div className="nfc-settings-subpanel-header">
        <div><strong id="database-maintenance-title">数据库维护</strong></div>
        <ConsoleButton size="sm" loading={preview.isFetching}
          onClick={() => { void preview.refetch(); }}>刷新预览</ConsoleButton>
      </div>

      {preview.isError && <p className="nfc-settings-help" role="alert">
        {getStructuredApiError(preview.error).message || '无法读取数据库维护预览。'}
      </p>}
      {data && <>
        <ResponsiveDescriptions items={[
          { label: '主库', value: formatBytes(data.database.database_bytes) },
          { label: 'WAL', value: formatBytes(data.database.wal_bytes) },
          { label: '主库空闲页', value: formatBytes(data.database.reusable_bytes) },
          { label: '预计可回收', value: formatBytes(data.database.estimated_reclaimable_bytes), emphasis: true },
          { label: 'WAL 重置后保留上限', value: formatBytes(data.database.wal_retained_limit_bytes) },
          { label: '正在运行或取消中的任务', value: number(data.database.active_jobs) },
          { label: '操作流水定期归档', value: data.policy.automatic ? '已启用' : '未启用' },
          { label: `可归档整理明细（保留 ${data.policy.task_event_retention_days} 天）`,
            value: `${number(data.task_events.rows)} 条，来自 ${number(data.task_events.jobs)} 个任务` },
          { label: `可归档操作流水（保留 ${data.policy.operation_journal_retention_days} 天）`,
            value: `${number(data.operation_journal.rows)} 条` },
        ]} />
        <ActionBar compact>
          <ConsoleButton size="sm" disabled={disabled || !data.task_events.rows}
            onClick={() => setConfirmation('task_events')}>归档一批整理明细</ConsoleButton>
          <ConsoleButton size="sm" disabled={disabled || !data.operation_journal.rows}
            onClick={() => setConfirmation('operation_journal')}>归档一批操作流水</ConsoleButton>
        </ActionBar>
      </>}
      {message && <p className="nfc-settings-help" role="status">{message}</p>}
      {archive.isError && <p className="nfc-settings-help" role="alert">
        {getStructuredApiError(archive.error).message || '归档失败，请稍后重试。'}
      </p>}
      <p className="nfc-settings-help">
        已删除任务的普通日志在后台清理。Worker 空闲时分批回收主库空闲页。
        手动归档文件保存在配置目录的 <code>history-archives</code>。
      </p>
      <ConsoleConfirmDialog
        open={confirmation !== null}
        onOpenChange={open => { if (!open) setConfirmation(null); }}
        title={confirmation ? `归档一批${archiveNames[confirmation]}` : '确认归档'}
        description="系统会先保存可校验的压缩归档，再移出符合条件的明细，保留需要恢复的记录。"
        confirmText="确认归档"
        busy={archive.isPending}
        danger={false}
        onConfirm={() => { void applyArchive(); }}
      />
    </section>
  );
}
