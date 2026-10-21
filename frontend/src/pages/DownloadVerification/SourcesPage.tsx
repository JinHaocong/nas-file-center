import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useTitle } from '../../hooks/useTitle';
import { downloadVerificationApi } from '../../api/downloadVerification';
import type { SourceInput, VerificationSource } from '../../api/downloadVerification';
import { getStructuredApiError } from '../../api/errors';

const empty: SourceInput = { name: '', provider: 'openlist', base_url: '', username: '', password: '' };
const message = (error: unknown) => getStructuredApiError(error).message || '操作失败';

export const DownloadSourcesPage: React.FC = () => {
  useTitle('下载校验来源');
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [draft, setDraft] = useState<SourceInput>({ ...empty });
  const [deleteTarget, setDeleteTarget] = useState<VerificationSource | null>(null);
  const [feedback, setFeedback] = useState('');
  const [error, setError] = useState('');

  const list = useQuery({
    queryKey: ['download-verify-sources'],
    queryFn: downloadVerificationApi.sources,
  });
  const items = list.data?.items || [];

  const save = useMutation({
    mutationFn: () => editing === null
      ? downloadVerificationApi.addSource(draft)
      : downloadVerificationApi.updateSource(editing, {
        ...draft, ...(!draft.password ? { password: undefined } : {}),
      }),
    onSuccess: source => {
      setFeedback('已保存来源：' + source.name);
      setError('');
      setFormOpen(false);
      setEditing(null);
      setDraft({ ...empty });
      void qc.invalidateQueries({ queryKey: ['download-verify-sources'] });
    },
    onError: err => setError(message(err)),
  });
  const disable = useMutation({
    mutationFn: (id: number) => downloadVerificationApi.deleteSource(id),
    onSuccess: () => {
      setFeedback('已停用来源，历史校验报告仍然保留');
      setDeleteTarget(null);
      setError('');
      void qc.invalidateQueries({ queryKey: ['download-verify-sources'] });
    },
    onError: err => {
      setDeleteTarget(null);
      setError(message(err));
    },
  });

  const add = () => {
    setEditing(null);
    setDraft({ ...empty });
    setError('');
    setFormOpen(true);
  };
  const edit = (source: VerificationSource) => {
    setEditing(source.id);
    setDraft({
      name: source.name, provider: source.provider, base_url: source.base_url,
      username: source.username, password: '',
    });
    setError('');
    setFormOpen(true);
  };

  return (
    <div className="nfc-operations-page nfc-page-layout-workbench nfc-download-verify nfc-dv-source-page">
      <PageHeader title="下载校验来源"
        description="集中管理 AList / OpenList 连接。每个来源可自定义名称、地址与只读账号，不需要把地址写进代码或 Compose。"
        actions={<ConsoleButton onClick={() => navigate('/download-verification')}
          leadingIcon={<ConsoleIcon name="arrow-left" size={16} />}>返回下载校验</ConsoleButton>} />

      <DataPanel title="已配置来源" description="来源只供只读目录浏览和核对使用；停用来源不会删除历史校验报告。"
        action={<ConsoleButton variant="primary" onClick={add}
          leadingIcon={<ConsoleIcon name="plus" size={16} />}>新增来源</ConsoleButton>}>
        {list.isLoading && <p className="nfc-dv-muted">正在读取来源…</p>}
        {list.isError && <p role="alert" className="nfc-dv-error">读取来源列表失败</p>}
        {feedback && <p role="status" className="nfc-dv-feedback">{feedback}</p>}
        {error && <p role="alert" className="nfc-dv-error">{error}</p>}
        {items.length === 0 && !list.isLoading && !list.isError && (
          <div className="nfc-dv-empty">
            <ConsoleIcon name="folder-open" size={28} />
            <strong>还没有配置来源</strong>
            <span>请添加 AList 或 OpenList，随后返回下载校验页选择目录。</span>
            <ConsoleButton size="sm" variant="primary" onClick={add}>添加第一个来源</ConsoleButton>
          </div>
        )}
        <div className="nfc-dv-source-list">
          {items.map(source => <article key={source.id} className="nfc-dv-source-entry">
            <div className="nfc-dv-source-symbol"><ConsoleIcon name="database" size={19} /></div>
            <div className="nfc-dv-source-info">
              <strong>{source.name}</strong>
              <span>{source.provider === 'alist' ? 'AList' : 'OpenList'} · {source.base_url}</span>
              <small>{source.username ? '服务账号：' + source.username : '公开目录访问'} · {source.has_password ? '已配置密码' : '无需密码'}</small>
            </div>
            <div className="nfc-dv-source-buttons">
              <ConsoleButton size="sm" onClick={() => edit(source)}
                leadingIcon={<ConsoleIcon name="pencil" size={14} />}>编辑</ConsoleButton>
              <ConsoleButton size="sm" variant="ghost" onClick={() => setDeleteTarget(source)}
                leadingIcon={<ConsoleIcon name="trash" size={14} />}>停用</ConsoleButton>
            </div>
          </article>)}
        </div>
      </DataPanel>

      {formOpen && <DataPanel title={editing === null ? '新增来源' : '编辑来源'}
        description="使用 NAS File Center 可以访问的容器内地址或局域网地址。PikPak 账号仍由 AList/OpenList 自己管理。">
        <form className="nfc-dv-source-form" onSubmit={event => {
          event.preventDefault();
          setError('');
          save.mutate();
        }}>
          <div className="nfc-dv-manager-grid">
            <label>来源名称
              <input aria-label="来源名称" required maxLength={120} value={draft.name}
                onChange={event => setDraft(x => ({ ...x, name: event.target.value }))} placeholder="例如：客厅的 OpenList" />
            </label>
            <label>服务类型
              <select aria-label="服务类型" value={draft.provider}
                onChange={event => setDraft(x => ({ ...x, provider: event.target.value as 'alist' | 'openlist' }))}>
                <option value="alist">AList</option><option value="openlist">OpenList</option>
              </select>
            </label>
            <label className="nfc-dv-wide">服务地址
              <input aria-label="服务地址" type="url" required value={draft.base_url}
                onChange={event => setDraft(x => ({ ...x, base_url: event.target.value }))}
                placeholder="http://openlist:5244" />
            </label>
            <label>服务只读账号（公开目录可不填）
              <input aria-label="服务只读账号" autoComplete="off" value={draft.username}
                onChange={event => setDraft(x => ({ ...x, username: event.target.value }))} />
            </label>
            <label>服务账号密码{editing !== null && '（留空保留旧密码）'}
              <input aria-label="服务账号密码" type="password" autoComplete="new-password"
                value={draft.password || ''}
                onChange={event => setDraft(x => ({ ...x, password: event.target.value }))} />
            </label>
          </div>
          <p className="nfc-dv-muted">连接凭据仅保存在服务端受保护的配置文件中，不会回显。建议在 AList/OpenList 创建专用只读账号。</p>
          <div className="nfc-dv-actions">
            <ConsoleButton type="submit" variant="primary" loading={save.isPending}>保存来源</ConsoleButton>
            <ConsoleButton onClick={() => { setFormOpen(false); setEditing(null); setError(''); }}
              disabled={save.isPending}>取消</ConsoleButton>
          </div>
          {error && <p role="alert" className="nfc-dv-error">{error}</p>}
        </form>
      </DataPanel>}
      <ConsoleConfirmDialog open={deleteTarget !== null}
        onOpenChange={open => { if (!open) setDeleteTarget(null); }}
        title="停用此来源？"
        description={<p>停用「{deleteTarget?.name}」后，无法继续使用该来源发起新校验；已有历史报告不会删除。</p>}
        confirmText="确认停用" busy={disable.isPending}
        onConfirm={() => { if (deleteTarget) disable.mutate(deleteTarget.id); }} />
    </div>
  );
};
