import React from 'react';
import { Form, Switch, DatePicker } from 'antd';
import dayjs from 'dayjs';
import { TouchStep } from '../../types/workflow';

interface TouchStepEditorProps {
  step: TouchStep;
  onChange: (updated: TouchStep) => void;
}

export const TouchStepEditor: React.FC<TouchStepEditorProps> = ({ step, onChange }) => {
  return (
    <Form layout="vertical">
      <Form.Item
        label="更新为当前时间 (touch_now)"
        extra="开启后将在执行时刷新为 NAS 服务端当前系统时间戳"
      >
        <Switch
          checked={step.touch_now}
          onChange={(checked) => {
            onChange({
              ...step,
              touch_now: checked,
              mtime_ns: checked ? null : step.mtime_ns || Date.now() * 1_000_000,
            });
          }}
        />
      </Form.Item>

      {!step.touch_now && (
        <Form.Item
          label="指定修改时间戳 (mtime_ns)"
          required
          extra="将文件修改时间显式固定为指定时间"
        >
          <DatePicker
            showTime
            value={step.mtime_ns ? dayjs(step.mtime_ns / 1_000_000) : null}
            onChange={(date) => {
              onChange({
                ...step,
                touch_now: false,
                mtime_ns: date ? date.valueOf() * 1_000_000 : null,
              });
            }}
          />
        </Form.Item>
      )}
    </Form>
  );
};
