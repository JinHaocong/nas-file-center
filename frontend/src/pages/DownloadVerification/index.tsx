import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { useTitle } from '../../hooks/useTitle';
import { downloadVerificationApi } from '../../api/downloadVerification';
import type { SourceInput } from '../../api/downloadVerification';
import { getStructuredApiError } from '../../api/errors';
import '../../styles/console-v2-download-verify.css';

const verdict: Record<string, string> = {
  METADATA_IDENTICAL: '路径、文件名和大小一致（未校验内容）',
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
const emptySource: SourceInput = {
  name: '', provider: 'openlist', base_url: '', username: '', password: '',
};
const formatBytes = (n: number | null) =>
  n === null ? '—' : n >= 1073741824 ? (n / 1073741824).toFixed(2) + ' GiB'
    : n >= 1048576 ? (n / 1048576).toFixed(2) + ' MiB'
      : n >= 1024 ? (n / 1024).toFixed(1) + ' KiB' : n + ' B';
const apiError = (error: unknown) => getStructuredApiError(error).message || '操作失败';

export const DownloadVerificationPage: React.FC = () => {
  useTitle('下载完整性校验');
  const qc = useQueryClient();
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [managerOpen, setManagerOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [draft, setDraft] = useState<SourceInput>(emptySource);
  const [browseOpen, setBrowseOpen] = useState(false);
  const [browsePath, setBrowsePath] = useState('');
  const [remoteRoot, setRemoteRoot] = useState('');
  const [localRoot, setLocalRoot] = useState('');
  const [mode, setMode] = useState<'metadata' | 'strict_sha256'>('metadata');
  const [selected, setSelected] = useState<number | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState('');

  const sources = useQuery({ queryKey: ['download-verify-sources'], queryFn: downloadVerificationApi.sources });
  const sourceList = sources.data?.items || [];
  const selectedSource = sourceList.find(source => source.id === sourceId) || sourceList[0];
  const chosenId = selectedSource?.id ?? null;
  const remote = useQuery({
    queryKey: ['download-verify-remote', chosenId, browsePath],
    queryFn: () => downloadVerificationApi.browse(chosenId!, browsePath),
    enabled: browseOpen && chosenId !== null,
    retry: false,
  });
  const runs = useQuery({
    queryKey: ['download-verify-runs'], queryFn: downloadVerificationApi.list,
    refetchInterval: 5000,
  });
  const details = useQuery({
    queryKey: ['download-verify-items', selected, page],
    queryFn: () => downloadVerificationApi.items(selected!, page),
    enabled: selected !== null,
    refetchInterval: selected === null ? false : 5000,
  });
  const saveSource = useMutation({
    mutationFn: () => editingId === null
      ? downloadVerificationApi.addSource(draft)
      : downloadVerificationApi.updateSource(editingId, {
        ...draft, ...(draft.password ? {} : { password: undefined }),
      }),
    onSuccess: (source) => {
      void qc.invalidateQueries({ queryKey: ['download-verify-sources'] });
      setSourceId(source.id);
      setManagerOpen(false);
      setEditingId(null);
      setBrowseOpen(false);
      setBrowsePath('');
      setRemoteRoot('');
      setError('');
    },
    onError: err => setError(apiError(err)),
  });
  const disableSource = useMutation({
    mutationFn: (id: number) => downloadVerificationApi.deleteSource(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['download-verify-sources'] });
      setSourceId(null);
      setBrowseOpen(false);
      setRemoteRoot('');
      setManagerOpen(false);
      setError('');
    },
    onError: err => setError(apiError(err)),
  });
  const start = useMutation({
    mutationFn: () => downloadVerificationApi.start(remoteRoot, localRoot, chosenId!, mode),
    onSuccess: run => {
      setError('');
      setSelected(run.id);
      setPage(1);
      void runs.refetch();
    },
    onError: err => setError(apiError(err)),
  });
  const openNew = () => {
    setDraft({ ...emptySource });
    setEditingId(null);
    setManagerOpen(true);
    setError('');
  };
  const openEdit = () => {
    if (!selectedSource) return;
    setDraft({
      name: selectedSource.name, provider: selectedSource.provider,
      base_url: selectedSource.base_url, username: selectedSource.username, password: '',
    });
    setEditingId(selectedSource.id);
    setManagerOpen(true);
    setError('');
  };
  const switchSource = (id: number) => {
    setSourceId(id);
    setBrowsePath('');
    setRemoteRoot('');
    setBrowseOpen(false);
    setError('');
  };
  const parentPath = browsePath.split('/').slice(0, -1).join('/');

  return (
    <div className="nfc-operations-page nfc-page-layout-workbench nfc-download-verify">
      <PageHeader title="下载完整性校验"
        description="选择 AList / OpenList 已挂载的目录，对照 NAS 下载目录。默认只比较清单，无需重新下载文件。" />

      <DataPanel title="新建校验" description="按顺序选择来源和两边的文件夹；只读比较，不会修改文件。"
        action={<ConsoleButton variant="secondary" size="sm" onClick={openNew}>+ 新增来源</ConsoleButton>}>
        <div className="nfc-dv-fields">
          <div className="nfc-dv-field nfc-dv-source">
            <label htmlFor="nfc-dv-source">1 · 云端来源</label>
            <div className="nfc-dv-control-row">
              <select id="nfc-dv-source" value={chosenId ?? ''} onChange={e => switchSource(Number(e.target.value))}
                disabled={sourceList.length === 0}>
                {sourceList.length === 0 && <option value="">尚未添加来源</option>}
                {sourceList.map(source => <option key={source.id} value={source.id}>
                  {source.name} · {source.provider === 'alist' ? 'AList' : 'OpenList'}
                </option>)}
              </select>
              <ConsoleButton size="sm" onClick={openEdit} disabled={!selectedSource}>管理</ConsoleButton>
            </div>
            <small>{selectedSource ? selectedSource.base_url : '点击「新增来源」配置你自己的地址及只读账号'}</small>
          </div>
          <div className="nfc-dv-field">
            <label>2 · 来源文件夹</label>
            <div className="nfc-dv-control-row">
              <input aria-label="云端相对目录" value={remoteRoot} onChange={e => setRemoteRoot(e.target.value)}
                placeholder="云盘根目录（可直接浏览选择）" disabled={!selectedSource} />
              <ConsoleButton size="sm" disabled={!selectedSource}
                onClick={() => { setBrowsePath(remoteRoot); setBrowseOpen(!browseOpen); }}>
                {browseOpen ? '收起' : '浏览'}
              </ConsoleButton>
            </div>
            <small>相对来源文件夹的路径；选择根目录时可留空</small>
          </div>
          <div className="nfc-dv-field nfc-dv-local">
            <label>3 · NAS 已下载文件夹</label>
            <DirectoryPicker value={localRoot} onChange={value =>
              setLocalRoot(typeof value === 'string' ? value : value[0] || '')} />
            <small>以两个所选文件夹为根，严格对照内部相对路径</small>
          </div>
        </div>

        {browseOpen && chosenId !== null && <div className="nfc-dv-browser">
          <div className="nfc-dv-browser-header">
            <span>来源目录：/{browsePath}</span>
            <div className="nfc-dv-control-row">
              <ConsoleButton size="sm" disabled={!browsePath} onClick={() => setBrowsePath(parentPath)}>上一级</ConsoleButton>
              <ConsoleButton size="sm" variant="primary" onClick={() => { setRemoteRoot(browsePath); setBrowseOpen(false); }}>选择此目录</ConsoleButton>
            </div>
          </div>
          {remote.isLoading && <p>正在读取目录…</p>}
          {remote.isError && <p role="alert">无法读取目录。请检查来源地址、账号权限及容器网络。</p>}
          {remote.data?.items.length === 0 && <p>此目录为空</p>}
          <div className="nfc-dv-directory-items">
            {remote.data?.items.map(entry => entry.kind === 'directory'
              ? <button key={entry.name} type="button" onClick={() =>
                setBrowsePath(browsePath ? browsePath + '/' + entry.name : entry.name)}>
                <span aria-hidden="true">📁</span> {entry.name} <span aria-hidden="true">›</span>
              </button>
              : <div key={entry.name}><span aria-hidden="true">📄</span> {entry.name}
                  <small>{formatBytes(entry.size)}</small></div>)}
          </div>
        </div>}

        {managerOpen && <form className="nfc-dv-manager" onSubmit={event => {
          event.preventDefault(); setError(''); saveSource.mutate();
        }}>
          <div className="nfc-dv-manager-heading">
            <strong>{editingId === null ? '新增来源' : '编辑来源'}</strong>
            <ConsoleButton size="sm" variant="ghost" onClick={() => setManagerOpen(false)}>关闭</ConsoleButton>
          </div>
          <div className="nfc-dv-manager-grid">
            <label>来源名称
              <input required maxLength={120} value={draft.name}
                onChange={e => setDraft(d => ({ ...d, name: e.target.value }))} placeholder="例如：我的 OpenList" />
            </label>
            <label>类型
              <select value={draft.provider}
                onChange={e => setDraft(d => ({ ...d, provider: e.target.value as 'alist' | 'openlist' }))}>
                <option value="alist">AList</option><option value="openlist">OpenList</option>
              </select>
            </label>
            <label className="nfc-dv-wide">服务地址（由你配置，不是写死的）
              <input type="url" required value={draft.base_url}
                onChange={e => setDraft(d => ({ ...d, base_url: e.target.value }))}
                placeholder="http://openlist:5244" />
            </label>
            <label>只读账号（公开目录可不填）
              <input autoComplete="off" value={draft.username}
                onChange={e => setDraft(d => ({ ...d, username: e.target.value }))} />
            </label>
            <label>密码 {editingId !== null && '（留空表示保持不变）'}
              <input type="password" autoComplete="new-password" value={draft.password ?? ''}
                onChange={e => setDraft(d => ({ ...d, password: e.target.value }))} />
            </label>
          </div>
          <p className="nfc-dv-muted">密码只保存在 NAS File Center 的受保护配置文件中，不会回传到网页或写入任务记录。HTTP 仅支持 Docker 服务名或私有局域网 IP，外网请使用 HTTPS。</p>
          <div className="nfc-dv-actions">
            <ConsoleButton type="submit" variant="primary" loading={saveSource.isPending}>保存来源</ConsoleButton>
            {editingId !== null && <ConsoleButton variant="danger" disabled={disableSource.isPending}
              onClick={() => { if (window.confirm('停用此来源？历史结果会保留。')) disableSource.mutate(editingId); }}>
              停用来源
            </ConsoleButton>}
          </div>
        </form>}

        <fieldset className="nfc-dv-modes">
          <legend>4 · 比较方式</legend>
          <label className={mode === 'metadata' ? 'is-selected' : ''}>
            <input type="radio" name="verify-mode" checked={mode === 'metadata'} onChange={() => setMode('metadata')} />
            <span><strong>快速核对 · 推荐</strong><small>目录、文件名、文件大小；不读取远端文件内容</small></span>
          </label>
          <label className={mode === 'strict_sha256' ? 'is-selected' : ''}>
            <input type="radio" name="verify-mode" checked={mode === 'strict_sha256'}
              onChange={() => setMode('strict_sha256')} />
            <span><strong>严格 SHA256</strong><small>完整读取云端和 NAS 文件，可能产生大量流量，且要求 WebDAV 原始文件流</small></span>
          </label>
        </fieldset>
        {mode === 'metadata' && <p className="nfc-dv-muted">快速核对只能证明清单匹配；文件大小相同不代表内容相同或未损坏。</p>}
        {error && <p className="nfc-dv-error" role="alert">{error}</p>}
        <div className="nfc-dv-actions">
          <ConsoleButton variant="primary" loading={start.isPending}
            disabled={!chosenId || !localRoot || start.isPending}
            onClick={() => { setError(''); start.mutate(); }}>开始只读核对</ConsoleButton>
        </div>
      </DataPanel>

      <DataPanel title="校验历史" description="仅「快速清单一致」或「完整 SHA256 一致」是对应模式的成功结论；任务 completed 只是执行结束。">
        {runs.isError && <p role="alert">读取校验历史失败</p>}
        <div className="nfc-dv-table-scroll">
          <table className="nfc-dv-table">
            <thead><tr><th>任务</th><th>来源 / NAS</th><th>模式</th><th>结果</th><th>进度</th><th>操作</th></tr></thead>
            <tbody>
              {(runs.data?.items || []).map(run => <tr key={run.id}>
                <td>#{run.id}</td>
                <td><div>{sourceList.find(source => source.id === run.source_id)?.name || (run.source_id ? '已停用来源' : '旧版 WebDAV')} / {run.remote_root || '/'}</div>
                  <small>{run.local_root}</small></td>
                <td>{run.mode === 'metadata' ? '快速核对' : 'SHA256'}</td>
                <td>{verdict[run.result] || run.result}{run.error_code && <small>{run.error_code}</small>}</td>
                <td>{run.checked}/{run.total}</td>
                <td><div className="nfc-dv-control-row">
                  <ConsoleButton size="sm" onClick={() => { setSelected(run.id); setPage(1); }}>查看条目</ConsoleButton>
                  <a href={'/tasks?task=' + run.work_job_id}>任务中心</a>
                </div></td>
              </tr>)}
              {runs.data?.items.length === 0 && <tr><td colSpan={6}>暂无校验记录</td></tr>}
            </tbody>
          </table>
        </div>
      </DataPanel>

      {selected !== null && <DataPanel title={'校验明细 #' + selected}
        action={<ConsoleButton size="sm" onClick={() => setSelected(null)}>关闭</ConsoleButton>}
        description="逐个相对路径查看差异；快速核对的文件不会显示 SHA256 一致。">
        {details.isError && <p role="alert">读取明细失败</p>}
        <div className="nfc-dv-table-scroll">
          <table className="nfc-dv-table">
            <thead><tr><th>相对路径</th><th>结果</th><th>云端大小</th><th>NAS 大小</th><th>内容 SHA256</th></tr></thead>
            <tbody>{(details.data?.items || []).map(item => <tr key={item.relative_path}>
              <td>{item.relative_path}</td><td>{verdict[item.status] || item.status}</td>
              <td>{formatBytes(item.remote_size)}</td><td>{formatBytes(item.local_size)}</td>
              <td>{item.remote_sha256 && item.local_sha256
                ? item.remote_sha256 === item.local_sha256 ? '一致' : '不一致' : '未检查'}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className="nfc-dv-pagination">
          <ConsoleButton size="sm" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>上一页</ConsoleButton>
          <span>第 {page} 页 · 共 {details.data?.total || 0} 项</span>
          <ConsoleButton size="sm" disabled={!details.data || page * 50 >= details.data.total}
            onClick={() => setPage(p => p + 1)}>下一页</ConsoleButton>
        </div>
      </DataPanel>}
    </div>
  );
};
