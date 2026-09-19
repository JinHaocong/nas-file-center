import React, { useReducer, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import {
  Alert,
  Button,
  message,
  Modal,
  Spin,
} from 'antd';
import {
  ArrowLeftOutlined,
  ExclamationCircleOutlined,
  ReloadOutlined,
  ScheduleOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import { scansApi } from '../../api/domain';
import { formatDedupeErrorMessage, getStructuredApiError } from '../../api/errors';
import {
  DedupeScorerConfig,
  DirectDedupePreviewResponse,
  DedupePreviewMemberRow,
} from '../../types/dedupe';
import {
  createDefaultDedupeScorerConfig,
  isScorerConfigDirty,
  validateScorerConfigForm,
} from '../../utils/dedupeConfig';
import {
  dedupeStateReducer,
  initialDedupeState,
  canGeneratePlan,
} from '../../utils/dedupeState';
import {
  DedupeScorerConfigEditor,
  DedupePreviewTable,
  DedupePreviewSummaryPanel,
  DedupeExplainDrawer,
  DedupeIdentitySafetyPanel,
} from '../../components/dedupe';
import { formatBytes } from '../../utils/format';
import { shouldAcceptDirectResponse } from '../../utils/hotfix2Helpers';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { CodePath } from '../../components/ui/CodePath';

export const AdvancedDedupePage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const scanId = parseInt(id || '0', 10);
  const navigate = useNavigate();

  const [dedupeState, dispatch] = useReducer(dedupeStateReducer, initialDedupeState);
  const [scorerConfig, setScorerConfig] = useState<DedupeScorerConfig>(
    createDefaultDedupeScorerConfig()
  );
  const [previewedConfig, setPreviewedConfig] = useState<DedupeScorerConfig | null>(null);
  const [previewData, setPreviewData] = useState<DirectDedupePreviewResponse | null>(null);
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(50);
  const [selectedMember, setSelectedMember] = useState<DedupePreviewMemberRow | null>(null);
  const [explainOpen, setExplainOpen] = useState<boolean>(false);

  const {
    data: scan,
    isLoading: scanLoading,
    error: scanError,
  } = useQuery({
    queryKey: ['scanDetail', scanId],
    queryFn: () => scansApi.getScanDetail(scanId),
    enabled: !!scanId,
  });

  const handleConfigChange = (newConfig: DedupeScorerConfig) => {
    setScorerConfig(newConfig);
    dispatch({ type: 'CONFIG_EDITED' });
  };

  interface PreviewMutationVariables {
    cfg: DedupeScorerConfig;
    generation: number;
    page: number;
    pageSize: number;
  }

  const previewMutation = useMutation({
    mutationFn: (variables: PreviewMutationVariables) =>
      scansApi.dedupePreview(scanId, {
        scorer_config: variables.cfg,
        page: variables.page,
        page_size: variables.pageSize,
      }),
    onSuccess: (data, variables) => {
      if (
        !shouldAcceptDirectResponse({
          responseGeneration: variables.generation,
          currentGeneration: dedupeState.configGeneration,
        })
      ) {
        return;
      }
      setPage(variables.page);
      setPageSize(variables.pageSize);
      setPreviewData(data);
      setPreviewedConfig(JSON.parse(JSON.stringify(variables.cfg)));
      dispatch({
        type: 'PREVIEW_SUCCESS',
        digest: data.preview_digest,
        requestGeneration: variables.generation,
      });
      message.success('高级预览计算完成');
    },
    onError: (err: any) => {
      const formatted = formatDedupeErrorMessage(err);
      dispatch({ type: 'PREVIEW_FAILED', error: formatted });
      message.error(formatted);
    },
  });

  const generateMutation = useMutation({
    mutationFn: () => {
      if (!previewData || !previewedConfig || !dedupeState.acceptedPreviewDigest) {
        throw new Error('无有效的权威预览数据，请先运行预览');
      }
      return scansApi.createAdvancedDedupePlan(scanId, {
        scorer_config: previewedConfig,
        expected_preview_digest: dedupeState.acceptedPreviewDigest,
      });
    },
    onSuccess: (res) => {
      dispatch({ type: 'GENERATE_SUCCESS' });
      message.success(`成功生成精确去重计划 #${res.id || res.plan_id}`);
      navigate(`/plans/${res.id || res.plan_id}`);
    },
    onError: (err: any) => {
      const structured = getStructuredApiError(err);
      const formatted = formatDedupeErrorMessage(err);

      if (
        structured.code === 'PREVIEW_CHANGED' ||
        structured.code === 'DEDUPE_PREVIEW_CHANGED'
      ) {
        dispatch({ type: 'PREVIEW_CHANGED_ERROR', error: formatted });
        Modal.confirm({
          title: '预览校验失败 (PREVIEW_CHANGED)',
          icon: <ExclamationCircleOutlined />,
          content: '检测到底层文件或打分状态已变化，权威摘要已失效。是否重新运行预览？',
          okText: '重新运行预览',
          cancelText: '取消',
          onOk: () => {
            handleRunPreview();
          },
        });
        return;
      }

      dispatch({ type: 'GENERATE_FAILED', error: formatted });

      if (structured.code === 'DEDUPE_SCAN_NOT_FOUND') {
        Modal.error({
          title: '扫描任务不存在 (DEDUPE_SCAN_NOT_FOUND)',
          content: (
            <div>
              <p>{formatted}</p>
              <p className="nfc-modal-support-copy">
                关联的底层扫描任务已不可用，当前去重计划草案无法生成。
              </p>
            </div>
          ),
          okText: '返回扫描列表',
          onOk: () => navigate('/scans'),
        });
      } else if (structured.code === 'DEDUPE_SCAN_NOT_COMPLETED') {
        Modal.warning({
          title: '扫描任务尚未完成 (DEDUPE_SCAN_NOT_COMPLETED)',
          content: (
            <div>
              <p>{formatted}</p>
              <p className="nfc-modal-support-copy">
                扫描任务当前未处于完成状态，请等待扫描完成后再生成去重计划。
              </p>
            </div>
          ),
          okText: '返回扫描详情',
          onOk: () => navigate(`/scans/${scanId}`),
        });
      } else if (structured.code === 'DEDUPE_EMPTY_PLAN') {
        Modal.info({
          title: '无可用去重操作 (DEDUPE_EMPTY_PLAN)',
          content: (
            <div>
              <p>{formatted}</p>
              <p className="nfc-modal-support-copy">
                当前配置下未产生任何可执行的去重操作。
              </p>
            </div>
          ),
          okText: '确定',
        });
      } else {
        message.error(formatted);
      }
    },
  });

  const isDirty =
    dedupeState.status === 'PREVIEW_STALE' ||
    dedupeState.acceptedPreviewDigest === null ||
    (previewedConfig ? isScorerConfigDirty(scorerConfig, previewedConfig) : true);

  const validation = validateScorerConfigForm(scorerConfig);

  const handleRunPreview = () => {
    if (!validation.valid) {
      message.error('请先修正配置校验错误');
      return;
    }
    const currentGen = dedupeState.configGeneration;
    dispatch({ type: 'PREVIEW_STARTED' });
    previewMutation.mutate({
      cfg: scorerConfig,
      generation: currentGen,
      page: 1,
      pageSize,
    });
  };

  const handleConfirmGeneratePlan = () => {
    Modal.confirm({
      title: '确认生成精确去重计划草案？',
      icon: <ExclamationCircleOutlined />,
      content: (
        <div>
          <p>将提交当前权威预览摘要以原子方式创建执行计划草案。</p>
          <p className="nfc-modal-support-copy">
            生成后仅创建 Draft 状态计划，底层物理文件不会发生任何改变。后续仍需完成
            <strong> Freeze -&gt; Validate -&gt; Execute </strong>
            流程。
          </p>
        </div>
      ),
      okText: '确认生成草案',
      cancelText: '取消',
      onOk: () => {
        dispatch({ type: 'GENERATE_STARTED' });
        generateMutation.mutate();
      },
    });
  };

  const handlePageChange = (newPage: number, newPageSize: number) => {
    const currentGen = dedupeState.configGeneration;
    dispatch({ type: 'PREVIEW_STARTED' });
    previewMutation.mutate({
      cfg: scorerConfig,
      generation: currentGen,
      page: newPage,
      pageSize: newPageSize,
    });
  };

  const handleSelectMember = (member: DedupePreviewMemberRow) => {
    setSelectedMember(member);
    setExplainOpen(true);
  };

  if (scanLoading) {
    return (
      <div className="nfc-centered-state">
        <Spin size="large" />
      </div>
    );
  }

  if (scanError || !scan) {
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

  if (scan.status !== 'completed') {
    return (
      <Alert
        message="扫描任务尚未完成"
        description={`扫描任务当前状态为 ${scan.status}，只有已完成的扫描才能进行高级去重分析。`}
        type="warning"
        showIcon
        action={<Button onClick={() => navigate(`/scans/${scanId}`)}>返回扫描详情</Button>}
      />
    );
  }

  if (scan.total_groups === 0) {
    return (
      <Alert
        message="未发现重复文件"
        description="本次扫描未发现任何重复文件组，无需执行去重。"
        type="info"
        showIcon
        action={<Button onClick={() => navigate(`/scans/${scanId}`)}>返回扫描详情</Button>}
      />
    );
  }

  const scanSummary = [
    { label: '扫描任务', value: scan.name },
    { label: '重复组', value: `${scan.total_groups.toLocaleString()} 组`, emphasis: true },
    {
      label: '重复文件',
      value: `${scan.total_files_in_groups.toLocaleString()} 个`,
      emphasis: true,
    },
    {
      label: '预估可释放',
      value: formatBytes(scan.reclaimable_bytes),
      emphasis: true,
    },
  ];

  return (
    <div className="nfc-operations-page nfc-dedupe-stage-stack nfc-advanced-dedupe-page">
      <PageHeader
        eyebrow="ADVANCED DEDUPE"
        title="高级精确去重"
        description={
          <div className="nfc-plan-header-meta">
            <span className="nfc-mono">Scan #{scanId}</span>
            <StatusBadge status={scan.status} />
            <span>只读评分预览 → Draft；Preview 本身不会修改文件系统。</span>
          </div>
        }
        actions={
          <ActionBar compact>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/scans/${scanId}`)}>
              返回扫描详情
            </Button>
          </ActionBar>
        }
      />

      <DataPanel
        title="扫描上下文"
        description="高级去重基于此已完成扫描快照进行评分和选择。"
        className="nfc-panel-flush"
      >
        <ResponsiveDescriptions items={scanSummary} />
        <div className="nfc-root-list">
          <span className="nfc-root-list-label">扫描根目录</span>
          <div className="nfc-root-list-values">
            {scan.roots.map((root, idx) => (
              <CodePath value={root} key={idx} />
            ))}
          </div>
        </div>
      </DataPanel>

      <DataPanel
        title="1. 评分策略与偏好配置"
        description="所有配置变化都会使已接受的 preview digest 失效，必须重新 Preview。"
      >
        <div className="nfc-dedupe-editor-wrap">
          <DedupeScorerConfigEditor
            value={scorerConfig}
            onChange={handleConfigChange}
            disabled={previewMutation.isPending || generateMutation.isPending}
          />
        </div>

        <ActionBar className="nfc-dedupe-config-actions">
          <ActionBar compact>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              onClick={handleRunPreview}
              loading={previewMutation.isPending}
              disabled={!validation.valid}
            >
              运行高级预览 (Preview)
            </Button>
            {isDirty && (
              <span className="nfc-status-badge nfc-status-warning">
                <span className="nfc-status-dot" />
                配置已修改，需重新运行预览
              </span>
            )}
          </ActionBar>
          <span className="nfc-dedupe-config-note">
            服务端只读计算权威预览；不会创建 BatchPlan，也不会修改真实文件。
          </span>
        </ActionBar>
      </DataPanel>

      {previewData && (
        <>
          <DedupeIdentitySafetyPanel
            authorityDigest={previewData.preview_digest}
            authorityType="preview_digest"
            previewSource={previewData.preview_source}
            liveFilesystemVerified={previewData.live_filesystem_verified}
            scorerConfigDigest={previewData.scorer_config_digest}
            sourceSnapshotDigest={previewData.source_snapshot_digest}
            decisionDigest={previewData.decision_digest}
            engineVersion={previewData.dedupe_engine_version}
            effectiveSafetyPolicy={
              previewData.effective_safety_policy ||
              previewData.summary?.effective_safety_policy
            }
          />

          <DedupePreviewSummaryPanel
            summary={{
              ...(previewData.summary || previewData),
              effective_safety_policy: previewData.effective_safety_policy,
            }}
            effectiveSafetyPolicy={previewData.effective_safety_policy}
            scanRoots={previewData.scan_roots || scan.roots}
            selectionMode={previewData.selection_mode}
          />

          <section
            className={`nfc-dedupe-plan-surface ${
              isDirty ? 'nfc-dedupe-plan-surface-stale' : 'nfc-dedupe-plan-surface-ready'
            }`}
          >
            <ActionBar>
              <div className="nfc-dedupe-plan-copy">
                <strong>2. 确认并生成执行计划草案</strong>
                <span>
                  {isDirty
                    ? '当前 preview_digest 对应旧配置；必须重新 Preview 后才能生成计划。'
                    : '提交当前 acceptedPreviewDigest / expected_preview_digest，原子创建 Draft。Draft 之后仍需 Freeze -> Validate -> Execute。'}
                </span>
              </div>
              <ActionBar compact>
                {isDirty && (
                  <Button
                    icon={<ReloadOutlined />}
                    onClick={handleRunPreview}
                    loading={previewMutation.isPending}
                  >
                    重新运行预览
                  </Button>
                )}
                <Button
                  type="primary"
                  icon={<ScheduleOutlined />}
                  onClick={handleConfirmGeneratePlan}
                  loading={generateMutation.isPending}
                  disabled={
                    !canGeneratePlan(dedupeState) ||
                    previewMutation.isPending ||
                    previewData.planned_quarantine_count === 0
                  }
                >
                  生成执行计划草案
                </Button>
              </ActionBar>
            </ActionBar>
          </section>

          <DataPanel
            title="去重候选与隔离决策"
            description="每个成员的选择、评分、保留资格与安全排除都可追溯解释。"
            action={<span className="nfc-panel-count">{previewData.total_rows} candidates</span>}
            className="nfc-panel-flush"
            variant="dense"
          >
            <DedupePreviewTable
              rows={previewData.rows}
              loading={previewMutation.isPending}
              scanRoots={previewData.scan_roots || scan.roots}
              onSelectMember={handleSelectMember}
              pagination={{
                current: page,
                pageSize,
                total: previewData.total_rows,
                onChange: handlePageChange,
              }}
            />
          </DataPanel>
        </>
      )}

      <DedupeExplainDrawer
        open={explainOpen}
        onClose={() => setExplainOpen(false)}
        member={selectedMember}
        groupMembers={previewData?.rows || []}
      />
    </div>
  );
};
