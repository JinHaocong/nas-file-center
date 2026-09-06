import React from 'react';
import { Form, Select, Input } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { indexesApi } from '../../api/domain';
import { IndexRoot } from '../../types';
import { MoveStep } from '../../types/workflow';

interface MoveStepEditorProps {
  step: MoveStep;
  onChange: (updated: MoveStep) => void;
  readOnly?: boolean;
}

export const MoveStepEditor: React.FC<MoveStepEditorProps> = ({ step, onChange, readOnly = false }) => {
  const { data: indexesData, isLoading } = useQuery({
    queryKey: ['indexesRootsList'],
    queryFn: async () => {
      const res = await indexesApi.listIndexes(1, 100);
      return res.items;
    },
  });

  const roots: IndexRoot[] = indexesData || [];

  return (
    <Form layout="vertical" disabled={readOnly}>
      <Form.Item
        label="目标根目录 (destination_root_id)"
        required
        extra="目标必须位于已注册的索引根路径内"
      >
        <Select
          value={step.destination_root_id || undefined}
          placeholder="请选择目标根目录"
          loading={isLoading}
          onChange={(id) => onChange({ ...step, destination_root_id: id })}
          options={roots.map((r) => ({
            label: `${r.root} (ID: ${r.id})`,
            value: r.id,
          }))}
          style={{ width: '100%' }}
        />
      </Form.Item>

      <Form.Item
        label="目标子路径 (destination_subpath)"
        extra="可选。目标根目录下的相对子路径（例如：archive/2026）"
      >
        <Input
          value={step.destination_subpath ?? ''}
          placeholder="留空表示移动至根目录顶层"
          onChange={(e) => {
            const val = e.target.value.trim();
            onChange({
              ...step,
              destination_subpath: val ? val : '',
            });
          }}
        />
      </Form.Item>
    </Form>
  );
};
