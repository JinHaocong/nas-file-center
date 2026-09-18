import React from "react";
import { Card, Alert, Typography, Space, Tag, Tooltip, Descriptions } from "antd";
import {
  SafetyCertificateOutlined,
  KeyOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import {
  formatQuarantineRootPresentation,
  formatAllowedRootPresentation,
  getProtectLastFileDescription,
} from "../../utils/dedupePresentation";

const { Text } = Typography;

interface Props {
  authorityDigest: string;
  authorityType: "preview_digest" | "compile_digest";
  dedupePreviewDigest?: string;
  previewSource?: string;
  workflowRevision?: number;
  definitionSha256?: string;
  runtimeScanJobId?: number;
  liveFilesystemVerified?: boolean;
  scorerConfigDigest?: string;
  sourceSnapshotDigest?: string;
  decisionDigest?: string;
  engineVersion?: number;
  effectiveSafetyPolicy?: {
    protect_last_file?: boolean;
    allowed_roots?: string[];
    quarantine_root?: string | null;
    [key: string]: any;
  };
}

export const DedupeIdentitySafetyPanel: React.FC<Props> = ({
  authorityDigest,
  authorityType,
  dedupePreviewDigest,
  previewSource,
  workflowRevision,
  definitionSha256,
  runtimeScanJobId,
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
    <div className="nfc-dedupe-identity-panel">
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
            : "当前预览基于已完成扫描数据和只读安全观察生成。实际物理身份与 SHA-256 仍将在 Freeze → Validate → Execute 阶段重新校验。"
        }
      />

      {/* 2. Authority Token & Pipeline Digests */}
      <Card
        size="small"
        title={
          <div className="nfc-dedupe-section-heading">
            <Space>
              <KeyOutlined className="nfc-accent-icon" />
              <span>身份凭证与安全摘要 (Identity & Safety Lineage)</span>
            </Space>
            {engineVersion && (
              <Tag color="blue">Dedupe Engine v{engineVersion}</Tag>
            )}
          </div>
        }
        className="nfc-dedupe-surface-card"
        bordered={false}
      >
        <Descriptions className="nfc-detail-descriptions nfc-dedupe-identity-descriptions" column={{ xs: 1, sm: 2 }} size="small">
          <Descriptions.Item
            label={
              <Tooltip title={isDirectScan ? "直接扫描生成计划必须提交的权威验证摘要" : "工作流生成计划必须提交的权威编译摘要"}>
                <Space size={4}>
                  <Text strong>{authorityLabel}</Text>
                  <InfoCircleOutlined className="nfc-accent-icon" />
                </Space>
              </Tooltip>
            }
            span={2}
          >
            <Text code copyable strong className="nfc-dedupe-authority-digest">
              {authorityDigest || "-"}
            </Text>
          </Descriptions.Item>

          {dedupePreviewDigest && (
            <Descriptions.Item
              label={
                <Tooltip title="底层去重步骤独立计算的算法与组结果摘要">
                  <Space size={4}>
                    <Text strong>去重预览摘要 (dedupe_preview_digest)</Text>
                    <InfoCircleOutlined className="nfc-accent-icon" />
                  </Space>
                </Tooltip>
              }
              span={2}
            >
              <Text code copyable strong className="nfc-dedupe-secondary-digest">
                {dedupePreviewDigest}
              </Text>
            </Descriptions.Item>
          )}

          {workflowRevision !== undefined && (
            <Descriptions.Item label="工作流基线版本 (Revision)">
              <Tag color="purple">第 r{workflowRevision} 版</Tag>
            </Descriptions.Item>
          )}

          {runtimeScanJobId !== undefined && (
            <Descriptions.Item label="运行时扫描任务 (scan_job_id)">
              <Tag color="cyan">Scan #{runtimeScanJobId}</Tag>
            </Descriptions.Item>
          )}

          {previewSource && (
            <Descriptions.Item label="预览数据源 (preview_source)">
              <Tag color="blue">{previewSource}</Tag>
            </Descriptions.Item>
          )}

          {scorerConfigDigest && (
            <Descriptions.Item label="打分配置摘要 (scorer_config_digest)">
              <Text code copyable className="nfc-dedupe-digest">
                {scorerConfigDigest}
              </Text>
            </Descriptions.Item>
          )}

          {sourceSnapshotDigest && (
            <Descriptions.Item label="源快照摘要 (source_snapshot_digest)">
              <Text code copyable className="nfc-dedupe-digest">
                {sourceSnapshotDigest}
              </Text>
            </Descriptions.Item>
          )}

          {decisionDigest && (
            <Descriptions.Item label="决策摘要 (decision_digest)">
              <Text code copyable className="nfc-dedupe-digest">
                {decisionDigest}
              </Text>
            </Descriptions.Item>
          )}

          {definitionSha256 && (
            <Descriptions.Item label="定义哈希 (definition_sha256)" span={2}>
              <Text code copyable className="nfc-dedupe-digest">
                {definitionSha256}
              </Text>
            </Descriptions.Item>
          )}

          <Descriptions.Item label="实时文件系统验证 (live_filesystem_verified)">
            <Tag color={liveFilesystemVerified ? "green" : "default"}>
              {liveFilesystemVerified ? "已验证 (true)" : "未验证 (false)"}
            </Tag>
          </Descriptions.Item>

          {effectiveSafetyPolicy && effectiveSafetyPolicy.protect_last_file !== undefined && (
            <Descriptions.Item
              label={
                <Tooltip title={getProtectLastFileDescription(effectiveSafetyPolicy.protect_last_file)}>
                  <Space size={4}>
                    <span>保留最后文件保护 (protect_last_file)</span>
                    <InfoCircleOutlined className="nfc-accent-icon" />
                  </Space>
                </Tooltip>
              }
            >
              <Tag color={effectiveSafetyPolicy.protect_last_file ? "green" : "default"}>
                {effectiveSafetyPolicy.protect_last_file ? "已启用 (true)" : "未启用 (false)"}
              </Tag>
            </Descriptions.Item>
          )}

          {effectiveSafetyPolicy && (
            <Descriptions.Item label="隔离区根目录 (quarantine_root)" span={2}>
              <Text code={Boolean(effectiveSafetyPolicy.quarantine_root)} className="nfc-dedupe-digest">
                {formatQuarantineRootPresentation(effectiveSafetyPolicy.quarantine_root)}
              </Text>
            </Descriptions.Item>
          )}

          {effectiveSafetyPolicy && effectiveSafetyPolicy.allowed_roots && effectiveSafetyPolicy.allowed_roots.length > 0 && (
            <Descriptions.Item label="允许扫描根目录 (allowed_roots)" span={2}>
              <Space direction="vertical" size={2}>
                {effectiveSafetyPolicy.allowed_roots.map((root, idx) => (
                  <Text key={idx} code className="nfc-dedupe-digest">
                    {formatAllowedRootPresentation(idx, root)}
                  </Text>
                ))}
              </Space>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>
    </div>
  );
};
