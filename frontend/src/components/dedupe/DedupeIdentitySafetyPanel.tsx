import React from "react";
import { Card, Alert, Typography, Space, Tag, Tooltip, Descriptions } from "antd";
import {
  SafetyCertificateOutlined,
  KeyOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";

const { Text } = Typography;

interface Props {
  authorityDigest: string;
  authorityType: "preview_digest" | "compile_digest";
  liveFilesystemVerified?: boolean;
  scorerConfigDigest?: string;
  sourceSnapshotDigest?: string;
  decisionDigest?: string;
  engineVersion?: number;
  effectiveSafetyPolicy?: {
    protect_last_file?: boolean;
    [key: string]: any;
  };
}

export const DedupeIdentitySafetyPanel: React.FC<Props> = ({
  authorityDigest,
  authorityType,
  liveFilesystemVerified = false,
  scorerConfigDigest,
  sourceSnapshotDigest,
  decisionDigest,
  engineVersion,
  effectiveSafetyPolicy,
}) => {
  const isDirectScan = authorityType === "preview_digest";
  const authorityLabel = isDirectScan
    ? "权威预览摘要 (preview_digest)"
    : "工作流编译摘要 (compile_digest)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* 1. Pre-freeze Draft Advisory Banner */}
      <Alert
        type={liveFilesystemVerified ? "success" : "info"}
        showIcon
        icon={<SafetyCertificateOutlined />}
        message={
          liveFilesystemVerified
            ? "实时文件系统状态已验证 (Live Filesystem Verified)"
            : "预冻结草案预览 (Pre-Freeze Draft Preview)"
        }
        description={
          liveFilesystemVerified
            ? "当前预览直接反映实时文件系统状态。"
            : "当前预览基于已完成扫描快照与只读安全观测（completed-scan-readonly-safety），纯内存计算候选与打分，尚未执行物理哈希比对。实际物理文件一致性及 SHA-256 哈希校验将在计划的 Freeze -> Validate -> Execute 阶段由后端事务严格执行。"
        }
      />

      {/* 2. Authority Token & Pipeline Digests */}
      <Card
        size="small"
        title={
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <Space>
              <KeyOutlined style={{ color: "#1890ff" }} />
              <span>身份凭证与安全摘要 (Identity & Safety Lineage)</span>
            </Space>
            {engineVersion && (
              <Tag color="blue">Dedupe Engine v{engineVersion}</Tag>
            )}
          </div>
        }
        bordered={false}
        style={{ background: "#fafafa" }}
      >
        <Descriptions column={{ xs: 1, sm: 2 }} size="small" bordered>
          <Descriptions.Item
            label={
              <Tooltip title={isDirectScan ? "直接扫描生成计划必须提交的权威验证摘要" : "工作流生成计划必须提交的权威验证摘要"}>
                <Space size={4}>
                  <Text strong>{authorityLabel}</Text>
                  <InfoCircleOutlined style={{ color: "#1890ff" }} />
                </Space>
              </Tooltip>
            }
            span={2}
          >
            <Text code copyable strong style={{ fontSize: 13, color: "#096dd9" }}>
              {authorityDigest || "-"}
            </Text>
          </Descriptions.Item>

          {scorerConfigDigest && (
            <Descriptions.Item label="打分配置摘要 (scorer_config_digest)">
              <Text code copyable style={{ fontSize: 12 }}>
                {scorerConfigDigest}
              </Text>
            </Descriptions.Item>
          )}

          {sourceSnapshotDigest && (
            <Descriptions.Item label="源快照摘要 (source_snapshot_digest)">
              <Text code copyable style={{ fontSize: 12 }}>
                {sourceSnapshotDigest}
              </Text>
            </Descriptions.Item>
          )}

          {decisionDigest && (
            <Descriptions.Item label="决策摘要 (decision_digest)">
              <Text code copyable style={{ fontSize: 12 }}>
                {decisionDigest}
              </Text>
            </Descriptions.Item>
          )}

          {effectiveSafetyPolicy && effectiveSafetyPolicy.protect_last_file !== undefined && (
            <Descriptions.Item label="保留最后文件策略 (protect_last_file)">
              <Tag color={effectiveSafetyPolicy.protect_last_file ? "green" : "red"}>
                {effectiveSafetyPolicy.protect_last_file ? "已启用 (true)" : "未启用 (false)"}
              </Tag>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>
    </div>
  );
};
