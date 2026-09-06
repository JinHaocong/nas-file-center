import React from 'react';
import { Form, Input } from 'antd';
import { QuarantineStep } from '../../types/workflow';

interface QuarantineStepEditorProps {
  step: QuarantineStep;
  onChange: (updated: QuarantineStep) => void;
  readOnly?: boolean;
}

export const QuarantineStepEditor: React.FC<QuarantineStepEditorProps> = ({ step, onChange, readOnly = false }) => {
  return (
    <Form layout="vertical" disabled={readOnly}>
      <Form.Item
        label="隔离归档原因 (reason)"
        required
        extra="简述隔离原因，将被写入隔离区条目及审计日志"
      >
        <Input
          value={step.reason}
          placeholder="例如：通过工作流规则隔离重复或过期文件"
          onChange={(e) => onChange({ ...step, reason: e.target.value })}
        />
      </Form.Item>
    </Form>
  );
};
