import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Typography,
  Alert,
  Descriptions,
  Input,
  message,
  Popconfirm,
  Select,
  Switch,
} from "antd";
import {
  EyeOutlined,
  ReloadOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { workflowApi } from "../../api/workflows";
import { indexesApi } from "../../api/domain";
import { IndexRoot } from "../../types";
import { getStructuredApiError, formatDedupeErrorMessage } from "../../api/errors";
import {
  WorkflowPreviewItem,
  WorkflowPreviewResponse,
  WorkflowMode,
} from "../../types/workflow";
import {
  DedupeSummary,
  DedupePreviewMemberRow,
} from "../../types/dedupe";
import {
  WorkflowPreviewState,
  transitionPreviewState,
} from "../../utils/workflowPreviewMachine";
import { canPreviewWorkflow, canGenerateDraft } from "../../utils/workflowRbac";
import { normalizeSelectedRoots } from "../../utils/rootCardinality";
import { computePreviewRowIndex } from "../../utils/workflowRevisionParser";
import { CompletedScanPicker } from "../../components/workflows/CompletedScanPicker";
import { mapWorkflowPreviewItemsToDedupeRows } from "../../utils/dedupePreview";
import {
  computeWorkflowDedupeTableTotal,
  shouldAcceptWorkflowResponse,
  computeCanDraft,
} from "../../utils/hotfix2Helpers";
import {
  DedupeIdentitySafetyPanel,
  DedupePreviewSummaryPanel,
  DedupePreviewTable,
  DedupeExplainDrawer,
} from "../../components/dedupe";

const { Text } = Typography;

export interface PreviewRequestSnapshot {
  workflowId: number;
  revision: number;
  mode: WorkflowMode;
  page: number;
  pageSize: number;
  onlyChanged: boolean;
  scanJobId?: number;
  roots?: number[];
  requestId: number;
}

interface WorkflowPreviewPanelProps {
  workflowId: number;
  revision: number;
  mode?: WorkflowMode;
  isDirty: boolean;
  isArchived?: boolean;
  onGeneratePlanSuccess: (planId: number) => void;
}

export const WorkflowPreviewPanel: React.FC<WorkflowPreviewPanelProps> = ({
  workflowId,
  revision,
  mode = "file",
  isDirty,
  isArchived = false,
  onGeneratePlanSuccess,
}) => {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [selectedRoots, setSelectedRoots] = useState<number[] | undefined>(undefined);
  const [selectedScanJobId, setSelectedScanJobId] = useState<number | undefined>(undefined);
  const [onlyChanged, setOnlyChanged] = useState<boolean>(false);
  const [customPlanName, setCustomPlanName] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // Explain drawer state for dedupe mode
  const [selectedDedupeMember, setSelectedDedupeMember] = useState<DedupePreviewMemberRow | null>(null);
  const [explainOpen, setExplainOpen] = useState(false);

  const isOrganizer = mode === "organizer";
  const isDedupe = mode === "dedupe";

  const [previewState, setPreviewState] = useState<WorkflowPreviewState>(
    isDirty ? "EDITING_DIRTY" : "SAVED_PREVIEW_REQUIRED"
  );
  const [previewData, setPreviewData] = useState<WorkflowPreviewResponse | null>(null);
  const latestRequestIdRef = useRef<number>(0);

  const { data: indexesData } = useQuery({
    queryKey: ["indexesRootsList"],
    queryFn: async () => {
      const res = await indexesApi.listIndexes(1, 100);
      return res.items;
    },
    enabled: !isDedupe,
  });
  const scanRoots: IndexRoot[] = indexesData || [];

  useEffect(() => {
    setPreviewState((prev) => transitionPreviewState(prev, { type: "DIRTY_CHANGE", isDirty }));
    if (isDirty) {
      setPreviewData(null);
    }
  }, [isDirty]);

  useEffect(() => {
    latestRequestIdRef.current += 1;
    setSelectedRoots(undefined);
    setSelectedScanJobId(undefined);
    setPreviewData(null);
    setPreviewState(isDirty ? "EDITING_DIRTY" : "SAVED_PREVIEW_REQUIRED");
  }, [mode, workflowId, revision]);

  const previewMutation = useMutation({
    mutationFn: async (snapshot: PreviewRequestSnapshot) => {
      if (!snapshot.workflowId || isDirty || isArchived) {
        throw new Error("当前状态无法执行工作流预览");
      }
      if (snapshot.mode === "dedupe") {
        if (!snapshot.scanJobId) {
          throw new Error("请先选择已完成的扫描任务");
        }
        return workflowApi.previewWorkflow(snapshot.workflowId, {
          revision: snapshot.revision,
          page: snapshot.page,
          page_size: snapshot.pageSize,
          only_changed: snapshot.onlyChanged,
          runtime_inputs: {
            scan_job_id: snapshot.scanJobId,
          },
        });
      }

      return workflowApi.previewWorkflow(snapshot.workflowId, {
        revision: snapshot.revision,
        page: snapshot.page,
        page_size: snapshot.pageSize,
        only_changed: snapshot.onlyChanged,
        runtime_inputs:
          snapshot.roots && snapshot.roots.length > 0
            ? { root_ids: snapshot.roots }
            : undefined,
      });
    },
    onMutate: () => {
      setPreviewError(null);
      setErrorMessage(null);
      setPreviewState((prev) => transitionPreviewState(prev, { type: "START_PREVIEW" }));
    },
    onSuccess: (data, variables) => {
      if (!shouldAcceptWorkflowResponse({
        snapshot: variables,
        currentWorkflowId: workflowId,
        currentRevision: revision,
        currentMode: mode,
        currentRequestId: latestRequestIdRef.current,
      })) {
        return;
      }
      setPage(variables.page);
      setPageSize(variables.pageSize);
      setPreviewData(data);
      setPreviewState((prev) =>
        transitionPreviewState(prev, {
          type: "PREVIEW_SUCCESS",
          compileDigest: data.compile_digest,
        })
      );
    },
    onError: (err, variables) => {
      if (!shouldAcceptWorkflowResponse({
        snapshot: variables,
        currentWorkflowId: workflowId,
        currentRevision: revision,
        currentMode: mode,
        currentRequestId: latestRequestIdRef.current,
      })) {
        return;
      }
      const formatted = formatDedupeErrorMessage(err);
      setPreviewError(formatted);
      setPreviewData(null);
      setPreviewState((prev) =>
        transitionPreviewState(prev, {
          type: "PREVIEW_ERROR",
          message: formatted,
        })
      );
    },
  });

  const triggerPreview = (params?: {
    page?: number;
    pageSize?: number;
    onlyChanged?: boolean;
    scanJobId?: number;
    roots?: number[];
  }) => {
    const p = params?.page ?? page;
    const ps = params?.pageSize ?? pageSize;
    const oc = params?.onlyChanged !== undefined ? params.onlyChanged : onlyChanged;
    const sid = params?.scanJobId !== undefined ? params.scanJobId : selectedScanJobId;
    const rts = params?.roots !== undefined ? params.roots : selectedRoots;

    const reqId = ++latestRequestIdRef.current;
    previewMutation.mutate({
      workflowId,
      revision,
      mode,
      page: p,
      pageSize: ps,
      onlyChanged: oc,
      scanJobId: sid,
      roots: rts,
      requestId: reqId,
    });
  };

  const handleRootsChange = (roots: number[] | undefined) => {
    latestRequestIdRef.current += 1;
    const normalized = normalizeSelectedRoots(roots, mode as any);
    setSelectedRoots(normalized);
    setPage(1);
    setPreviewState((prev) => transitionPreviewState(prev, { type: "ROOTS_CHANGE" }));
    setPreviewData(null);
  };

  const handleScanJobChange = (scanJobId?: number) => {
    latestRequestIdRef.current += 1;
    setSelectedScanJobId(scanJobId);
    setPage(1);
    setPreviewState("SAVED_PREVIEW_REQUIRED");
    setPreviewData(null);
  };

  const generatePlanMutation = useMutation({
    mutationFn: () => {
      if (!previewData?.compile_digest) {
        throw new Error("未获取到编译摘要，无法生成计划");
      }
      if (isDedupe) {
        if (!selectedScanJobId) {
          throw new Error("请先选择已完成的扫描任务");
        }
        return workflowApi.generatePlan(workflowId, {
          expected_compile_digest: previewData.compile_digest,
          revision,
          runtime_inputs: {
            scan_job_id: selectedScanJobId,
          },
          plan_name: customPlanName.trim() || undefined,
        });
      }

      return workflowApi.generatePlan(workflowId, {
        expected_compile_digest: previewData.compile_digest,
        revision,
        runtime_inputs:
          selectedRoots && selectedRoots.length > 0
            ? { root_ids: selectedRoots }
            : undefined,
        plan_name: customPlanName.trim() || undefined,
      });
    },
    onSuccess: (data) => {
      message.success(`批处理计划草稿 #${data.plan_id} 生成成功`);
      queryClient.invalidateQueries({ queryKey: ["plansList"] });
      onGeneratePlanSuccess(data.plan_id);
    },
    onError: (err) => {
      const structured = getStructuredApiError(err);
      const formatted = formatDedupeErrorMessage(err);
      if (
        structured.code === "PREVIEW_CHANGED" ||
        structured.code === "DEDUPE_PREVIEW_CHANGED"
      ) {
        setErrorMessage(formatted);
        setPreviewData((prev) => (prev ? { ...prev, compile_digest: "" } : null));
        setPreviewState((prev) =>
          transitionPreviewState(prev, { type: "PREVIEW_CHANGED_ERROR" })
        );
      } else if (structured.code === "WORKFLOW_ARCHIVED") {
        setErrorMessage(formatted);
        setPreviewData(null);
        setPreviewState("PREVIEW_STALE");
      } else {
        setErrorMessage(formatted);
      }
    },
  });

  // Mapped dedupe rows if mode is dedupe
  const dedupeRows = useMemo(() => {
    if (!isDedupe || !previewData?.items) return [];
    return mapWorkflowPreviewItemsToDedupeRows(previewData.items);
  }, [isDedupe, previewData?.items]);

  // Directly consume dedupe_summary from previewData (Blocker 1)
  const dedupeSummary: DedupeSummary | null = isDedupe
    ? (previewData?.dedupe_summary ?? null)
    : null;

  const columns = [
    {
      title: "序号",
      key: "index",
      width: 60,
      render: (_: any, __: any, idx: number) => computePreviewRowIndex(page, pageSize, idx),
    },
    {
      title: "操作类型",
      dataIndex: "operation",
      key: "operation",
      width: 100,
      render: (op: string) => {
        const colors: Record<string, string> = {
          rename: "cyan",
          move: "purple",
          touch: "blue",
          quarantine: "orange",
        };
        return <Tag color={colors[op] || "default"}>{op}</Tag>;
      },
    },
    {
      title: "变更状态",
      dataIndex: "changed",
      key: "changed",
      width: 100,
      render: (changed: boolean) =>
        changed ? <Tag color="processing">有变更</Tag> : <Tag color="default">保持/更新</Tag>,
    },
    {
      title: "源文件路径",
      dataIndex: "source_path",
      key: "source_path",
      ellipsis: true,
    },
    {
      title: "目标文件路径",
      dataIndex: "target_path",
      key: "target_path",
      ellipsis: true,
      render: (target: string | null, record: WorkflowPreviewItem) => {
        if (record.operation === "touch") {
          return (
            <Text type="secondary">
              刷新时间戳 (mtime):{" "}
              {record.mtime_ns
                ? new Date(record.mtime_ns / 1e6).toLocaleString()
                : "当前时间"}
            </Text>
          );
        }
        return target || <Text type="secondary">-</Text>;
      },
    },
  ];

  const getStateTag = () => {
    switch (previewState) {
      case "EDITING_DIRTY":
        return <Tag color="warning">配置已修改，需先保存新版本</Tag>;
      case "SAVED_PREVIEW_REQUIRED":
        return <Tag color="default">待显式生成预览</Tag>;
      case "PREVIEWING":
        return <Tag color="processing">正在分析执行预览...</Tag>;
      case "PREVIEW_READY":
        return <Tag color="success">预览已就绪 (可生成草稿)</Tag>;
      case "PREVIEW_STALE":
        return <Tag color="error">预览已失效 (需重新刷新预览)</Tag>;
      default:
        return null;
    }
  };

  const canPreview =
    canPreviewWorkflow(isArchived) &&
    !isDirty &&
    (!isDedupe || Boolean(selectedScanJobId));

  const canDraft =
    canGenerateDraft(isArchived) &&
    computeCanDraft({
      isArchived,
      isDirty,
      previewState,
      compileDigest: previewData?.compile_digest,
      previewPending: previewMutation.isPending,
      generatePending: generatePlanMutation.isPending,
      isDedupe,
      selectedScanJobId,
      hasDedupeSummary: Boolean(previewData?.dedupe_summary),
    });

  return (
    <Card
      title={
        <Space>
          <EyeOutlined style={{ color: "#1677ff" }} />
          <span>执行预览与批处理计划生成 (Workflow Preview & Generate Plan)</span>
          {getStateTag()}
        </Space>
      }
      bordered={false}
      style={{ borderRadius: 12, marginTop: 16 }}
      extra={
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => triggerPreview()}
            loading={previewMutation.isPending}
            disabled={!canPreview}
          >
            {previewData ? "刷新预览" : "生成预览"}
          </Button>

          <Popconfirm
            title="确认基于此预览生成批处理计划草稿？"
            description="计划生成为只读草稿态，仍需冻结与校验后方可执行。"
            onConfirm={() => generatePlanMutation.mutate()}
            disabled={!canDraft}
            okText="生成草稿"
            cancelText="取消"
          >
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              disabled={!canDraft}
              loading={generatePlanMutation.isPending}
            >
              生成批处理计划草稿 (Draft)
            </Button>
          </Popconfirm>
        </Space>
      }
    >
      {isArchived ? (
        <Alert
          type="info"
          showIcon
          message="工作流已归档"
          description="此工作流已被归档封存，处于只读模式，不可执行预览或生成批处理计划。"
          style={{ marginBottom: 16 }}
        />
      ) : isDirty ? (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          message="检测到工作流定义有未保存的变动"
          description="为保障编译与计划生成的权威性及版本一致性，系统禁止在草稿未保存状态下进行预览或生成计划。请先点击上方“保存新版本”按钮。"
          style={{ marginBottom: 16 }}
        />
      ) : (
        <>
          {errorMessage && (
            <Alert
              type="error"
              showIcon
              message="操作失败"
              description={errorMessage}
              closable
              onClose={() => setErrorMessage(null)}
              style={{ marginBottom: 16 }}
            />
          )}

          {previewError && (
            <Alert
              type="error"
              showIcon
              message="工作流预览失败"
              description={previewError}
              style={{ marginBottom: 16 }}
            />
          )}

          {isDedupe && previewData && !previewData.dedupe_summary && (
            <Alert
              type="error"
              showIcon
              message="缺少去重权威摘要 (dedupe_summary)"
              description="后端返回的预览数据中未包含权威 dedupe_summary，无法验证去重统计与安全性，系统已禁止生成计划草案。"
              style={{ marginBottom: 16 }}
            />
          )}

          {/* Runtime Inputs Selector */}
          <div
            style={{
              display: "flex",
              gap: 16,
              marginBottom: 16,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            {isDedupe ? (
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <Text type="secondary">指定扫描任务 (纯运行时参数):</Text>
                <CompletedScanPicker
                  value={selectedScanJobId}
                  onChange={handleScanJobChange}
                  disabled={previewMutation.isPending || generatePlanMutation.isPending}
                />
                <Space align="center" style={{ marginLeft: 8 }}>
                  <Switch
                    checked={onlyChanged}
                    onChange={(checked) => {
                      setOnlyChanged(checked);
                      if (selectedScanJobId) {
                        triggerPreview({ page: 1, pageSize, onlyChanged: checked, scanJobId: selectedScanJobId });
                      }
                    }}
                    disabled={previewMutation.isPending || generatePlanMutation.isPending}
                  />
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    仅显示将隔离项 (only_changed)
                  </Text>
                </Space>
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Text type="secondary">覆盖根目录 (可选):</Text>
                {isOrganizer ? (
                  <Select
                    placeholder="覆盖单一根目录 (整理模式仅限 1 个)"
                    value={selectedRoots?.[0]}
                    onChange={(val) => handleRootsChange(val ? [val] : undefined)}
                    style={{ minWidth: 260 }}
                    options={(scanRoots || []).map((r) => ({
                      label: `${r.root} (ID: ${r.id})`,
                      value: r.id,
                    }))}
                    allowClear
                  />
                ) : (
                  <Select
                    mode="multiple"
                    maxCount={16}
                    placeholder="使用步骤预设根目录 (最多16个)"
                    value={selectedRoots}
                    onChange={handleRootsChange}
                    style={{ minWidth: 260 }}
                    options={(scanRoots || []).map((r) => ({
                      label: `${r.root} (ID: ${r.id})`,
                      value: r.id,
                      disabled:
                        !selectedRoots?.includes(r.id) &&
                        (selectedRoots?.length ?? 0) >= 16,
                    }))}
                    allowClear
                  />
                )}
              </div>
            )}

            <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
              <Input
                placeholder="自定义计划名称 (可选)"
                value={customPlanName}
                onChange={(e) => setCustomPlanName(e.target.value)}
                style={{ width: 260 }}
              />
            </div>
          </div>

          {/* Results Section */}
          {previewData && (
            isDedupe ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <DedupeIdentitySafetyPanel
                  authorityDigest={previewData.compile_digest}
                  authorityType="compile_digest"
                  dedupePreviewDigest={dedupeSummary?.preview_digest}
                  workflowRevision={previewData.workflow_revision}
                  definitionSha256={previewData.definition_sha256}
                  runtimeScanJobId={selectedScanJobId}
                  previewSource={previewData.preview_source}
                  liveFilesystemVerified={previewData.live_filesystem_verified}
                  scorerConfigDigest={dedupeSummary?.scorer_config_digest}
                  sourceSnapshotDigest={dedupeSummary?.source_snapshot_digest}
                  decisionDigest={dedupeSummary?.decision_digest}
                  engineVersion={dedupeSummary?.dedupe_engine_version}
                  effectiveSafetyPolicy={dedupeSummary?.effective_safety_policy}
                />

                {dedupeSummary && (
                  <DedupePreviewSummaryPanel summary={dedupeSummary} />
                )}

                <Card
                  title={
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span>去重流水线预览明细 (Dedupe Preview Items)</span>
                      <Text type="secondary" style={{ fontSize: 13 }}>
                        共 {previewData.items?.length || 0} 项
                      </Text>
                    </div>
                  }
                  size="small"
                  bordered={false}
                  style={{ background: "#fff", borderRadius: 8 }}
                >
                  <DedupePreviewTable
                    rows={dedupeRows}
                    loading={previewMutation.isPending}
                    onSelectMember={(member) => {
                      setSelectedDedupeMember(member);
                      setExplainOpen(true);
                    }}
                    pagination={{
                      current: page,
                      pageSize,
                      total: computeWorkflowDedupeTableTotal(previewData, onlyChanged),
                      onChange: (p, ps) => {
                        triggerPreview({ page: p, pageSize: ps });
                      },
                    }}
                  />
                </Card>

                <DedupeExplainDrawer
                  open={explainOpen}
                  onClose={() => setExplainOpen(false)}
                  member={selectedDedupeMember}
                  groupMembers={dedupeRows}
                />
              </div>
            ) : (
              <>
                <Card size="small" style={{ marginBottom: 16, background: "#fafafa" }}>
                  <Descriptions size="small" column={3} bordered>
                    <Descriptions.Item label="匹配文件/目录数">
                      <Text strong>{previewData.matched_count}</Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="计划操作总数">
                      <Text strong style={{ color: "#1677ff" }}>
                        {previewData.planned_operations_count} 项
                      </Text>
                    </Descriptions.Item>
                    <Descriptions.Item label="预览数据源">
                      <Tag color={previewData.preview_source === "index" ? "blue" : "purple"}>
                        {previewData.preview_source}
                      </Tag>
                    </Descriptions.Item>
                    <Descriptions.Item label="编译摘要 (Compile Digest)" span={3}>
                      <Text code copyable style={{ fontSize: 12 }}>
                        {previewData.compile_digest || "(已失效，请重新生成预览)"}
                      </Text>
                    </Descriptions.Item>
                  </Descriptions>
                </Card>

                <Table
                  dataSource={previewData?.items || []}
                  columns={columns}
                  rowKey={(r, idx) => `${r.source_path}-${r.operation}-${idx}`}
                  loading={previewMutation.isPending}
                  size="small"
                  pagination={{
                    current: page,
                    pageSize,
                    total: previewData?.planned_operations_count ?? 0,
                    showSizeChanger: true,
                    pageSizeOptions: ["20", "50", "100"],
                    onChange: (p, ps) => {
                      if (previewState === "PREVIEW_READY") {
                        triggerPreview({ page: p, pageSize: ps });
                      }
                    },
                  }}
                />
              </>
            )
          )}
        </>
      )}
    </Card>
  );
};
