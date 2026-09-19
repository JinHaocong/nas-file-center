import React, { useState } from 'react';
import { Button, Empty, message, Pagination, Table } from 'antd';
import { ReloadOutlined, ScheduleOutlined } from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { plansApi } from '../../api/domain';
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

export const PlansPage: React.FC = () => {
  useTitle('执行计划');
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['plansList', page, pageSize],
    queryFn: () => plansApi.listPlans(page, pageSize),
    refetchInterval: (query) => {
      const items = query.state.data?.items || [];
      const hasActive = items.some((p: any) => p.status === 'validating' || p.status === 'executing');
      return hasActive ? 3000 : false;
    },
  });

  const deletePlanMutation = useMutation({
    mutationFn: (id: number) => plansApi.deletePlan(id),
    onMutate: (id) => setDeletingId(id),
    onSuccess: (_, id) => {
      message.success(`计划 #${id} 已安全删除`);
      queryClient.invalidateQueries({ queryKey: ['plansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      if (data?.items?.length === 1 && page > 1) {
        setPage((prev) => prev - 1);
      }
    },
    onError: (err: any, id: number) => {
      message.error(err.message || '删除计划失败');
      invalidatePlanDeleteFailure(queryClient, id);
    },
    onSettled: () => setDeletingId(null),
  });

  const items = data?.items || [];

  const columns = [
    {
      title: '计划名称',
      dataIndex: 'name',
      key: 'name',
      render: (text: string, record: any) => (
        <button type="button" className="nfc-plan-name" onClick={() => navigate(`/plans/${record.id}`)}>
          <ScheduleOutlined />
          <span>{text}</span>
        </button>
      ),
    },
    {
      title: '类型',
      dataIndex: 'kind',
      key: 'kind',
      width: 130,
      render: (kind: string) => <span className="nfc-kind-badge">{kind}</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 142,
      render: (status: string) => <StatusBadge status={status} />,
    },
    {
      title: '变更项',
      dataIndex: 'expected_changes',
      key: 'expected_changes',
      width: 108,
      render: (val: number) => <span className="nfc-mono">{val.toLocaleString()} 项</span>,
    },
    {
      title: '预计可释放',
      dataIndex: 'expected_reclaim_bytes',
      key: 'expected_reclaim_bytes',
      width: 126,
      render: (bytes: number) => (
        <span className={bytes > 0 ? 'nfc-data-emphasis' : 'nfc-table-muted'}>{formatBytes(bytes)}</span>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 174,
      render: (val: string) => <span className="nfc-table-meta">{formatDateTime(val)}</span>,
    },
    {
      title: '操作',
      key: 'action',
      width: 170,
      render: (_: any, record: any) => (
        <div className="nfc-row-actions">
          <Button size="small" type="text" onClick={() => navigate(`/plans/${record.id}`)}>
            查看与执行
          </Button>
          <PlanDeleteButton
            plan={record}
            onDelete={() => deletePlanMutation.mutate(record.id)}
            loading={deletingId === record.id}
            type="text"
          />
        </div>
      ),
    },
  ];

  return (
    <div className="nfc-operations-page nfc-plans-page">
      <PageHeader
        eyebrow="Execution control"
        title="执行计划"
        description="Dry Run 计划生命周期：Draft → Frozen → Validate → Execute。任何真实文件变更都必须经过计划链路。"
        actions={
          <ActionBar compact>
            <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isFetching}>
              刷新
            </Button>
            <PlanHistoryCleanupModal />
          </ActionBar>
        }
      />

      <LegacyPlanCleanup />

      <DataPanel
        title="计划列表"
        description="计划状态、预期变更与可释放容量均来自当前 BatchPlan。"
        action={<span className="nfc-panel-count">{data?.total ?? 0} plans</span>}
        className="nfc-panel-flush"
        variant="dense"
      >
        <ResponsiveDataView
          desktop={
            <Table
              dataSource={items}
              columns={columns}
              rowKey="id"
              loading={isLoading}
              pagination={{
                current: page,
                pageSize,
                total: data?.total || 0,
                showSizeChanger: true,
                pageSizeOptions: ['10', '20', '50', '100'],
                onChange: (p, ps) => {
                  setPage(p);
                  setPageSize(ps);
                },
              }}
            />
          }
          mobile={
            <>
              <div className="nfc-mobile-record-list">
                {items.length === 0 ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无执行计划" />
                ) : (
                  items.map((plan: any) => (
                    <article className="nfc-plan-mobile-card" key={plan.id}>
                      <div className="nfc-mobile-record-heading">
                        <div className="nfc-plan-mobile-heading-copy">
                          <button
                            type="button"
                            className="nfc-mobile-record-title"
                            onClick={() => navigate(`/plans/${plan.id}`)}
                          >
                            {plan.name}
                          </button>
                          <span className="nfc-kind-badge">{plan.kind}</span>
                        </div>
                        <StatusBadge status={plan.status} />
                      </div>

                      <div className="nfc-mobile-record-facts nfc-mobile-record-facts-3">
                        <span>变更项 <b>{plan.expected_changes?.toLocaleString?.() ?? plan.expected_changes}</b></span>
                        <span>可释放 <b>{formatBytes(plan.expected_reclaim_bytes || 0)}</b></span>
                        <span>创建 <b>{formatDateTime(plan.created_at)}</b></span>
                      </div>

                      <div className="nfc-mobile-record-actions">
                        <Button type="text" onClick={() => navigate(`/plans/${plan.id}`)}>
                          查看与执行
                        </Button>
                        <PlanDeleteButton
                          plan={plan}
                          onDelete={() => deletePlanMutation.mutate(plan.id)}
                          loading={deletingId === plan.id}
                          type="text"
                          size="middle"
                        />
                      </div>
                    </article>
                  ))
                )}
              </div>
              <div className="nfc-mobile-pagination">
                <Pagination
                  current={page}
                  pageSize={pageSize}
                  total={data?.total || 0}
                  showSizeChanger
                  pageSizeOptions={['10', '20', '50', '100']}
                  onChange={(p, ps) => {
                    setPage(p);
                    setPageSize(ps);
                  }}
                />
              </div>
            </>
          }
        />
      </DataPanel>
    </div>
  );
};
