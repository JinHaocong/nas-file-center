import React, { useState, useEffect, useMemo, useRef } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  message,
  Pagination,
  Popconfirm,
  Select,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import {
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
import { DataPanel } from "../../components/ui/DataPanel";
import { ActionBar } from "../../components/ui/ActionBar";
import { ResponsiveDescriptions } from "../../components/ui/ResponsiveDescriptions";
import { ResponsiveDataView } from "../../components/ui/ResponsiveDataView";
import { CodePath } from "../../components/ui/CodePath";
import { StatusBadge } from "../../components/ui/StatusBadge";

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
      } else if (
        structured.code === "DEDUPE_SCAN_NOT_FOUND" ||
        structured.code === "DEDUPE_SCAN_NOT_COMPLETED"
      ) {
        setErrorMessage(formatted);
        setPreviewData(null);
        setSelectedScanJobId(undefined);
        setPreviewState("SAVED_PREVIEW_REQUIRED");
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
    <DataPanel
      title="执行预览与批处理计划生成"
      description="Preview 基于已保存 revision 与显式 runtime inputs 生成权威 compile digest；Generate 只创建 Draft。"
      action={
        <ActionBar compact>
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
              生成计划草稿
            </Button>
          </Popconfirm>
        </ActionBar>
      }
      className="nfc-workflow-preview-panel"
    >
      <div className="nfc-workflow-preview-body">
        <div className="nfc-workflow-preview-state">{getStateTag()}</div>

        {isArchived ? (
          <Alert
            type="info"
            showIcon
            message="工作流已归档"
            description="此工作流已被归档封存，处于只读模式，不可执行预览或生成批处理计划。"
          />
        ) : isDirty ? (
          <Alert
            type="warning"
            showIcon
            icon={<WarningOutlined />}
            message="检测到工作流定义有未保存的变动"
            description="为保障编译与计划生成的权威性及版本一致性，草稿未保存时禁止 Preview 与 Generate。请先保存新版本。"
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
              />
            )}

            {previewError && (
              <Alert
                type="error"
                showIcon
                message="工作流预览失败"
                description={previewError}
              />
            )}

            {isDedupe && previewData && !previewData.dedupe_summary && (
              <Alert
                type="error"
                showIcon
                message="缺少去重权威摘要 (dedupe_summary)"
                description="后端预览未包含权威 dedupe_summary，无法验证去重统计与安全性，已禁止生成计划草稿。"
              />
            )}

            <ActionBar className="nfc-workflow-runtime-bar">
              {isDedupe ? (
                <>
                  <span className="nfc-form-inline-label">扫描任务</span>
                  <CompletedScanPicker
                    value={selectedScanJobId}
                    onChange={handleScanJobChange}
                    disabled={previewMutation.isPending || generatePlanMutation.isPending}
                  />
                  <label className="nfc-inline-switch">
                    <Switch
                      checked={onlyChanged}
                      onChange={(checked) => {
                        setOnlyChanged(checked);
                        if (selectedScanJobId) {
                          triggerPreview({
                            page: 1,
                            pageSize,
                            onlyChanged: checked,
                            scanJobId: selectedScanJobId,
                          });
                        }
                      }}
                      disabled={previewMutation.isPending || generatePlanMutation.isPending}
                    />
                    <span>仅显示将隔离项</span>
                  </label>
                </>
              ) : (
                <>
                  <span className="nfc-form-inline-label">覆盖根目录（可选）</span>
                  {isOrganizer ? (
                    <Select
                      placeholder="覆盖单一根目录"
                      value={selectedRoots?.[0]}
                      onChange={(value) =>
                        handleRootsChange(value ? [value] : undefined)
                      }
                      className="nfc-workflow-root-select"
                      options={(scanRoots || []).map((root) => ({
                        label: `${root.root} (ID: ${root.id})`,
                        value: root.id,
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
                      className="nfc-workflow-root-select"
                      options={(scanRoots || []).map((root) => ({
                        label: `${root.root} (ID: ${root.id})`,
                        value: root.id,
                        disabled:
                          !selectedRoots?.includes(root.id) &&
                          (selectedRoots?.length ?? 0) >= 16,
                      }))}
                      allowClear
                    />
                  )}
                </>
              )}

              <Input
                placeholder="自定义计划名称 (可选)"
                value={customPlanName}
                onChange={(event) => setCustomPlanName(event.target.value)}
                className="nfc-workflow-plan-name-input"
              />
            </ActionBar>

            {previewData &&
              (isDedupe ? (
                <div className="nfc-dedupe-stage-stack">
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

                  <section className="nfc-workflow-preview-subsection">
                    <div className="nfc-workflow-preview-subheader">
                      <div>
                        <strong>去重流水线预览明细</strong>
                        <span>当前页 {previewData.items?.length || 0} 项</span>
                      </div>
                    </div>
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
                        total: computeWorkflowDedupeTableTotal(
                          previewData,
                          onlyChanged
                        ),
                        onChange: (nextPage, nextPageSize) => {
                          triggerPreview({
                            page: nextPage,
                            pageSize: nextPageSize,
                          });
                        },
                      }}
                    />
                  </section>

                  <DedupeExplainDrawer
                    open={explainOpen}
                    onClose={() => setExplainOpen(false)}
                    member={selectedDedupeMember}
                    groupMembers={dedupeRows}
                  />
                </div>
              ) : (
                <>
                  <ResponsiveDescriptions
                    items={[
                      {
                        label: "匹配文件/目录数",
                        value: previewData.matched_count,
                        emphasis: true,
                      },
                      {
                        label: "计划操作总数",
                        value: previewData.planned_operations_count,
                        emphasis: true,
                      },
                      {
                        label: "预览数据源",
                        value: (
                          <span className="nfc-kind-badge">
                            {previewData.preview_source}
                          </span>
                        ),
                      },
                      {
                        label: "Compile Digest",
                        value: (
                          <span className="nfc-mono nfc-digest-value">
                            {previewData.compile_digest ||
                              "(已失效，请重新生成预览)"}
                          </span>
                        ),
                      },
                    ]}
                  />

                  <ResponsiveDataView
                    desktop={
                      <Table
                        dataSource={previewData.items || []}
                        columns={columns}
                        rowKey={(row, index) =>
                          `${row.source_path}-${row.operation}-${index}`
                        }
                        loading={previewMutation.isPending}
                        size="small"
                        pagination={{
                          current: page,
                          pageSize,
                          total: previewData.planned_operations_count ?? 0,
                          showSizeChanger: true,
                          pageSizeOptions: ["20", "50", "100"],
                          onChange: (nextPage, nextPageSize) => {
                            if (previewState === "PREVIEW_READY") {
                              triggerPreview({
                                page: nextPage,
                                pageSize: nextPageSize,
                              });
                            }
                          },
                        }}
                      />
                    }
                    mobile={
                      <>
                        <div className="nfc-mobile-record-list">
                          {(previewData.items || []).length === 0 ? (
                            <Empty
                              image={Empty.PRESENTED_IMAGE_SIMPLE}
                              description="当前预览无操作项"
                            />
                          ) : (
                            (previewData.items || []).map((item, index) => (
                              <article
                                className="nfc-workflow-preview-item-mobile-card"
                                key={`${item.source_path}-${item.operation}-${index}`}
                              >
                                <div className="nfc-mobile-record-heading">
                                  <div className="nfc-inline-badges">
                                    <span className={`nfc-operation-badge nfc-operation-${item.operation}`}>
                                      {item.operation}
                                    </span>
                                    <span className="nfc-mono">
                                      #{computePreviewRowIndex(page, pageSize, index)}
                                    </span>
                                  </div>
                                  <StatusBadge
                                    status={item.changed ? "validating" : "completed"}
                                    label={item.changed ? "有变更" : "保持/更新"}
                                  />
                                </div>
                                <div className="nfc-plan-item-paths">
                                  <div className="nfc-plan-item-path-row">
                                    <span>源路径</span>
                                    <CodePath value={item.source_path} />
                                  </div>
                                  <div className="nfc-plan-item-path-row">
                                    <span>
                                      {item.operation === "touch"
                                        ? "mtime"
                                        : "目标"}
                                    </span>
                                    {item.operation === "touch" ? (
                                      <span className="nfc-table-meta">
                                        {item.mtime_ns
                                          ? new Date(
                                              item.mtime_ns / 1e6
                                            ).toLocaleString()
                                          : "当前时间"}
                                      </span>
                                    ) : (
                                      <CodePath value={item.target_path} muted />
                                    )}
                                  </div>
                                </div>
                              </article>
                            ))
                          )}
                        </div>
                        <div className="nfc-mobile-pagination">
                          <Pagination
                            current={page}
                            pageSize={pageSize}
                            total={previewData.planned_operations_count ?? 0}
                            showSizeChanger
                            pageSizeOptions={["20", "50", "100"]}
                            onChange={(nextPage, nextPageSize) => {
                              if (previewState === "PREVIEW_READY") {
                                triggerPreview({
                                  page: nextPage,
                                  pageSize: nextPageSize,
                                });
                              }
                            }}
                          />
                        </div>
                      </>
                    }
                  />
                </>
              ))}
          </>
        )}
      </div>
    </DataPanel>
  );
};
