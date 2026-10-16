import React, { useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';

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
const REASONS: Record<string, string> = {
  NOT_EXTRACTED_FROM_VERIFIED_HEADER: '压缩包目录有此文件，但读取器未能提取；不代表文件一定损坏',
  ARCHIVE_DATA_ERROR: '解码时发生数据错误',
  TRUNCATED: '数据少于目录声明的长度',
  FORMAT_DECODE_FAILED: '图片完整解码失败',
  CRC_MISMATCH: 'CRC 校验不匹配',
  OUTPUT_CONFLICT: '输出路径冲突，未覆盖已有文件',
  UNSAFE_PATH: '文件路径不安全，已跳过',
  PASSWORD_OR_DATA_ERROR: '密码或压缩数据异常，无法单独判断',
  STANDARD_DECODER_FAILED: '标准读取器未能解码',
};
const reasonText = (reason?: string): string =>
  reason ? (REASONS[reason] || reason) : '原因暂未明确';

/** Archive selection, async worker status and per-file recovery evidence. */
export const ArchiveRecoveryPage: React.FC = () => {
  useTitle('压缩包检测与恢复');
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  // Track the WorkJob by a non-secret URL task ID so refresh/navigation cannot
  // silently detach a still-running recovery from the visible task monitor.
  const rawTaskId = searchParams.get('task') || '';
  const parsedTaskId = Number(rawTaskId);
  const taskId = /^[1-9][0-9]*$/.test(rawTaskId) && Number.isSafeInteger(parsedTaskId)
    ? parsedTaskId : null;
  const sourceInputRef = useRef<HTMLInputElement>(null);
  const [folder, setFolder] = useState('/data');
  const [selected, setSelected] = useState('');
  const [password, setPassword] = useState('');
  const [deep, setDeep] = useState(true);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');

  const listing = useQuery({
    queryKey: ['archive-dir', folder, page, search],
    queryFn: () => filesystemApi.listDirectory(folder, false, page, 100, search),
    enabled: Boolean(folder), retry: false,
  });
  const check = useMutation({ mutationFn: archiveRecoveryApi.check });
  const start = useMutation({
    mutationFn: () => archiveRecoveryApi.start(selected, password, deep),
    onSuccess: data => {
      setSearchParams(current => {
        const next = new URLSearchParams(current);
        next.set('task', String(data.work_job_id));
        return next;
      }, { replace: true });
      setPassword('');
    },
  });
  const job = useQuery({
    queryKey: ['archive-recovery-task', taskId],
    queryFn: () => tasksApi.getTaskDetail(taskId!),
    enabled: taskId !== null,
    retry: false,
    refetchInterval: q => ['queued', 'running', 'cancel_requested'].includes(q.state.data?.status || '') ? 2000 : false,
  });
  // A manually supplied task link must never offer archive cancellation or
  // recovery-report actions against another WorkJob kind.
  const recoveryJobMatches = job.data?.job_type === 'archive-recovery';
  const terminal = recoveryJobMatches &&
    ['completed', 'failed', 'cancelled'].includes(job.data?.status || '');
  const report = useQuery({
    queryKey: ['archive-recovery-report', taskId],
    queryFn: () => archiveRecoveryApi.report(taskId!),
    enabled: taskId !== null && terminal,
    retry: false,
  });
  const cancel = useMutation({ mutationFn: () => tasksApi.cancelTask(taskId!) });

  // Retire the monitor without cancelling the Worker. Failed/unrelated deep
  // links can be dismissed only explicitly; valid active jobs stay tracked.
  const clearTaskMonitor = () => {
    setSearchParams(current => {
      const next = new URLSearchParams(current);
      next.delete('task');
      return next;
    }, { replace: true });
    setSelected('');
    setPassword('');
    setFilter('all');
    check.reset();
    start.reset();
    cancel.reset();
    // The clicked action unmounts on dismissal: return keyboard focus to
    // the surviving source input instead of losing it to document.body.
    sourceInputRef.current?.focus();
  };

  const startAnotherRecovery = () => {
    if (!terminal || taskId === null) return;
    clearTaskMonitor();
  };

  const recoverInvalidTaskLink = () => {
    if (taskId === null || (!job.isError && (!job.data || recoveryJobMatches))) return;
    clearTaskMonitor();
  };
  const archiveRows = (listing.data?.items || []).filter(entry =>
    entry.type === 'file' && EXTENSIONS.test(entry.name));
  const canonicalRows = report.data?.file_outcomes || report.data?.items || [];
  const shown = canonicalRows.filter(item => filter === 'all' ||
    (filter === 'missing' ? ['incomplete', 'unrecovered'].includes(item.status) : item.status === filter));
  const missingFiles = report.data?.missing_files || [];
  // Older APIs and missing tmpfs must fail closed for password-bearing starts.
  // A preflight authorizes only the exact selected source, never a stale path.
  const checkedSourceMatchesSelected = Boolean(selected) && check.data?.source === selected;
  const passwordChannelBlocked = Boolean(password) &&
    check.data?.password_channel_available !== true;

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
    <div className="nfc-operations-page nfc-page-layout-ledger nfc-archive-recovery-page">
      <PageHeader eyebrow="File tools" title="压缩包检测与恢复"
        description="支持 TAR、ZIP、7z、RAR 的尽力恢复。原压缩包只读；结果存放同级唯一文件夹，自动清理中间文件。" />
      <div className="nfc-archive-recovery-intro" aria-label="恢复功能安全特性"><span>ZIP / TAR / 7z / RAR</span><span>原始文件只读</span><span>恢复结果独立保存</span></div>
      <div className="nfc-archive-recovery-layout">
      <DataPanel className="nfc-archive-recovery-select-panel" title="01 · 选择压缩包" description="从 NAS 目录中选择文件；仅展示已知扩展名，服务端会检查实际文件格式。">
        <div className="nfc-archive-recovery-field-label" id="recovery-folder-label">压缩包所在目录</div>
        <div id="recovery-folder" role="group" aria-labelledby="recovery-folder-label"><DirectoryPicker value={folder}
          onChange={value => {
            const next = typeof value === 'string' ? value : value[0] || '';
            if (next === folder) return;
            setFolder(next);
            setPage(1);
            // A folder switch must invalidate any prior archive and its preflight.
            setSelected('');
            setPassword('');
            check.reset();
            start.reset();
          }} />
        </div>
        <div className="nfc-archive-recovery-filter-row"><ActionBar>
          <input aria-label="按文件名筛选" placeholder="搜索压缩包" value={search}
            onChange={event => { setSearch(event.target.value); setPage(1); }} />
          <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
            onClick={() => { void listing.refetch(); }}>刷新</ConsoleButton>
        </ActionBar></div>
        {listing.isError && <p role="alert">目录读取失败：{getStructuredApiError(listing.error).message}</p>}
        {listing.isLoading && <p>读取目录中…</p>}
        <div className="nfc-mobile-record-list nfc-archive-recovery-file-list" aria-label="可恢复的压缩包文件">
          {!listing.isLoading && !listing.isError && archiveRows.length === 0 && <p className="nfc-archive-recovery-empty">当前目录没有匹配的压缩包，可以切换目录或手动输入文件路径。</p>}
          {archiveRows.map(entry => (
            <button key={entry.path} type="button"
              className={'nfc-mobile-record-card nfc-archive-recovery-file' + (selected === entry.path ? ' is-selected' : '')}
              aria-pressed={selected === entry.path}
              onClick={() => {
                setSelected(entry.path);
                setPassword('');
                check.reset();
                start.reset();
                // Keep the running/completed WorkJob visible even when browsing.
              }}>
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
        <label className="nfc-archive-recovery-field-label" htmlFor="recovery-source">或手动指定压缩包路径</label>
        <input id="recovery-source" ref={sourceInputRef} value={selected} placeholder="/data/Download/photos.7z"
          onChange={event => {
            setSelected(event.target.value);
            setPassword('');
            check.reset();
            start.reset();
            // Only the explicit terminal action may dismiss a WorkJob monitor.
          }} />
      </DataPanel>
      <DataPanel className="nfc-archive-recovery-run-panel" title="02 · 检测与恢复" description="先检测文件与环境，再决定是否启动恢复任务。">
        <label className="nfc-archive-recovery-field-label" htmlFor="recovery-password">密码（可留空，不保存到任务记录）</label>
        <input id="recovery-password" type="password" autoComplete="off" value={password}
          onChange={event => setPassword(event.target.value)} />
        <label className="nfc-archive-recovery-toggle"><input type="checkbox" checked={deep} onChange={event => setDeep(event.target.checked)} />
          启用增强恢复（ZIP/TAR 扫描、内层 TAR、符合条件的 7z AES + LZMA2 重同步）</label>
        <p className="nfc-archive-recovery-help">7z AES/LZMA2 深度扫描需要正确密码、CRC 完好的 7z 文件头、可独立解码的 LZMA2 重置块及文件 CRC；不支持任意加密流重建和 RAR Solid 深度重同步。单个重置段最多处理 32 MiB；破损块头后的重新扫描窗口最多 8 MiB。整体文件产出限制为 10,000 个、4 GiB、30 分钟。</p>
        <ActionBar>
          <ConsoleButton disabled={!selected || check.isPending || Boolean(taskId)}
            loading={check.isPending} onClick={() => { void check.mutateAsync(selected).catch(() => {}); }}>检测</ConsoleButton>
          <ConsoleButton variant="primary" disabled={!checkedSourceMatchesSelected || !check.data?.can_write || !check.data?.dependency_available || passwordChannelBlocked || start.isPending || Boolean(taskId)}
            loading={start.isPending} onClick={() => { void start.mutateAsync().catch(() => {}); }}>开始恢复</ConsoleButton>
        </ActionBar>
        {passwordChannelBlocked && checkedSourceMatchesSelected && <p className="nfc-archive-recovery-warning" role="alert">
          密码恢复暂不可启动：API 未确认共享 tmpfs 密码通道已就绪。请由部署管理员同时为 API 与 Worker
          挂载同一个 /run/nfc-recovery-secrets tmpfs（Komodo 可使用
          compose.komodo.archive-recovery-secrets.yaml），部署后重新点击“检测”。
          请勿将密码放入普通磁盘卷、数据库或环境变量。
        </p>}
        {check.isError && <p role="alert">检测失败：{getStructuredApiError(check.error).message}</p>}
        {start.isError && <p role="alert">启动失败：{getStructuredApiError(start.error).message}</p>}
        {checkedSourceMatchesSelected && check.data && <div className="nfc-archive-recovery-check-result" role="status">
          <p>实际格式：{check.data.format} · 原包大小：{check.data.source_bytes.toLocaleString()} 字节 · 当前空闲：{check.data.free_bytes.toLocaleString()} 字节</p>
          <p>写入允许：{check.data.can_write ? '是' : '否'} · 依赖：{check.data.dependency_available ? '可用' : '缺失'}</p>
          <p>密码通道（API 侧）：{check.data.password_channel_available === true ? 'tmpfs 已检测到（还需确认 Worker 共享挂载）' : '未就绪；带密码的恢复不可启动'}</p>
          <p>增强策略：{check.data.deep_strategy}。{check.data.warning}</p>
        </div>}
      </DataPanel>
      </div>
      {taskId !== null && <DataPanel className="nfc-archive-recovery-task-panel" title="03 · 恢复任务" description="任务状态与恢复证据将在这里更新。">
        <p className="nfc-archive-recovery-task-status" role="status">任务 #{taskId} · {job.isError ? '状态暂不可用' : (job.data?.status || '排队中')} · {job.data?.progress.message || '等待 Worker'}</p>
        <p className="nfc-archive-recovery-help">切换待恢复文件或目录不会取消正在运行的任务。任务结束后，请通过“开始下一次恢复”明确结束本次跟踪；任务记录仍保留在任务中心。</p>
        {job.data && !recoveryJobMatches && <p role="alert">任务编号对应的不是压缩包恢复任务。此页面不会提供取消、报告或下一次恢复操作；请前往任务中心查看，或返回不带任务编号的压缩包恢复页面。</p>}
        {job.isError && <p role="alert">任务状态读取失败：{getStructuredApiError(job.error).message}。可重试读取任务状态，或返回重新选择压缩包。</p>}
        {cancel.isError && <p role="alert">取消请求失败：{getStructuredApiError(cancel.error).message}</p>}
        <ActionBar>
          <ConsoleButton onClick={() => navigate('/tasks?task=' + taskId)}>任务详情与日志</ConsoleButton>
          {job.isError && <ConsoleButton disabled={job.isFetching} loading={job.isFetching}
            onClick={() => { void job.refetch(); }}>重试读取任务状态</ConsoleButton>}
          {(job.isError || (job.data && !recoveryJobMatches)) &&
            <ConsoleButton onClick={recoverInvalidTaskLink}>返回选择压缩包</ConsoleButton>}
          <ConsoleButton disabled={!recoveryJobMatches || !['running', 'queued'].includes(job.data?.status || '') || cancel.isPending}
            onClick={() => { void cancel.mutateAsync().catch(() => {}); }}>取消任务</ConsoleButton>
          {terminal && <ConsoleButton onClick={startAnotherRecovery}>开始下一次恢复</ConsoleButton>}
        </ActionBar>
        {report.data && <>
          <p>最终状态：{report.data.recovery_status} · 原包文件总数：{report.data.known_total ?? '无法确定'}</p>
          {report.data.inventory && <>
            <p className="nfc-archive-recovery-stats">
              目录清单：{report.data.inventory.status === 'verified' ? '已通过压缩包头 CRC 验证'
                : report.data.inventory.status === 'listed' ? '已读取（目录本身不等于文件 CRC 验证）'
                : '无法完整读取'}
              {report.data.inventory.declared_files !== null
                ? <> · 列出 {report.data.inventory.declared_files} 个文件
                  · 已恢复 {report.data.inventory.recovered_files} 个
                  · 未成功恢复 {report.data.inventory.unrecovered_files} 个</>
                : <> · 已观察到恢复 {report.data.inventory.recovered_files} 个；
                  其他未扫描到的文件数量未知</>}
            </p>
            {report.data.inventory.status === 'unavailable' &&
              <p className="nfc-archive-recovery-warning" role="status">
                当前无法获得完整原包目录，报告只能列出已发现的条目；无法推断未扫描到的文件名。
                {report.data.inventory.reason && <> 原因：{report.data.inventory.reason}</>}
              </p>}
          </>}
          {missingFiles.length > 0 && <section className="nfc-archive-recovery-missing" aria-label="恢复失败或未恢复的文件">
            <h3>未成功恢复的文件（{missingFiles.length}）</h3>
            <p className="nfc-archive-recovery-help">以下是目录中可识别、但没有成功产出的文件；未恢复不等于文件已经损坏。请保留原压缩包。</p>
            <div className="nfc-mobile-record-list">
              {missingFiles.slice(0, 100).map((item, index) => <div className="nfc-mobile-record-card" key={index}>
                <strong>{item.name}</strong> · {STATUS[item.status]}
                <small> · {reasonText(item.reason)}</small>
              </div>)}
            </div>
            {missingFiles.length > 100 && <p>仅展示前 100 个，下载 JSON 报告查看全部。</p>}
          </section>}
          <p className="nfc-archive-recovery-output">结果目录：<code>{report.data.output}</code></p>
          {report.data.aes_lzma2_deep && <p>
            AES/LZMA2 深度恢复：{report.data.aes_lzma2_deep.status} ·
            CRC 确认文件 {report.data.aes_lzma2_deep.recovered} 个 ·
            已验证重置点 {report.data.aes_lzma2_deep.reset_points ?? 0} 个。
            {report.data.aes_lzma2_deep.reason && <> 限制或失败原因：{report.data.aes_lzma2_deep.reason}</>}
          </p>}
          <p className="nfc-archive-recovery-stats">完整性通过 {report.data.stats.integrity_passed || 0} · 格式通过 {report.data.stats.format_validated || 0} · 未验证 {report.data.stats.unverified || 0} · 不完整 {report.data.stats.incomplete || 0} · 未恢复 {report.data.stats.unrecovered || 0}</p>
          <ActionBar>
            <ConsoleButton onClick={downloadReport}>下载 JSON 报告</ConsoleButton>
            <select aria-label="恢复验证状态" value={filter} onChange={event => setFilter(event.target.value)}>
              <option value="all">全部</option>
              <option value="missing">仅看未成功恢复</option>
              {Object.entries(STATUS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
            </select>
          </ActionBar>
          {report.data.warnings?.map(note => <p className="nfc-archive-recovery-warning" key={note}>{note}</p>)}
          <div className="nfc-mobile-record-list nfc-archive-recovery-results" aria-label="恢复结果明细">
            {shown.slice(0, 500).map((item, index) => <div key={index} className="nfc-mobile-record-card nfc-archive-recovery-result">
              <strong>{item.name}</strong> · {STATUS[item.status]} {item.bytes !== undefined ? '· ' + item.bytes + ' bytes' : ''}
              {item.reason && <small> · {reasonText(item.reason)}</small>}
            </div>)}
          </div>
          {shown.length > 500 && <p>仅显示前 500 项；下载 JSON 报告查看全部条目。</p>}
        </>}
      </DataPanel>}
    </div>
  );
};