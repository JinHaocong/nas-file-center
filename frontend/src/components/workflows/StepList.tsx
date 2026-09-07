import React from 'react';
import { Button, Dropdown, Empty } from 'antd';
import {
  PlusOutlined,
  FolderOpenOutlined,
  FilterOutlined,
  EditOutlined,
  FolderOutlined,
  ClockCircleOutlined,
  SafetyCertificateOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';
import type { MenuProps } from 'antd';
import { WorkflowStep, WorkflowMode } from '../../types/workflow';
import { StepCard } from './StepCard';
import { createDefaultOrganizerSnapshot } from '../../utils/organizerDefaults';
import { getAllowedInsertions, canMoveStep, canDeleteStep } from '../../utils/workflowTopology';

interface StepListProps {
  steps: WorkflowStep[];
  mode: WorkflowMode;
  readOnly?: boolean;
  onChange: (steps: WorkflowStep[]) => void;
}

export const StepList: React.FC<StepListProps> = ({
  steps,
  mode,
  readOnly = false,
  onChange,
}) => {
  const generateId = (prefix: string) => `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;

  const handleAddStep = (type: WorkflowStep['type']) => {
    let newStep: WorkflowStep;
    switch (type) {
      case 'scan':
        newStep = {
          id: generateId('scan'),
          type: 'scan',
          root_ids: [],
        };
        break;
      case 'filter':
        newStep = {
          id: generateId('filter'),
          type: 'filter',
          filter: {
            field: 'extension',
            operator: 'eq',
            value: 'jpg',
            case_sensitive: false,
          },
        };
        break;
      case 'rename':
        newStep = {
          id: generateId('rename'),
          type: 'rename',
          pattern: 'draft',
          replacement: 'final',
        };
        break;
      case 'move':
        newStep = {
          id: generateId('move'),
          type: 'move',
          destination_root_id: 1,
          destination_subpath: '',
        };
        break;
      case 'touch':
        newStep = {
          id: generateId('touch'),
          type: 'touch',
          touch_now: true,
          mtime_ns: null,
        };
        break;
      case 'quarantine':
        newStep = {
          id: generateId('quarantine'),
          type: 'quarantine',
          reason: 'quarantine by workflow',
        };
        break;
      case 'organize':
        newStep = {
          id: generateId('organize'),
          type: 'organize',
          profile_snapshot: createDefaultOrganizerSnapshot('默认整理快照'),
        };
        break;
    }
    onChange([...steps, newStep]);
  };

  const allowedInsertions = getAllowedInsertions(steps, mode);

  const rawMenuItems: Array<{ key: WorkflowStep['type']; icon: React.ReactNode; label: string }> =
    mode === 'file'
      ? [
          {
            key: 'scan',
            icon: <FolderOpenOutlined />,
            label: '扫描根目录 (Scan)',
          },
          {
            key: 'filter',
            icon: <FilterOutlined />,
            label: '条件过滤 (Filter)',
          },
          {
            key: 'rename',
            icon: <EditOutlined />,
            label: '字面量重命名 (Rename)',
          },
          {
            key: 'move',
            icon: <FolderOutlined />,
            label: '路径移动 (Move)',
          },
          {
            key: 'touch',
            icon: <ClockCircleOutlined />,
            label: '刷新时间戳 (Touch)',
          },
          {
            key: 'quarantine',
            icon: <SafetyCertificateOutlined />,
            label: '隔离归档 (Quarantine)',
          },
        ]
      : [
          {
            key: 'scan',
            icon: <FolderOpenOutlined />,
            label: '扫描根目录 (Scan)',
          },
          {
            key: 'organize',
            icon: <AppstoreOutlined />,
            label: '目录整理方案 (Organize)',
          },
        ];

  const menuItems: MenuProps['items'] = rawMenuItems.map((item) => ({
    key: item.key,
    icon: item.icon,
    label: item.label,
    disabled: !allowedInsertions.includes(item.key),
    onClick: () => handleAddStep(item.key),
  }));

  const handleStepChange = (index: number, updated: WorkflowStep) => {
    const nextSteps = [...steps];
    nextSteps[index] = updated;
    onChange(nextSteps);
  };

  const handleMoveUp = (index: number) => {
    if (index === 0) return;
    const nextSteps = [...steps];
    const temp = nextSteps[index - 1];
    nextSteps[index - 1] = nextSteps[index];
    nextSteps[index] = temp;
    onChange(nextSteps);
  };

  const handleMoveDown = (index: number) => {
    if (index >= steps.length - 1) return;
    const nextSteps = [...steps];
    const temp = nextSteps[index + 1];
    nextSteps[index + 1] = nextSteps[index];
    nextSteps[index] = temp;
    onChange(nextSteps);
  };

  const handleDelete = (index: number) => {
    onChange(steps.filter((_, i) => i !== index));
  };

  return (
    <div>
      {steps.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无工作流步骤，请点击下方按钮添加步骤"
          style={{ padding: '24px 0' }}
        />
      ) : (
        steps.map((step, idx) => (
          <StepCard
            key={step.id || idx}
            step={step}
            index={idx}
            totalSteps={steps.length}
            mode={mode}
            readOnly={readOnly}
            canMoveUp={canMoveStep(steps, idx, 'up', mode)}
            canMoveDown={canMoveStep(steps, idx, 'down', mode)}
            canDelete={canDeleteStep(steps, idx, mode)}
            onChange={(updated) => handleStepChange(idx, updated)}
            onMoveUp={() => handleMoveUp(idx)}
            onMoveDown={() => handleMoveDown(idx)}
            onDelete={() => handleDelete(idx)}
          />
        ))
      )}

      {!readOnly && (
        <div style={{ marginTop: 16, textAlign: 'center' }}>
          <Dropdown menu={{ items: menuItems }} placement="bottom">
            <Button type="dashed" icon={<PlusOutlined />} size="large">
              添加执行步骤
            </Button>
          </Dropdown>
        </div>
      )}
    </div>
  );
};
