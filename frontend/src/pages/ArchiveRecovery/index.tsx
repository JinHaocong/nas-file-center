import React, { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { archiveRecoveryApi, type RecoveryItem } from '../../api/archiveRecovery';
import { filesystemApi } from '../../api/filesystem';
import { tasksApi } from '../../api/tasks';
import { getStructuredApiError } from '../../api/errors';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { ActionBar } from '../../components/ui/ActionBar';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { DataPanel } from '../../components/ui/DataPanel';
import { PageHeader } from '../../components/ui/PageHeader';
import { useTitle } from '../../hooks/useTitle';

const EXTENSIONS = /\.(zip|7z|rar|tar|tgz|txz|tbz2|tar\.gz|tar\.bz2|tar\.xz)$/i;
const STATUS: Record<RecoveryItem['status'], string> = {
  integrity_passed: '完整性校验通过', format_validated: '格式验证通过',
  unverified: '未验证', incomplete: '不完整或损坏', unrecovered: '未恢复',
};

/** Archive selection, async worker status and per-file recovery evidence. */
export const ArchiveRecoveryPage: React.FC = () => {
  useTitle('压缩包检测与恢复');
  const navigate = useNavigate();
  const [folder, setFolder] = useState('/data');
  const [selected, setSelected] = useState('');
  const [password, setPassword] = useState('');
  const [deep, setDeep] = useState(true);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const [taskId, setTaskId] = useState<number | null>(null);

  const listing = useQuery({
    queryKey: ['archive-dir', folder, page, search],
    queryFn: () => filesystemApi.listDirectory(folder, false, page, 100, search),
    enabled: Boolean(folder), retry: false,
  });
  const check = useMutation({ mutationFn: archiveRecoveryApi.check });
  const start = useMutation({
    mutationFn: () => archiveRecoveryApi.start(selected, password, deep),
    onSuccess: data => {
      setTaskId(data.work_job_id);
      setPassword('');
    },
  });
  const job = useQuery({
    queryKey: ['archive-recovery-task', taskId],
    queryFn: () => tasksApi.getTaskDetail(taskId!),
    enabled: taskId !== null,
    refetchInterval: q => ['queued', 'running', 'cancel_requested'].includes(q.state.data?.status || '') ? 2000 : false,
  });
  const terminal = ['completed', 'failed', 'cancelled'].includes(job.data?.status || '');
  const report = useQuery({
    queryKey: ['archive-recovery-report', taskId],
    queryFn: () => archiveRecoveryApi.report(taskId!),
    enabled: taskId !== null && terminal,
    retry: false,
  });
  const cancel = useMutation({ mutationFn: () => tasksApi.cancelTask(taskId!) });
  const archiveRows = (listing.data?.items || []).filter(entry =>
    entry.type === 'file' && EXTENSIONS.test(entry.name));
  const shown = report.data?.items.filter(item => filter === 'all' || item.status === filter) || [];

  /** Download current evidence; no extra file is written beside the source archive. */
  const downloadReport = () => {
    if (!report.data) return;
    const file = new Blob([JSON.stringify(report.data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(file);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'archive-recovery-' + String(taskId) + '.json';
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="nfc-operations-page nfc-page-layout-ledger">
      <PageHeader eyebrow="File tools" title="压缩包检测与恢复"
        description="支持 TAR、ZIP、7z、RAR 的尽力恢复。原压缩包只读；结果存放同级唯一文件夹，自动清理中间文件。" />
      <DataPanel title="选择压缩包" description="从 NAS 目录中选择文件；仅展示已知扩展名，服务端会检查实际文件格式。">
        <label htmlFor="recovery-folder">压缩包所在目录</label>
        <div id="recovery-folder"><DirectoryPicker value={folder}
          onChange={value => { setFolder(typeof value === 'string' ? value : value[0] || ''); setPage(1); }} />
        </div>
        <ActionBar>
          <input aria-label="按文件名筛选" placeholder="搜索压缩包" value={search}
            onChange={event => { setSearch(event.target.value); setPage(1); }} />
          <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
            onClick={() => { void listing.refetch(); }}>刷新</ConsoleButton>
        </ActionBar>
        {listing.isError && <p role="alert">目录读取失败：{getStructuredApiError(listing.error).message}</p>}
        {listing.isLoading && <p>读取目录中…</p>}
        <div className="nfc-mobile-record-list">
          {archiveRows.map(entry => (
            <button key={entry.path} type="button"
              className={'nfc-mobile-record-card' + (selected === entry.path ? ' is-selected' : '')}
              aria-pressed={selected === entry.path}
              onClick={() => { setSelected(entry.path); check.reset(); start.reset(); setTaskId(null); setFilter('all'); }}>
              <ConsoleIcon name="archive" size={18} /> {entry.name}
              {selected === entry.path && <strong> ✓ 已选择</strong>}
            </button>
          ))}
        </div>
        <ActionBar>
          <ConsoleButton disabled={page <= 1} onClick={() => setPage(value => value - 1)}>上一页</ConsoleButton>
          <span>{page} / {Math.max(1, Math.ceil((listing.data?.total || 0) / 100))}</span>
          <ConsoleButton disabled={!listing.data?.has_more} onClick={() => setPage(value => value + 1)}>下一页</ConsoleButton>
        </ActionBar>
        <label htmlFor="recovery-source">或手动指定压缩包路径</label>
        <input id="recovery-source" value={selected} placeholder="/data/Download/photos.7z"
          onChange={event => { setSelected(event.target.value); check.reset(); start.reset(); setTaskId(null); }} />
      </DataPanel>
      <DataPanel title="检测与执行">
        <label htmlFor="recovery-password">密码（可留空，不保存到任务记录）</label>
        <input id="recovery-password" type="password" autoComplete="off" value={password}
          onChange={event => setPassword(event.target.value)} />
        <label><input type="checkbox" checked={deep} onChange={event => setDeep(event.target.checked)} />
          启用增强恢复（ZIP/TAR 扫描、内层 TAR、符合条件的 7z AES + LZMA2 重同步）</label>
        <p>7z AES/LZMA2 深度扫描需要正确密码、CRC 完好的 7z 文件头、可独立解码的 LZMA2 重置块及文件 CRC；不支持任意加密流重建和 RAR Solid 深度重同步。单个重置段最多处理 32 MiB；破损块头后的重新扫描窗口最多 8 MiB。整体文件产出限制为 10,000 个、4 GiB、30 分钟。</p>
        <ActionBar>
          <ConsoleButton disabled={!selected || check.isPending || Boolean(taskId)}
            loading={check.isPending} onClick={() => { void check.mutateAsync(selected).catch(() => {}); }}>检测</ConsoleButton>
          <ConsoleButton variant="primary" disabled={!selected || !check.data?.can_write || !check.data?.dependency_available || start.isPending || Boolean(taskId)}
            loading={start.isPending} onClick={() => { void start.mutateAsync().catch(() => {}); }}>开始恢复</ConsoleButton>
        </ActionBar>
        {check.isError && <p role="alert">检测失败：{getStructuredApiError(check.error).message}</p>}
        {start.isError && <p role="alert">启动失败：{getStructuredApiError(start.error).message}</p>}
        {check.data && <div>
          <p>实际格式：{check.data.format} · 原包大小：{check.data.source_bytes.toLocaleString()} 字节 · 当前空闲：{check.data.free_bytes.toLocaleString()} 字节</p>
          <p>写入允许：{check.data.can_write ? '是' : '否'} · 依赖：{check.data.dependency_available ? '可用' : '缺失'}</p>
          <p>增强策略：{check.data.deep_strategy}。{check.data.warning}</p>
        </div>}
      </DataPanel>
      {taskId !== null && <DataPanel title="恢复任务">
        <p>任务 #{taskId} · {job.data?.status || '排队中'} · {job.data?.progress.message || '等待 Worker'}</p>
        <ActionBar>
          <ConsoleButton onClick={() => navigate('/tasks?task=' + taskId)}>任务详情与日志</ConsoleButton>
          <ConsoleButton disabled={!['running', 'queued'].includes(job.data?.status || '') || cancel.isPending}
            onClick={() => { void cancel.mutateAsync().catch(() => {}); }}>取消任务</ConsoleButton>
        </ActionBar>
        {report.data && <>
          <p>最终状态：{report.data.recovery_status} · 原包条目总数：{report.data.known_total ?? '未知'}</p>
          <p>结果目录：<code>{report.data.output}</code></p>
          {report.data.aes_lzma2_deep && <p>
            AES/LZMA2 深度恢复：{report.data.aes_lzma2_deep.status} ·
            CRC 确认文件 {report.data.aes_lzma2_deep.recovered} 个 ·
            已验证重置点 {report.data.aes_lzma2_deep.reset_points ?? 0} 个。
            {report.data.aes_lzma2_deep.reason && <> 限制或失败原因：{report.data.aes_lzma2_deep.reason}</>}
          </p>}
          <p>完整性通过 {report.data.stats.integrity_passed || 0} · 格式通过 {report.data.stats.format_validated || 0} · 未验证 {report.data.stats.unverified || 0} · 不完整 {report.data.stats.incomplete || 0} · 未恢复 {report.data.stats.unrecovered || 0}</p>
          <ActionBar>
            <ConsoleButton onClick={downloadReport}>下载 JSON 报告</ConsoleButton>
            <select aria-label="恢复验证状态" value={filter} onChange={event => setFilter(event.target.value)}>
              <option value="all">全部</option>
              {Object.entries(STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </ActionBar>
          {report.data.warnings?.map(note => <p key={note}>{note}</p>)}
          <div className="nfc-mobile-record-list">
            {shown.slice(0, 500).map((item, index) => <div key={index} className="nfc-mobile-record-card">
              <strong>{item.name}</strong> · {STATUS[item.status]} {item.bytes !== undefined ? '· ' + item.bytes + ' bytes' : ''}
              {item.reason && <small> · {item.reason}</small>}
            </div>)}
          </div>
          {shown.length > 500 && <p>仅显示前 500 项；下载 JSON 报告查看全部条目。</p>}
        </>}
      </DataPanel>}
    </div>
  );
};