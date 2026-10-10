import React, { useId } from 'react';
import type { TouchStep } from '../../types/workflow';
import { formatTouchTimeLocal, parseTouchTimeLocal } from '../../utils/workflowStepFields';
interface Props { step: TouchStep; onChange: (step: TouchStep) => void; readOnly?: boolean; }
export const TouchStepEditor: React.FC<Props> = ({ step, onChange, readOnly = false }) => {
  const id = useId();
  const changeMode = (checked: boolean) => {
    if (readOnly) return;
    onChange({ ...step, touch_now: checked,
      mtime_ns: checked ? null : step.mtime_ns || Date.now() * 1_000_000 });
  };
  const changeTime = (value: string) => {
    if (readOnly || step.touch_now) return;
    const mtimeNs = parseTouchTimeLocal(value);
    if (value && mtimeNs === null) return;
    onChange({ ...step, touch_now: false, mtime_ns: mtimeNs });
  };
  return (
    <fieldset className="nfc-workflow-step-form nfc-v2-simple-step-form" disabled={readOnly}>
      <div className="nfc-v2-step-field">
        <label className="nfc-v2-step-checkbox-label" htmlFor={id + '-now'}>
          <input id={id + '-now'} type="checkbox" checked={step.touch_now}
            onChange={event => changeMode(event.target.checked)} />
          <span>更新为当前时间 (touch_now)</span>
        </label>
        <p>开启后将在执行时刷新为 NAS 服务端当前系统时间戳</p>
      </div>
      {!step.touch_now && (
        <div className="nfc-v2-step-field">
          <label htmlFor={id + '-time'}>指定修改时间戳 (mtime_ns) <span aria-hidden="true">*</span></label>
          <p id={id + '-time-help'}>将文件修改时间显式固定为指定时间；按浏览器本地时区显示。</p>
          <input id={id + '-time'} type="datetime-local" step="0.001" required
            className="nfc-workflow-full-control nfc-v2-step-datetime"
            aria-describedby={id + '-time-help'}
            value={formatTouchTimeLocal(step.mtime_ns)}
            onChange={event => changeTime(event.target.value)} />
        </div>
      )}
    </fieldset>
  );
};
