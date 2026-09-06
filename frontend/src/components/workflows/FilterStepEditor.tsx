import React from 'react';
import { FilterStep, FilterNode } from '../../types/workflow';
import { FilterBuilder } from './FilterBuilder';

interface FilterStepEditorProps {
  step: FilterStep;
  onChange: (updated: FilterStep) => void;
}

export const FilterStepEditor: React.FC<FilterStepEditorProps> = ({ step, onChange }) => {
  return (
    <div>
      <div style={{ marginBottom: 8, fontSize: 13, color: '#595959' }}>
        配置过滤树（支持文件名、后缀、大小、修改时间、目录状态等组合条件）：
      </div>
      <FilterBuilder
        value={step.filter}
        onChange={(newCond: FilterNode) => onChange({ ...step, filter: newCond })}
      />
    </div>
  );
};
