import { useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';

import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../ui/ConsoleConfirmDialog';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { DataPanel } from '../ui/DataPanel';
import { CodePath } from '../ui/CodePath';
import { SettingsGroup, SettingsRow, SettingsStatus } from './SettingsRows';

import { databaseMaintenanceApi, type ArchiveKind } from '../../api/databaseMaintenance';
import { getStructuredApiError } from '../../api/errors';

import { formatBytes } from '../../utils/format';

const archiveNames = { task_events: '整理明细', operation_journal: '操作流水' } as const;
const number = (count: number) => count.toLocaleString('zh-CN');
/** 数据库占用以 1024 为进位单位，标签明确显示为二进制单位。 */
const databaseSize = (bytes: number) => formatBytes(bytes).replace(/[KMGTPE]B$/, unit => unit[0] + 'iB');

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
  const usage = data ? [
    ['主库', data.database.database_bytes], ['WAL', data.database.wal_bytes],
    ['主库空闲页', data.database.reusable_bytes], ['预计可回收', data.database.estimated_reclaimable_bytes],
  ] as const : [];
  return (
    <DataPanel id="database" title="数据库维护" className="nfc-settings-panel-database"
      description="查看数据库占用、可回收空间和历史记录归档。"
      action={<ConsoleButton size="sm" loading={preview.isFetching} leadingIcon={<ConsoleIcon name="refresh" size={15} />}
        onClick={() => { void preview.refetch(); }}>刷新预览</ConsoleButton>}>
      <div className="nfc-settings-groups">
        {preview.isPending && <p className="nfc-settings-inline-note" role="status">正在读取数据库占用…</p>}
        {preview.isError && <p className="nfc-v2-settings-error" role="alert">
          {getStructuredApiError(preview.error).message || '无法读取数据库维护预览。'}
        </p>}
        {data && <>
          <dl className="nfc-settings-database-metrics" aria-label="数据库占用">
            {usage.map(([label, bytes]) => <div key={label}><dt>{label}</dt><dd>{databaseSize(bytes)}</dd></div>)}
          </dl>
          <SettingsGroup title="历史归档">
            <SettingsRow label="智能整理明细" description={'保留 ' + data.policy.task_event_retention_days +
              ' 天 · ' + number(data.task_events.jobs) + ' 个任务可归档。'}>
              <SettingsStatus>{number(data.task_events.rows)} 条</SettingsStatus>
              <ConsoleButton size="sm" aria-label="归档一批整理明细" disabled={disabled || !data.task_events.rows}
                leadingIcon={<ConsoleIcon name="archive" size={15} />} onClick={() => setConfirmation('task_events')}>归档一批</ConsoleButton>
            </SettingsRow>
            <SettingsRow label="操作流水" description={'保留 ' + data.policy.operation_journal_retention_days +
              ' 天 · 定期归档' + (data.policy.automatic ? '已启用。' : '已关闭。')}>
              <SettingsStatus>{number(data.operation_journal.rows)} 条</SettingsStatus>
              <ConsoleButton size="sm" aria-label="归档一批操作流水" disabled={disabled || !data.operation_journal.rows}
                leadingIcon={<ConsoleIcon name="archive" size={15} />} onClick={() => setConfirmation('operation_journal')}>归档一批</ConsoleButton>
            </SettingsRow>
            <SettingsRow label="归档文件目录" description="用于保留可校验的历史明细。">
              <CodePath value="history-archives/" copy={false} />
            </SettingsRow>
          </SettingsGroup>
          <SettingsGroup title="空间回收">
            <SettingsRow label="WAL 重置后保留上限"><SettingsStatus>{databaseSize(data.database.wal_retained_limit_bytes)}</SettingsStatus></SettingsRow>
            <SettingsRow label="当前任务" description="Worker 空闲时分批回收数据库空闲页。">
              <SettingsStatus tone={data.database.active_jobs > 0 ? 'neutral' : 'success'}>
                {data.database.active_jobs > 0 ? number(data.database.active_jobs) + ' 项任务运行或取消中' : '当前空闲'}
              </SettingsStatus>
            </SettingsRow>
          </SettingsGroup>
        </>}
        {message && <p className="nfc-settings-inline-note" role="status">{message}</p>}
        {archive.isError && <p className="nfc-v2-settings-error" role="alert">
          {getStructuredApiError(archive.error).message || '归档失败，请稍后重试。'}
        </p>}
      </div>
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
    </DataPanel>
  );
}
