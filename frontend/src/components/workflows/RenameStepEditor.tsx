import React from 'react';
import { Form, Input } from 'antd';
import { RenameStep } from '../../types/workflow';

interface RenameStepEditorProps {
  step: RenameStep;
  onChange: (updated: RenameStep) => void;
}

export const RenameStepEditor: React.FC<RenameStepEditorProps> = ({ step, onChange }) => {
  return (
    <Form layout="vertical">
      <Form.Item
        label="重命名正则/匹配表达式 (pattern)"
        required
        extra="要匹配并替换的正则字符串"
      >
        <Input
          value={step.pattern}
          placeholder="例如：IMG_(\d+)"
          onChange={(e) => onChange({ ...step, pattern: e.target.value })}
        />
      </Form.Item>

      <Form.Item
        label="替换为的目标表达式 (replacement)"
        required
        extra="替换后的新命名模式，可引用分组如 $1"
      >
        <Input
          value={step.replacement}
          placeholder="例如：PHOTO_$1"
          onChange={(e) => onChange({ ...step, replacement: e.target.value })}
        />
      </Form.Item>
    </Form>
  );
};
