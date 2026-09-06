import React from 'react';
import { Form, Input } from 'antd';
import { RenameStep } from '../../types/workflow';

interface RenameStepEditorProps {
  step: RenameStep;
  onChange: (updated: RenameStep) => void;
  readOnly?: boolean;
}

export const RenameStepEditor: React.FC<RenameStepEditorProps> = ({ step, onChange, readOnly = false }) => {
  return (
    <Form layout="vertical" disabled={readOnly}>
      <Form.Item
        label="字面量匹配文本 (pattern)"
        required
        extra="要被匹配并替换的纯文本字面量（仅支持纯文本字面量匹配，不支持正则表达式）"
      >
        <Input
          value={step.pattern}
          placeholder="例如：draft 或 old_name"
          onChange={(e) => onChange({ ...step, pattern: e.target.value })}
        />
      </Form.Item>

      <Form.Item
        label="字面量替换文本 (replacement)"
        required
        extra="替换后的目标纯文本字面量（不支持正则捕获组如 $1）"
      >
        <Input
          value={step.replacement}
          placeholder="例如：final 或 new_name"
          onChange={(e) => onChange({ ...step, replacement: e.target.value })}
        />
      </Form.Item>
    </Form>
  );
};
