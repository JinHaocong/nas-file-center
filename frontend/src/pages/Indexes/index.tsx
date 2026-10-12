import React, { useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { indexesApi } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import type { IndexRoot } from '../../types';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import {
  getIndexRemoveAvailability, getIndexPathStatePresentation,
} from '../../components/indexes/index_lifecycle';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

const stateClass = (state: string) =>
  state === 'available' ? 'nfc-status-success' :
  state === 'blocked' ? 'nfc-status-danger' : 'nfc-status-warning';

const INDEX_REMOVE_DESCRIPTION = (
  <div className="nfc-confirm-copy">
    <p>将删除 NAS File Center 保存的该根目录索引元数据，包括该 Root 对应的 IndexedPath 记录。</p>
    <p><strong>不会删除 NAS 上的任何真实文件或目录</strong>，且不会删除 Task、Scan、Plan 或 Audit 历史记录。</p>
  </div>
);

export const IndexesPage: React.FC = () => {
  useTitle('文件索引');
  const toast = useConsoleToast();
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [rootDraft, setRootDraft] = useState('');
  const [rootError, setRootError] = useState('');
  const [removeTarget, setRemoveTarget] = useState<IndexRoot | null>(null);
  const [removePending, setRemovePending] = useState(false);
  const removeInFlight = useRef(false);
  const createInFlight = useRef(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['indexesList', page, pageSize],
    queryFn: () => indexesApi.listIndexes(page, pageSize),
  });

  const createMutation = useMutation({
    mutationFn: (root: string) => indexesApi.createIndex(root),
    onSuccess: res => {
      toast.success('索引任务 #' + res.work_job_id + ' 已加入后台队列');
      setModalOpen(false);
      setRootDraft('');
      setRootError('');
      void queryClient.invalidateQueries({ queryKey: ['indexesList'] });
      void queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
    },
    onError: (err: unknown) => {
      toast.error(getStructuredApiError(err).message || '加入索引队列失败');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => indexesApi.deleteIndex(id),
    onSuccess: () => {
      toast.success('已安全移除索引元数据');
      void queryClient.invalidateQueries({ queryKey: ['indexesList'] });
      void queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      if (page > 1 && data?.items?.length === 1) setPage(previous => previous - 1);
    },
    onError: (err: unknown) => {
      toast.error(getStructuredApiError(err).message || '移除索引失败');
      void queryClient.invalidateQueries({ queryKey: ['indexesList'] });
    },
  });

  const items: IndexRoot[] = data?.items || [];
  const openCreate = () => {
    if (createInFlight.current || createMutation.isPending) return;
    setRootDraft('');
    setRootError('');
    setModalOpen(true);
  };
  const closeCreate = () => {
    if (createInFlight.current || createMutation.isPending) return;
    setModalOpen(false);
    setRootDraft('');
    setRootError('');
  };
  const handleCreate = async () => {
    if (!modalOpen || createInFlight.current || createMutation.isPending) return;
    const root = rootDraft.trim();
    if (!root) {
      setRootError('请选择或输入要索引的目录绝对路径');
      return;
    }
    if (!root.startsWith('/')) {
      setRootError('目录路径必须为 / 开头的绝对路径；服务端仍会验证 ALLOWED_ROOTS');
      return;
    }
    createInFlight.current = true;
    setRootError('');
    try {
      await createMutation.mutateAsync(root);
    } catch {
      // onError reports failure; keep dialog and input for an explicit retry.
    } finally {
      createInFlight.current = false;
    }
  };
  const handleReindex = async (record: IndexRoot) => {
    if (record.path_state !== 'available' || createInFlight.current || createMutation.isPending) return;
    createInFlight.current = true;
    try {
      await createMutation.mutateAsync(record.root);
    } catch {
      // Error is surfaced by mutation.onError.
    } finally {
      createInFlight.current = false;
    }
  };

  const openRemove = (record: IndexRoot) => {
    if (!getIndexRemoveAvailability(record).canRemove ||
        removeInFlight.current || deleteMutation.isPending) return;
    setRemoveTarget(record);
  };
  const closeRemove = (next: boolean) => {
    if (!next && !removeInFlight.current && !removePending) setRemoveTarget(null);
  };
  const handleRemove = async () => {
    if (!removeTarget || removeInFlight.current || deleteMutation.isPending) return;
    if (!getIndexRemoveAvailability(removeTarget).canRemove) return;
    const record = removeTarget;
    removeInFlight.current = true;
    setRemovePending(true);
    try {
      await deleteMutation.mutateAsync(record.id);
      setRemoveTarget(null);
    } catch {
      // Fail closed with the confirmation still visible, for deliberate retry.
    } finally {
      removeInFlight.current = false;
      setRemovePending(false);
    }
  };

  const renderPathState = (state: string) => {
    const pres = getIndexPathStatePresentation(state);
    return (
      <span className={'nfc-status-badge ' + stateClass(state)}
        title={pres.tooltip} aria-label={'目录状态：' + pres.label}>
        <span className="nfc-status-dot" />{pres.label}
      </span>
    );
  };
  const renderActions = (record: IndexRoot, mobile = false) => {
    const isAvailable = record.path_state === 'available';
    const remove = getIndexRemoveAvailability(record);
    return (
      <div className={'nfc-row-actions nfc-v2-index-actions' + (mobile ? ' is-mobile' : '')}>
        <span title={!isAvailable ? '目录当前不可用或被阻止，无法重新索引' : '将后台排队执行增量索引，不直接在此页遍历目录'}>
          <ConsoleButton size="sm" variant="ghost"
            leadingIcon={<ConsoleIcon name="refresh" size={15} />}
            disabled={!isAvailable || createMutation.isPending}
            loading={createMutation.isPending && createMutation.variables === record.root}
            onClick={() => { void handleReindex(record); }}>重新索引</ConsoleButton>
        </span>
        <span title={remove.reason || '仅移除 NFC 索引元数据，不删除 NAS 文件'}>
          <ConsoleButton size="sm" variant="ghost"
            leadingIcon={<ConsoleIcon name="trash" size={15} />}
            disabled={!remove.canRemove || deleteMutation.isPending || removePending}
            loading={deleteMutation.isPending && deleteMutation.variables === record.id}
            onClick={() => openRemove(record)}>移除索引</ConsoleButton>
        </span>
      </div>
    );
  };

  const changePage = (nextPage: number, nextSize: number) => {
    if (nextSize !== pageSize) {
      setPageSize(nextSize);
      setPage(1);
    } else {
      setPage(nextPage);
    }
  };

  return (
    <div className="nfc-operations-page nfc-indexes-page nfc-page-layout-ledger nfc-v2-indexes-page">
      <PageHeader eyebrow="Index roots" title="文件索引"
        description="维护大型 NAS 目录的增量元数据索引。移除操作只清理 NFC 索引元数据，不触碰真实文件。"
        actions={<ActionBar compact>
          <ConsoleButton loading={isFetching} leadingIcon={<ConsoleIcon name="refresh" size={16} />}
            onClick={() => { void refetch(); }}>刷新</ConsoleButton>
          <ConsoleButton variant="primary" leadingIcon={<ConsoleIcon name="plus" size={16} />}
            onClick={openCreate}>加入索引队列</ConsoleButton>
        </ActionBar>}
      />
      <DataPanel title="索引根目录" description="目录状态、索引规模与后台任务一览。"
        action={<span className="nfc-panel-count">{data?.total ?? 0} roots</span>}
        className="nfc-panel-flush" variant="dense">
        {isError && (
          <div className="nfc-v2-indexes-error" role="alert">
            <strong>获取索引根目录失败</strong>
            <p>{getStructuredApiError(error).message || '无法获取索引数据，请重试'}</p>
            <ConsoleButton size="sm" onClick={() => { void refetch(); }}>重新加载</ConsoleButton>
          </div>
        )}
        {!isError && isLoading && <div role="status" className="nfc-v2-indexes-loading">正在读取索引根目录…</div>}
        {!isError && !isLoading && items.length === 0 &&
          <ConsoleEmpty title="暂无索引根目录" description="可以从上方加入新的索引任务。" />}
        {!isError && !isLoading && items.length > 0 && (
          <>
            <ResponsiveDataView
              desktop={<div className="nfc-v2-indexes-table-scroll">
                <table className="nfc-v2-indexes-table">
                  <thead><tr>
                    <th scope="col">索引根目录</th>
                    <th scope="col">目录状态</th>
                    <th scope="col">文件</th>
                    <th scope="col">目录</th>
                    <th scope="col">最近成功索引</th>
                    <th scope="col">任务状态</th>
                    <th scope="col">操作</th>
                  </tr></thead>
                  <tbody>{items.map(record => (
                    <tr key={record.root}>
                      <td><div className="nfc-path-cell">
                        <ConsoleIcon name="folder-open" size={17} />
                        <CodePath value={record.root} />
                      </div></td>
                      <td>{renderPathState(record.path_state)}</td>
                      <td className="nfc-mono">{record.files.toLocaleString()}</td>
                      <td className="nfc-mono">{record.folders.toLocaleString()}</td>
                      <td className="nfc-table-meta">{record.last_indexed_at
                        ? formatDateTime(record.last_indexed_at) : '尚未完成索引'}</td>
                      <td>{record.has_active_job && record.active_job_id
                        ? <span className="nfc-kind-badge">#{record.active_job_id} {record.active_job_status}</span>
                        : <span className="nfc-table-muted">—</span>}</td>
                      <td>{renderActions(record)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>}
              mobile={<div className="nfc-mobile-record-list nfc-v2-indexes-mobile">
                {items.map(record => {
                  const pres = getIndexPathStatePresentation(record.path_state);
                  return (
                    <article className="nfc-index-mobile-card" key={record.root}>
                      <div className="nfc-mobile-record-heading">
                        <div className="nfc-index-mobile-path">
                          <ConsoleIcon name="folder-open" size={17} />
                          <CodePath value={record.root} />
                        </div>
                        <span className={'nfc-status-badge ' + stateClass(record.path_state)}
                          title={pres.tooltip}>
                          <span className="nfc-status-dot" />{pres.label}
                        </span>
                      </div>
                      <div className="nfc-mobile-record-facts nfc-mobile-record-facts-3">
                        <span>文件 <b>{record.files.toLocaleString()}</b></span>
                        <span>目录 <b>{record.folders.toLocaleString()}</b></span>
                        <span>最近索引 <b>{record.last_indexed_at ? formatDateTime(record.last_indexed_at) : '尚未完成'}</b></span>
                      </div>
                      {record.has_active_job && record.active_job_id && (
                        <div className="nfc-mobile-record-note">
                          任务 #{record.active_job_id} · {record.active_job_status}
                        </div>
                      )}
                      <div className="nfc-mobile-record-actions">{renderActions(record, true)}</div>
                    </article>
                  );
                })}
              </div>}
            />
            <ConsolePagination page={page} pageSize={pageSize}
              total={data?.total || 0} onChange={changePage} />
          </>
        )}
      </DataPanel>

      <ConsoleConfirmDialog open={removeTarget !== null} onOpenChange={closeRemove}
        title={'确认移除索引？' + (removeTarget ? ' · #' + removeTarget.id : '')}
        description={INDEX_REMOVE_DESCRIPTION}
        confirmText="移除" danger
        busy={removePending}
        disabled={!removeTarget || !getIndexRemoveAvailability(removeTarget).canRemove}
        onConfirm={() => { void handleRemove(); }} />

      <Dialog.Root open={modalOpen} onOpenChange={next => { if (!next) closeCreate(); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="nfc-v2-dialog-overlay nfc-v2-confirm-overlay" />
          <Dialog.Content
            className="nfc-v2-dialog nfc-overlay-modal nfc-index-create-modal nfc-v2-index-create-dialog"
            onEscapeKeyDown={event => { if (createMutation.isPending || createInFlight.current) event.preventDefault(); }}
            onPointerDownOutside={event => event.preventDefault()}>
            <header className="nfc-v2-dialog-heading">
              <span className="nfc-v2-dialog-icon"><ConsoleIcon name="folder-open" size={21} /></span>
              <div>
                <Dialog.Title>创建增量文件索引</Dialog.Title>
                <Dialog.Description className="nfc-v2-index-dialog-subtitle">
                  加入后台索引队列；目录必须位于 ALLOWED_ROOTS 允许的挂载路径内。
                </Dialog.Description>
              </div>
              <button type="button" className="nfc-v2-dialog-close" aria-label="关闭索引窗口"
                disabled={createMutation.isPending} onClick={closeCreate}>
                <ConsoleIcon name="x" size={18} />
              </button>
            </header>
            <form className="nfc-v2-index-form" onSubmit={event => { event.preventDefault(); void handleCreate(); }}>
              <label className="nfc-v2-index-form-label" id="index-create-root-label">目录路径</label>
              <div aria-labelledby="index-create-root-label">
                <DirectoryPicker multiple={false} allowManualInput={true}
                  value={rootDraft} disabled={createMutation.isPending}
                  onChange={value => {
                    setRootDraft(typeof value === 'string' ? value : value[0] || '');
                    setRootError('');
                  }} placeholder="点击选择要建立索引的根目录..." />
              </div>
              {rootError && <p className="nfc-v2-index-field-error" role="alert">{rootError}</p>}
              <p className="nfc-form-note">后台 Worker 将异步遍历该目录并生成 SQLite 增量索引，不会阻塞当前界面。服务端会再次校验目录白名单与访问规则。</p>
              <div className="nfc-v2-confirm-actions">
                <ConsoleButton disabled={createMutation.isPending} onClick={closeCreate}>取消</ConsoleButton>
                <ConsoleButton variant="primary" type="submit" loading={createMutation.isPending}
                  disabled={!rootDraft.trim()}>加入队列</ConsoleButton>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
};
