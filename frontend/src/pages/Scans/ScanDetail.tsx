import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Alert,
  Button,
  Empty,
  Pagination,
  Spin,
  Table,
  Tooltip,
  message,
} from 'antd';
import {
  ArrowLeftOutlined,
  ReloadOutlined,
  ScheduleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { scansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { DedupePlanModal } from './DedupePlanModal';
import { DuplicateGroup } from '../../types';
import { ScanDeleteButton } from '../../components/scans/ScanDeleteButton';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { CodePath } from '../../components/ui/CodePath';

export const ScanDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const scanId = Number(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  useTitle(`扫描详情 #${scanId}`);

  const [planModalOpen, setPlanModalOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const deleteScanMutation = useMutation({
    mutationFn: () => scansApi.deleteScan(scanId),
    onSuccess: () => {
      message.success(`扫描 #${scanId} 已成功删除`);
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      navigate('/scans');
    },
    onError: (err: any) => {
      message.error(err.message || '删除扫描失败');
    },
  });

  const { data: scan, isLoading: scanLoading, isFetching: scanFetching, refetch: refetchScan } = useQuery({
    queryKey: ['scanDetail', scanId],
    queryFn: () => scansApi.getScanDetail(scanId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 3000 : false;
    },
  });

  const { data: groupsData, isLoading: groupsLoading, refetch: refetchGroups } = useQuery({
    queryKey: ['scanGroups', scanId, page, pageSize],
    queryFn: () => scansApi.getScanGroups(scanId, page, pageSize),
    enabled: scan?.status === 'completed',
  });

  if (scanLoading) {
    return (
      <div className="nfc-centered-state">
        <Spin size="large" />
      </div>
    );
  }

  if (!scan) {
    return (
      <Alert
        message="扫描任务不存在"
        description={`未找到 ID 为 #${scanId} 的扫描任务`}
        type="error"
        showIcon
        action={<Button onClick={() => navigate('/scans')}>返回扫描列表</Button>}
      />
    );
  }

  const groupColumns = [
    {
      title: '组 ID',
      dataIndex: 'id',
      key: 'id',
      width: 82,
      render: (value: number) => <span className="nfc-mono">#{value}</span>,
    },
    {
      title: '内容哈希',
      dataIndex: 'content_hash',
      key: 'content_hash',
      render: (hash: string) => (
        <Tooltip title={hash}>
          <span className="nfc-mono nfc-hash-value">{hash.slice(0, 18)}…</span>
        </Tooltip>
      ),
    },
    {
      title: '单文件大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 118,
      render: (bytes: number) => formatBytes(bytes),
    },
    {
      title: '重复副本',
      dataIndex: 'member_count',
      key: 'member_count',
      width: 100,
      render: (count: number) => <span className="nfc-mono">{count} 份</span>,
    },
    {
      title: '预计可释放',
      dataIndex: 'reclaimable_bytes',
      key: 'reclaimable_bytes',
      width: 130,
      render: (bytes: number) => <span className="nfc-data-emphasis">{formatBytes(bytes)}</span>,
    },
  ];

  const expandedRowRender = (record: DuplicateGroup) => (
    <div className="nfc-duplicate-member-table">
      <Table
        columns={[
          {
            title: 'Root',
            dataIndex: 'root_id',
            key: 'root_id',
            width: 86,
            render: (rootId: number) => <span className="nfc-kind-badge">root #{rootId}</span>,
          },
          {
            title: '相对路径',
            dataIndex: 'relative_path',
            key: 'relative_path',
            render: (value: string) => <CodePath value={value} />,
          },
          {
            title: '完整路径',
            dataIndex: 'path',
            key: 'path',
            render: (value: string) => <CodePath value={value} />,
          },
          {
            title: '大小',
            dataIndex: 'size',
            key: 'size',
            width: 110,
            render: (bytes: number) => formatBytes(bytes),
          },
        ]}
        dataSource={record.members}
        pagination={false}
        rowKey="id"
        size="small"
      />
    </div>
  );

  const descriptionItems = [
    { label: '任务 ID', value: <span className="nfc-mono">#{scan.id}</span> },
    {
      label: '扫描模式',
      value: <span className="nfc-kind-badge">{scan.mode === 'isolate' ? 'A/B isolate' : 'standard'}</span>,
    },
    { label: '创建时间', value: formatDateTime(scan.created_at) },
    { label: '开始时间', value: scan.started_at ? formatDateTime(scan.started_at) : '—' },
    { label: '完成时间', value: scan.finished_at ? formatDateTime(scan.finished_at) : '—' },
    { label: '发现重复组数', value: `${scan.total_groups.toLocaleString()} 组`, emphasis: true },
    { label: '重复文件总数', value: `${scan.total_files_in_groups.toLocaleString()} 个`, emphasis: true },
    { label: '预计可释放容量', value: formatBytes(scan.reclaimable_bytes), emphasis: true },
  ];

  const groupItems = groupsData?.items || [];

  return (
    <div className="nfc-operations-page nfc-scan-detail-page">
      <PageHeader
        eyebrow="SCAN SNAPSHOT"
        title={scan.name}
        description={
          <div className="nfc-plan-header-meta">
            <span className="nfc-mono">Scan #{scan.id}</span>
            <StatusBadge status={scan.status} />
            {scan.has_dependent_plan && <span className="nfc-kind-badge">dependent plan</span>}
          </div>
        }
        actions={
          <ActionBar compact>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/scans')}>
              返回列表
            </Button>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                refetchScan();
                refetchGroups();
              }}
              loading={scanFetching}
            >
              刷新
            </Button>
            <ScanDeleteButton
              scan={scan}
              onDelete={() => deleteScanMutation.mutate()}
              loading={deleteScanMutation.isPending}
              buttonText="删除扫描"
              type="default"
            />
            {scan.status === 'completed' && scan.total_groups > 0 && (
              <>
                <Button icon={<ScheduleOutlined />} onClick={() => setPlanModalOpen(true)}>
                  经典去重计划
                </Button>
                <Button
                  type="primary"
                  icon={<ThunderboltOutlined />}
                  onClick={() => navigate(`/scans/${scan.id}/dedupe`)}
                >
                  高级去重 (Advanced Dedupe)
                </Button>
              </>
            )}
          </ActionBar>
        }
      />

      {scan.error && (
        <Alert
          message="扫描执行失败"
          description={scan.error}
          type="error"
          showIcon
          className="nfc-page-alert"
        />
      )}

      <DataPanel
        title="扫描摘要"
        description="扫描结果是只读快照；后续文件操作必须通过 Plan 生命周期。"
        className="nfc-panel-flush nfc-scan-summary"
      >
        <ResponsiveDescriptions items={descriptionItems} />
        <div className="nfc-root-list">
          <span className="nfc-root-list-label">扫描根目录</span>
          <div className="nfc-root-list-values">
            {scan.roots.map((root, idx) => (
              <CodePath value={root} key={idx} />
            ))}
          </div>
        </div>
      </DataPanel>

      {scan.status === 'completed' && (
        <DataPanel
          title="重复文件组"
          description="展开组可查看每个成员；这里只展示扫描快照，不会直接修改文件。"
          action={<span className="nfc-panel-count">{groupsData?.total || 0} groups</span>}
          className="nfc-panel-flush"
        >
          <ResponsiveDataView
            desktop={
              <Table
                dataSource={groupItems}
                columns={groupColumns}
                rowKey="id"
                loading={groupsLoading}
                expandable={{ expandedRowRender }}
                pagination={{
                  current: page,
                  pageSize,
                  total: groupsData?.total || 0,
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
                  {groupItems.length === 0 ? (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无重复文件组" />
                  ) : (
                    groupItems.map((group) => (
                      <article className="nfc-duplicate-group-mobile-card" key={group.id}>
                        <div className="nfc-mobile-record-heading">
                          <div>
                            <span className="nfc-mobile-record-title nfc-mono">Group #{group.id}</span>
                            <span className="nfc-kind-badge">{group.member_count} copies</span>
                          </div>
                          <span className="nfc-data-emphasis">{formatBytes(group.reclaimable_bytes)}</span>
                        </div>
                        <div className="nfc-mobile-record-facts">
                          <span>单文件大小 <b>{formatBytes(group.file_size)}</b></span>
                          <span>Hash <b className="nfc-mono">{group.content_hash.slice(0, 14)}…</b></span>
                        </div>
                        <details className="nfc-duplicate-member-list">
                          <summary>查看 {group.members.length} 个成员</summary>
                          <div>
                            {group.members.map((member) => (
                              <div className="nfc-duplicate-member" key={member.id}>
                                <span className="nfc-kind-badge">root #{member.root_id}</span>
                                <CodePath value={member.path} />
                                <span className="nfc-table-meta">{formatBytes(member.size)}</span>
                              </div>
                            ))}
                          </div>
                        </details>
                      </article>
                    ))
                  )}
                </div>
                <div className="nfc-mobile-pagination">
                  <Pagination
                    current={page}
                    pageSize={pageSize}
                    total={groupsData?.total || 0}
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
      )}

      <DedupePlanModal scanId={scanId} open={planModalOpen} onClose={() => setPlanModalOpen(false)} />
    </div>
  );
};
