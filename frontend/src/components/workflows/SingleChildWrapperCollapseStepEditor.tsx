import React, { useId } from 'react';
import { useQuery } from '@tanstack/react-query';
import { indexesApi } from '../../api/domain';
import type { SingleChildWrapperCollapseStep } from '../../types/workflow';
import { ConsoleIcon } from '../ui/ConsoleIcon';

interface Props {
  step: SingleChildWrapperCollapseStep;
  onChange: (step: SingleChildWrapperCollapseStep) => void;
  readOnly?: boolean;
}

/** Read-only preview remains authoritative; the editor never performs filesystem operations. */
export const SingleChildWrapperCollapseStepEditor: React.FC<Props> = ({
  step, onChange, readOnly = false,
}) => {
  const id = useId();
  const { data: roots = [], isLoading, isError } = useQuery({
    queryKey: ['indexesRootsList'],
    queryFn: async () => (await indexesApi.listIndexes(1, 100)).items,
  });
  const subpath = step.subpath || '';
  const invalidSubpath = subpath.startsWith('/') || subpath.startsWith('\\') || /(^|[\\/])\.\.([\\/]|$)/.test(subpath);
  const knownRootIds = roots.map(root => root.id);
  const savedUnknownRoot = step.root_id > 0 && !knownRootIds.includes(step.root_id);

  const selectRoot = (raw: string) => {
    const rootId = Number(raw);
    if (readOnly || !Number.isSafeInteger(rootId) || !knownRootIds.includes(rootId)) return;
    onChange({ ...step, root_id: rootId });
  };
  return (
    <div className="nfc-workflow-step-editor-stack nfc-v2-utility-editor">
      <div className="nfc-v2-step-notice" role="note">
        <ConsoleIcon name="layers" size={18} />
        <div>
          <strong>单子目录壳折叠 (Single Child Wrapper Collapse)</strong>
          <p>作用域只能从已管理的 Index Root 中选择，并可附加安全相对子路径。Preview 只读发现候选；不会接受任意 NAS 绝对路径。</p>
        </div>
      </div>
      <fieldset className="nfc-workflow-step-form nfc-v2-simple-step-form" disabled={readOnly}>
        <div className="nfc-v2-step-field">
          <label htmlFor={id + '-root'}>已管理根目录</label>
          {isLoading && <span role="status" className="nfc-v2-step-muted">正在加载索引根目录…</span>}
          {isError && <span role="alert" className="nfc-v2-step-warning">根目录列表不可用；原有根目录保持不变。</span>}
          <select id={id + '-root'} className="nfc-workflow-full-control nfc-workflow-field-spaced nfc-v2-step-select"
            value={step.root_id > 0 ? step.root_id : ''} required
            onChange={event => selectRoot(event.target.value)}>
            <option value="" disabled>请选择一个已管理的 Index Root</option>
            {savedUnknownRoot && <option value={step.root_id}>
              #{step.root_id} — 当前列表未返回，已保存
            </option>}
            {roots.map(root => <option key={root.id} value={root.id}>#{root.id} — {root.root}</option>)}
          </select>
        </div>
        <div className="nfc-v2-step-field">
          <label htmlFor={id + '-subpath'}>可选相对子路径</label>
          <input id={id + '-subpath'} type="text" className="nfc-workflow-full-control nfc-workflow-field-spaced"
            value={subpath} aria-invalid={invalidSubpath} aria-describedby={invalidSubpath ? id + '-subpath-error' : undefined}
            placeholder="例如 media/incoming；留空表示整个管理根目录"
            onChange={event => { if (!readOnly) onChange({ ...step, subpath: event.target.value }); }} />
          {invalidSubpath && <span className="nfc-v2-step-warning" id={id + '-subpath-error'} role="alert">
            仅允许根目录内的相对子路径，不能使用绝对路径或 .. 跳转。
          </span>}
        </div>
      </fieldset>
    </div>
  );
};
