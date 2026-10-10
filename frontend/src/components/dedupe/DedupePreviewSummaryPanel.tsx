import React from 'react';
import type { DedupeSummary, DedupeSelectionMode } from '../../types/dedupe';
import { getProtectLastFileDescription } from '../../utils/dedupePresentation';
import { formatBytes } from '../../utils/format';
import { formatScanRootLabel, mapReleasedBytesByScanRoot } from '../../utils/dedupePreview';
import { ConsoleIcon, type ConsoleIconName } from '../ui/ConsoleIcon';

interface Props {
  summary: DedupeSummary;
  effectiveSafetyPolicy?: {
    protect_last_file?: boolean;
    [key: string]: any;
  };
  scanRoots?: string[];
  selectionMode?: DedupeSelectionMode;
}

const SummaryNotice: React.FC<{
  title: string;
  children: React.ReactNode;
  warning?: boolean;
}> = ({ title, children, warning = false }) => (
  <div className={'nfc-v2-dedupe-summary-notice' + (warning ? ' is-warning' : '')} role="note">
    <ConsoleIcon name="shield-check" size={18} />
    <div><strong>{title}</strong><p>{children}</p></div>
  </div>
);

/** A read-only projection of server-calculated dedupe summary; never calculate scores locally. */
export const DedupePreviewSummaryPanel: React.FC<Props> = ({
  summary, effectiveSafetyPolicy, scanRoots = [], selectionMode,
}) => {
  const policy = effectiveSafetyPolicy || summary.effective_safety_policy;
  const rootEntries = mapReleasedBytesByScanRoot(
    summary.released_bytes_by_scan_root,
    scanRoots.length > 0 ? scanRoots : summary.scan_roots
  );
  const mode = selectionMode || summary.selection_mode;
  const storageAction = summary.storage_action || 'quarantine';
  const actionMetric =
    storageAction === 'hardlink'
      ? {
          key: 'storage-action', label: '计划 Hardlink 优化',
          value: String(summary.planned_action_count ?? 0), suffix: '个',
          meta: 'metadata 阻断 ' + (summary.storage_blocked_count ?? 0),
          icon: 'git-compare' as ConsoleIconName, tone: 'warning',
        }
      : storageAction === 'reflink'
        ? {
            key: 'storage-action', label: '计划 Reflink 优化',
            value: String(summary.planned_action_count ?? 0), suffix: '个',
            meta: 'metadata 阻断 ' + (summary.storage_blocked_count ?? 0),
            icon: 'file-check' as ConsoleIconName, tone: 'accent',
          }
        : {
            key: 'quarantine', label: '计划隔离副本',
            value: String(summary.planned_quarantine_count ?? 0), suffix: '个',
            meta: '执行后进入隔离区',
            icon: 'trash' as ConsoleIconName, tone: 'warning',
          };
  const metrics = [
    {
      key: 'groups', label: '重复组数',
      value: String(summary.group_count ?? summary.actionable_group_count ?? 0),
      suffix: '组',
      meta: '可处理 ' + (summary.actionable_group_count ?? 0) +
        ' · 跳过 ' + (summary.skipped_group_count ?? 0),
      icon: 'folder' as ConsoleIconName, tone: 'success',
    },
    {
      key: 'members', label: '重复副本总数',
      value: String(summary.candidate_member_count ?? 0), suffix: '个',
      meta: '候选文件总数',
      icon: 'file-text' as ConsoleIconName, tone: 'accent',
    },
    actionMetric,
    {
      key: 'reclaim', label: '预计释放容量',
      value: formatBytes(summary.expected_reclaim_bytes ?? 0), suffix: '',
      meta: '去重后净收益容量',
      icon: 'database' as ConsoleIconName, tone: 'neutral',
    },
  ];

  return (
    <section className="nfc-dedupe-summary-panel nfc-v2-dedupe-summary" aria-label="高级去重预览汇总">
      <div className="nfc-dedupe-summary-grid">
        {metrics.map(metric => (
          <article className={'nfc-dedupe-summary-metric tone-' + metric.tone} key={metric.key}>
            <div className="nfc-dedupe-summary-metric-topline">
              <span>{metric.label}</span>
              <span className="nfc-dedupe-summary-metric-icon">
                <ConsoleIcon name={metric.icon} size={17} />
              </span>
            </div>
            <div className="nfc-dedupe-summary-value">
              {metric.value}
              {metric.suffix && <small>{metric.suffix}</small>}
            </div>
            <div className="nfc-dedupe-summary-meta">{metric.meta}</div>
          </article>
        ))}
      </div>

      {storageAction === 'hardlink' && (
        <SummaryNotice title="Hardlink 语义已选择" warning>
          两个路径最终共享同一个 inode；未来经任一路径写入都会修改同一份文件内容。
        </SummaryNotice>
      )}
      {storageAction === 'reflink' && (
        <SummaryNotice title="Reflink 语义已选择">
          独立 inode + Copy-on-Write（写时复制）；不是普通完整复制。
        </SummaryNotice>
      )}
      {mode === 'balanced_by_bytes' && (
        <SummaryNotice title="根目录字节平衡模式已生效">
          Balanced by Bytes 使用 backend released_bytes 作为跨组选择层，
          在候选允许的情况下尽量均衡各 Scan Root 的累计计划释放字节。
          该机制独立于因子权重计分之外。
        </SummaryNotice>
      )}

      {rootEntries.length > 0 && (
        <section className="nfc-dedupe-root-release-panel">
          <header className="nfc-embedded-section-header">
            <div>
              <div className="nfc-embedded-section-kicker">Capacity distribution</div>
              <h3>各扫描根目录预计释放容量</h3>
            </div>
            <span className="nfc-v2-dedupe-summary-tag">容量分布</span>
          </header>
          <div className="nfc-dedupe-root-release-list">
            {rootEntries.map(entry => (
              <div className="nfc-dedupe-root-release-row" key={entry.rootIndex}>
                <strong>{formatScanRootLabel(entry.rootIndex, entry.rootPath)}</strong>
                <strong className={entry.releasedBytes > 0 ? 'nfc-warning-text' : 'nfc-table-muted'}>
                  {formatBytes(entry.releasedBytes)}
                </strong>
              </div>
            ))}
          </div>
        </section>
      )}
      <div className="nfc-dedupe-safety-footnote nfc-v2-dedupe-summary-footnote">
        <ConsoleIcon name="shield-check" size={18} className={policy?.protect_last_file ? 'is-safe' : 'is-warning'} />
        <span>
          {policy && policy.protect_last_file !== undefined
            ? getProtectLastFileDescription(policy.protect_last_file)
            : '去重安全保护策略 (protect_last_file): 未配置。'}
        </span>
      </div>
    </section>
  );
};
