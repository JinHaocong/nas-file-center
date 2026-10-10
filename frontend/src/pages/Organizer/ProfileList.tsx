import React, { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { organizerProfilesApi } from '../../api/organizerProfiles';
import { getStructuredApiError } from '../../api/errors';
import type { OrganizerProfile } from '../../types';
import { formatDateTime } from '../../utils/format';
import {
  parseOrganizerProfileImport, resolveOrganizerProfileDelete, organizerExportFilename,
} from '../../utils/organizerProfileListActions';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { getPaginationState } from '../../components/ui/paginationModel';

interface ProfileListProps {
  onSelectProfile: (profile: OrganizerProfile) => void;
  onCreateProfile: () => void;
  onEditProfile: (profile: OrganizerProfile) => void;
}

export const ProfileList: React.FC<ProfileListProps> = ({
  onSelectProfile, onCreateProfile, onEditProfile,
}) => {
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  const cloneGuard = useRef(false);
  const deleteGuard = useRef(false);
  const importGuard = useRef(false);
  const fileReadToken = useRef(0);
  const fileRef = useRef<HTMLInputElement>(null);
  const exportGuard = useRef(false);

  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [importJsonText, setImportJsonText] = useState('');
  const [readingFile, setReadingFile] = useState(false);
  const [deleteIntent, setDeleteIntent] = useState<{ id: number; name: string } | null>(null);
  const [exportingId, setExportingId] = useState<number | null>(null);

  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['organizer-profiles', page, pageSize, search],
    queryFn: () => organizerProfilesApi.listProfiles(page, pageSize, search),
  });
  const items = data?.items || [];
  const total = data?.total || 0;
  const currentPage = getPaginationState(page, pageSize, total).current;

  useEffect(() => {
    if (!isLoading && !isError && data && currentPage !== page) setPage(currentPage);
  }, [isLoading, isError, data?.total, page, currentPage]);

  const refreshList = () => {
    void queryClient.invalidateQueries({ queryKey: ['organizer-profiles'] });
  };
  const cloneMutation = useMutation({
    mutationFn: (id: number) => organizerProfilesApi.cloneProfile(id),
    onSuccess: cloned => {
      toast.success('已复制为个人方案: ' + cloned.name);
      refreshList();
    },
    onError: (err: unknown) => toast.error(getStructuredApiError(err).message || '复制方案失败'),
    onSettled: () => { cloneGuard.current = false; },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: number) => organizerProfilesApi.deleteProfile(id),
    onSuccess: () => {
      toast.success('已删除该方案');
      setDeleteIntent(null);
      // Removing the final item from a page should not strand pagination.
      if (items.length === 1 && page > 1) setPage(page - 1);
      refreshList();
    },
    onError: (err: unknown) => toast.error(getStructuredApiError(err).message || '删除方案失败'),
    onSettled: () => { deleteGuard.current = false; },
  });
  const importMutation = useMutation({
    mutationFn: (payload: ReturnType<typeof parseOrganizerProfileImport>) => organizerProfilesApi.importProfile(payload),
    onSuccess: imported => {
      toast.success('方案「' + imported.name + '」导入成功');
      setImportModalOpen(false);
      setImportJsonText('');
      if (fileRef.current) fileRef.current.value = '';
      setPage(1);
      refreshList();
    },
    onError: (err: unknown) => toast.error(getStructuredApiError(err).message || '导入方案失败'),
    onSettled: () => { importGuard.current = false; },
  });
  const busy = cloneMutation.isPending || deleteMutation.isPending || importMutation.isPending;
  const deleteTarget = resolveOrganizerProfileDelete(deleteIntent, items, busy || deleteGuard.current);

  const handleClone = (profile: OrganizerProfile) => {
    if (busy || cloneGuard.current || deleteGuard.current || importGuard.current) return;
    if (!items.some(item => item.id === profile.id)) return;
    cloneGuard.current = true;
    cloneMutation.mutate(profile.id);
  };
  const handleDeleteRequest = (profile: OrganizerProfile) => {
    if (busy || deleteGuard.current || profile.is_builtin) return;
    if (!items.some(item => item.id === profile.id && !item.is_builtin)) return;
    setDeleteIntent({ id: profile.id, name: profile.name });
  };
  const handleDeleteConfirm = () => {
    if (busy || deleteGuard.current) return;
    // Revalidate the exact ID, identity, and immutable builtin status at confirmation.
    const profile = resolveOrganizerProfileDelete(deleteIntent, items, false);
    if (!profile) { setDeleteIntent(null); return; }
    deleteGuard.current = true;
    deleteMutation.mutate(profile.id);
  };
  const handleExport = async (profile: OrganizerProfile) => {
    if (exportGuard.current || busy || !items.some(item => item.id === profile.id)) return;
    exportGuard.current = true;
    setExportingId(profile.id);
    try {
      const result = await organizerProfilesApi.exportProfile(profile.id);
      const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      try {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = organizerExportFilename(profile.name);
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        URL.revokeObjectURL(url);
      }
      toast.success('已导出方案: ' + profile.name);
    } catch (err: unknown) {
      toast.error(getStructuredApiError(err).message || '导出方案失败');
    } finally {
      exportGuard.current = false;
      setExportingId(null);
    }
  };

  const closeImport = () => {
    if (importMutation.isPending || importGuard.current || readingFile) return;
    fileReadToken.current += 1;
    setImportModalOpen(false);
    setImportJsonText('');
    if (fileRef.current) fileRef.current.value = '';
  };
  const handleImportFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || busy || readingFile) return;
    if (file.size > 5 * 1024 * 1024) {
      toast.error('JSON 文件超过 5 MiB，请导入较小的方案配置');
      event.target.value = '';
      return;
    }
    const token = ++fileReadToken.current;
    setReadingFile(true);
    try {
      const text = await file.text();
      if (token === fileReadToken.current) setImportJsonText(text);
    } catch {
      toast.error('读取 JSON 文件失败，请重新选择');
    } finally {
      if (token === fileReadToken.current) setReadingFile(false);
    }
  };
  const handleImportSubmit = () => {
    if (busy || importGuard.current || readingFile) return;
    if (!importJsonText.trim()) {
      toast.error('请输入或粘贴方案 JSON 内容');
      return;
    }
    try {
      const payload = parseOrganizerProfileImport(importJsonText);
      importGuard.current = true;
      importMutation.mutate(payload);
    } catch (err: unknown) {
      toast.error(err instanceof SyntaxError ? 'JSON 格式无效，请检查语法' :
        getStructuredApiError(err).message);
    }
  };
  const changePage = (nextPage: number, nextSize: number) => {
    setPage(nextPage);
    setPageSize(nextSize);
    setDeleteIntent(null);
  };
  const renderActions = (profile: OrganizerProfile, mobile = false) => (
    <div className={mobile ? 'nfc-mobile-record-actions nfc-v2-organizer-actions' : 'nfc-row-actions nfc-v2-organizer-actions'}>
      <ConsoleButton size="sm" variant="primary"
        leadingIcon={<ConsoleIcon name="file-search" size={15} />}
        onClick={() => onSelectProfile(profile)}>预览 / 整理</ConsoleButton>
      <ConsoleButton size="sm" variant="ghost" disabled={busy || exportingId !== null}
        loading={cloneMutation.isPending} leadingIcon={<ConsoleIcon name="copy" size={15} />}
        onClick={() => handleClone(profile)}>复制</ConsoleButton>
      <ConsoleButton size="sm" variant="ghost"
        title={profile.is_builtin ? '内置方案配置不可直接修改，请先复制为个人方案' : '编辑方案'}
        disabled={profile.is_builtin || busy} leadingIcon={<ConsoleIcon name={profile.is_builtin ? 'lock' : 'pencil'} size={15} />}
        onClick={() => { if (!profile.is_builtin && !busy) onEditProfile(profile); }}>编辑</ConsoleButton>
      <ConsoleButton size="sm" variant="ghost" disabled={busy || exportingId !== null}
        loading={exportingId === profile.id}
        leadingIcon={<ConsoleIcon name="file-text" size={15} />}
        onClick={() => { void handleExport(profile); }}>导出</ConsoleButton>
      {!profile.is_builtin && (
        <ConsoleButton size="sm" variant="danger" disabled={busy}
          leadingIcon={<ConsoleIcon name="trash" size={15} />}
          onClick={() => handleDeleteRequest(profile)}>删除</ConsoleButton>
      )}
    </div>
  );
  const rootCell = (profile: OrganizerProfile) => profile.root
    ? <CodePath value={profile.root} />
    : <span className="nfc-table-muted">每次手动选择</span>;

  return (
    <>
      <DataPanel title="整理方案"
        description="内置 Profile 只读；复制后可编辑为个人方案。导入/导出使用 JSON 配置。"
        action={<span className="nfc-panel-count">{total} profiles</span>}
        className="nfc-panel-flush nfc-v2-organizer-profile-list" variant="dense">
        <ActionBar className="nfc-filter-bar nfc-organizer-profile-toolbar nfc-v2-organizer-profile-toolbar">
          <label className="nfc-v2-organizer-search">
            <ConsoleIcon name="search" size={17} />
            <input type="search" placeholder="搜索方案名称或描述..." value={search}
              aria-label="搜索整理方案"
              onChange={event => { setSearch(event.target.value); setPage(1); setDeleteIntent(null); }} />
          </label>
          <ConsoleButton leadingIcon={<ConsoleIcon name="file-text" size={16} />}
            onClick={() => setImportModalOpen(true)}>导入 JSON</ConsoleButton>
          <ConsoleButton variant="primary" leadingIcon={<ConsoleIcon name="plus" size={16} />}
            onClick={onCreateProfile}>新建整理方案</ConsoleButton>
        </ActionBar>

        {isError && <div role="alert" className="nfc-v2-organizer-list-error">
          <strong>获取方案列表失败</strong>
          <p>{getStructuredApiError(error).message}</p>
          <ConsoleButton onClick={() => { void refetch(); }}>重试</ConsoleButton>
        </div>}
        {isLoading && <div role="status" className="nfc-v2-organizer-list-loading">
          <span className="nfc-console-spinner" aria-hidden="true" />
          正在加载整理方案…
        </div>}
        {!isLoading && !isError && items.length === 0 && (
          <ConsoleEmpty title={search ? '没有匹配的整理方案' : '暂无整理方案'}
            description={search ? '请尝试其他搜索关键词' : '可创建新方案或导入已导出的 JSON 配置'}
            action={!search && <ConsoleButton variant="primary" onClick={onCreateProfile}>新建方案</ConsoleButton>} />
        )}
        {!isLoading && !isError && items.length > 0 && (
          <>
            <ResponsiveDataView
              desktop={
                <div className="nfc-v2-organizer-table-scroll">
                  <table className="nfc-v2-organizer-table">
                    <caption className="nfc-v2-organizer-sr-only">整理方案名称、默认根目录、更新时间和操作</caption>
                    <thead><tr>
                      <th scope="col">方案名称</th><th scope="col">默认根目录</th>
                      <th scope="col">更新时间</th><th scope="col">操作</th>
                    </tr></thead>
                    <tbody>{items.map(profile => (
                      <tr key={profile.id}>
                        <td><div className="nfc-profile-name-cell">
                          <strong>{profile.name}</strong>
                          <span className="nfc-kind-badge">{profile.is_builtin ? 'builtin' : 'user'}</span>
                          {profile.description && <small>{profile.description}</small>}
                        </div></td>
                        <td>{rootCell(profile)}</td>
                        <td><time dateTime={profile.updated_at || undefined} className="nfc-table-meta">
                          {profile.updated_at ? formatDateTime(profile.updated_at) : '—'}
                        </time></td>
                        <td>{renderActions(profile)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              }
              mobile={
                <div className="nfc-mobile-record-list nfc-v2-organizer-mobile-list">
                  {items.map(profile => (
                    <article className="nfc-organizer-profile-mobile-card" key={profile.id}>
                      <div className="nfc-mobile-record-heading">
                        <div className="nfc-plan-mobile-heading-copy">
                          <strong className="nfc-mobile-record-title">{profile.name}</strong>
                          <span className="nfc-kind-badge">{profile.is_builtin ? 'builtin' : 'user'}</span>
                        </div>
                      </div>
                      {profile.description && <p className="nfc-mobile-record-note">{profile.description}</p>}
                      <div className="nfc-plan-item-paths">
                        <div className="nfc-plan-item-path-row"><span>默认根</span>{rootCell(profile)}</div>
                      </div>
                      <div className="nfc-mobile-record-facts">
                        <span>更新时间 <b>{profile.updated_at ? formatDateTime(profile.updated_at) : '—'}</b></span>
                      </div>
                      {renderActions(profile, true)}
                    </article>
                  ))}
                </div>
              }
            />
            <ConsolePagination page={currentPage} pageSize={pageSize} total={total}
              pageSizes={[10, 20, 50, 100]} onChange={changePage} />
          </>
        )}
      </DataPanel>

      <ConsoleConfirmDialog open={deleteIntent !== null}
        onOpenChange={next => { if (!next && !deleteMutation.isPending && !deleteGuard.current) setDeleteIntent(null); }}
        title={'删除整理方案「' + (deleteIntent?.name || '') + '」？'}
        description="删除个人方案不可撤销；内置方案不可删除。若仍有服务端依赖或权限限制，后端会拒绝该操作。"
        confirmText="确认删除" danger
        busy={deleteMutation.isPending || deleteGuard.current}
        disabled={!deleteTarget} onConfirm={handleDeleteConfirm} />

      <Dialog.Root open={importModalOpen} onOpenChange={next => { if (!next) closeImport(); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-organizer-import-overlay" />
          <Dialog.Content className="nfc-v2-organizer-import-dialog nfc-overlay-modal"
            onEscapeKeyDown={event => { if (importMutation.isPending || importGuard.current || readingFile) event.preventDefault(); }}
            onPointerDownOutside={event => event.preventDefault()}>
            <header className="nfc-v2-organizer-import-heading">
              <div>
                <Dialog.Title>导入整理方案 (JSON)</Dialog.Title>
                <Dialog.Description>选择导出的 JSON 文件，或将完整 JSON 内容粘贴到输入框；校验后提交服务器。</Dialog.Description>
              </div>
              <button type="button" className="nfc-v2-organizer-import-close"
                aria-label="关闭导入窗口" disabled={importMutation.isPending || readingFile} onClick={closeImport}>
                <ConsoleIcon name="x" size={18} />
              </button>
            </header>
            <div className="nfc-v2-organizer-import-body">
              <input type="file" ref={fileRef} accept=".json,application/json"
                aria-label="选择本地 JSON 方案文件" className="nfc-v2-organizer-file-input"
                onChange={event => { void handleImportFile(event); }} />
              <ConsoleButton disabled={readingFile || importMutation.isPending} loading={readingFile}
                leadingIcon={<ConsoleIcon name="file-text" size={16} />}
                onClick={() => fileRef.current?.click()}>选择本地 .json 文件</ConsoleButton>
              <label className="nfc-v2-organizer-import-text-label" htmlFor="nfc-v2-organizer-import-json">
                JSON 配置内容
              </label>
              <textarea id="nfc-v2-organizer-import-json" rows={10}
                aria-label="方案 JSON 内容" value={importJsonText}
                disabled={importMutation.isPending || readingFile}
                placeholder="粘贴导出文件的 JSON 内容..."
                onChange={event => setImportJsonText(event.target.value)} />
              <p className="nfc-v2-organizer-import-hint">
                必须包含 schema_version 和 profile 对象；后端仍会校验版本、方案内容与权限。
              </p>
            </div>
            <footer className="nfc-v2-organizer-import-actions">
              <ConsoleButton disabled={importMutation.isPending || readingFile} onClick={closeImport}>取消</ConsoleButton>
              <ConsoleButton variant="primary" loading={importMutation.isPending}
                disabled={!importJsonText.trim() || readingFile}
                onClick={handleImportSubmit}>确认导入</ConsoleButton>
            </footer>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
};
