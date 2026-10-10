import React, { useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { getStructuredApiError } from '../../api/errors';
import type { WorkflowListItem } from '../../types/workflow';
import { RevisionDrawer } from '../../components/workflows/RevisionDrawer';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { useAuth } from '../../contexts/AuthContext';
import {
  canArchiveWorkflow, canCreateWorkflow, canPermanentlyDeleteWorkflow,
} from '../../utils/workflowRbac';
import {
  getAuthorizedWorkflowListTarget, type WorkflowListIntent,
} from '../../utils/workflowListActions';
import { getPaginationState } from '../../components/ui/paginationModel';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

const modeLabel = (mode: WorkflowListItem['mode']) => {
  if (mode === 'dedupe') return '高级去重流';
  if (mode === 'organizer') return '目录整理流';
  if (mode === 'utility') return '目录工具流';
  return '文件规则流';
};

export const WorkflowListPage: React.FC = () => {
  useTitle('工作流中心');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const toast = useConsoleToast();
  const mutationInFlight = useRef(false);

  const [includeArchived, setIncludeArchived] = useState(false);
  const [selectedWorkflowForRevision, setSelectedWorkflowForRevision] = useState<WorkflowListItem | null>(null);
  const [confirmation, setConfirmation] = useState<WorkflowListIntent | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(15);

  const { data: workflows, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['workflowsList', includeArchived],
    queryFn: () => workflowApi.listWorkflows(includeArchived),
  });

  const archiveMutation = useMutation({
    mutationFn: (workflow: WorkflowListItem) =>
      workflowApi.archiveWorkflow(workflow.id, workflow.current_revision),
    onSuccess: () => {
      toast.success('工作流已成功归档');
      setConfirmation(null);
      void queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
      void refetch();
    },
    onError: err => {
      setConfirmation(null);
      toast.error(getStructuredApiError(err).message || '归档失败');
    },
    onSettled: () => { mutationInFlight.current = false; },
  });

  const permanentDeleteMutation = useMutation({
    mutationFn: (workflow: WorkflowListItem) =>
      workflowApi.permanentlyDeleteWorkflow(workflow.id, workflow.current_revision),
    onSuccess: (_, workflow) => {
      toast.success(`工作流「${workflow.name}」及其版本历史已彻底删除`);
      setConfirmation(null);
      if (selectedWorkflowForRevision?.id === workflow.id) {
        setSelectedWorkflowForRevision(null);
      }
      void queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
      void refetch();
    },
    onError: err => {
      setConfirmation(null);
      toast.error(getStructuredApiError(err).message || '彻底删除工作流失败');
    },
    onSettled: () => { mutationInFlight.current = false; },
  });

  const items = workflows || [];
  const { current: currentPage } = getPaginationState(page, pageSize, items.length);
  const visibleItems = useMemo(
    () => items.slice((currentPage - 1) * pageSize, currentPage * pageSize),
    [items, currentPage, pageSize],
  );
  const busy = archiveMutation.isPending || permanentDeleteMutation.isPending;
  const confirmTarget = getAuthorizedWorkflowListTarget(
    confirmation, items, user?.role, busy || mutationInFlight.current,
  );

  const requestAction = (kind: WorkflowListIntent['kind'], workflow: WorkflowListItem) => {
    if (busy || mutationInFlight.current) return;
    const intent: WorkflowListIntent = {
      kind, workflowId: workflow.id, expectedRevision: workflow.current_revision,
    };
    if (!getAuthorizedWorkflowListTarget(intent, items, user?.role, false)) return;
    setConfirmation(intent);
  };

  const handleConfirmAction = () => {
    if (!confirmation || busy || mutationInFlight.current) return;
    // Recheck against the current query snapshot, current RBAC and frozen revision.
    const workflow = getAuthorizedWorkflowListTarget(confirmation, items, user?.role, false);
    if (!workflow) { setConfirmation(null); return; }
    mutationInFlight.current = true;
    if (confirmation.kind === 'archive') archiveMutation.mutate(workflow);
    else permanentDeleteMutation.mutate(workflow);
  };

  const renderActions = (workflow: WorkflowListItem, mobile = false) => (
    <div className={mobile ? 'nfc-mobile-record-actions nfc-v2-workflow-actions' : 'nfc-row-actions nfc-v2-workflow-actions'}>
      <ConsoleButton variant="ghost" size="sm"
        leadingIcon={<ConsoleIcon name="pencil" size={15} />}
        onClick={() => navigate(`/workflows/${workflow.id}`)}>
        {workflow.is_builtin ? '查看/试运行' : '编排配置'}
      </ConsoleButton>
      <ConsoleButton variant="ghost" size="sm"
        leadingIcon={<ConsoleIcon name="history" size={15} />}
        onClick={() => setSelectedWorkflowForRevision(workflow)}>
        {mobile ? '版本历史' : '版本'}
      </ConsoleButton>
      {!workflow.is_builtin && !workflow.archived_at &&
        canArchiveWorkflow(user?.role, Boolean(workflow.archived_at)) && (
          <ConsoleButton variant="danger" size="sm"
            leadingIcon={<ConsoleIcon name="archive" size={15} />}
            disabled={busy} onClick={() => requestAction('archive', workflow)}>
            归档
          </ConsoleButton>
        )}
      {canPermanentlyDeleteWorkflow(user?.role, Boolean(workflow.archived_at), workflow.is_builtin) && (
        <ConsoleButton variant="danger" size="sm"
          leadingIcon={<ConsoleIcon name="trash" size={15} />}
          disabled={busy} onClick={() => requestAction('delete', workflow)}>
          彻底删除
        </ConsoleButton>
      )}
    </div>
  );

  return (
    <div className="nfc-operations-page nfc-workflows-page nfc-v2-workflow-list-page nfc-page-layout-ledger">
      <PageHeader
        eyebrow="Automation workflows"
        title="工作流编排中心"
        description="以版本化定义编排 NAS 文件规则、目录整理、高级去重和目录工具；Preview 与 Draft 都不会直接执行文件操作。"
        actions={
          <ActionBar compact>
            <label className="nfc-v2-workflow-archive-filter">
              <input type="checkbox" checked={includeArchived}
                onChange={event => {
                  setIncludeArchived(event.target.checked);
                  setPage(1);
                  setConfirmation(null);
                }} />
              <span>包含已归档</span>
            </label>
            <ConsoleButton loading={isFetching}
              leadingIcon={<ConsoleIcon name="refresh" size={16} />}
              onClick={() => { void refetch(); }}>
              刷新
            </ConsoleButton>
            {canCreateWorkflow(user?.role) && (
              <ConsoleButton variant="primary"
                leadingIcon={<ConsoleIcon name="plus" size={16} />}
                onClick={() => navigate('/workflows/new')}>新建工作流</ConsoleButton>
            )}
          </ActionBar>
        }
      />
      <DataPanel
        title="工作流定义"
        description="工作流保存为修订版本；内置与归档定义保持只读。"
        action={<span className="nfc-panel-count">{items.length} workflows</span>}
        className="nfc-panel-flush"
        variant="dense">
        {isError && (
          <div role="alert" className="nfc-v2-workflow-list-error">
            <strong>获取工作流列表失败</strong>
            <p>{getStructuredApiError(error).message}</p>
            <ConsoleButton onClick={() => { void refetch(); }}>重试</ConsoleButton>
          </div>
        )}
        {isLoading && (
          <div role="status" className="nfc-v2-workflow-list-loading">
            <span className="nfc-console-spinner" aria-hidden="true" />
            加载工作流中…
          </div>
        )}
        {!isLoading && !isError && items.length === 0 && (
          <ConsoleEmpty title="暂无工作流" description="当前筛选下尚无工作流定义。" />
        )}
        {!isLoading && !isError && items.length > 0 && (
          <>
            <ResponsiveDataView
              desktop={
                <div className="nfc-v2-workflow-table-scroll">
                  <table className="nfc-v2-workflow-table">
                    <caption className="nfc-v2-workflow-sr-only">工作流定义、版本、状态与操作</caption>
                    <thead><tr>
                      <th scope="col">ID</th><th scope="col">工作流</th>
                      <th scope="col">模式</th><th scope="col">版本</th>
                      <th scope="col">类别</th><th scope="col">状态</th>
                      <th scope="col">更新时间</th><th scope="col">操作</th>
                    </tr></thead>
                    <tbody>
                      {visibleItems.map(workflow => (
                        <tr key={workflow.id}>
                          <td className="nfc-mono">#{workflow.id}</td>
                          <td><button type="button" className="nfc-workflow-name"
                            onClick={() => navigate(`/workflows/${workflow.id}`)}>
                            <strong>{workflow.name}</strong>
                            {workflow.description && <span>{workflow.description}</span>}
                          </button></td>
                          <td><span className="nfc-kind-badge">{modeLabel(workflow.mode)}</span></td>
                          <td className="nfc-mono">r{workflow.current_revision}</td>
                          <td><span className="nfc-kind-badge">{workflow.is_builtin ? 'builtin' : 'user'}</span></td>
                          <td><StatusBadge status={workflow.archived_at ? 'stale' : 'completed'}
                            label={workflow.archived_at ? '已归档' : '启用中'} /></td>
                          <td><time dateTime={workflow.updated_at} className="nfc-table-meta">
                            {formatDateTime(workflow.updated_at)}
                          </time></td>
                          <td>{renderActions(workflow)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              }
              mobile={
                <div className="nfc-mobile-record-list nfc-v2-workflow-mobile-list">
                  {visibleItems.map(workflow => (
                    <article className="nfc-workflow-mobile-card" key={workflow.id}>
                      <div className="nfc-mobile-record-heading">
                        <div className="nfc-plan-mobile-heading-copy">
                          <button type="button" className="nfc-mobile-record-title"
                            onClick={() => navigate(`/workflows/${workflow.id}`)}>
                            {workflow.name}
                          </button>
                          <div className="nfc-inline-badges">
                            <span className="nfc-kind-badge">{modeLabel(workflow.mode)}</span>
                            <span className="nfc-kind-badge">{workflow.is_builtin ? 'builtin' : 'user'}</span>
                          </div>
                        </div>
                        <StatusBadge status={workflow.archived_at ? 'stale' : 'completed'}
                          label={workflow.archived_at ? '已归档' : '启用中'} />
                      </div>
                      {workflow.description && <p className="nfc-mobile-record-note">{workflow.description}</p>}
                      <div className="nfc-mobile-record-facts">
                        <span>版本 <b className="nfc-mono">r{workflow.current_revision}</b></span>
                        <span>更新 <b>{formatDateTime(workflow.updated_at)}</b></span>
                      </div>
                      {renderActions(workflow, true)}
                    </article>
                  ))}
                </div>
              }
            />
            <ConsolePagination page={currentPage} pageSize={pageSize} total={items.length}
              pageSizes={[15, 30, 60]}
              onChange={(nextPage, nextPageSize) => {
                setPage(nextPage);
                setPageSize(nextPageSize);
              }}
            />
          </>
        )}
      </DataPanel>

      {selectedWorkflowForRevision && (
        <RevisionDrawer
          open={Boolean(selectedWorkflowForRevision)}
          workflowId={selectedWorkflowForRevision.id}
          currentRevision={selectedWorkflowForRevision.current_revision}
          isBuiltin={selectedWorkflowForRevision.is_builtin}
          isArchived={Boolean(selectedWorkflowForRevision.archived_at)}
          onClose={() => setSelectedWorkflowForRevision(null)}
          onRollbackSuccess={() => {
            void queryClient.invalidateQueries({ queryKey: ['workflowsList'] });
            void refetch();
          }}
        />
      )}
      <ConsoleConfirmDialog open={confirmation !== null}
        onOpenChange={next => { if (!next && !busy && !mutationInFlight.current) setConfirmation(null); }}
        title={confirmation?.kind === 'delete' ? '彻底删除此已归档工作流？' : '确认归档此工作流？'}
        description={confirmation?.kind === 'delete'
          ? '工作流定义和全部修订版本将从数据库删除。若仍有可执行计划依赖，服务端会拒绝本操作。'
          : '归档后工作流进入只读封存态，不再执行任何计划构建。'}
        confirmText={confirmation?.kind === 'delete' ? '彻底删除' : '确认归档'}
        danger busy={busy || mutationInFlight.current}
        disabled={!confirmTarget} onConfirm={handleConfirmAction}
      />
    </div>
  );
};
