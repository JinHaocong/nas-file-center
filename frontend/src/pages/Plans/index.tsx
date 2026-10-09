import React, { useState } from 'react';
import { message } from 'antd';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { plansApi } from '../../api/domain';
import type { Plan } from '../../types';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { PlanDeleteButton } from '../../components/plans/PlanDeleteButton';
import { PlanHistoryCleanupModal } from '../../components/plans/PlanHistoryCleanupModal';
import { LegacyPlanCleanup } from '../../components/plans/LegacyPlanCleanup';
import { invalidatePlanDeleteFailure } from '../../components/plans/plan_cleanup';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';

export const PlansPage: React.FC = () => {
  useTitle('执行计划');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const { data, isLoading, isFetching, isError, refetch } = useQuery({
    queryKey: ['plansList', page, pageSize],
    queryFn: () => plansApi.listPlans(page, pageSize),
    refetchInterval: (query) => {
      const items = query.state.data?.items || [];
      const hasActive = items.some((p: Plan) =>
        p.status === 'validating' || p.status === 'executing'
      );
      return hasActive ? 3000 : false;
    },
  });

  const deletePlanMutation = useMutation({
    mutationFn: (id: number) => plansApi.deletePlan(id),
    onMutate: (id) => setDeletingId(id),
    onSuccess: (_, id) => {
      message.success('计划 #' + id + ' 已安全删除');
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      if (data?.items?.length === 1 && page > 1) {
        setPage(prev => prev - 1);
      }
    },
    onError: (err: any, id: number) => {
      message.error(err.message || '删除计划失败');
      invalidatePlanDeleteFailure(queryClient, id);
    },
    onSettled: () => setDeletingId(null),
  });

  const items: Plan[] = data?.items || [];
  const openPlan = (id: number) => navigate('/plans/' + id);
  const changePage = (nextPage: number, nextSize: number) => {
    if (nextSize !== pageSize) {
      setPageSize(nextSize);
      setPage(1);
    } else {
      setPage(nextPage);
    }
  };

  return (
    <div className="nfc-operations-page nfc-plans-page nfc-page-layout-ledger nfc-v2-plans-page">
      <PageHeader eyebrow="Execution control" title="执行计划"
        description="Dry Run 计划生命周期：Draft → Frozen → Validate → Execute。任何真实文件变更都必须经过计划链路。"
        actions={
          <ActionBar compact>
            <ConsoleButton loading={isFetching}
              leadingIcon={<ConsoleIcon name="refresh" size={16} />}
              onClick={() => refetch()}>刷新</ConsoleButton>
            <PlanHistoryCleanupModal />
          </ActionBar>
        }
      />
      <LegacyPlanCleanup />
      <DataPanel title="计划列表"
        description="显示计划状态、预期变更和预计可释放空间。点击任一计划查看校验与执行细节。"
        action={<span className="nfc-panel-count">{data?.total ?? 0} plans</span>}
        className="nfc-panel-flush" variant="dense">
        {isError ? (
          <div className="nfc-v2-plan-list-state">
            <ConsoleEmpty title="计划列表加载失败"
              description="请检查连接后重试。原有计划没有被修改。"
              action={<ConsoleButton onClick={() => refetch()}>重新加载</ConsoleButton>} />
          </div>
        ) : isLoading ? (
          <div className="nfc-v2-plan-list-state" role="status">正在加载执行计划…</div>
        ) : items.length === 0 ? (
          <ConsoleEmpty title="暂无执行计划"
            description="可以从扫描去重、批量整理或重命名预览创建计划草稿。" />
        ) : (
          <ResponsiveDataView
            desktop={
              <div className="nfc-v2-plan-table-scroll">
                <table className="nfc-v2-plan-table">
                  <thead><tr>
                    <th scope="col">计划名称</th>
                    <th scope="col">类型</th>
                    <th scope="col">状态</th>
                    <th scope="col">变更项</th>
                    <th scope="col">预计可释放</th>
                    <th scope="col">创建时间</th>
                    <th scope="col">操作</th>
                  </tr></thead>
                  <tbody>{items.map(plan => (
                    <tr key={plan.id}>
                      <td>
                        <button type="button" className="nfc-plan-name nfc-v2-plan-name"
                          onClick={() => openPlan(plan.id)}>
                          <ConsoleIcon name="file-text" size={18} />
                          <span>{plan.name}</span>
                        </button>
                        <small className="nfc-v2-plan-id">#{plan.id}</small>
                      </td>
                      <td><span className="nfc-kind-badge">{plan.kind}</span></td>
                      <td><StatusBadge status={plan.status} /></td>
                      <td className="nfc-v2-plan-number">{plan.expected_changes.toLocaleString()} 项</td>
                      <td className="nfc-v2-plan-number">
                        {formatBytes(plan.expected_reclaim_bytes || 0)}
                      </td>
                      <td className="nfc-v2-plan-date">{formatDateTime(plan.created_at)}</td>
                      <td><div className="nfc-row-actions">
                        <ConsoleButton size="sm" variant="ghost" onClick={() => openPlan(plan.id)}>
                          查看与执行
                        </ConsoleButton>
                        <PlanDeleteButton plan={plan}
                          onDelete={() => deletePlanMutation.mutate(plan.id)}
                          loading={deletingId === plan.id} type="text" />
                      </div></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            }
            mobile={
              <div className="nfc-mobile-record-list">
                {items.map(plan => (
                  <article className="nfc-plan-mobile-card" key={plan.id}>
                    <div className="nfc-mobile-record-heading">
                      <div className="nfc-plan-mobile-heading-copy">
                        <button type="button" className="nfc-mobile-record-title"
                          onClick={() => openPlan(plan.id)}>
                          {plan.name}
                        </button>
                        <span className="nfc-kind-badge">{plan.kind}</span>
                      </div>
                      <StatusBadge status={plan.status} />
                    </div>
                    <div className="nfc-mobile-record-facts nfc-mobile-record-facts-3">
                      <span>变更项 <b>{plan.expected_changes.toLocaleString()}</b></span>
                      <span>可释放 <b>{formatBytes(plan.expected_reclaim_bytes || 0)}</b></span>
                      <span>创建 <b>{formatDateTime(plan.created_at)}</b></span>
                    </div>
                    <div className="nfc-mobile-record-actions">
                      <ConsoleButton variant="ghost" size="sm"
                        onClick={() => openPlan(plan.id)}>查看与执行</ConsoleButton>
                      <PlanDeleteButton plan={plan}
                        onDelete={() => deletePlanMutation.mutate(plan.id)}
                        loading={deletingId === plan.id} type="text" size="middle" />
                    </div>
                  </article>
                ))}
              </div>
            }
          />
        )}
        {!isError && !isLoading && (data?.total || 0) > 0 && (
          <ConsolePagination page={page} pageSize={pageSize}
            total={data?.total || 0} onChange={changePage} />
        )}
      </DataPanel>
    </div>
  );
};
