import React, { useState, useReducer } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Card,
  Button,
  Space,
  Typography,
  Alert,
  Spin,
  Tag,
  Descriptions,
  message,
  Modal,
} from "antd";
import {
  ArrowLeftOutlined,
  ThunderboltOutlined,
  ScheduleOutlined,
  ReloadOutlined,
  ExclamationCircleOutlined,
} from "@ant-design/icons";
import { scansApi } from "../../api/domain";
import { formatDedupeErrorMessage, getStructuredApiError } from "../../api/errors";
import {
  DedupeScorerConfig,
  DirectDedupePreviewResponse,
  DedupePreviewMemberRow,
} from "../../types/dedupe";
import {
  createDefaultDedupeScorerConfig,
  isScorerConfigDirty,
  validateScorerConfigForm,
} from "../../utils/dedupeConfig";
import {
  dedupeStateReducer,
  initialDedupeState,
  canGeneratePlan,
} from "../../utils/dedupeState";
import {
  DedupeScorerConfigEditor,
  DedupePreviewTable,
  DedupePreviewSummaryPanel,
  DedupeExplainDrawer,
  DedupeIdentitySafetyPanel,
} from "../../components/dedupe";
import { formatBytes } from "../../utils/format";
import { shouldAcceptDirectResponse } from "../../utils/hotfix2Helpers";

const { Title, Text, Paragraph } = Typography;

export const AdvancedDedupePage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const scanId = parseInt(id || "0", 10);
  const navigate = useNavigate();

  // Dedupe state machine
  const [dedupeState, dispatch] = useReducer(dedupeStateReducer, initialDedupeState);

  // Scorer configuration state
  const [scorerConfig, setScorerConfig] = useState<DedupeScorerConfig>(
    createDefaultDedupeScorerConfig()
  );
  // Track the configuration that was previewed to detect dirty state
  const [previewedConfig, setPreviewedConfig] = useState<DedupeScorerConfig | null>(null);
  const [previewData, setPreviewData] = useState<DirectDedupePreviewResponse | null>(null);

  // Pagination for preview table (Default 50)
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(50);

  // Explain drawer state
  const [selectedMember, setSelectedMember] = useState<DedupePreviewMemberRow | null>(null);
  const [explainOpen, setExplainOpen] = useState<boolean>(false);

  // Load scan detail
  const {
    data: scan,
    isLoading: scanLoading,
    error: scanError,
  } = useQuery({
    queryKey: ["scanDetail", scanId],
    queryFn: () => scansApi.getScanDetail(scanId),
    enabled: !!scanId,
  });

  // Config change handler: triggers state machine CONFIG_EDITED
  const handleConfigChange = (newCfg: DedupeScorerConfig) => {
    setScorerConfig(newCfg);
    dispatch({ type: "CONFIG_EDITED" });
  };

  // Preview mutation with generation correlation
  interface PreviewMutationVariables {
    cfg: DedupeScorerConfig;
    generation: number;
    page: number;
    pageSize: number;
  }

  // Preview mutation with generation correlation
  const previewMutation = useMutation({
    mutationFn: (variables: PreviewMutationVariables) =>
      scansApi.dedupePreview(scanId, {
        scorer_config: variables.cfg,
        page: variables.page,
        page_size: variables.pageSize,
      }),
    onSuccess: (data, variables) => {
      if (!shouldAcceptDirectResponse({
        responseGeneration: variables.generation,
        currentGeneration: dedupeState.configGeneration,
      })) {
        return;
      }
      setPage(variables.page);
      setPageSize(variables.pageSize);
      setPreviewData(data);
      setPreviewedConfig(JSON.parse(JSON.stringify(variables.cfg)));
      dispatch({
        type: "PREVIEW_SUCCESS",
        digest: data.preview_digest,
        requestGeneration: variables.generation,
      });
      message.success("高级预览计算完成");
    },
    onError: (err: any) => {
      const formatted = formatDedupeErrorMessage(err);
      dispatch({ type: "PREVIEW_FAILED", error: formatted });
      message.error(formatted);
    },
  });

  // Generate plan mutation
  const generateMutation = useMutation({
    mutationFn: () => {
      if (!previewData || !previewedConfig || !dedupeState.acceptedPreviewDigest) {
        throw new Error("无有效的权威预览数据，请先运行预览");
      }
      return scansApi.createAdvancedDedupePlan(scanId, {
        scorer_config: previewedConfig,
        expected_preview_digest: dedupeState.acceptedPreviewDigest,
      });
    },
    onSuccess: (res) => {
      dispatch({ type: "GENERATE_SUCCESS" });
      message.success(`成功生成精确去重计划 #${res.id || res.plan_id}`);
      navigate(`/plans/${res.id || res.plan_id}`);
    },
    onError: (err: any) => {
      const structured = getStructuredApiError(err);
      const formatted = formatDedupeErrorMessage(err);
      if (
        structured.code === "PREVIEW_CHANGED" ||
        structured.code === "DEDUPE_PREVIEW_CHANGED"
      ) {
        dispatch({ type: "PREVIEW_CHANGED_ERROR", error: formatted });
        Modal.confirm({
          title: "预览校验失败 (PREVIEW_CHANGED)",
          icon: <ExclamationCircleOutlined style={{ color: "#fa8c16" }} />,
          content: "检测到底层文件或打分状态已变化，权威摘要已失效。是否重新运行预览？",
          okText: "重新运行预览",
          cancelText: "取消",
          onOk: () => {
            handleRunPreview();
          },
        });
      } else {
        dispatch({ type: "GENERATE_FAILED", error: formatted });
        if (structured.code === "DEDUPE_SCAN_NOT_FOUND") {
          Modal.error({
            title: "扫描任务不存在 (DEDUPE_SCAN_NOT_FOUND)",
            content: (
              <div>
                <p>{formatted}</p>
                <p style={{ color: "#8c8c8c" }}>关联的底层扫描任务已不可用，当前去重计划草案无法生成。</p>
              </div>
            ),
            okText: "返回扫描列表",
            onOk: () => navigate("/scans"),
          });
        } else if (structured.code === "DEDUPE_SCAN_NOT_COMPLETED") {
          Modal.warning({
            title: "扫描任务尚未完成 (DEDUPE_SCAN_NOT_COMPLETED)",
            content: (
              <div>
                <p>{formatted}</p>
                <p style={{ color: "#8c8c8c" }}>扫描任务当前未处于完成状态，请等待扫描完成后再生成去重计划。</p>
              </div>
            ),
            okText: "返回扫描详情",
            onOk: () => navigate(`/scans/${scanId}`),
          });
        } else if (structured.code === "DEDUPE_EMPTY_PLAN") {
          Modal.info({
            title: "无可用去重操作 (DEDUPE_EMPTY_PLAN)",
            content: (
              <div>
                <p>{formatted}</p>
                <p style={{ color: "#8c8c8c" }}>当前配置下未产生任何可执行的去重操作（如所有重复项均被安全保护策略排除或未发现冗余副本）。</p>
              </div>
            ),
            okText: "确定",
          });
        } else {
          message.error(formatted);
        }
      }
    },
  });

  const isDirty =
    dedupeState.status === "PREVIEW_STALE" ||
    dedupeState.acceptedPreviewDigest === null ||
    (previewedConfig ? isScorerConfigDirty(scorerConfig, previewedConfig) : true);

  const validation = validateScorerConfigForm(scorerConfig);

  const handleRunPreview = () => {
    if (!validation.valid) {
      message.error("请先修正配置校验错误");
      return;
    }
    const currentGen = dedupeState.configGeneration;
    dispatch({ type: "PREVIEW_STARTED" });
    previewMutation.mutate({
      cfg: scorerConfig,
      generation: currentGen,
      page: 1,
      pageSize,
    });
  };

  const handleConfirmGeneratePlan = () => {
    Modal.confirm({
      title: "确认生成精确去重计划草案？",
      icon: <ExclamationCircleOutlined style={{ color: "#1890ff" }} />,
      content: (
        <div>
          <Paragraph>
            将提交当前权威预览摘要以原子方式创建执行计划草案。
          </Paragraph>
          <Paragraph type="secondary" style={{ fontSize: 13 }}>
            注意：生成后仅创建 <strong>Draft</strong> 状态计划，底层物理文件不会发生任何改变。后续仍需在计划详情页完成 <strong>Freeze -&gt; Validate -&gt; Execute</strong> 流程。
          </Paragraph>
        </div>
      ),
      okText: "确认生成草案",
      cancelText: "取消",
      onOk: () => {
        dispatch({ type: "GENERATE_STARTED" });
        generateMutation.mutate();
      },
    });
  };

  const handlePageChange = (newPage: number, newPageSize: number) => {
    const currentGen = dedupeState.configGeneration;
    dispatch({ type: "PREVIEW_STARTED" });
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
      <div style={{ textAlign: "center", padding: 80 }}>
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
        action={<Button onClick={() => navigate("/scans")}>返回扫描列表</Button>}
      />
    );
  }

  if (scan.status !== "completed") {
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* 1. Header Navigation */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(`/scans/${scanId}`)}>
            返回扫描详情
          </Button>
          <Title level={4} style={{ margin: 0 }}>
            高级精确去重 (Advanced Dedupe)
          </Title>
          <Tag color="blue">扫描 #{scanId}</Tag>
          <Tag color="green">已完成</Tag>
        </Space>
      </div>

      {/* 2. Scan Summary Context */}
      <Card size="small" bordered={false} style={{ borderRadius: 8 }}>
        <Descriptions column={{ xs: 1, sm: 2, md: 4 }} size="small">
          <Descriptions.Item label="扫描任务">{scan.name}</Descriptions.Item>
          <Descriptions.Item label="发现重复组">
            <Text strong style={{ color: "#fa8c16" }}>
              {scan.total_groups.toLocaleString()} 组
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="重复文件总数">
            <Text strong>{scan.total_files_in_groups.toLocaleString()} 个</Text>
          </Descriptions.Item>
          <Descriptions.Item label="预估可释放容量">
            <Text strong style={{ color: "#52c41a" }}>
              {formatBytes(scan.reclaimable_bytes)}
            </Text>
          </Descriptions.Item>
          <Descriptions.Item label="扫描根目录" span={4}>
            <Space wrap>
              {scan.roots.map((r, idx) => (
                <Tag key={idx} color="cyan">
                  Scan Root {idx} {r}
                </Tag>
              ))}
            </Space>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 3. Scorer Configuration Section */}
      <Card
        title="1. 评分策略与偏好配置 (Scorer Configuration)"
        bordered={false}
        style={{ borderRadius: 8 }}
      >
        <DedupeScorerConfigEditor
          value={scorerConfig}
          onChange={handleConfigChange}
          disabled={previewMutation.isPending || generateMutation.isPending}
        />

        <div
          style={{
            marginTop: 16,
            paddingTop: 16,
            borderTop: "1px solid #f0f0f0",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <Space>
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
              <Tag color="warning" icon={<ExclamationCircleOutlined />}>
                配置已修改，需重新运行预览
              </Tag>
            )}
          </Space>
          <Text type="secondary" style={{ fontSize: 13 }}>
            预览由服务端基于已完成扫描数据与只读安全观察生成；不会修改文件系统，也不会创建 BatchPlan。
          </Text>
        </div>
      </Card>

      {/* 4. Preview Results Section */}
      {previewData && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Identity & Safety Snapshot Panel */}
          <DedupeIdentitySafetyPanel
            authorityDigest={previewData.preview_digest}
            authorityType="preview_digest"
            previewSource={previewData.preview_source}
            liveFilesystemVerified={previewData.live_filesystem_verified}
            scorerConfigDigest={previewData.scorer_config_digest}
            sourceSnapshotDigest={previewData.source_snapshot_digest}
            decisionDigest={previewData.decision_digest}
            engineVersion={previewData.dedupe_engine_version}
            effectiveSafetyPolicy={previewData.effective_safety_policy || previewData.summary?.effective_safety_policy}
          />

          {/* Preview Summary Panel */}
          <DedupePreviewSummaryPanel
            summary={{
              ...(previewData.summary || previewData),
              effective_safety_policy: previewData.effective_safety_policy,
            }}
            effectiveSafetyPolicy={previewData.effective_safety_policy}
            scanRoots={previewData.scan_roots || scan.roots}
            selectionMode={previewData.selection_mode}
          />

          {/* Action Bar for Plan Draft Generation */}
          <Card
            bordered={false}
            style={{
              background: isDirty ? "#fffbe6" : "#f6ffed",
              border: isDirty ? "1px solid #ffe58f" : "1px solid #b7eb8f",
              borderRadius: 8,
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                flexWrap: "wrap",
                gap: 16,
              }}
            >
              <div>
                <Text strong style={{ fontSize: 15, display: "block" }}>
                  2. 确认并生成执行计划草案 (Generate Plan Draft)
                </Text>
                <Paragraph type="secondary" style={{ margin: 0, fontSize: 13 }}>
                  {isDirty
                    ? "配置已修改：当前生成的 preview_digest 对应修改前的配置。请重新运行预览后方可生成计划。"
                    : "将提交当前权威预览摘要（preview_digest）以原子方式创建执行计划草案。草案生成后不会立即改动文件。"}
                </Paragraph>
              </div>
              <Space>
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
                  size="large"
                  icon={<ScheduleOutlined />}
                  onClick={handleConfirmGeneratePlan}
                  loading={generateMutation.isPending}
                  disabled={
                    !canGeneratePlan(dedupeState) ||
                    previewMutation.isPending ||
                    previewData.planned_quarantine_count === 0
                  }
                  style={{ background: "#52c41a", borderColor: "#52c41a" }}
                >
                  生成执行计划草案
                </Button>
              </Space>
            </div>
          </Card>

          {/* Preview Members Table */}
          <Card
            title={
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span>去重候选与隔离决策明细 (Dedupe Preview Items)</span>
                <Text type="secondary" style={{ fontSize: 13 }}>
                  共 {previewData.total_rows} 项候选文件
                </Text>
              </div>
            }
            bordered={false}
            style={{ borderRadius: 8 }}
          >
            <DedupePreviewTable
              rows={previewData.rows}
              loading={previewMutation.isPending}
              scanRoots={previewData.scan_roots || scan.roots}
              onSelectMember={handleSelectMember}
              pagination={{
                current: page,
                pageSize: pageSize,
                total: previewData.total_rows,
                onChange: handlePageChange,
              }}
            />
          </Card>
        </div>
      )}

      {/* Explain Drawer */}
      <DedupeExplainDrawer
        open={explainOpen}
        onClose={() => setExplainOpen(false)}
        member={selectedMember}
        groupMembers={previewData?.rows || []}
      />
    </div>
  );
};
