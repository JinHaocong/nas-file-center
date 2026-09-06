import React from 'react';
import { Form, Select, Input } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { indexesApi } from '../../api/domain';
import { IndexRoot } from '../../types';
import { ScanStep } from '../../types/workflow';

interface ScanStepEditorProps {
  step: ScanStep;
  onChange: (updated: ScanStep) => void;
  readOnly?: boolean;
}

export const ScanStepEditor: React.FC<ScanStepEditorProps> = ({ step, onChange, readOnly = false }) => {
  const { data: rootsData, isLoading } = useQuery({
    queryKey: ['indexesRootsList'],
    queryFn: async () => {
      const res = await indexesApi.listIndexes(1, 100);
      return res.items;
    },
  });

  const roots: IndexRoot[] = rootsData || [];

  return (
    <div>
      <Form layout="vertical" disabled={readOnly}>
        <Form.Item
          label="扫描索引根目录 (root_ids)"
          required
          extra="选择工作流执行范围所涵盖的已注册索引根路径"
        >
          <Select
            mode="multiple"
            value={step.root_ids}
            placeholder="请选择根目录"
            loading={isLoading}
            onChange={(ids) => onChange({ ...step, root_ids: ids })}
            options={roots.map((r) => ({
              label: `${r.root} (ID: ${r.id})`,
              value: r.id,
            }))}
            style={{ width: '100%' }}
          />
        </Form.Item>

        <Form.Item
          label="子路径范围过滤 (subpath)"
          extra="可选。限定扫描子目录，无需前导斜杠（例如：photos/2026）。禁止填写 null。"
        >
          <Input
            value={step.subpath ?? ''}
            placeholder="留空表示扫描整个根目录"
            onChange={(e) => {
              const val = e.target.value.trim();
              onChange({
                ...step,
                subpath: val ? val : undefined,
              });
            }}
          />
        </Form.Item>
      </Form>
    </div>
  );
};
