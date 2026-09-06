import React, { useState } from 'react';
import { Card, Space, Tag, Button, Typography, Tooltip } from 'antd';
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  DeleteOutlined,
  DownOutlined,
  RightOutlined,
  FolderOpenOutlined,
  FilterOutlined,
  EditOutlined,
  FolderOutlined,
  ClockCircleOutlined,
  SafetyCertificateOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';
import { WorkflowStep, WorkflowMode } from '../../types/workflow';
import { ScanStepEditor } from './ScanStepEditor';
import { FilterStepEditor } from './FilterStepEditor';
import { RenameStepEditor } from './RenameStepEditor';
import { MoveStepEditor } from './MoveStepEditor';
import { TouchStepEditor } from './TouchStepEditor';
import { QuarantineStepEditor } from './QuarantineStepEditor';
import { OrganizerStepEditor } from './OrganizerStepEditor';

const { Text } = Typography;

interface StepCardProps {
  step: WorkflowStep;
  index: number;
  totalSteps: number;
  mode: WorkflowMode;
  readOnly?: boolean;
  onChange: (updated: WorkflowStep) => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDelete: () => void;
}

export const StepCard: React.FC<StepCardProps> = ({
  step,
  index,
  totalSteps,
  readOnly = false,
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
          title: '扫描根目录 (Scan)',
          color: 'blue',
          icon: <FolderOpenOutlined />,
          summary: `根目录 IDs: [${step.root_ids.join(', ')}]${step.subpath ? ` / 子路径: ${step.subpath}` : ''}`,
        };
      case 'filter':
        return {
          title: '条件过滤 (Filter)',
          color: 'green',
          icon: <FilterOutlined />,
          summary: '过滤条件规则树',
        };
      case 'rename':
        return {
          title: '正则重命名 (Rename)',
          color: 'cyan',
          icon: <EditOutlined />,
          summary: `${step.pattern} -> ${step.replacement}`,
        };
      case 'move':
        return {
          title: '路径移动 (Move)',
          color: 'purple',
          icon: <FolderOutlined />,
          summary: `目标根目录: #${step.destination_root_id || '-'}${step.destination_subpath ? ` / ${step.destination_subpath}` : ''}`,
        };
      case 'touch':
        return {
          title: '时间戳更新 (Touch)',
          color: 'geekblue',
          icon: <ClockCircleOutlined />,
          summary: step.touch_now ? '更新为 NAS 当前系统时间' : `固定 mtime: ${step.mtime_ns ? new Date(step.mtime_ns / 1e6).toLocaleString() : '-'}`,
        };
      case 'quarantine':
        return {
          title: '隔离归档 (Quarantine)',
          color: 'orange',
          icon: <SafetyCertificateOutlined />,
          summary: `原因: ${step.reason}`,
        };
      case 'organize':
        return {
          title: '目录整理方案 (Organize)',
          color: 'magenta',
          icon: <AppstoreOutlined />,
          summary: `方案快照: ${step.profile_snapshot?.name || '未命名'}`,
        };
    }
  };

  const meta = getStepMeta();

  return (
    <Card
      size="small"
      style={{
        marginBottom: 12,
        borderRadius: 8,
        boxShadow: '0 1px 2px rgba(0, 0, 0, 0.04)',
      }}
      title={
        <Space>
          <Button
            type="text"
            size="small"
            icon={expanded ? <DownOutlined /> : <RightOutlined />}
            onClick={() => setExpanded(!expanded)}
          />
          <Text strong>第 {index + 1} 步</Text>
          <Tag color={meta.color} icon={meta.icon}>
            {meta.title}
          </Tag>
          {!expanded && (
            <Text type="secondary" style={{ fontSize: 13 }}>
              {meta.summary}
            </Text>
          )}
        </Space>
      }
      extra={
        !readOnly && (
          <Space>
            <Tooltip title="上移步骤">
              <Button
                type="text"
                size="small"
                icon={<ArrowUpOutlined />}
                disabled={index === 0}
                onClick={onMoveUp}
              />
            </Tooltip>
            <Tooltip title="下移步骤">
              <Button
                type="text"
                size="small"
                icon={<ArrowDownOutlined />}
                disabled={index === totalSteps - 1}
                onClick={onMoveDown}
              />
            </Tooltip>
            <Tooltip title="删除步骤">
              <Button
                type="text"
                danger
                size="small"
                icon={<DeleteOutlined />}
                onClick={onDelete}
              />
            </Tooltip>
          </Space>
        )
      }
    >
      {expanded && (
        <div style={{ padding: '8px 0' }}>
          {step.type === 'scan' && (
            <ScanStepEditor step={step} onChange={onChange} />
          )}
          {step.type === 'filter' && (
            <FilterStepEditor step={step} onChange={onChange} />
          )}
          {step.type === 'rename' && (
            <RenameStepEditor step={step} onChange={onChange} />
          )}
          {step.type === 'move' && (
            <MoveStepEditor step={step} onChange={onChange} />
          )}
          {step.type === 'touch' && (
            <TouchStepEditor step={step} onChange={onChange} />
          )}
          {step.type === 'quarantine' && (
            <QuarantineStepEditor step={step} onChange={onChange} />
          )}
          {step.type === 'organize' && (
            <OrganizerStepEditor step={step} onChange={onChange} />
          )}
        </div>
      )}
    </Card>
  );
};
