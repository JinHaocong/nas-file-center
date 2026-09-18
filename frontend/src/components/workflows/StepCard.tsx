import React, { useState } from 'react';
import { Button, Card, Tag, Tooltip } from 'antd';
import {
  AppstoreOutlined,
  ArrowDownOutlined,
  ArrowUpOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  DownOutlined,
  EditOutlined,
  FilterOutlined,
  FolderOpenOutlined,
  FolderOutlined,
  RightOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import { WorkflowMode, WorkflowStep } from '../../types/workflow';
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

export const StepCard: React.FC<StepCardProps> = ({
  step,
  index,
  totalSteps: _totalSteps,
  mode = 'file',
  readOnly = false,
  canMoveUp = true,
  canMoveDown = true,
  canDelete = true,
  onChange,
  onMoveUp,
  onMoveDown,
  onDelete,
}) => {
  const [expanded, setExpanded] = useState(true);

  const getStepMeta = () => {
    switch (step.type) {
      case 'scan':
        return {
          title: '扫描根目录',
          code: 'SCAN',
          color: 'blue',
          icon: <FolderOpenOutlined />,
          summary: `根目录 [${step.root_ids.join(', ')}]${step.subpath ? ` / ${step.subpath}` : ''}`,
        };
      case 'filter':
        return { title: '条件过滤', code: 'FILTER', color: 'green', icon: <FilterOutlined />, summary: '过滤条件规则树' };
      case 'rename':
        return { title: '字面量重命名', code: 'RENAME', color: 'cyan', icon: <EditOutlined />, summary: `${step.pattern} → ${step.replacement}` };
      case 'move':
        return { title: '路径移动', code: 'MOVE', color: 'purple', icon: <FolderOutlined />, summary: `目标根 #${step.destination_root_id || '—'}${step.destination_subpath ? ` / ${step.destination_subpath}` : ''}` };
      case 'touch':
        return { title: '时间戳更新', code: 'TOUCH', color: 'geekblue', icon: <ClockCircleOutlined />, summary: step.touch_now ? '更新为 NAS 当前系统时间' : `固定 mtime: ${step.mtime_ns ? new Date(step.mtime_ns / 1e6).toLocaleString() : '—'}` };
      case 'quarantine':
        return { title: '隔离归档', code: 'QUARANTINE', color: 'orange', icon: <SafetyCertificateOutlined />, summary: `原因: ${step.reason}` };
      case 'organize':
        return { title: '目录整理方案', code: 'ORGANIZE', color: 'magenta', icon: <AppstoreOutlined />, summary: `方案: ${step.profile_snapshot?.name || '未命名'}` };
      case 'dedupe':
        return { title: '高级精确去重', code: 'DEDUPE', color: 'purple', icon: <ThunderboltOutlined />, summary: `选择模式: ${step.scorer_config?.selection_mode || 'weighted'}` };
      case 'single_child_wrapper_collapse':
        return { title: '单子目录壳折叠', code: 'UTILITY', color: 'gold', icon: <ToolOutlined />, summary: `管理根 #${step.root_id || '—'}${step.subpath ? ` / ${step.subpath}` : ''}` };
    }
  };

  const meta = getStepMeta();

  return (
    <Card
      size="small"
      className={`nfc-workflow-step-card ${expanded ? 'is-expanded' : 'is-collapsed'}`}
      title={
        <div className="nfc-workflow-step-heading">
          <Button
            type="text"
            className="nfc-step-toggle"
            icon={expanded ? <DownOutlined /> : <RightOutlined />}
            onClick={() => setExpanded(!expanded)}
            aria-label={expanded ? '折叠步骤' : '展开步骤'}
          />
          <span className="nfc-step-index">{String(index + 1).padStart(2, '0')}</span>
          <div className="nfc-step-heading-copy">
            <div className="nfc-step-title-row">
              <Tag color={meta.color} icon={meta.icon}>{meta.code}</Tag>
              <strong>{meta.title}</strong>
            </div>
            <span className="nfc-step-summary">{meta.summary}</span>
          </div>
        </div>
      }
      extra={
        !readOnly && (
          <div className="nfc-step-actions">
            <Tooltip title="上移步骤">
              <Button type="text" size="small" icon={<ArrowUpOutlined />} disabled={!canMoveUp} onClick={onMoveUp} />
            </Tooltip>
            <Tooltip title="下移步骤">
              <Button type="text" size="small" icon={<ArrowDownOutlined />} disabled={!canMoveDown} onClick={onMoveDown} />
            </Tooltip>
            <Tooltip title="删除步骤">
              <Button type="text" danger size="small" icon={<DeleteOutlined />} disabled={!canDelete} onClick={onDelete} />
            </Tooltip>
          </div>
        )
      }
    >
      {expanded && (
        <div className="nfc-workflow-step-editor">
          {step.type === 'scan' && <ScanStepEditor step={step} onChange={onChange} readOnly={readOnly} mode={mode} />}
          {step.type === 'filter' && <FilterStepEditor step={step} onChange={onChange} readOnly={readOnly} />}
          {step.type === 'rename' && <RenameStepEditor step={step} onChange={onChange} readOnly={readOnly} />}
          {step.type === 'move' && <MoveStepEditor step={step} onChange={onChange} readOnly={readOnly} />}
          {step.type === 'touch' && <TouchStepEditor step={step} onChange={onChange} readOnly={readOnly} />}
          {step.type === 'quarantine' && <QuarantineStepEditor step={step} onChange={onChange} readOnly={readOnly} />}
          {step.type === 'organize' && <OrganizerStepEditor step={step} onChange={onChange} readOnly={readOnly} />}
          {step.type === 'dedupe' && <DedupeStepEditor step={step} onChange={onChange} readOnly={readOnly} />}
          {step.type === 'single_child_wrapper_collapse' && <SingleChildWrapperCollapseStepEditor step={step} onChange={onChange} readOnly={readOnly} />}
        </div>
      )}
    </Card>
  );
};
