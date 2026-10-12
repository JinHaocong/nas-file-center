import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { workflowApi } from '../../api/workflows';
import { formatDedupeErrorMessage, getStructuredApiError } from '../../api/errors';
import type { WorkflowPreviewItem } from '../../types/workflow';
import { computeRebuildReadiness } from '../../utils/rebuildReadiness';
import { useResponsive } from '../../hooks/useResponsive';
import { ConsoleSheet } from '../ui/ConsoleSheet';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { ConsolePagination } from '../ui/ConsolePagination';
import { ConsoleEmpty } from '../ui/ConsoleEmpty';
import { CodePath } from '../ui/CodePath';
import { useConsoleToast } from '../ui/ConsoleToast';

interface StaleRebuildDrawerProps {
  open: boolean;
  planId: number;
  onClose: () => void;
  onRebuildSuccess: (newPlanId: number) => void;
}

const operationTone: Record<string, string> = {
  rename: 'info', move: 'info', touch: 'neutral', quarantine: 'warning',
};
const operationBadge = (op: string) => (
  <span className={'nfc-v2-rebuild-badge is-' + (operationTone[op] || 'neutral')}>{op}</span>
);
const changeBadge = (changed: boolean) => (
  <span className={'nfc-v2-rebuild-badge ' + (changed ? 'is-info' : 'is-neutral')}>
    {changed ? '有变更' : '保持/更新'}
  </span>
);
const targetLabel = (item: WorkflowPreviewItem) =>
  item.operation === 'touch'
    ? 'mtime → ' + (item.mtime_ns ? new Date(item.mtime_ns / 1e6).toLocaleString() : '当前时间')
    : null;

export const StaleRebuildDrawer: React.FC<StaleRebuildDrawerProps> = ({
  open, planId, onClose, onRebuildSuccess,
}) => {
  const { isMobile } = useResponsive();
  const toast = useConsoleToast();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [customPlanName, setCustomPlanName] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [previewInvalidated, setPreviewInvalidated] = useState(false);
  const [acceptedDigest, setAcceptedDigest] = useState<string | null>(null);
  const submitInFlight = useRef(false);
  const [submitBusy, setSubmitBusy] = useState(false);

  const { data: preview, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ['rebuildPlanPreview', planId, page, pageSize],
    queryFn: () => workflowApi.rebuildPlanPreview(planId, { page, page_size: pageSize }),
    enabled: open && !!planId,
  });

  useEffect(() => {
    setPage(1);
    setPageSize(50);
    setCustomPlanName('');
    setErrorMessage(null);
    setAcceptedDigest(null);
    setPreviewInvalidated(false);
  }, [planId]);

  useEffect(() => {
    if (open && preview?.compile_digest && !previewInvalidated) {
      setAcceptedDigest(preview.compile_digest);
    }
  }, [open, preview, previewInvalidated]);

  const handleManualRefresh = async () => {
    if (submitInFlight.current || submitBusy) return;
    setErrorMessage(null);
    setPreviewInvalidated(true);
    setAcceptedDigest(null);
    try {
      const res = await refetch();
      if (res.isSuccess && res.data?.compile_digest) {
        setAcceptedDigest(res.data.compile_digest);
        setPreviewInvalidated(false);
      } else {
        setPreviewInvalidated(true);
        setAcceptedDigest(null);
      }
    } catch {
      setPreviewInvalidated(true);
      setAcceptedDigest(null);
    }
  };

  const readiness = computeRebuildReadiness({
    hasPreview: Boolean(preview),
    previewInvalidated, acceptedDigest, isLoading, isFetching,
  });

  const rebuildMutation = useMutation({
    mutationFn: async (digest: string) => workflowApi.rebuildPlan(planId, {
      expected_compile_digest: digest,
      plan_name: customPlanName.trim() || undefined,
    }),
    onSuccess: data => {
      toast.success('全新重建草稿计划 #' + (data.id || data.plan_id) + ' 创建成功');
      onClose();
      onRebuildSuccess(data.id || data.plan_id);
    },
    onError: (err: unknown) => {
      const structured = getStructuredApiError(err);
      if (structured.code === 'PREVIEW_CHANGED') {
        setPreviewInvalidated(true);
        setAcceptedDigest(null);
        setErrorMessage('文件状态或底层快照已变化，请重新刷新预览。');
      } else if (structured.code === 'WORKFLOW_ARCHIVED') {
        setErrorMessage('关联工作流已归档，无法重新生成计划。');
      } else if (structured.code === 'DEDUPE_RESCAN_REQUIRED') {
        setErrorMessage(formatDedupeErrorMessage(err));
      } else {
        setErrorMessage(structured.message || '重建计划失败');
      }
    },
  });
  const closeSafely = () => {
    if (!submitInFlight.current && !submitBusy && !rebuildMutation.isPending) onClose();
  };
  const submitRebuild = async () => {
    if (!open || submitInFlight.current || submitBusy || rebuildMutation.isPending) return;
    if (!readiness.canSubmit || !readiness.submitDigest) {
      setErrorMessage('当前预览已失效或正在获取，请先刷新预览');
      return;
    }
    submitInFlight.current = true;
    setSubmitBusy(true);
    try {
      await rebuildMutation.mutateAsync(readiness.submitDigest);
    } catch {
      // Failure is reported by mutation.onError; digest mismatch requires fresh Preview.
    } finally {
      submitInFlight.current = false;
      setSubmitBusy(false);
    }
  };

  const items = preview?.items || [];
  const renderTarget = (item: WorkflowPreviewItem) => {
    const time = targetLabel(item);
    return time ? <span className="nfc-table-meta">{time}</span>
      : item.target_path ? <CodePath value={item.target_path} /> : '—';
  };

  return (
    <ConsoleSheet open={open} onClose={closeSafely}
      title={'过期计划 #' + planId}
      eyebrow="REBUILD PREVIEW"
      description="基于权威 Workflow Lineage 和快照重新生成草稿；不自动执行或修改源文件。"
      className="nfc-stale-rebuild-drawer nfc-v2-stale-rebuild"
      titleAside={<div className="nfc-v2-rebuild-actions">
        <ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="refresh" size={15} />}
          onClick={() => { void handleManualRefresh(); }}
          disabled={submitBusy || rebuildMutation.isPending}
          loading={isLoading || isFetching}>刷新预览</ConsoleButton>
        <ConsoleButton size="sm" variant="primary" leadingIcon={<ConsoleIcon name="zap" size={15} />}
          loading={submitBusy} disabled={!readiness.canSubmit || submitBusy || rebuildMutation.isPending}
          onClick={() => { void submitRebuild(); }}>生成草稿</ConsoleButton>
      </div>}>
      <div className="nfc-overlay-stack nfc-v2-rebuild-body">
        {previewInvalidated && <div className="nfc-v2-rebuild-alert is-warning" role="alert">
          <ConsoleIcon name="info" size={17} /><div>
            <strong>预览摘要已失效</strong>
            <p>底层状态已变化，旧编译摘要不能提交。请刷新预览获取新的 digest。</p>
          </div>
        </div>}
        {errorMessage && <div className="nfc-v2-rebuild-alert is-error" role="alert">
          <ConsoleIcon name="info" size={17} /><div>
            <strong>重建操作受阻</strong><p>{errorMessage}</p>
            <ConsoleButton size="sm" variant="ghost" onClick={() => setErrorMessage(null)}>关闭提示</ConsoleButton>
          </div>
        </div>}
        {isError && <div className="nfc-v2-rebuild-alert is-error" role="alert">
          <ConsoleIcon name="info" size={17} /><div>
            <strong>无法生成重建预览</strong><p>{formatDedupeErrorMessage(error)}</p>
          </div>
        </div>}
        {isLoading && <div className="nfc-overlay-loading" role="status">
          正在基于权威 Lineage 与快照计算预览…
        </div>}
        {preview && (
          <>
            <section className="nfc-overlay-section">
              <header className="nfc-overlay-section-header"><div>
                <span>Authority</span><h3>重建基线</h3>
              </div></header>
              <dl className="nfc-v2-rebuild-facts">
                <div><dt>工作流</dt><dd>#{preview.workflow_id}</dd></div>
                <div><dt>Lineage Revision</dt><dd>r{preview.workflow_revision}</dd></div>
                <div><dt>计划项</dt><dd>{preview.planned_operations_count}</dd></div>
                <div><dt>匹配对象</dt><dd>{preview.matched_count}</dd></div>
                <div className="is-wide"><dt>Compile Digest</dt>
                  <dd><code>{preview.compile_digest}</code></dd></div>
                <div className="is-wide"><dt>Definition SHA256</dt>
                  <dd><code>{preview.definition_sha256}</code></dd></div>
              </dl>
            </section>
            <section className="nfc-overlay-section nfc-overlay-section-flush">
              <header className="nfc-overlay-section-header nfc-overlay-section-header-actions"><div>
                <span>Operations</span><h3>计划操作预览</h3>
              </div></header>
              <label className="nfc-v2-rebuild-name">草稿计划名称（可选）
                <input value={customPlanName} disabled={submitBusy}
                  onChange={event => setCustomPlanName(event.target.value)}
                  placeholder="自定义新草稿名称（可选）" />
              </label>
              {items.length === 0 && <ConsoleEmpty title="无预览操作" description="当前预览没有可显示的操作。" />}
              {items.length > 0 && (isMobile ? (
                <div className="nfc-rebuild-mobile-list">
                  {items.map((item, index) => (
                    <article className="nfc-rebuild-mobile-card" key={item.source_path + item.operation + index}>
                      <div className="nfc-rebuild-mobile-topline">
                        {operationBadge(item.operation)}{changeBadge(item.changed)}
                      </div>
                      <div className="nfc-rebuild-mobile-paths">
                        <CodePath value={item.source_path} /><span>→</span>{renderTarget(item)}
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="nfc-v2-rebuild-table-scroll"><table className="nfc-v2-rebuild-table">
                  <thead><tr><th scope="col">序号</th><th scope="col">操作</th>
                    <th scope="col">变更</th><th scope="col">源路径</th>
                    <th scope="col">目标路径 / mtime</th></tr></thead>
                  <tbody>{items.map((item, index) => (
                    <tr key={item.source_path + item.operation + index}>
                      <td>{(page - 1) * pageSize + index + 1}</td>
                      <td>{operationBadge(item.operation)}</td><td>{changeBadge(item.changed)}</td>
                      <td><CodePath value={item.source_path} /></td>
                      <td>{renderTarget(item)}</td>
                    </tr>
                  ))}</tbody>
                </table></div>
              ))}
              <ConsolePagination page={page} pageSize={pageSize}
                total={preview.planned_operations_count} pageSizes={[20, 50, 100]}
                onChange={(next, size) => {
                  if (submitBusy) return;
                  setPage(size !== pageSize ? 1 : next);
                  setPageSize(size);
                  setAcceptedDigest(null);
                  setPreviewInvalidated(true);
                }} />
              <div className="nfc-v2-rebuild-boundary" role="note">
                <ConsoleIcon name="shield-check" size={16} />
                <span>只生成新的 Draft Plan；执行仍须另行 Freeze → Validate → Execute。</span>
              </div>
            </section>
          </>
        )}
      </div>
    </ConsoleSheet>
  );
};
