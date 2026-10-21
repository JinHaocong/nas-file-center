import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useTitle } from '../../hooks/useTitle';
import { downloadVerificationApi } from '../../api/downloadVerification';
import type { DownloadVerificationRun } from '../../api/downloadVerification';
import { getStructuredApiError } from '../../api/errors';
import { RemoteDirectoryPicker } from './RemoteDirectoryPicker';

const verdict: Record<string, string> = {
  METADATA_IDENTICAL: '快速清单一致（未校验内容）',
  VERIFIED_IDENTICAL: '完整 SHA256 一致',
  DIFFERENT: '发现差异',
  INCOMPLETE: '未完成 / 无法验证',
  STALE: '校验期间目录发生变化',
  METADATA_MATCH: '文件名及大小匹配',
  VERIFIED_MATCH: 'SHA256 一致',
  HASH_MISMATCH: 'SHA256 不一致',
  ONLY_LOCAL: '仅 NAS 存在',
  ONLY_REMOTE: '仅来源存在',
  SIZE_MISMATCH: '大小不同',
  TYPE_MISMATCH: '类型不同',
  DIRECTORY_MATCH: '目录一致',
};
const formatBytes = (n: number | null) =>
  n === null ? '—' : n >= 1073741824 ? (n / 1073741824).toFixed(2) + ' GiB'
    : n >= 1048576 ? (n / 1048576).toFixed(2) + ' MiB'
      : n >= 1024 ? (n / 1024).toFixed(1) + ' KiB' : n + ' B';
const formatError = (error: unknown) => getStructuredApiError(error).message || '操作失败';
const displayJob = (state: string) =>
  ({ completed: '已完成', failed: '执行失败', cancelled: '已取消',
     queued: '排队中', running: '执行中', paused: '已暂停',
     cancel_requested: '取消中', unknown: '任务记录不存在' } as Record<string, string>)[state] || state;

export const DownloadVerificationPage: React.FC = () => {
  useTitle('下载完整性校验');
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [remoteRoot, setRemoteRoot] = useState('');
  const [localRoot, setLocalRoot] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);
  const opener = useRef<HTMLButtonElement | null>(null);
  const [mode, setMode] = useState<'metadata' | 'strict_sha256'>('metadata');
  const [selected, setSelected] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [historyPage, setHistoryPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState<DownloadVerificationRun | null>(null);
  const [selectedReportIds, setSelectedReportIds] = useState<number[]>([]);
  const [bulkDeleteTarget, setBulkDeleteTarget] = useState<number[] | null>(null);
  const selectAllRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState('');
  const [feedback, setFeedback] = useState('');

  const sources = useQuery({
    queryKey: ['download-verify-sources'], queryFn: downloadVerificationApi.sources,
  });
  const sourceList = sources.data?.items || [];
  const selectedSource = sourceList.find(source => source.id === sourceId) || sourceList[0];
  const chosenId = selectedSource?.id ?? null;
  const runs = useQuery({
    queryKey: ['download-verify-runs', historyPage],
    queryFn: () => downloadVerificationApi.list(historyPage),
    refetchInterval: 5000,
  });
  const details = useQuery({
    queryKey: ['download-verify-items', selected, page],
    queryFn: () => downloadVerificationApi.items(selected!, page),
    enabled: selected !== null,
    refetchInterval: selected === null ? false : 5000,
  });
  const start = useMutation({
    mutationFn: () => downloadVerificationApi.start(remoteRoot, localRoot, chosenId!, mode),
    onSuccess: run => {
      setError('');
      setFeedback('已提交只读校验任务 #' + run.id + '，可在历史记录中查看进度');
      setSelected(run.id);
      setPage(1);
      setHistoryPage(1);
      void qc.invalidateQueries({ queryKey: ['download-verify-runs'] });
    },
    onError: err => setError(formatError(err)),
  });
  const remove = useMutation({
    mutationFn: (id: number) => downloadVerificationApi.removeReport(id),
    onSuccess: (_, id) => {
      setDeleteTarget(null);
      setError('');
      setFeedback('已删除校验报告 #' + id + '，任务中心记录及 NAS 文件不受影响');
      if (selected === id) setSelected(null);
      setSelectedReportIds(ids => ids.filter(item => item !== id));
      void qc.invalidateQueries({ queryKey: ['download-verify-runs'] });
      if ((runs.data?.items.length || 0) === 1 && historyPage > 1) setHistoryPage(x => x - 1);
    },
    onError: err => {
      setDeleteTarget(null);
      setError(formatError(err));
    },
  });
  const bulkRemove = useMutation({
    mutationFn: (ids: number[]) => downloadVerificationApi.bulkDeleteReports(ids),
    onSuccess: (result, ids) => {
      setBulkDeleteTarget(null);
      setSelectedReportIds([]);
      setError('');
      setFeedback('已批量删除 ' + result.deleted + ' 份校验报告，NAS 文件和任务中心记录不受影响');
      if (selected !== null && ids.includes(selected)) setSelected(null);
      void qc.invalidateQueries({ queryKey: ['download-verify-runs'] });
      if (totalRuns - result.deleted <= (historyPage - 1) * 50 && historyPage > 1) {
        setHistoryPage(p => p - 1);
      }
    },
    onError: err => {
      setBulkDeleteTarget(null);
      setError(formatError(err));
      void qc.invalidateQueries({ queryKey: ['download-verify-runs'] });
    },
  });
  const changeSource = (id: number) => {
    setSourceId(id);
    setRemoteRoot('');
    setPickerOpen(false);
    setError('');
  };
  const totalRuns = runs.data?.total ?? 0;
  const lastHistoryPage = Math.max(1, Math.ceil(totalRuns / 50));
  const deletableRunIds = (runs.data?.items || []).filter(run => run.can_delete).map(run => run.id);
  const selectedDeletableIds = selectedReportIds.filter(id => deletableRunIds.includes(id));
  const allDeletableSelected = deletableRunIds.length > 0 &&
    selectedDeletableIds.length === deletableRunIds.length;
  useEffect(() => { setSelectedReportIds([]); }, [historyPage]);
  useEffect(() => {
    if (selectAllRef.current) {
      selectAllRef.current.indeterminate = selectedDeletableIds.length > 0 && !allDeletableSelected;
    }
  });

  return (
    <div className="nfc-operations-page nfc-page-layout-workbench nfc-download-verify nfc-download-verify-page">
      <PageHeader title="下载完整性校验"
        description="核对 AList / OpenList 云端清单与 NAS 下载目录。默认只比较路径、文件名和文件大小，不会再次下载文件。"
        actions={<ConsoleButton leadingIcon={<ConsoleIcon name="settings" size={16} />}
          onClick={() => navigate('/download-sources')}>管理来源</ConsoleButton>} />

      <DataPanel title="新建下载核对" description="选择一个来源、对应的两个目录和比较方式，整个过程只读。">
        <div className="nfc-dv-workspace">
          <div className="nfc-dv-field nfc-dv-source">
            <label htmlFor="nfc-dv-source">1 · 选择来源</label>
            <div className="nfc-dv-control-row">
              <select id="nfc-dv-source" value={chosenId ?? ''}
                onChange={event => changeSource(Number(event.target.value))}
                disabled={sourceList.length === 0}>
                {sourceList.length === 0 && <option value="">尚未添加来源</option>}
                {sourceList.map(source => <option key={source.id} value={source.id}>
                  {source.name} · {source.provider === 'alist' ? 'AList' : 'OpenList'}
                </option>)}
              </select>
            </div>
            <small>{selectedSource ? selectedSource.base_url : '请先在「管理来源」中添加 AList / OpenList 服务'}</small>
            {sources.isError && <span role="alert" className="nfc-dv-error">读取来源配置失败</span>}
            {sourceList.length === 0 && <ConsoleButton size="sm" variant="secondary"
              onClick={() => navigate('/download-sources')}
              leadingIcon={<ConsoleIcon name="plus" size={14} />}>新增来源</ConsoleButton>}
          </div>

          <div className="nfc-dv-pair">
            <div className="nfc-dv-pair-card">
              <div className="nfc-dv-pair-heading">
                <ConsoleIcon name="folder-open" size={17} />
                <span>2 · 来源文件夹</span>
              </div>
              <div className="nfc-dv-field nfc-download-verify-field">
                <label htmlFor="nfc-dv-remote-path">远端目录</label>
                <div className="nfc-dv-control-row">
                  <input id="nfc-dv-remote-path" aria-label="云端相对目录" value={remoteRoot}
                    onChange={event => setRemoteRoot(event.target.value)}
                    placeholder="根目录 /" disabled={chosenId === null} />
                  <ConsoleButton disabled={chosenId === null}
                    leadingIcon={<ConsoleIcon name="folder-open" size={16} />}
                    onClick={event => { opener.current = event.currentTarget; setPickerOpen(true); }}>
                    选择目录
                  </ConsoleButton>
                </div>
                <small>从已挂载的云端目录中选择；留空表示来源根目录</small>
              </div>
            </div>
            <div className="nfc-dv-pair-card">
              <div className="nfc-dv-pair-heading">
                <ConsoleIcon name="hard-drive" size={17} />
                <span>3 · NAS 下载文件夹</span>
              </div>
              <div className="nfc-dv-field">
                <label>本地目录</label>
                <DirectoryPicker value={localRoot} onChange={value =>
                  setLocalRoot(typeof value === 'string' ? value : value[0] || '')}
                  placeholder="请选择 NAS 已下载文件夹" />
                <small>以两个选择的文件夹为根，逐级比较内部相对路径</small>
              </div>
            </div>
          </div>

          <fieldset className="nfc-dv-modes">
            <legend>4 · 比较方式</legend>
            <label className={mode === 'metadata' ? 'is-selected' : ''}>
              <input type="radio" name="verify-mode" checked={mode === 'metadata'}
                onChange={() => setMode('metadata')} />
              <span><strong>快速核对 · 推荐</strong>
                <small>路径、文件名、对象类型、大小及空目录；无需读取文件内容</small></span>
            </label>
            <label className={mode === 'strict_sha256' ? 'is-selected' : ''}>
              <input type="radio" name="verify-mode" checked={mode === 'strict_sha256'}
                onChange={() => setMode('strict_sha256')} />
              <span><strong>严格 SHA256</strong>
                <small>完整读取云端与 NAS 文件，可能产生大量流量，要求 WebDAV 原始流</small></span>
            </label>
          </fieldset>
          <div className="nfc-dv-footer">
            <p>快速核对只能证明清单匹配；文件大小相同不代表内容相同或未损坏。</p>
            <ConsoleButton variant="primary" loading={start.isPending}
              disabled={chosenId === null || !localRoot || start.isPending}
              leadingIcon={<ConsoleIcon name="play" size={16} />}
              onClick={() => { setError(''); setFeedback(''); start.mutate(); }}>开始只读核对</ConsoleButton>
          </div>
          {error && <p role="alert" className="nfc-dv-error">{error}</p>}
          {feedback && <p role="status" className="nfc-dv-feedback">{feedback}</p>}
        </div>
      </DataPanel>

      <DataPanel title="校验历史" description="记录各次核对结果；删除报告不会删除 NAS 文件，也不会清除任务中心日志。">
        {runs.isError && <p role="alert" className="nfc-dv-error">读取校验历史失败</p>}
        <div className="nfc-dv-bulk-toolbar">
          <span aria-live="polite">当前页可删除 {deletableRunIds.length} 项，已选 {selectedDeletableIds.length} 项</span>
          <div className="nfc-dv-bulk-actions">
            <ConsoleButton size="sm" variant="ghost"
              disabled={selectedDeletableIds.length === 0 || bulkRemove.isPending}
              onClick={() => setSelectedReportIds([])}>清空选择</ConsoleButton>
            <ConsoleButton size="sm" variant="danger"
              leadingIcon={<ConsoleIcon name="trash" size={14} />}
              disabled={selectedDeletableIds.length === 0 || bulkRemove.isPending || remove.isPending}
              onClick={() => setBulkDeleteTarget([...selectedDeletableIds])}>
              批量删除（{selectedDeletableIds.length}）
            </ConsoleButton>
          </div>
        </div>
        <div className="nfc-dv-table-scroll nfc-download-verify-table-scroll">
          <table className="nfc-dv-table nfc-download-verify-table" aria-label="校验历史">
            <thead><tr><th className="nfc-dv-select-cell">
              <input ref={selectAllRef} type="checkbox" aria-label="全选当前页可删除的校验报告"
                checked={allDeletableSelected} disabled={deletableRunIds.length === 0 || bulkRemove.isPending}
                onChange={event => setSelectedReportIds(event.target.checked ? deletableRunIds : [])} />
            </th><th>任务</th><th>来源 / NAS</th><th>模式</th><th>结果</th><th>进度</th><th>操作</th></tr></thead>
            <tbody>
              {(runs.data?.items || []).map(run => <tr key={run.id}>
                <td className="nfc-dv-select-cell">
                  <input type="checkbox" aria-label={'选择校验报告 #' + run.id}
                    checked={selectedDeletableIds.includes(run.id)}
                    disabled={!run.can_delete || bulkRemove.isPending}
                    onChange={event => setSelectedReportIds(ids => event.target.checked
                      ? [...ids.filter(id => id !== run.id), run.id]
                      : ids.filter(id => id !== run.id))} />
                </td>
                <td className="nfc-dv-id">#{run.id}</td>
                <td><div className="nfc-dv-path">
                  <strong>{sourceList.find(source => source.id === run.source_id)?.name
                    || (run.source_id ? '已停用来源' : '旧版 WebDAV')}</strong>
                  <span className="nfc-dv-remote-path">{run.remote_root ? '/' + run.remote_root : '来源根目录 /'}</span>
                </div><small className="nfc-dv-local-path">NAS：{run.local_root}</small></td>
                <td>{run.mode === 'metadata' ? '快速核对' : 'SHA256'}</td>
                <td><span className={'nfc-dv-result ' + (run.result === 'DIFFERENT' || run.job_status === 'failed' ? 'is-different'
                  : run.result === 'VERIFIED_IDENTICAL' || run.result === 'METADATA_IDENTICAL' ? 'is-matched' : '')}>
                  {verdict[run.result] || run.result}</span>
                  <small>{displayJob(run.job_status)}{run.error_code ? ' · ' + run.error_code : ''}</small></td>
                <td>{run.checked}/{run.total}</td>
                <td><div className="nfc-dv-row-actions">
                  <ConsoleButton size="sm" onClick={() => { setSelected(run.id); setPage(1); }}>查看条目</ConsoleButton>
                  <ConsoleButton size="sm" variant="secondary"
                    leadingIcon={<ConsoleIcon name="activity" size={14} />}
                    onClick={() => navigate('/tasks?task=' + run.work_job_id)}>任务中心</ConsoleButton>
                  <ConsoleButton size="sm" variant="ghost"
                    title={run.can_delete ? '删除校验报告' : '任务尚未结束，不可删除报告'}
                    disabled={!run.can_delete}
                    leadingIcon={<ConsoleIcon name="trash" size={14} />}
                    onClick={() => setDeleteTarget(run)}>删除</ConsoleButton>
                </div></td>
              </tr>)}
              {!runs.isLoading && runs.data?.items.length === 0 &&
                <tr><td colSpan={7} className="nfc-dv-no-rows">暂无校验历史，完成第一次核对后将显示在这里。</td></tr>}
            </tbody>
          </table>
        </div>
        {totalRuns > 50 && <div className="nfc-dv-pagination">
          <ConsoleButton size="sm" disabled={historyPage <= 1} onClick={() => setHistoryPage(x => Math.max(1, x - 1))}>上一页</ConsoleButton>
          <span>第 {historyPage}/{lastHistoryPage} 页 · 共 {totalRuns} 项</span>
          <ConsoleButton size="sm" disabled={historyPage >= lastHistoryPage} onClick={() => setHistoryPage(x => x + 1)}>下一页</ConsoleButton>
        </div>}
      </DataPanel>

      {selected !== null && <DataPanel title={'校验明细 #' + selected}
        action={<ConsoleButton size="sm" onClick={() => setSelected(null)}>关闭</ConsoleButton>}
        description="逐条查看相对路径与文件大小差异。快速核对不会声称内容 SHA256 一致。">
        {details.isError && <p role="alert">读取明细失败</p>}
        <div className="nfc-dv-table-scroll nfc-download-verify-table-scroll">
          <table className="nfc-dv-table nfc-download-verify-table" aria-label="校验明细">
            <thead><tr><th>相对路径</th><th>结果</th><th>云端大小</th><th>NAS 大小</th><th>内容 SHA256</th></tr></thead>
            <tbody>{(details.data?.items || []).map(item => <tr key={item.relative_path}>
              <td className="nfc-dv-path">{item.relative_path}</td>
              <td>{verdict[item.status] || item.status}</td>
              <td>{formatBytes(item.remote_size)}</td><td>{formatBytes(item.local_size)}</td>
              <td>{item.remote_sha256 && item.local_sha256
                ? item.remote_sha256 === item.local_sha256 ? '一致' : '不一致' : '未检查'}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="nfc-dv-pagination">
          <ConsoleButton size="sm" disabled={page <= 1}
            onClick={() => setPage(x => Math.max(1, x - 1))}>上一页</ConsoleButton>
          <span>第 {page} 页 · 共 {details.data?.total || 0} 项</span>
          <ConsoleButton size="sm" disabled={!details.data || page * 50 >= details.data.total}
            onClick={() => setPage(x => x + 1)}>下一页</ConsoleButton>
        </div>
      </DataPanel>}

      <RemoteDirectoryPicker open={pickerOpen} sourceId={chosenId}
        sourceName={selectedSource?.name || ''} initialPath={remoteRoot}
        onClose={() => setPickerOpen(false)} onConfirm={setRemoteRoot}
        returnFocusTo={opener.current} />
      <ConsoleConfirmDialog open={deleteTarget !== null}
        onOpenChange={open => { if (!open) setDeleteTarget(null); }}
        title={'删除校验报告 #' + (deleteTarget?.id || '') + '？'}
        description={<p>仅删除这条校验历史及其文件清单明细。NAS 文件、AList/OpenList 来源、任务中心执行记录均会保留。此操作不可撤销。</p>}
        confirmText="删除报告" busy={remove.isPending}
        onConfirm={() => { if (deleteTarget) remove.mutate(deleteTarget.id); }} />
      <ConsoleConfirmDialog open={bulkDeleteTarget !== null}
        onOpenChange={open => { if (!open && !bulkRemove.isPending) setBulkDeleteTarget(null); }}
        title={'批量删除 ' + (bulkDeleteTarget?.length || 0) + ' 份校验报告？'}
        description={<p>仅删除选中的校验历史及其明细；NAS 文件、AList/OpenList 来源和任务中心日志均会保留。任何报告仍在运行或已不存在时，将整批取消删除。此操作不可撤销。</p>}
        confirmText="确认批量删除" danger busy={bulkRemove.isPending}
        onConfirm={() => { if (bulkDeleteTarget) bulkRemove.mutate(bulkDeleteTarget); }} />
    </div>
  );
};
