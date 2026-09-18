import React from 'react';
import { Alert, Input, Select, Space, Typography } from 'antd';
import { useQuery } from '@tanstack/react-query';
import { indexesApi } from '../../api/domain';
import { SingleChildWrapperCollapseStep } from '../../types/workflow';

const { Text } = Typography;

interface Props {
  step: SingleChildWrapperCollapseStep;
  onChange: (step: SingleChildWrapperCollapseStep) => void;
  readOnly?: boolean;
}

export const SingleChildWrapperCollapseStepEditor: React.FC<Props> = ({ step, onChange, readOnly = false }) => {
  const { data: roots = [], isLoading } = useQuery({
    queryKey: ['indexesRootsList'],
    queryFn: async () => (await indexesApi.listIndexes(1, 100)).items,
  });
  const subpath = step.subpath || '';
  const invalidSubpath = subpath.startsWith('/') || subpath.startsWith('\\') || /(^|[\\/])\.\.([\\/]|$)/.test(subpath);

  return (
    <Space className="nfc-workflow-step-editor-stack" direction="vertical" size={12}>
      <Alert
        type="info"
        showIcon
        message="单子目录壳折叠 (Single Child Wrapper Collapse)"
        description="作用域只能从已管理的 Index Root 中选择，并可附加安全相对子路径。Preview 只读发现候选；不会接受任意 NAS 绝对路径。"
      />
      <div>
        <Text strong>已管理根目录</Text>
        <Select
          style={{ width: '100%', marginTop: 6 }}
          loading={isLoading}
          disabled={readOnly}
          placeholder="请选择一个已管理的 Index Root"
          value={step.root_id > 0 ? step.root_id : undefined}
          options={roots.map((root) => ({ value: root.id, label: `#${root.id} — ${root.root}` }))}
          onChange={(rootId) => onChange({ ...step, root_id: rootId })}
        />
      </div>
      <div>
        <Text strong>可选相对子路径</Text>
        <Input
          style={{ marginTop: 6 }}
          disabled={readOnly}
          status={invalidSubpath ? 'error' : undefined}
          placeholder="例如 media/incoming；留空表示整个管理根目录"
          value={subpath}
          onChange={(event) => onChange({ ...step, subpath: event.target.value })}
        />
        {invalidSubpath && <Text type="danger">仅允许根目录内的相对子路径，不能使用绝对路径或 .. 跳转。</Text>}
      </div>
    </Space>
  );
};
