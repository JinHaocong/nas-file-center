import React, { useId } from 'react';
import { useQuery } from '@tanstack/react-query';
import { indexesApi } from '../../api/domain';
import type { IndexRoot } from '../../types';
import type { MoveStep } from '../../types/workflow';
import { moveSubpathValue } from '../../utils/workflowStepFields';
interface Props { step: MoveStep; onChange: (step: MoveStep) => void; readOnly?: boolean; }
export const MoveStepEditor: React.FC<Props> = ({ step, onChange, readOnly = false }) => {
  const id = useId();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['indexesRootsList'],
    queryFn: async () => (await indexesApi.listIndexes(1, 100)).items,
  });
  const roots: IndexRoot[] = data || [];
  const available = roots.map(r => r.id);
  const savedUnknownRoot = step.destination_root_id > 0 && !available.includes(step.destination_root_id);
  const updateRoot = (raw: string) => {
    const targetId = Number(raw);
    if (readOnly || !Number.isSafeInteger(targetId) || !available.includes(targetId)) return;
    onChange({ ...step, destination_root_id: targetId });
  };
  return (
    <fieldset className="nfc-workflow-step-form nfc-v2-simple-step-form" disabled={readOnly}>
      <div className="nfc-v2-step-field">
        <label htmlFor={id + '-root'}>目标根目录 (destination_root_id) <span aria-hidden="true">*</span></label>
        <p id={id + '-root-help'}>目标必须位于已注册的索引根路径内</p>
        {isLoading && <span role="status" className="nfc-v2-step-muted">正在加载索引根目录…</span>}
        {isError && <span role="alert" className="nfc-v2-step-warning">索引根目录加载失败，当前目标不会被清空。</span>}
        <select id={id + '-root'} className="nfc-workflow-full-control nfc-v2-step-select"
          value={step.destination_root_id > 0 ? step.destination_root_id : ''}
          required aria-describedby={id + '-root-help'}
          onChange={event => updateRoot(event.target.value)}>
          <option value="" disabled>请选择目标根目录</option>
          {savedUnknownRoot && <option value={step.destination_root_id}>
            根目录 #{step.destination_root_id}（当前列表未返回）
          </option>}
          {roots.map(root => <option key={root.id} value={root.id}>{root.root} (ID: {root.id})</option>)}
        </select>
      </div>
      <div className="nfc-v2-step-field">
        <label htmlFor={id + '-subpath'}>目标子路径 (destination_subpath)</label>
        <p id={id + '-subpath-help'}>可选。目标根目录下的相对子路径（例如：archive/2026）</p>
        <input id={id + '-subpath'} className="nfc-workflow-full-control" type="text"
          value={step.destination_subpath ?? ''} placeholder="留空表示移动至根目录顶层"
          aria-describedby={id + '-subpath-help'}
          onChange={event => { if (!readOnly) onChange({ ...step, destination_subpath: moveSubpathValue(event.target.value) }); }} />
      </div>
    </fieldset>
  );
};
