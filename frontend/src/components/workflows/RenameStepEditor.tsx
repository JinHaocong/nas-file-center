import React from 'react';
import { RenameStep } from '../../types/workflow';

interface RenameStepEditorProps {
  step: RenameStep;
  onChange: (updated: RenameStep) => void;
  readOnly?: boolean;
}

export const RenameStepEditor: React.FC<RenameStepEditorProps> = ({ step, onChange, readOnly = false }) => (
  <fieldset className="nfc-workflow-step-form nfc-v2-simple-step-form" disabled={readOnly}>
    <div className="nfc-v2-step-field">
      <label htmlFor={`nfc-rename-pattern-${step.id}`}>字面量匹配文本 (pattern) <span aria-hidden="true">*</span></label>
      <p id={`nfc-rename-pattern-help-${step.id}`}>要被匹配并替换的纯文本字面量（仅支持纯文本字面量匹配，不支持正则表达式）</p>
      <input id={`nfc-rename-pattern-${step.id}`} type="text" required
        aria-describedby={`nfc-rename-pattern-help-${step.id}`}
        value={step.pattern} placeholder="例如：draft 或 old_name"
        onChange={event => { if (!readOnly) onChange({ ...step, pattern: event.target.value }); }} />
    </div>
    <div className="nfc-v2-step-field">
      <label htmlFor={`nfc-rename-replacement-${step.id}`}>字面量替换文本 (replacement) <span aria-hidden="true">*</span></label>
      <p id={`nfc-rename-replacement-help-${step.id}`}>替换后的目标纯文本字面量（不支持正则捕获组如 $1）</p>
      <input id={`nfc-rename-replacement-${step.id}`} type="text"
        aria-describedby={`nfc-rename-replacement-help-${step.id}`}
        value={step.replacement} placeholder="例如：final 或 new_name"
        onChange={event => { if (!readOnly) onChange({ ...step, replacement: event.target.value }); }} />
    </div>
  </fieldset>
);
