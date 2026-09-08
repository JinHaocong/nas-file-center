import React from "react";
import { Alert } from "antd";
import { ThunderboltOutlined } from "@ant-design/icons";
import { DedupeStep } from "../../types/workflow";
import { DedupeScorerConfigEditor } from "../dedupe/DedupeScorerConfigEditor";
import { createDefaultDedupeScorerConfig } from "../../utils/dedupeConfig";

interface DedupeStepEditorProps {
  step: DedupeStep;
  onChange: (step: DedupeStep) => void;
  readOnly?: boolean;
}

export const DedupeStepEditor: React.FC<DedupeStepEditorProps> = ({
  step,
  onChange,
  readOnly = false,
}) => {
  const scorerConfig = step.scorer_config || createDefaultDedupeScorerConfig();

  const handleConfigChange = (newConfig: typeof scorerConfig) => {
    onChange({
      ...step,
      scorer_config: newConfig,
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <Alert
        type="info"
        showIcon
        icon={<ThunderboltOutlined />}
        message="高级去重步骤规范 (Dedupe Step Specification)"
        description="本步骤固化去重评分规则与偏好。工作流采用单一步骤拓扑（禁止增删与调序）。运行时指定已完成的扫描任务，计算 compile_digest 编译摘要并生成执行计划。"
      />
      <DedupeScorerConfigEditor
        value={scorerConfig}
        onChange={handleConfigChange}
        disabled={readOnly}
      />
    </div>
  );
};
