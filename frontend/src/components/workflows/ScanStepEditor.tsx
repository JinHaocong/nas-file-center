import React, { useId } from 'react';
import { useQuery } from '@tanstack/react-query';
import { indexesApi } from '../../api/domain';
import type { IndexRoot } from '../../types';
import type { ScanStep, WorkflowMode } from '../../types/workflow';
import { MAX_SCAN_ROOTS, mergeMissingRootIds, selectOrganizerRoot, toggleScanRoot, scanSubpathValue } from '../../utils/workflowStepFields';

interface Props { step: ScanStep; onChange: (step: ScanStep) => void; readOnly?: boolean; mode?: WorkflowMode; }
export const ScanStepEditor: React.FC<Props> = ({ step, onChange, readOnly = false, mode = 'file' }) => {
  const id = useId();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['indexesRootsList'],
    queryFn: async () => (await indexesApi.listIndexes(1, 100)).items,
  });
  const roots: IndexRoot[] = data || [];
  const availableIds = roots.map(r => r.id);
  const selectedIds = step.root_ids || [];
  const shownIds = mergeMissingRootIds(availableIds, selectedIds);
  const isOrganizer = mode === 'organizer';
  const labelForRoot = (rootId: number) => {
    const known = roots.find(r => r.id === rootId);
    return known ? known.root + ' (ID: ' + known.id + ')' : '根目录 #' + rootId + '（当前列表未返回）';
  };
  const handleOrganizerRoot = (value: string) => {
    if (readOnly) return;
    const next = selectOrganizerRoot(selectedIds, Number(value), availableIds);
    if (next.length === 1 && next[0] !== selectedIds[0]) onChange({ ...step, root_ids: next });
  };
  const handleScanRoot = (rootId: number, checked: boolean) => {
    if (readOnly) return;
    const next = toggleScanRoot(selectedIds, rootId, checked, availableIds);
    if (next.length !== selectedIds.length || next.some((root, i) => root !== selectedIds[i])) {
      onChange({ ...step, root_ids: next });
    }
  };
  return (
    <fieldset className="nfc-workflow-step-form nfc-v2-simple-step-form nfc-v2-step-root-form" disabled={readOnly}>
      <div className="nfc-v2-step-field">
        <label id={id + '-root-label'} htmlFor={isOrganizer ? id + '-root' : undefined}>
          扫描索引根目录 (root_ids) <span aria-hidden="true">*</span>
        </label>
        <p id={id + '-root-help'}>{isOrganizer
          ? '整理模式 (Organizer) 仅支持且必须选择 1 个根目录'
          : '选择工作流执行范围所涵盖的已注册索引根路径 (支持多选 1..16)'}</p>
        {isLoading && <span className="nfc-v2-step-muted" role="status">正在加载索引根目录…</span>}
        {isError && <span className="nfc-v2-step-warning" role="alert">索引根目录加载失败，已有选择不会被清空。</span>}
        {isOrganizer ? (
          <select id={id + '-root'} value={selectedIds[0] ?? ''} required
            className="nfc-workflow-full-control nfc-v2-step-select"
            aria-describedby={id + '-root-help'}
            onChange={event => handleOrganizerRoot(event.target.value)}>
            <option value="" disabled>请选择单一根目录</option>
            {shownIds.map(rootId => <option key={rootId} value={rootId}>{labelForRoot(rootId)}</option>)}
          </select>
        ) : (
          <div role="group" aria-labelledby={id + '-root-label'} aria-describedby={id + '-root-help'}
            className="nfc-workflow-full-control nfc-v2-step-root-options">
            {!shownIds.length && !isLoading && <span className="nfc-v2-step-muted">暂无索引根目录</span>}
            {shownIds.map(rootId => {
              const checked = selectedIds.includes(rootId);
              return <label className="nfc-v2-step-root-option" key={rootId}>
                <input type="checkbox" checked={checked} value={rootId}
                  disabled={readOnly || (!checked && (!availableIds.includes(rootId) || selectedIds.length >= MAX_SCAN_ROOTS))}
                  onChange={event => handleScanRoot(rootId, event.target.checked)} />
                <span>{labelForRoot(rootId)}</span>
              </label>;
            })}
            <span className="nfc-v2-step-count">{selectedIds.length} / {MAX_SCAN_ROOTS} 根目录</span>
          </div>
        )}
      </div>
      <div className="nfc-v2-step-field">
        <label htmlFor={id + '-subpath'}>子路径范围过滤 (subpath)</label>
        <p id={id + '-subpath-help'}>可选。限定扫描子目录，无需前导斜杠（例如：photos/2026）。禁止填写 null。</p>
        <input type="text" id={id + '-subpath'} className="nfc-workflow-full-control"
          aria-describedby={id + '-subpath-help'}
          value={step.subpath ?? ''} placeholder="留空表示扫描整个根目录"
          onChange={event => { if (!readOnly) onChange({ ...step, subpath: scanSubpathValue(event.target.value) }); }} />
      </div>
    </fieldset>
  );
};
