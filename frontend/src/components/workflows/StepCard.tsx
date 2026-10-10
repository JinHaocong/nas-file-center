import React, { useId, useState } from 'react';
import { WorkflowMode, WorkflowStep } from '../../types/workflow';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon, type ConsoleIconName } from '../ui/ConsoleIcon';
import { ScanStepEditor } from './ScanStepEditor';
import { FilterStepEditor } from './FilterStepEditor';
import { RenameStepEditor } from './RenameStepEditor';
import { MoveStepEditor } from './MoveStepEditor';
import { TouchStepEditor } from './TouchStepEditor';
import { QuarantineStepEditor } from './QuarantineStepEditor';
import { OrganizerStepEditor } from './OrganizerStepEditor';
import { DedupeStepEditor } from './DedupeStepEditor';
import { SingleChildWrapperCollapseStepEditor } from './SingleChildWrapperCollapseStepEditor';

interface StepCardProps {
  step: WorkflowStep;
  index: number;
  totalSteps: number;
  mode: WorkflowMode;
  readOnly?: boolean;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
  canDelete?: boolean;
  onChange: (updated: WorkflowStep) => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDelete: () => void;
}

type StepMeta = {
  title: string;
  code: string;
  tone: string;
  icon: ConsoleIconName;
  summary: string;
};

/** Presentation-only metadata: never alters persisted step topology or definition. */
function getStepMeta(step: WorkflowStep): StepMeta {
  switch (step.type) {
    case 'scan':
      return { title: '扫描根目录', code: 'SCAN', tone: 'scan', icon: 'folder-open',
        summary: `根目录 [${step.root_ids.join(', ')}]${step.subpath ? ` / ${step.subpath}` : ''}` };
    case 'filter':
      return { title: '条件过滤', code: 'FILTER', tone: 'filter', icon: 'sliders', summary: '过滤条件规则树' };
    case 'rename':
      return { title: '字面量重命名', code: 'RENAME', tone: 'rename', icon: 'pencil',
        summary: `${step.pattern} → ${step.replacement}` };
    case 'move':
      return { title: '路径移动', code: 'MOVE', tone: 'move', icon: 'folder',
        summary: `目标根 #${step.destination_root_id || '—'}${step.destination_subpath ? ` / ${step.destination_subpath}` : ''}` };
    case 'touch':
      return { title: '时间戳更新', code: 'TOUCH', tone: 'touch', icon: 'clock',
        summary: step.touch_now ? '更新为 NAS 当前系统时间' :
          `固定 mtime: ${step.mtime_ns ? new Date(step.mtime_ns / 1e6).toLocaleString() : '—'}` };
    case 'quarantine':
      return { title: '隔离归档', code: 'QUARANTINE', tone: 'quarantine', icon: 'shield-check',
        summary: `原因: ${step.reason}` };
    case 'organize':
      return { title: '目录整理方案', code: 'ORGANIZE', tone: 'organize', icon: 'folders',
        summary: `方案: ${step.profile_snapshot?.name || '未命名'}` };
    case 'dedupe':
      return { title: '高级精确去重', code: 'DEDUPE', tone: 'dedupe', icon: 'zap',
        summary: `选择模式: ${step.scorer_config?.selection_mode || 'weighted'}` };
    case 'single_child_wrapper_collapse':
      return { title: '单子目录壳折叠', code: 'UTILITY', tone: 'utility', icon: 'layers',
        summary: `管理根 #${step.root_id || '—'}${step.subpath ? ` / ${step.subpath}` : ''}` };
  }
}

export const StepCard: React.FC<StepCardProps> = ({
  step, index, totalSteps: _totalSteps, mode = 'file', readOnly = false,
  canMoveUp = true, canMoveDown = true, canDelete = true,
  onChange, onMoveUp, onMoveDown, onDelete,
}) => {
  const [expanded, setExpanded] = useState(true);
  const editorId = useId();
  const meta = getStepMeta(step);
  const handleChange = (updated: WorkflowStep) => { if (!readOnly && updated.type === step.type && updated.id === step.id) onChange(updated); };
  const handleMoveUp = () => { if (!readOnly && canMoveUp) onMoveUp(); };
  const handleMoveDown = () => { if (!readOnly && canMoveDown) onMoveDown(); };
  const handleDelete = () => { if (!readOnly && canDelete) onDelete(); };

  return (
    <section className={`nfc-workflow-step-card nfc-v2-step-card ${expanded ? 'is-expanded' : 'is-collapsed'}`}
      aria-label={`步骤 ${index + 1}：${meta.title}`}>
      <header className="nfc-workflow-step-heading nfc-v2-step-heading">
        <button type="button" className="nfc-step-toggle nfc-v2-step-toggle"
          aria-label={expanded ? '折叠步骤' : '展开步骤'}
          aria-expanded={expanded} aria-controls={editorId}
          onClick={() => setExpanded(value => !value)}>
          <ConsoleIcon name={expanded ? 'chevron-down' : 'chevron-right'} size={18} />
        </button>
        <span className="nfc-step-index">{String(index + 1).padStart(2, '0')}</span>
        <div className="nfc-step-heading-copy">
          <div className="nfc-step-title-row">
            <span className={`nfc-v2-step-type is-${meta.tone}`}>
              <ConsoleIcon name={meta.icon} size={14} />
              {meta.code}
            </span>
            <strong>{meta.title}</strong>
            {readOnly && <span className="nfc-v2-step-readonly">只读</span>}
          </div>
          <span className="nfc-step-summary" title={meta.summary}>{meta.summary}</span>
        </div>
        {!readOnly && (
          <div className="nfc-step-actions nfc-v2-step-actions" aria-label="调整步骤顺序">
            <ConsoleButton size="sm" variant="ghost" className="nfc-v2-step-icon-action"
              title="上移步骤" aria-label="上移步骤" disabled={!canMoveUp}
              onClick={handleMoveUp} leadingIcon={<ConsoleIcon name="arrow-up" size={16} />}>
              上移
            </ConsoleButton>
            <ConsoleButton size="sm" variant="ghost" className="nfc-v2-step-icon-action"
              title="下移步骤" aria-label="下移步骤" disabled={!canMoveDown}
              onClick={handleMoveDown} leadingIcon={<ConsoleIcon name="arrow-down" size={16} />}>
              下移
            </ConsoleButton>
            <ConsoleButton size="sm" variant="danger" className="nfc-v2-step-icon-action"
              title="删除步骤" aria-label="删除步骤" disabled={!canDelete}
              onClick={handleDelete} leadingIcon={<ConsoleIcon name="trash" size={16} />}>
              删除
            </ConsoleButton>
          </div>
        )}
      </header>
      <div id={editorId} hidden={!expanded} className="nfc-workflow-step-editor nfc-v2-step-editor">
        {expanded && (
          <>
            {step.type === 'scan' && <ScanStepEditor step={step} onChange={handleChange} readOnly={readOnly} mode={mode} />}
            {step.type === 'filter' && <FilterStepEditor step={step} onChange={handleChange} readOnly={readOnly} />}
            {step.type === 'rename' && <RenameStepEditor step={step} onChange={handleChange} readOnly={readOnly} />}
            {step.type === 'move' && <MoveStepEditor step={step} onChange={handleChange} readOnly={readOnly} />}
            {step.type === 'touch' && <TouchStepEditor step={step} onChange={handleChange} readOnly={readOnly} />}
            {step.type === 'quarantine' && <QuarantineStepEditor step={step} onChange={handleChange} readOnly={readOnly} />}
            {step.type === 'organize' && <OrganizerStepEditor step={step} onChange={handleChange} readOnly={readOnly} />}
            {step.type === 'dedupe' && <DedupeStepEditor step={step} onChange={handleChange} readOnly={readOnly} />}
            {step.type === 'single_child_wrapper_collapse' &&
              <SingleChildWrapperCollapseStepEditor step={step} onChange={handleChange} readOnly={readOnly} />}
          </>
        )}
      </div>
    </section>
  );
};
