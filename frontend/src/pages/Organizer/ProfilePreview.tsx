import React, { useEffect, useState } from 'react';
import {
  Alert,
  Button,
  Empty,
  Form,
  Pagination,
  Radio,
  Table,
  Tooltip,
  message,
} from 'antd';
import {
  ArrowLeftOutlined,
  ArrowRightOutlined,
  EyeOutlined,
  ScheduleOutlined,
} from '@ant-design/icons';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { organizerProfilesApi } from '../../api/organizerProfiles';
import {
  OrganizerPreviewSummary,
  OrganizerProfile,
  OrganizerProposal,
} from '../../types';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { formatBytes } from '../../utils/format';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { MetricCard } from '../../components/ui/MetricCard';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';

interface ProfilePreviewProps {
  profile: OrganizerProfile;
  onBack: () => void;
}

export const ProfilePreview: React.FC<ProfilePreviewProps> = ({
  profile,
  onBack,
}) => {
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [currentRoot, setCurrentRoot] = useState(profile.root || '');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [filterMode, setFilterMode] = useState<'all' | 'changed' | 'conflicts'>('all');

  const [proposals, setProposals] = useState<OrganizerProposal[]>([]);
  const [summary, setSummary] = useState<OrganizerPreviewSummary | null>(null);
  const [totalItems, setTotalItems] = useState(0);
  const [hasPreviewed, setHasPreviewed] = useState(false);
  const [snapshotId, setSnapshotId] = useState<string | undefined>(undefined);
  const [previewDigest, setPreviewDigest] = useState<string | undefined>(undefined);
  const [advancedEnabled, setAdvancedEnabled] = useState(false);
  const [structuralRequired, setStructuralRequired] = useState(false);

  useEffect(() => {
    form.setFieldsValue({ root: profile.root || '' });
    setCurrentRoot(profile.root || '');
  }, [profile, form]);

  const previewMutation = useMutation({
    mutationFn: (params: {
      root: string;
      page: number;
      pageSize: number;
      onlyChanged: boolean;
      onlyConflicts: boolean;
      snapshotId?: string;
    }) =>
      organizerProfilesApi.previewProfile(profile.id, {
        root: params.root,
        page: params.page,
        page_size: params.pageSize,
        only_changed: params.onlyChanged,
        only_conflicts: params.onlyConflicts,
        snapshot_id: params.snapshotId,
      }),
    onSuccess: (result) => {
      setProposals(result.proposals);
      setSummary(result.summary);
      setTotalItems(result.total);
      setHasPreviewed(true);
      setPreviewDigest(result.preview_digest);
      setAdvancedEnabled(Boolean(result.advanced_enabled));
      setStructuralRequired(Boolean(result.structural_required));
      if (result.snapshot_id) {
        setSnapshotId(result.snapshot_id);
      }
    },
    onError: (err: any) => {
      message.error(err.message || '预览计算失败');
    },
  });

  const planMutation = useMutation({
    mutationFn: (params: { root: string; expectedPreviewDigest?: string }) =>
      organizerProfilesApi.createPlan(profile.id, {
        root: params.root,
        include_touch: profile.mtime_mode === 'ordered',
        expected_preview_digest: params.expectedPreviewDigest,
      }),
    onSuccess: (result) => {
      message.success(
        structuralRequired
          ? `Stage A 结构计划 #${result.id} 已生成；执行完成后必须重新 Preview 才能进入 Stage B`
          : advancedEnabled
          ? `Stage B 重命名计划 #${result.id} 已生成`
          : `已生成整理计划 #${result.id}`
      );
      navigate(`/plans/${result.id}`);
    },
    onError: (err: any) => {
      message.error(err.message || '生成计划失败');
    },
  });

  const fetchPreview = (
    targetPage = page,
    targetPageSize = pageSize,
    selectedFilter: 'all' | 'changed' | 'conflicts' = filterMode,
    currentSnapshotId: string | undefined = snapshotId
  ) => {
    const rootValue = (form.getFieldValue('root') || currentRoot || '').trim();
    if (!rootValue) {
      message.warning('请先选择或输入整理根目录');
      return;
    }
    previewMutation.mutate({
      root: rootValue,
      page: targetPage,
      pageSize: targetPageSize,
      onlyChanged: selectedFilter === 'changed',
      onlyConflicts: selectedFilter === 'conflicts',
      snapshotId: currentSnapshotId,
    });
  };

  const handlePreviewClick = async () => {
    try {
      const values = await form.validateFields();
      setCurrentRoot(values.root.trim());
      setPage(1);
      setSnapshotId(undefined);
      setPreviewDigest(undefined);
      setAdvancedEnabled(false);
      setStructuralRequired(false);
      fetchPreview(1, pageSize, filterMode, undefined);
    } catch {
      // AntD handles validation presentation.
    }
  };

  const handleFilterChange = (selectedFilter: 'all' | 'changed' | 'conflicts') => {
    setFilterMode(selectedFilter);
    setPage(1);
    if (hasPreviewed) {
      fetchPreview(1, pageSize, selectedFilter, snapshotId);
    }
  };

  const handlePageChange = (nextPage: number, nextPageSize: number) => {
    setPage(nextPage);
    setPageSize(nextPageSize);
    fetchPreview(nextPage, nextPageSize, filterMode, snapshotId);
  };

  const actionableChanges = summary
    ? Math.max(summary.advanced_changes ?? 0, summary.changed_directories ?? 0)
    : 0;
  const canGeneratePlan =
    Boolean(summary) &&
    summary!.conflicts === 0 &&
    (!advancedEnabled || Boolean(previewDigest)) &&
    (structuralRequired ||
      actionableChanges > 0 ||
      (profile.mtime_mode === 'ordered' && summary!.total_directories > 0));

  const previewStageLabel = structuralRequired
    ? 'Stage A · Structural'
    : advancedEnabled
    ? 'Stage B · Rename'
    : 'Standard';

  const handleGeneratePlan = () => {
    const rootValue = (form.getFieldValue('root') || currentRoot || '').trim();
    if (!rootValue) {
      message.warning('请选择整理根目录');
      return;
    }
    if (summary && summary.conflicts > 0) {
      message.error(`当前存在 ${summary.conflicts} 个冲突项，请解决冲突后再生成计划`);
      return;
    }
    if (!canGeneratePlan) {
      message.info('当前没有需要执行的整理操作');
      return;
    }
    if (advancedEnabled && !previewDigest) {
      message.error('Advanced Rules 缺少 preview digest，请重新 Preview');
      return;
    }
    planMutation.mutate({
      root: rootValue,
      expectedPreviewDigest: advancedEnabled ? previewDigest : undefined,
    });
  };

  const statusForProposal = (proposal: OrganizerProposal) => {
    if (proposal.conflict) {
      return <StatusBadge status="failed" label="冲突" />;
    }
    if (proposal.proposal_type === 'wrapper_collapse' && proposal.changed) {
      return <StatusBadge status="validating" label="Stage A" />;
    }
    if (proposal.changed) {
      return <StatusBadge status="validating" label="Stage B" />;
    }
    return <StatusBadge status="completed" label="已规范" />;
  };

  const proposalRuleLabel = (proposal: OrganizerProposal) => {
    const labels: Record<string, string> = {
      wrapper_collapse: 'Wrapper collapse',
      directory_rename: 'Directory rename',
      file_rename: 'File numbering',
      latest_child_prefix: 'Latest prefix',
      touch: 'mtime',
    };
    return labels[proposal.proposal_type] || proposal.proposal_type || 'Legacy';
  };

  const columns = [
    {
      title: '阶段 / 规则',
      key: 'stage',
      width: 170,
      render: (_: unknown, record: OrganizerProposal) => (
        <div className="nfc-inline-badges">
          <span className="nfc-kind-badge">
            {record.proposal_type === 'wrapper_collapse' ? 'Stage A' : 'Stage B'}
          </span>
          <span className="nfc-kind-badge">{proposalRuleLabel(record)}</span>
        </div>
      ),
    },
    {
      title: '原路径',
      dataIndex: 'source',
      key: 'source',
      render: (value: string) => <CodePath value={value} />,
    },
    {
      title: '预计目标',
      dataIndex: 'target',
      key: 'target',
      render: (value: string, record: OrganizerProposal) => (
        <div className="nfc-target-path">
          {record.changed && <ArrowRightOutlined />}
          <CodePath value={value} muted={!record.changed} />
        </div>
      ),
    },
    {
      title: '统计',
      key: 'stats',
      width: 230,
      render: (_: unknown, record: OrganizerProposal) => (
        <div className="nfc-inline-badges">
          <span className="nfc-kind-badge">{record.images} P</span>
          {record.videos > 0 && (
            <span className="nfc-kind-badge">{record.videos} V</span>
          )}
          <span className="nfc-kind-badge">{formatBytes(record.total_bytes)}</span>
          {record.preserved_tags?.map((tag) => (
            <span className="nfc-kind-badge" key={tag}>{tag}</span>
          ))}
        </div>
      ),
    },
    {
      title: '状态',
      key: 'status',
      width: 120,
      render: (_: unknown, record: OrganizerProposal) =>
        record.conflict ? (
          <Tooltip title={record.conflict_reason || '重命名冲突'}>
            {statusForProposal(record)}
          </Tooltip>
        ) : (
          statusForProposal(record)
        ),
    },
  ];

  return (
    <div className="nfc-organizer-preview nfc-organizer-preview-page nfc-operations-page nfc-page-layout-workbench">
      <PageHeader
        title={profile.name}
        description={
          <div className="nfc-plan-header-meta">
            {profile.is_builtin && <span className="nfc-kind-badge">builtin</span>}
            {profile.description && <span>{profile.description}</span>}
          </div>
        }
        actions={
          <ActionBar compact>
            <Button icon={<ArrowLeftOutlined />} onClick={onBack}>
              返回方案列表
            </Button>
          </ActionBar>
        }
      />

      <DataPanel
        title="整理目标"
        description="Advanced Rules 使用 digest-bound staged Preview：Stage A 结构整理完成后必须 fresh Preview，才会进入 Stage B。"
        className="nfc-complex-form-panel"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="root"
            label="整理目标根目录"
            rules={[{ required: true, message: '请选择整理根目录' }]}
            extra="路径必须在 ALLOWED_ROOTS 白名单内"
          >
            <DirectoryPicker
              multiple={false}
              placeholder="点击选择整理根目录..."
            />
          </Form.Item>

          <ActionBar>
            <Button
              type="primary"
              icon={<EyeOutlined />}
              onClick={handlePreviewClick}
              loading={previewMutation.isPending}
            >
              执行只读预览
            </Button>
            {hasPreviewed && summary && (
              <Button
                icon={<ScheduleOutlined />}
                onClick={handleGeneratePlan}
                loading={planMutation.isPending}
                disabled={!canGeneratePlan}
              >
                {structuralRequired
                  ? '生成 Stage A 结构 Plan'
                  : advancedEnabled
                  ? '生成 Stage B 重命名 Plan'
                  : '生成整理 Plan'}
                {actionableChanges > 0
                  ? ` (${actionableChanges} 项待变更)`
                  : profile.mtime_mode === 'ordered'
                  ? ` (${summary.total_directories} 项 mtime 刷新)`
                  : ''}
              </Button>
            )}
            {snapshotId && (
              <span className="nfc-panel-count">
                {previewStageLabel} · snapshot {snapshotId.slice(0, 12)}
              </span>
            )}
          </ActionBar>
        </Form>
      </DataPanel>

      {summary && (
        <>
          {advancedEnabled && structuralRequired && (
            <Alert
              type="warning"
              showIcon
              message="Stage A Structural Preview：Stage B 已锁定"
              description="当前树包含可折叠的 single-child wrapper。这里只能生成 Stage A MOVE → rmdir_empty 结构计划；执行完成后当前 Preview 立即作废，必须重新 Preview 后才能生成 Stage B。"
              className="nfc-page-alert nfc-organizer-stage-alert"
            />
          )}

          {advancedEnabled && !structuralRequired && (
            <Alert
              type="success"
              showIcon
              message="Stage B Rename Preview 已就绪"
              description="当前 fresh Preview 不再需要结构变更，可基于此 preview digest 生成目录/文件/prefix 重命名计划。"
              className="nfc-page-alert nfc-organizer-stage-alert"
            />
          )}

          {advancedEnabled && previewDigest && (
            <div className="nfc-organizer-preview-digest">
              <span className="nfc-panel-count">preview digest</span>
              <code>{previewDigest}</code>
            </div>
          )}

          <div className="nfc-metric-grid nfc-organizer-metric-grid">
            <MetricCard
              label="检测目录"
              value={summary.total_directories.toLocaleString()}
              meta="当前 snapshot"
            />
            <MetricCard
              label={structuralRequired ? "Stage A 候选" : "待变更"}
              value={(structuralRequired ? (summary.wrapper_candidates ?? 0) : actionableChanges).toLocaleString()}
              meta={structuralRequired ? "仅结构阶段可生成" : "Stage B / 标准操作"}
              tone="attention"
            />
            <MetricCard
              label="命名冲突"
              value={summary.conflicts.toLocaleString()}
              meta={summary.conflicts > 0 ? 'Plan 已锁定' : '无阻塞冲突'}
              tone={summary.conflicts > 0 ? 'danger' : 'success'}
            />
            <MetricCard
              label="扫描容量"
              value={formatBytes(summary.total_bytes)}
              meta="只读统计"
            />
          </div>

          {summary.conflicts > 0 && (
            <Alert
              type="error"
              showIcon
              message={`检测到 ${summary.conflicts} 个目标命名冲突`}
              description="Preview 返回了 blocking conflict。目标碰撞、时间戳并列、wrapper 形状/目标异常等冲突都会 fail-closed 禁止生成 Plan。"
              className="nfc-page-alert"
            />
          )}

          <DataPanel
            title={structuralRequired ? "Stage A / Stage B 分段提议" : "整理提议"}
            description={structuralRequired
              ? "Wrapper collapse 标记为 Stage A；其余 rename/file/prefix 提议属于 Stage B，仅供参考并被锁定，必须在 Stage A 完成后重新 Preview。"
              : "同一 snapshot 下切换过滤和分页，保持 digest 与预览口径一致。" }
            action={<span className="nfc-panel-count">{totalItems} proposals</span>}
            className="nfc-panel-flush"
            variant="dense"
          >
            <ActionBar className="nfc-filter-bar nfc-organizer-preview-filter">
              <Radio.Group
                value={filterMode}
                onChange={(event) => handleFilterChange(event.target.value)}
              >
                <Radio.Button value="all">
                  全部 ({summary.total_directories})
                </Radio.Button>
                <Radio.Button value="changed">
                  待变更 ({actionableChanges})
                </Radio.Button>
                <Radio.Button value="conflicts">
                  冲突 ({summary.conflicts})
                </Radio.Button>
              </Radio.Group>
            </ActionBar>

            <ResponsiveDataView
              desktop={
                <Table
                  dataSource={proposals}
                  columns={columns}
                  rowKey="source"
                  loading={previewMutation.isPending}
                  pagination={{
                    current: page,
                    pageSize,
                    total: totalItems,
                    showSizeChanger: true,
                    onChange: handlePageChange,
                  }}
                />
              }
              mobile={
                <>
                  <div className="nfc-mobile-record-list">
                    {proposals.length === 0 ? (
                      <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description="当前过滤下无整理提议"
                      />
                    ) : (
                      proposals.map((proposal) => (
                        <article
                          className="nfc-organizer-proposal-mobile-card"
                          key={proposal.source}
                        >
                          <div className="nfc-mobile-record-heading">
                            <div className="nfc-inline-badges">
                              <span className="nfc-kind-badge">
                                {proposal.proposal_type === 'wrapper_collapse' ? 'Stage A' : 'Stage B'}
                              </span>
                              <span className="nfc-kind-badge">{proposalRuleLabel(proposal)}</span>
                              <span className="nfc-kind-badge">
                                {proposal.images} P
                              </span>
                              {proposal.videos > 0 && (
                                <span className="nfc-kind-badge">
                                  {proposal.videos} V
                                </span>
                              )}
                              <span className="nfc-kind-badge">
                                {formatBytes(proposal.total_bytes)}
                              </span>
                            </div>
                            {statusForProposal(proposal)}
                          </div>
                          <div className="nfc-plan-item-paths">
                            <div className="nfc-plan-item-path-row">
                              <span>源目录</span>
                              <CodePath value={proposal.source} />
                            </div>
                            <div className="nfc-plan-item-path-row">
                              <span>目标</span>
                              <CodePath
                                value={proposal.target}
                                muted={!proposal.changed}
                              />
                            </div>
                          </div>
                          {proposal.conflict && (
                            <p className="nfc-mobile-record-error">
                              {proposal.conflict_reason || '重命名冲突'}
                            </p>
                          )}
                        </article>
                      ))
                    )}
                  </div>
                  <div className="nfc-mobile-pagination">
                    <Pagination
                      current={page}
                      pageSize={pageSize}
                      total={totalItems}
                      showSizeChanger
                      onChange={handlePageChange}
                    />
                  </div>
                </>
              }
            />
          </DataPanel>
        </>
      )}
    </div>
  );
};
