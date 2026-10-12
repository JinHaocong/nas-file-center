import React, { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { batchApi, plansApi } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import type { RenameProposal } from '../../types';
import {
  type AdvancedRenameDraft, type AdvancedRenameRequest,
  DEFAULT_ADVANCED_RENAME_DRAFT, buildAdvancedRenameRequest, canGenerateAdvancedRenamePlan,
} from '../../utils/advancedRenameSafety';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { getPaginationState } from '../../components/ui/paginationModel';

/** Advanced Regex Rename: Preview -> conflict-free rename Plan; never immediate file edits. */
export const AdvancedRenameEditor: React.FC = () => {
  const navigate = useNavigate();
  const toast = useConsoleToast();
  const [draft, setDraft] = useState<AdvancedRenameDraft>({ ...DEFAULT_ADVANCED_RENAME_DRAFT, paths: [] });
  const [proposals, setProposals] = useState<RenameProposal[] | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const activePreviewKey = useRef<string | null>(null);
  const previewGuard = useRef(false);
  const planGuard = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; activePreviewKey.current = null; };
  }, []);

  const invalidatePreview = () => {
    activePreviewKey.current = null;
    setProposals(null);
    setPage(1);
  };
  const patch = <K extends keyof AdvancedRenameDraft>(field: K, value: AdvancedRenameDraft[K]) => {
    if (planGuard.current) return;
    setDraft(previous => ({ ...previous, [field]: value }));
    invalidatePreview();
  };

  const previewMutation = useMutation({
    mutationFn: (payload: AdvancedRenameRequest) => batchApi.previewRename(payload),
  });
  const planMutation = useMutation({ mutationFn: plansApi.createPlan });
  const busy = previewLoading || planLoading;
  const hasConflicts = proposals?.some(proposal => proposal.conflict) ?? false;
  const canPlan = canGenerateAdvancedRenamePlan(proposals, activePreviewKey.current,
    busy || previewGuard.current || planGuard.current);

  const handlePreview = async () => {
    if (previewGuard.current || planGuard.current) return;
    const payload = buildAdvancedRenameRequest(draft);
    if (!payload) {
      toast.error(draft.paths.length === 0
        ? '请至少选择或输入一个待重命名路径'
        : '编号设置无效：起始值须为非负整数，补零宽度须在 1 到 10 之间');
      return;
    }
    invalidatePreview();
    const key = JSON.stringify(payload);
    activePreviewKey.current = key;
    previewGuard.current = true;
    setPreviewLoading(true);
    try {
      const result = await previewMutation.mutateAsync(payload);
      if (!mountedRef.current || activePreviewKey.current !== key) return;
      setProposals(result.items);
      const conflicts = result.items.filter(item => item.conflict).length;
      if (conflicts) toast.error(`预览完成，但发现 ${conflicts} 处重命名冲突！`);
      else toast.success(`预览完成，成功生成 ${result.items.length} 个重命名提议`);
    } catch (error: unknown) {
      if (mountedRef.current && activePreviewKey.current === key) {
        invalidatePreview();
        toast.error(getStructuredApiError(error).message || '重命名预览失败');
      }
    } finally {
      previewGuard.current = false;
      if (mountedRef.current) setPreviewLoading(false);
    }
  };

  const handleGeneratePlan = async () => {
    if (planGuard.current || previewGuard.current ||
        !canGenerateAdvancedRenamePlan(proposals, activePreviewKey.current, busy)) return;
    const currentPayload = buildAdvancedRenameRequest(draft);
    if (!currentPayload || JSON.stringify(currentPayload) !== activePreviewKey.current || !proposals) return;
    const items = proposals.map(proposal => ({
      operation: 'rename', source: proposal.source, target: proposal.target,
    }));
    planGuard.current = true;
    setPlanLoading(true);
    try {
      const result = await planMutation.mutateAsync({
        name: '批量重命名计划', kind: 'rename', items,
      });
      if (!mountedRef.current) return;
      toast.success(`已生成批量重命名计划 #${result.id}`);
      navigate(`/plans/${result.id}`);
    } catch (error: unknown) {
      if (mountedRef.current) toast.error(getStructuredApiError(error).message || '生成计划失败');
    } finally {
      planGuard.current = false;
      if (mountedRef.current) setPlanLoading(false);
    }
  };

  const field = (
    key: Exclude<keyof AdvancedRenameDraft, 'paths' | 'include_parent'>,
    label: string, placeholder: string, hint?: string,
  ) => (
    <label className="nfc-v2-advanced-rename-field">
      <span>{label}</span>
      <input name={key} type={key === 'number_start' || key === 'number_width' ? 'number' : 'text'}
        min={key === 'number_start' ? 0 : key === 'number_width' ? 1 : undefined}
        max={key === 'number_width' ? 10 : undefined}
        step={key === 'number_start' || key === 'number_width' ? 1 : undefined}
        placeholder={placeholder} value={String(draft[key])} disabled={planLoading}
        onChange={event => patch(key, event.target.value)} />
      {hint && <small>{hint}</small>}
    </label>
  );
  const pages = getPaginationState(page, pageSize, proposals?.length || 0);
  const visible = (proposals || []).slice((pages.current - 1) * pageSize, pages.current * pageSize);
  const status = (proposal: RenameProposal) => (
    <StatusBadge status={proposal.conflict ? 'failed' : 'completed'}
      label={proposal.conflict ? `冲突: ${proposal.conflict_reason || '目标已存在'}` : '安全'} />
  );

  return (
    <div className="nfc-v2-advanced-rename">
      <PageHeader title="批量重命名"
        description="组合正则、扩展名替换、前后缀、父目录名与编号规则；必须先 Preview，并在无冲突时生成 Rename Plan。" />
      <DataPanel title="重命名规则"
        description="Preview 只计算目标路径与冲突；不会直接修改任何文件名。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench">
        <div className="nfc-rename-form nfc-v2-advanced-rename-form">
          <div className="nfc-v2-advanced-rename-field">
            <span>文件或目录绝对路径清单</span>
            <DirectoryPicker multiple value={draft.paths} disabled={planLoading}
              placeholder="点击选择或添加待重命名目录..."
              onChange={paths => {
                if (Array.isArray(paths)) patch('paths', paths);
                else patch('paths', paths ? [paths] : []);
              }} />
            <small>支持可视化选择目录或高级手动多行输入；路径必须符合后端白名单。</small>
          </div>
          <div className="nfc-form-grid">
            {field('regex_pattern', '正则查找 (Regex Pattern)', String.raw`例如：^DSC_(\d+)`)}
            {field('regex_replacement', '正则替换 (Replacement)', '例如：Photo_$1')}
          </div>
          <div className="nfc-form-grid">
            {field('source_extension', '原扩展名过滤', '例如：.webp',
              '可填写 webp 或 .webp；匹配不区分大小写')}
            {field('target_extension', '目标扩展名', '例如：.jpg', '必须与原扩展名过滤同时填写')}
          </div>
          <div className="nfc-v2-advanced-rename-notice nfc-page-alert" role="note">
            <ConsoleIcon name="info" size={18} />
            <div><strong>扩展名替换仅执行重命名</strong>
              <p>只修改文件名后缀，不会转换图片格式，也不会进行 WebP → JPEG 转码。</p>
            </div>
          </div>
          <div className="nfc-form-grid">
            {field('prefix', '添加前缀 (Prefix)', '例如：2026_')}
            {field('suffix', '添加后缀 (Suffix)', '例如：_backup')}
          </div>
          <div className="nfc-form-grid">
            {field('number_start', '起始数字序号 (可选，如 1)', '留空不添加序号')}
            {field('number_width', '序号补零宽度 (位数)', '3')}
          </div>
          <label className="nfc-v2-advanced-rename-check">
            <input name="include_parent" type="checkbox" checked={draft.include_parent}
              disabled={planLoading}
              onChange={event => patch('include_parent', event.target.checked)} />
            <span>在文件名前拼入直接父文件夹名称</span>
          </label>
          <ActionBar className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={previewLoading} disabled={planLoading}
              leadingIcon={<ConsoleIcon name="file-search" size={17}/>}
              onClick={() => { void handlePreview(); }}>生成重命名 Preview</ConsoleButton>
            {proposals && proposals.length > 0 && (
              <ConsoleButton loading={planLoading} disabled={!canPlan}
                leadingIcon={<ConsoleIcon name="calendar" size={17}/>}
                onClick={() => { void handleGeneratePlan(); }}>
                生成执行 Plan ({proposals.length} 项)
              </ConsoleButton>
            )}
          </ActionBar>
        </div>
      </DataPanel>
      {hasConflicts && (
        <div className="nfc-v2-advanced-rename-warning nfc-page-alert" role="alert">
          <ConsoleIcon name="info" size={18}/>
          <div><strong>检测到重命名目标冲突</strong>
            <p>目标路径已存在或产生内部重名冲突；生成 Plan 已锁定，请修正规则并重新 Preview。</p>
          </div>
        </div>
      )}
      {proposals !== null && (
        <DataPanel title="重命名 Preview"
          description="逐项检查 source → target 与冲突状态；只有全量安全时才能生成 Plan。"
          action={<span className="nfc-panel-count">{proposals.length} proposals</span>}
          className="nfc-panel-flush nfc-file-tool-result-panel" variant="dense">
          {visible.length === 0 ? (
            <ConsoleEmpty title="无重命名提议" description="可以修改规则并重新执行只读 Preview。" />
          ) : (
            <ResponsiveDataView
              desktop={
                <div className="nfc-v2-advanced-rename-table-scroll">
                  <table className="nfc-v2-advanced-rename-table">
                    <caption className="nfc-v2-advanced-rename-sr-only">高级重命名只读提议与冲突状态</caption>
                    <thead><tr><th scope="col">原完整路径</th><th scope="col">重命名后目标路径</th><th scope="col">状态</th></tr></thead>
                    <tbody>{visible.map((proposal, index) => (
                      <tr key={proposal.source + ':' + index}>
                        <td><CodePath value={proposal.source}/></td>
                        <td><div className="nfc-target-path nfc-v2-advanced-rename-target">
                          <ConsoleIcon name="arrow-right" size={16}/>
                          <CodePath value={proposal.target} muted={proposal.conflict}/>
                        </div></td>
                        <td>{status(proposal)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              }
              mobile={
                <div className="nfc-mobile-record-list nfc-v2-advanced-rename-mobile">
                  {visible.map((proposal, index) => (
                    <article className="nfc-rename-proposal-mobile-card" key={proposal.source + ':' + index}>
                      <div className="nfc-mobile-record-heading">
                        <span className="nfc-kind-badge">rename</span>
                        {status(proposal)}
                      </div>
                      <div className="nfc-plan-item-paths">
                        <div className="nfc-plan-item-path-row">
                          <span>源路径</span><CodePath value={proposal.source}/>
                        </div>
                        <div className="nfc-plan-item-path-row">
                          <span>目标</span><CodePath value={proposal.target} muted={proposal.conflict}/>
                        </div>
                      </div>
                      {proposal.conflict &&
                        <p className="nfc-mobile-record-error">{proposal.conflict_reason || '目标已存在'}</p>}
                    </article>
                  ))}
                </div>
              }
            />
          )}
          <ConsolePagination page={pages.current} pageSize={pageSize} total={proposals.length}
            pageSizes={[10,20,50]} onChange={(nextPage, nextSize) => {
              setPage(nextPage);
              setPageSize(nextSize);
            }} />
        </DataPanel>
      )}
    </div>
  );
};
