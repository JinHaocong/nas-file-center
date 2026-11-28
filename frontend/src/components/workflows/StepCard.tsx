import React, { useEffect, useId, useState } from 'react';

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

import { isFilterAndOrNode, isFilterLeafNode, type WorkflowMode, type WorkflowStep } from '../../types/workflow';

interface StepCardProps {
  step: WorkflowStep;
  index: number;
  mode: WorkflowMode;
  expanded: boolean;
  readOnly?: boolean;
  canMoveUp?: boolean;
  canMoveDown?: boolean;
  canDelete?: boolean;
  onToggle: () => void;
  onChange: (updated: WorkflowStep) => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDelete: () => void;
}

type StepMeta = {
  title: string;
  icon: ConsoleIconName;
  summary: string;
};

/** 从当前配置提取折叠行的摘要。 */
function getStepMeta(step: WorkflowStep): StepMeta {
  switch (step.type) {
    case 'scan':
      return { title: '扫描根目录', icon: 'folder-open',
        summary: step.root_ids.length
          ? `${step.root_ids.length} 个索引根目录${step.subpath ? ` · ${step.subpath}` : ''}`
          : '尚未选择索引根目录' };
    case 'filter': {
      const { filter } = step;
      const value = isFilterLeafNode(filter) ? filter.value : null;
      const valueText = Array.isArray(value) ? value.join('、') : String(value ?? '');
      const summary = value !== null
        ? `匹配值 · ${valueText || '未填写'}`
        : isFilterAndOrNode(filter)
          ? `${filter.op === 'and' ? '同时匹配' : '任一匹配'} · ${filter.children.length} 项条件`
          : '排除匹配结果';
      return { title: '条件过滤', icon: 'sliders', summary };
    }
    case 'rename':
      return { title: '字面量重命名', icon: 'pencil',
        summary: step.pattern ? `${step.pattern} → ${step.replacement || '移除'}` : '尚未填写原文字' };
    case 'move':
      return { title: '路径移动', icon: 'folder',
        summary: `目标根 #${step.destination_root_id || '—'}${step.destination_subpath ? ` / ${step.destination_subpath}` : ''}` };
    case 'touch':
      return { title: '时间戳更新', icon: 'clock',
        summary: step.touch_now ? '使用 NAS 当前时间' :
          `指定时间 · ${step.mtime_ns !== null ? new Date(step.mtime_ns / 1e6).toLocaleString() : '未设置'}` };
    case 'quarantine':
      return { title: '隔离归档', icon: 'shield-check',
        summary: step.reason || '尚未填写隔离原因' };
    case 'organize':
      return { title: '目录整理方案', icon: 'folders',
        summary: step.profile_snapshot?.name || '未命名方案' };
    case 'dedupe': {
      const modes = {
        weighted: '按评分选择保留文件',
        balanced_by_bytes: '按扫描根平衡释放空间',
        recursive_directory_balanced_by_bytes: '按目录递归平衡释放空间',
      };
      return { title: '高级精确去重', icon: 'zap',
        summary: modes[step.scorer_config?.selection_mode ?? 'weighted'] };
    }
    case 'single_child_wrapper_collapse':
      return { title: '单子目录壳折叠', icon: 'layers',
        summary: `管理根 #${step.root_id || '—'}${step.subpath ? ` / ${step.subpath}` : ''}` };
  }
}

export const StepCard: React.FC<StepCardProps> = ({
  step, index, mode, expanded, readOnly = false,
  canMoveUp = true, canMoveDown = true, canDelete = true,
  onToggle, onChange, onMoveUp, onMoveDown, onDelete,
}) => {
  const [hasOpened, setHasOpened] = useState(expanded);
  const editorId = useId();
  const meta = getStepMeta(step);
  const title = `步骤 ${index + 1}：${meta.title}`;

  // 首次展开时加载编辑器，同时保留折叠前尚未录入的过滤标签等局部状态。
  useEffect(() => {
    if (expanded) setHasOpened(true);
  }, [expanded]);

  const handleChange = (updated: WorkflowStep) => { if (!readOnly && updated.type === step.type && updated.id === step.id) onChange(updated); };
  const handleMoveUp = () => { if (!readOnly && canMoveUp) onMoveUp(); };
  const handleMoveDown = () => { if (!readOnly && canMoveDown) onMoveDown(); };
  const handleDelete = () => { if (!readOnly && canDelete) onDelete(); };

  return (
    <section className={`nfc-workflow-step-card nfc-v2-step-card ${expanded ? 'is-expanded' : 'is-collapsed'}`}
      aria-label={title}>
      <header className="nfc-workflow-step-heading nfc-v2-step-heading">
        <button type="button" className="nfc-step-toggle nfc-v2-step-toggle"
          data-step-id={step.id} aria-label={title}
          aria-describedby={`${editorId}-summary`} aria-expanded={expanded} aria-controls={editorId}
          onClick={onToggle}>
          <span className="nfc-step-index" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
          <span className="nfc-v2-step-type"><ConsoleIcon name={meta.icon} size={19} /></span>
          <span className="nfc-step-heading-copy">
            <strong>{meta.title}</strong>
            <span className="nfc-step-summary" id={`${editorId}-summary`} title={meta.summary}>{meta.summary}</span>
          </span>
          <ConsoleIcon name="chevron-right" size={18} className="nfc-v2-step-chevron" />
        </button>
      </header>
      <div id={editorId} className="nfc-v2-step-reveal" aria-hidden={expanded ? undefined : true}
        {...(expanded ? {} : { inert: '' })}>
        <div className="nfc-v2-step-clip">
          <div className="nfc-workflow-step-editor nfc-v2-step-editor">
            {(expanded || hasOpened) && (
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
            {!readOnly && expanded && (canMoveUp || canMoveDown || canDelete) && (
              <div className="nfc-step-actions nfc-v2-step-actions" role="group" aria-label="步骤操作">
                {canMoveUp && (
                  <ConsoleButton size="sm" variant="ghost" title="上移步骤" aria-label="上移步骤"
                    onClick={handleMoveUp} leadingIcon={<ConsoleIcon name="arrow-up" size={16} />}>上移</ConsoleButton>
                )}
                {canMoveDown && (
                  <ConsoleButton size="sm" variant="ghost" title="下移步骤" aria-label="下移步骤"
                    onClick={handleMoveDown} leadingIcon={<ConsoleIcon name="arrow-down" size={16} />}>下移</ConsoleButton>
                )}
                {canDelete && (
                  <ConsoleButton size="sm" variant="danger" title="删除步骤" aria-label="删除步骤"
                    onClick={handleDelete} leadingIcon={<ConsoleIcon name="trash" size={16} />}>删除</ConsoleButton>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
};
