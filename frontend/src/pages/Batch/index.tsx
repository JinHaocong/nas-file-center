import React, { useEffect, useId, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { plansApi } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import { organizerJobId } from '../../api/mediaOrganizerBatch';
import { useTitle } from '../../hooks/useTitle';
import { splitLines } from '../../utils/format';
import { type BatchOperation, buildBatchDraft } from '../../utils/batchDraftSafety';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { fileWorkspaceReturn } from '../../components/layout/navItems';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { MediaSortEditor } from './MediaSortEditor';
import { MediaOrganizerBatchEditor } from './MediaOrganizerBatchEditor';

type BatchMode = BatchOperation | 'media-sort' | 'media-organize';
const operations: readonly { op: BatchMode; title: string }[] = [
  { op: 'quarantine', title: '批量隔离' },
  { op: 'touch', title: '更新时间戳' },
  { op: 'move', title: '批量移动' },
  { op: 'rename', title: '批量改名' },
  { op: 'media-sort', title: '媒体分类' },
  { op: 'media-organize', title: '智能媒体整理' },
];

/** Open the unified organizer from new and historical links. */
function opensMediaOrganizer(params: URLSearchParams): boolean {
  const operation = params.get('operation');
  return operation === 'media-organize' || operation === 'media_package-organize' ||
    operation === 'semantic-media-organize' || params.has('execution') ||
    params.has('preview') || params.has('batch');
}

/** Only create a Plan Draft, never Freeze/Validate/Execute a filesystem operation. */
export const BatchPage: React.FC = () => {
  useTitle('批量处理');
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const toast = useConsoleToast();
  const [name, setName] = useState('批量处理');
  // Both tool-directory links and browser Back can change only the query string.
  const operation: BatchMode = opensMediaOrganizer(searchParams) ? 'media-organize' :
    operations.find(item => item.op === searchParams.get('operation'))?.op ?? 'quarantine';
  const [paths, setPaths] = useState<string[]>([]);
  const [mappingsText, setMappingsText] = useState('');
  const [planLoading, setPlanLoading] = useState(false);
  const [validationError, setValidationError] = useState('');
  const [toolPickerOpen, setToolPickerOpen] = useState(false);
  const toolPicker = useRef<HTMLDivElement>(null);
  const toolPickerTrigger = useRef<HTMLButtonElement>(null);
  const toolPickerMenuId = useId();
  const mountedRef = useRef(true);
  const planGuard = useRef(false);
  const planMutation = useMutation({ mutationFn: plansApi.createPlan });

  useEffect(() => { setValidationError(''); setToolPickerOpen(false); }, [operation]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (!toolPickerOpen) return;
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !toolPicker.current?.contains(event.target)) {
        setToolPickerOpen(false);
      }
    };
    document.addEventListener('pointerdown', closeOutside);
    return () => document.removeEventListener('pointerdown', closeOutside);
  }, [toolPickerOpen]);

  const handleGeneratePlan = async () => {
    if (planGuard.current) return;
    const { draft, error } = buildBatchDraft(name, operation, paths, mappingsText);
    if (!draft) {
      const message = error || '请检查计划内容';
      setValidationError(message);
      toast.error(message);
      return;
    }
    setValidationError('');
    planGuard.current = true;
    setPlanLoading(true);
    try {
      const created = await planMutation.mutateAsync(draft);
      if (!mountedRef.current) return;
      toast.success('已生成批量处理计划 #' + created.id + '，仍需冻结与校验');
      navigate('/plans/' + created.id);
    } catch (error: unknown) {
      if (mountedRef.current) {
        toast.error(getStructuredApiError(error).message || '生成计划失败');
      }
    } finally {
      planGuard.current = false;
      if (mountedRef.current) setPlanLoading(false);
    }
  };

  /** Change tools and clear an organizer link when leaving the organizer. */
  const onOperationChange = (next: BatchMode) => {
    if (planGuard.current) return;
    closeToolPicker();
    setSearchParams(current => {
      const params = new URLSearchParams(current);
      for (const key of ['directory', 'execution', 'preview', 'batch']) params.delete(key);
      if (next === 'quarantine') params.delete('operation');
      else params.set('operation', next);
      return params;
    });
    setValidationError('');
  };
  const onPathsChange = (next: string | string[]) => {
    if (planGuard.current) return;
    setPaths(Array.isArray(next) ? [...next] : splitLines(next));
    setValidationError('');
  };

  const isMedia = operation === 'media-sort' || operation === 'media-organize';
  const returnToFiles = operation === 'media-organize' ? fileWorkspaceReturn(location.state) : undefined;
  const organizerTask = operation === 'media-organize' &&
    (organizerJobId(searchParams, 'batch') ?? organizerJobId(searchParams, 'preview'));
  const tool = operations.find(item => item.op === operation);
  const scopeCount = operation === 'move' || operation === 'rename' ? splitLines(mappingsText).length : paths.length;
  /** Return to the stable trigger when a tool opens or the chooser is dismissed by keyboard. */
  function closeToolPicker() {
    setToolPickerOpen(false);
    toolPickerTrigger.current?.focus({ preventScroll: true });
  }
  const toolChooser = (
    <div className="nfc-studio-tool-picker" ref={toolPicker}
      onBlur={event => {
        if (event.relatedTarget instanceof Node && !event.currentTarget.contains(event.relatedTarget)) setToolPickerOpen(false);
      }}
      onKeyDown={event => {
        if (event.key === 'Escape' && toolPickerOpen) {
          event.preventDefault();
          closeToolPicker();
        }
      }}>
      <button type="button" className="nfc-studio-tool-picker-trigger" ref={toolPickerTrigger}
        aria-expanded={toolPickerOpen} aria-controls={toolPickerOpen ? toolPickerMenuId : undefined}
        onClick={() => setToolPickerOpen(open => !open)}>
        <ConsoleIcon name="sliders" size={15} />切换文件工具<ConsoleIcon name="chevron-down" size={14} />
      </button>
      {toolPickerOpen && (
        <div id={toolPickerMenuId} className="nfc-v2-batch-operations nfc-studio-tool-picker-panel" role="group" aria-label="操作类型">
          <p className="nfc-v2-batch-operation-label">操作类型</p>
          <div className="nfc-batch-operation-grid">
            {operations.map(item => (
              <button type="button" key={item.op} className={'nfc-v2-batch-radio' +
                (operation === item.op ? ' is-selected' : '')} aria-pressed={operation === item.op}
                disabled={planLoading} onClick={() => onOperationChange(item.op)}>
                <i className="nfc-v2-batch-operation-indicator" aria-hidden="true" />
                <span>{item.title}</span>
              </button>
            ))}
            <button type="button" className="nfc-v2-batch-radio is-disabled" disabled>
              <i className="nfc-v2-batch-operation-indicator" aria-hidden="true" />
              <span>硬链接去重<small>未实现</small></span>
            </button>
            <button type="button" className="nfc-v2-batch-radio is-disabled" disabled>
              <i className="nfc-v2-batch-operation-indicator" aria-hidden="true" />
              <span>Reflink 浅克隆<small>未实现</small></span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
  return (
    <div className="nfc-operations-page nfc-batch-page nfc-page-layout-workbench nfc-v2-batch"
      data-media-organizer={operation === 'media-organize' || undefined}>
      <PageHeader title={tool?.title ?? '批量处理'} actions={<ActionBar compact>
        {returnToFiles && <Link className="nfc-console-button nfc-console-button-secondary nfc-console-button-sm"
          to={returnToFiles} state={{ restoreFileWorkspace: true }}>
          <ConsoleIcon name="arrow-left" size={16} />返回文件空间
        </Link>}
        {organizerTask && <Link className="nfc-console-button nfc-console-button-ghost nfc-console-button-sm"
          to={'/tasks?' + new URLSearchParams({ task: organizerTask })} state={{ fileWorkspaceReturn: returnToFiles }}>
          <ConsoleIcon name="activity" size={16} />查看任务
        </Link>}
        {toolChooser}
      </ActionBar>} />

      {!isMedia && <div className="nfc-batch-authoring">
        <DataPanel title="操作范围" description="核对路径后生成执行计划。"
          className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench">
          <div className="nfc-batch-form nfc-v2-batch-form">
            <label className="nfc-v2-batch-field">
              <span>计划名称</span>
              <input value={name} required disabled={planLoading}
                placeholder="批量处理计划" aria-invalid={Boolean(validationError) && !name.trim()}
                onChange={event => { setName(event.target.value); setValidationError(''); }} />
            </label>

            {operation === 'quarantine' && (
              <div className="nfc-v2-batch-notice nfc-page-alert" role="note">
                <ConsoleIcon name="shield-check" size={19} />
                <div><strong>Quarantine-first 隔离</strong>
                  <p>文件移动到 NAS File Center 隔离区并保留原目录结构；不会直接永久删除。</p>
                </div>
              </div>
            )}
            {(operation === 'quarantine' || operation === 'touch') && (
              <div className="nfc-v2-batch-field" role="group" aria-label="文件或目录绝对路径清单">
                <span>文件或目录绝对路径清单</span>
                <DirectoryPicker multiple value={paths} disabled={planLoading}
                  placeholder="点击选择或添加目录或路径..."
                  onChange={onPathsChange} />
                <small>支持可视化选择目录；单文件路径可通过高级手动输入填写。</small>
              </div>
            )}
            {(operation === 'move' || operation === 'rename') && (
              <label className="nfc-v2-batch-field">
                <span>路径映射清单</span>
                <textarea rows={7} className="nfc-mono-input" disabled={planLoading}
                  value={mappingsText}
                  placeholder={'/data/DiskA/file1.txt -> /data/DiskB/file1.txt\n/data/DiskA/file2.txt -> /data/DiskB/file2.txt'}
                  onChange={event => { setMappingsText(event.target.value); setValidationError(''); }} />
                <small>每行一条：源路径 -&gt; 目标路径；均需填写绝对路径。</small>
              </label>
            )}
            {validationError && <p className="nfc-v2-batch-error" role="alert">{validationError}</p>}
          </div>
        </DataPanel>
        <DataPanel title="计划摘要" className="nfc-batch-draft-inspector" variant="quiet">
          <dl>
            <div><dt>操作类型</dt><dd>{tool?.title}</dd></div>
            <div><dt>{operation === 'move' || operation === 'rename' ? '路径映射' : '已选路径'}</dt><dd>{scopeCount.toLocaleString()} 项</dd></div>
          </dl>
          <ActionBar className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={planLoading}
              leadingIcon={<ConsoleIcon name="calendar" size={17} />}
              onClick={() => { void handleGeneratePlan(); }}>
              生成批量处理 Plan
            </ConsoleButton>
            <span className="nfc-form-note">
              Plan 创建后仍需在计划详情完成 Freeze、Validate 与 Execute。
            </span>
          </ActionBar>
        </DataPanel>
      </div>}
      {operation === 'media-sort' && <MediaSortEditor />}
      {operation === 'media-organize' && <MediaOrganizerBatchEditor />}
    </div>
  );
};
