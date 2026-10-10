import React, { useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { batchApi, plansApi } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import type { RenameProposal } from '../../types';
import {
  type ImmediateRenameKind, type ImmediateRenameDraft,
  DEFAULT_IMMEDIATE_RENAME_DRAFT, buildImmediateRenameRequest,
  canCreateImmediateRenamePlan, type ImmediateRenameRequest,
} from '../../utils/immediateRenameSafety';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { CodePath } from '../../components/ui/CodePath';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { getPaginationState } from '../../components/ui/paginationModel';

interface Props { kind: ImmediateRenameKind; }
/** UI sends preview/Plan requests only. The backend remains authoritative for allowed paths and mutations. */
export const ImmediateRenameEditor: React.FC<Props> = ({ kind }) => {
  const navigate = useNavigate();
  const toast = useConsoleToast();
  const isFile = kind === 'file';
  const label = isFile ? '文件' : '目录';
  const [draft, setDraft] = useState<ImmediateRenameDraft>({ ...DEFAULT_IMMEDIATE_RENAME_DRAFT });
  const [proposals, setProposals] = useState<RenameProposal[] | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const activePreviewKey = useRef<string | null>(null);
  const previewGuard = useRef(false);
  const planGuard = useRef(false);

  const invalidatePreview = () => {
    activePreviewKey.current = null;
    setProposals(null);
    setPage(1);
  };
  const patch = <K extends keyof ImmediateRenameDraft>(key: K, value: ImmediateRenameDraft[K]) => {
    if (planGuard.current) return;
    setDraft(old => ({ ...old, [key]: value }));
    invalidatePreview();
  };
  const previewMutation = useMutation({
    mutationFn: (request: ImmediateRenameRequest) => isFile
      ? batchApi.previewImmediateFileRename({
        parent: request.parent, mode: request.mode, find: request.find,
        value: request.value, preserve_extension: request.preserve_extension !== false,
      })
      : batchApi.previewImmediateDirectoryRename({
        parent: request.parent, mode: request.mode, find: request.find, value: request.value,
      }),
  });
  const planMutation = useMutation({ mutationFn: plansApi.createPlan });
  const busy = previewLoading || planLoading;
  const hasConflicts = proposals?.some(item => item.conflict) ?? false;
  const canPlan = canCreateImmediateRenamePlan(proposals, activePreviewKey.current,
    busy || previewGuard.current || planGuard.current);

  const handlePreview = async () => {
    if (previewGuard.current || planGuard.current) return;
    const request = buildImmediateRenameRequest(kind, draft);
    if (!request) {
      toast.error(!draft.parent.trim() ? '请先选择当前目录' :
        draft.module === 'replace' ? '请输入要查找的字面量文本' : '请输入要新增的文本');
      return;
    }
    invalidatePreview();
    const key = JSON.stringify(request);
    activePreviewKey.current = key;
    previewGuard.current = true;
    setPreviewLoading(true);
    try {
      const result = await previewMutation.mutateAsync(request);
      // Editing while Preview ran invalidates this exact request; never allow stale Plan.
      if (activePreviewKey.current !== key) return;
      setProposals(result.items);
      const conflicts = result.items.filter(item => item.conflict).length;
      if (conflicts) toast.error(`发现 ${conflicts} 项冲突，不能创建执行计划`);
      else toast.success(`预览完成，${result.count} 个${label}需要改名`);
    } catch (error: unknown) {
      if (activePreviewKey.current === key) {
        invalidatePreview();
        toast.error(getStructuredApiError(error).message || label + '重命名预览失败');
      }
    } finally {
      previewGuard.current = false;
      setPreviewLoading(false);
    }
  };
  const generatePlan = async () => {
    if (planGuard.current || previewGuard.current ||
        !canCreateImmediateRenamePlan(proposals, activePreviewKey.current, busy)) return;
    // Check that every rule and path byte still matches the Preview request.
    const request = buildImmediateRenameRequest(kind, draft);
    const key = request ? JSON.stringify(request) : null;
    if (!key || key !== activePreviewKey.current || !proposals) return;
    const items = proposals.map(({ source, target }) => ({ operation: 'rename', source, target }));
    planGuard.current = true;
    setPlanLoading(true);
    try {
      const result = await planMutation.mutateAsync({
        name: `一级${label}批量重命名`, kind: 'rename', items,
      });
      toast.success(`${label}重命名计划 #${result.id} 已创建`);
      navigate(`/plans/${result.id}`);
    } catch (error: unknown) {
      toast.error(getStructuredApiError(error).message || '创建重命名计划失败');
    } finally {
      planGuard.current = false;
      setPlanLoading(false);
    }
  };
  const readonly = planLoading;
  const renderRadio = <T extends string>(name: string, value: T, options: { value: T; label: string }[],
    onChange: (value: T) => void) => (
    <div role="radiogroup" aria-label={name} className="nfc-v2-immediate-radio">
      {options.map(option => (
        <label key={option.value} className={value === option.value ? 'is-selected' : ''}>
          <input type="radio" name={kind + '-' + name} value={option.value}
            checked={value === option.value} disabled={readonly}
            onChange={() => onChange(option.value)} />
          <span>{option.label}</span>
        </label>
      ))}
    </div>
  );
  const textInput = (id: string, title: string, value: string,
    onChange: (value: string) => void, placeholder: string, required = false) => (
    <label className="nfc-v2-immediate-field" htmlFor={kind + '-' + id}>
      <span>{title}</span>
      <input id={kind + '-' + id} type="text" value={value} maxLength={255}
        required={required} disabled={readonly} placeholder={placeholder}
        onChange={event => onChange(event.target.value)} />
    </label>
  );
  const pages = getPaginationState(page, pageSize, proposals?.length ?? 0);
  const visible = proposals?.slice((pages.current - 1) * pageSize, pages.current * pageSize) || [];
  const renderStatus = (item: RenameProposal) => (
    <StatusBadge status={item.conflict ? 'failed' : 'completed'}
      label={item.conflict ? item.conflict_reason || '命名冲突' : '安全'} />
  );

  return (
    <div className="nfc-v2-immediate-rename">
      <PageHeader title={`一级${label}批量重命名`}
        description={isFile
          ? '只处理选中目录下的直接普通文件；不递归、不修改目录。按字面量操作，不使用正则。'
          : '只处理选中目录的直接子目录；不递归、不改文件、不改选中目录本身。所有替换按字面量处理，不使用正则表达式。'} />
      <DataPanel title="选择目录和命名规则"
        description="先生成只读预览，再生成 Rename Plan；需要经原有 Plan 校验和 Worker 执行。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench">
        <div className="nfc-v2-immediate-editor-form">
          <div className="nfc-v2-immediate-field">
            <span>当前目录</span>
            <DirectoryPicker multiple={false} value={draft.parent} disabled={readonly}
              placeholder={isFile ? '选择需要批量重命名直接文件的目录' : '选择需要批量重命名其子文件夹的目录'}
              onChange={path => { if (typeof path === 'string') patch('parent', path); }} />
            <small>{isFile
              ? '只处理当前目录的直接普通文件；子文件夹内的文件不参与。'
              : '只处理该目录下的一级子文件夹；其内部的文件和更深层文件夹不会被逐项重命名。'}</small>
          </div>
          <div className="nfc-v2-immediate-field">
            <span>操作模块</span>
            {renderRadio('操作模块', draft.module, [
              { value: 'replace', label: '批量替换' }, { value: 'add', label: '新增内容' },
            ], value => patch('module', value))}
          </div>
          {draft.module === 'replace' ? (
            <>
              <div className="nfc-v2-immediate-field">
                <span>替换范围</span>
                {renderRadio('替换范围', draft.replaceTarget, [
                  { value: 'name', label: '替换名称中的字面量' },
                  { value: 'suffix', label: isFile ? '替换文件主名末尾的字面量' : '替换名称末尾的字面量' },
                ], value => patch('replaceTarget', value))}
              </div>
              <div className="nfc-v2-immediate-notice" role="note">
                <ConsoleIcon name="info" size={17} />
                {isFile
                  ? (draft.replaceTarget === 'name'
                    ? '名称替换只针对当前处理范围（默认不含最后一个扩展名）中完全匹配的文本，区分大小写'
                    : '末尾替换作用于当前处理范围的结尾：保留扩展名时为主名末尾，关闭时为整个文件名末尾')
                  : (draft.replaceTarget === 'name'
                    ? '名称替换会替换目录名中出现的全部完全匹配文本（区分大小写）'
                    : '末尾替换仅在整个目录名以指定文本结尾时生效；目录名中的点号也按普通字符处理')}
              </div>
              <div className="nfc-form-grid">
                {textInput('find', '查找字面量', draft.find, value => patch('find', value),
                  draft.replaceTarget === 'name' ? '例如：旧名称' : '例如：_old', true)}
                {textInput('value', '替换为（可留空表示删除）', draft.value,
                  value => patch('value', value), '例如：新名称')}
              </div>
            </>
          ) : (
            <>
              <div className="nfc-v2-immediate-field">
                <span>新增位置</span>
                {renderRadio('新增位置', draft.addPosition, [
                  { value: 'prefix', label: '前缀' }, { value: 'suffix', label: '后缀' },
                ], value => patch('addPosition', value))}
              </div>
              {textInput('value', draft.addPosition === 'prefix' ? '新增前缀' : '新增后缀',
                draft.value, value => patch('value', value),
                draft.addPosition === 'prefix' ? '例如：2026_' : '例如：_完成', true)}
            </>
          )}
          {isFile && (
            <label className="nfc-v2-immediate-preserve">
              <input type="checkbox" checked={draft.preserveExtension} disabled={readonly}
                onChange={event => patch('preserveExtension', event.target.checked)} />
              <span>保留文件扩展名（推荐）</span>
              <small>仅修改最后一个扩展名前的内容，例如 .jpg、.gz；关闭后将修改完整文件名。</small>
            </label>
          )}
          <ActionBar className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={previewLoading} disabled={planLoading}
              leadingIcon={<ConsoleIcon name="file-search" size={17}/>}
              onClick={() => { void handlePreview(); }}>生成一级{label} Preview</ConsoleButton>
            {proposals !== null && proposals.length > 0 && (
              <ConsoleButton disabled={!canPlan} loading={planLoading}
                leadingIcon={<ConsoleIcon name="calendar" size={17}/>}
                onClick={() => { void generatePlan(); }}>生成执行 Plan（{proposals.length} 项）</ConsoleButton>
            )}
          </ActionBar>
        </div>
      </DataPanel>
      {hasConflicts && (
        <div className="nfc-v2-immediate-error" role="alert">
          <ConsoleIcon name="info" size={19}/>
          <div><strong>存在目标{label}重名或不安全路径</strong>
            <p>请修改规则并重新预览。已有{label}不会被覆盖；全部安全后才允许生成计划。</p>
          </div>
        </div>
      )}
      {proposals !== null && (
        <DataPanel title={isFile ? '一级文件改名预览' : '一级子目录改名预览'}
          description={`仅显示名称会变化的一级${label}；无匹配项表示无需重命名。`}
          action={<span className="nfc-panel-count">{proposals.length} 个{label}</span>}
          className="nfc-panel-flush nfc-file-tool-result-panel" variant="dense">
          {visible.length === 0 ? (
            <ConsoleEmpty title={`没有需要重命名的一级${label}`} description="更换规则后可重新执行只读 Preview。" />
          ) : (
            <ResponsiveDataView
              desktop={
                <div className="nfc-v2-immediate-table-scroll">
                  <table className="nfc-v2-immediate-table">
                    <caption className="nfc-v2-immediate-sr-only">一级{label}重命名只读提议</caption>
                    <thead><tr><th scope="col">原{label}</th><th scope="col">新{label}</th><th scope="col">预览状态</th></tr></thead>
                    <tbody>{visible.map((item, i) => (
                      <tr key={item.source + ':' + i}>
                        <td><CodePath value={item.source}/></td>
                        <td><div className="nfc-target-path nfc-v2-immediate-target">
                          <ConsoleIcon name="arrow-right" size={15}/>
                          <CodePath value={item.target} muted={item.conflict}/>
                        </div></td>
                        <td>{renderStatus(item)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              }
              mobile={
                <div className="nfc-mobile-record-list nfc-v2-immediate-mobile-list">
                  {visible.map((item, i) => (
                    <article className="nfc-rename-proposal-mobile-card" key={item.source + ':' + i}>
                      <div className="nfc-mobile-record-heading">
                        <span className="nfc-kind-badge">rename</span>
                        {renderStatus(item)}
                      </div>
                      <div className="nfc-plan-item-paths">
                        <div className="nfc-plan-item-path-row"><span>原{label}</span><CodePath value={item.source}/></div>
                        <div className="nfc-plan-item-path-row"><span>目标</span><CodePath value={item.target} muted={item.conflict}/></div>
                      </div>
                      {item.conflict && <p className="nfc-mobile-record-error">{item.conflict_reason}</p>}
                    </article>
                  ))}
                </div>
              }
            />
          )}
          <ConsolePagination page={pages.current} pageSize={pageSize} total={proposals.length}
            pageSizes={[10,20,50]} onChange={(p, size) => { setPage(p); setPageSize(size); }} />
        </DataPanel>
      )}
    </div>
  );
};
