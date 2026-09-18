import React from 'react';
import { Alert, Tag, Typography } from 'antd';
import {
  DeleteOutlined,
  FileTextOutlined,
  FolderOutlined,
  SaveOutlined,
  CheckCircleOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import { DedupeSummary, DedupeSelectionMode } from '../../types/dedupe';
import { getProtectLastFileDescription } from '../../utils/dedupePresentation';
import { formatBytes } from '../../utils/format';
import { formatScanRootLabel, mapReleasedBytesByScanRoot } from '../../utils/dedupePreview';

const { Text } = Typography;

interface Props {
  summary: DedupeSummary;
  effectiveSafetyPolicy?: {
    protect_last_file?: boolean;
    [key: string]: any;
  };
  scanRoots?: string[];
  selectionMode?: DedupeSelectionMode;
}

export const DedupePreviewSummaryPanel: React.FC<Props> = ({
  summary,
  effectiveSafetyPolicy,
  scanRoots = [],
  selectionMode,
}) => {
  const policy = effectiveSafetyPolicy || summary.effective_safety_policy;
  const rootEntries = mapReleasedBytesByScanRoot(
    summary.released_bytes_by_scan_root,
    scanRoots.length > 0 ? scanRoots : summary.scan_roots
  );
  const mode = selectionMode || summary.selection_mode;

  const metrics = [
    {
      key: 'groups',
      label: '重复组数',
      value: `${summary.group_count ?? summary.actionable_group_count ?? 0}`,
      suffix: '组',
      meta: `可处理 ${summary.actionable_group_count ?? 0} · 跳过 ${summary.skipped_group_count ?? 0}`,
      icon: <FolderOutlined />,
      tone: 'success',
    },
    {
      key: 'members',
      label: '重复副本总数',
      value: `${summary.candidate_member_count ?? 0}`,
      suffix: '个',
      meta: '候选文件总数',
      icon: <FileTextOutlined />,
      tone: 'accent',
    },
    {
      key: 'quarantine',
      label: '计划隔离副本',
      value: `${summary.planned_quarantine_count ?? 0}`,
      suffix: '个',
      meta: '执行后进入隔离区',
      icon: <DeleteOutlined />,
      tone: 'warning',
    },
    {
      key: 'reclaim',
      label: '预计释放容量',
      value: formatBytes(summary.expected_reclaim_bytes ?? 0),
      suffix: '',
      meta: '去重后净收益容量',
      icon: <SaveOutlined />,
      tone: 'neutral',
    },
  ];

  return (
    <div className="nfc-dedupe-summary-panel">
      <div className="nfc-dedupe-summary-grid">
        {metrics.map((metric) => (
          <article className={`nfc-dedupe-summary-metric tone-${metric.tone}`} key={metric.key}>
            <div className="nfc-dedupe-summary-metric-topline">
              <span>{metric.label}</span>
              <span className="nfc-dedupe-summary-metric-icon">{metric.icon}</span>
            </div>
            <div className="nfc-dedupe-summary-value">
              {metric.value}
              {metric.suffix && <small>{metric.suffix}</small>}
            </div>
            <div className="nfc-dedupe-summary-meta">{metric.meta}</div>
          </article>
        ))}
      </div>

      {mode === 'balanced_by_bytes' && (
        <Alert
          className="nfc-overlay-alert"
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          message="根目录字节平衡模式已生效"
          description="Balanced by Bytes 使用 backend released_bytes 作为跨组选择层，在候选允许的情况下尽量均衡各 Scan Root 的累计计划释放字节。该机制独立于因子权重计分之外。"
        />
      )}

      {rootEntries.length > 0 && (
        <section className="nfc-dedupe-root-release-panel">
          <header className="nfc-embedded-section-header">
            <div>
              <div className="nfc-embedded-section-kicker">Capacity distribution</div>
              <h3>各扫描根目录预计释放容量</h3>
            </div>
            <Tag color="blue">容量分布</Tag>
          </header>
          <div className="nfc-dedupe-root-release-list">
            {rootEntries.map((entry) => (
              <div className="nfc-dedupe-root-release-row" key={entry.rootIndex}>
                <Text strong>{formatScanRootLabel(entry.rootIndex, entry.rootPath)}</Text>
                <Text strong className={entry.releasedBytes > 0 ? 'nfc-warning-text' : 'nfc-table-muted'}>
                  {formatBytes(entry.releasedBytes)}
                </Text>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="nfc-dedupe-safety-footnote">
        <CheckCircleOutlined className={policy?.protect_last_file ? 'is-safe' : 'is-warning'} />
        <Text type="secondary">
          {policy && policy.protect_last_file !== undefined
            ? getProtectLastFileDescription(policy.protect_last_file)
            : '去重安全保护策略 (protect_last_file): 未配置。'}
        </Text>
      </div>
    </div>
  );
};
