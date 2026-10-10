import React from 'react';
import { QuarantineStep } from '../../types/workflow';

interface QuarantineStepEditorProps {
  step: QuarantineStep;
  onChange: (updated: QuarantineStep) => void;
  readOnly?: boolean;
}

export const QuarantineStepEditor: React.FC<QuarantineStepEditorProps> = ({ step, onChange, readOnly = false }) => (
  <fieldset className="nfc-workflow-step-form nfc-v2-simple-step-form" disabled={readOnly}>
    <div className="nfc-v2-step-field">
      <label htmlFor={`nfc-quarantine-reason-${step.id}`}>隔离归档原因 (reason) <span aria-hidden="true">*</span></label>
      <p id={`nfc-quarantine-reason-help-${step.id}`}>简述隔离原因，将被写入隔离区条目及审计日志</p>
      <input id={`nfc-quarantine-reason-${step.id}`} type="text" required
        aria-describedby={`nfc-quarantine-reason-help-${step.id}`}
        value={step.reason} placeholder="例如：通过工作流规则隔离重复或过期文件"
        onChange={event => { if (!readOnly) onChange({ ...step, reason: event.target.value }); }} />
    </div>
  </fieldset>
);
