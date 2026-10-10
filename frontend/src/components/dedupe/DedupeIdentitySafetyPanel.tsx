import React from 'react';
import {
  formatQuarantineRootPresentation, formatAllowedRootPresentation,
  getProtectLastFileDescription,
} from '../../utils/dedupePresentation';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { useConsoleToast } from '../ui/ConsoleToast';
import { CodePath } from '../ui/CodePath';

interface Props {
  authorityDigest: string;
  authorityType: 'preview_digest' | 'compile_digest';
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

/** Copy only the supplied authoritative digest; never derive or recompute one in the UI. */
const Digest: React.FC<{
  value: string;
  primary?: boolean;
  onCopy: (value: string) => void;
}> = ({ value, primary = false, onCopy }) => (
  <span className={'nfc-v2-safety-digest' + (primary ? ' is-primary' : '')}>
    <code title={value || '未提供摘要'}>{value || '-'}</code>
    {Boolean(value) && (
      <ConsoleButton variant="ghost" size="sm"
        aria-label="复制摘要" onClick={() => onCopy(value)}>复制</ConsoleButton>
    )}
  </span>
);

const Fact: React.FC<{
  label: string;
  hint?: string;
  full?: boolean;
  children: React.ReactNode;
}> = ({ label, hint, full = false, children }) => (
  <div className={'nfc-v2-safety-fact' + (full ? ' is-full' : '')}>
    <dt title={hint}>{label}{hint && <ConsoleIcon name="info" size={14} />}</dt>
    <dd>{children}</dd>
  </div>
);

export const DedupeIdentitySafetyPanel: React.FC<Props> = ({
  authorityDigest, authorityType, dedupePreviewDigest, previewSource,
  workflowRevision, definitionSha256, runtimeScanJobId,
  liveFilesystemVerified = false, scorerConfigDigest, sourceSnapshotDigest,
  decisionDigest, engineVersion, effectiveSafetyPolicy,
}) => {
  const toast = useConsoleToast();
  const isDirectScan = authorityType === 'preview_digest';
  const authorityLabel = isDirectScan
    ? '权威预览摘要 (preview_digest)'
    : '工作流编译摘要 (compile_digest)';
  const copyDigest = (value: string) => {
    if (!navigator.clipboard?.writeText) {
      toast.error('当前浏览器不支持复制摘要');
      return;
    }
    void navigator.clipboard.writeText(value)
      .then(() => toast.success('摘要已复制'))
      .catch(() => toast.error('复制失败，请手动选择摘要'));
  };

  return (
    <section className="nfc-dedupe-identity-panel nfc-v2-identity-panel" aria-label="身份凭证与安全摘要">
      <div className={'nfc-v2-safety-advisory' + (liveFilesystemVerified ? ' is-verified' : '')} role="note">
        <ConsoleIcon name="shield-check" size={19} />
        <div>
          <strong>{liveFilesystemVerified
            ? '实时文件系统状态已验证 (Live Filesystem Verified)'
            : '预冻结草案预览 (Pre-Freeze Draft Preview)'}</strong>
          <p>{liveFilesystemVerified
            ? '当前预览直接反映实时文件系统状态。'
            : '当前预览基于已完成扫描数据和只读安全观察生成。实际物理身份与 SHA-256 仍将在 Freeze → Validate → Execute 阶段重新校验。'}</p>
        </div>
      </div>

      <div className="nfc-dedupe-surface-card nfc-v2-safety-card">
        <div className="nfc-dedupe-section-heading nfc-v2-safety-heading">
          <h3><ConsoleIcon name="lock" size={18} /> 身份凭证与安全摘要 (Identity & Safety Lineage)</h3>
          {engineVersion !== undefined && (
            <span className="nfc-v2-safety-tag">Dedupe Engine v{engineVersion}</span>
          )}
        </div>
        <dl className="nfc-detail-descriptions nfc-dedupe-identity-descriptions nfc-v2-safety-facts">
          <Fact full label={authorityLabel}
            hint={isDirectScan
              ? '直接扫描生成计划必须提交的权威验证摘要'
              : '工作流生成计划必须提交的权威编译摘要'}>
            <Digest value={authorityDigest} primary onCopy={copyDigest} />
          </Fact>
          {dedupePreviewDigest && (
            <Fact full label="去重预览摘要 (dedupe_preview_digest)"
              hint="底层去重步骤独立计算的算法与组结果摘要">
              <Digest value={dedupePreviewDigest} onCopy={copyDigest} />
            </Fact>
          )}
          {workflowRevision !== undefined && (
            <Fact label="工作流基线版本 (Revision)">
              <span className="nfc-v2-safety-tag">第 r{workflowRevision} 版</span>
            </Fact>
          )}
          {runtimeScanJobId !== undefined && (
            <Fact label="运行时扫描任务 (scan_job_id)">
              <span className="nfc-v2-safety-tag">Scan #{runtimeScanJobId}</span>
            </Fact>
          )}
          {previewSource && (
            <Fact label="预览数据源 (preview_source)">
              <span className="nfc-v2-safety-tag">{previewSource}</span>
            </Fact>
          )}
          {scorerConfigDigest && (
            <Fact label="打分配置摘要 (scorer_config_digest)">
              <Digest value={scorerConfigDigest} onCopy={copyDigest} />
            </Fact>
          )}
          {sourceSnapshotDigest && (
            <Fact label="源快照摘要 (source_snapshot_digest)">
              <Digest value={sourceSnapshotDigest} onCopy={copyDigest} />
            </Fact>
          )}
          {decisionDigest && (
            <Fact label="决策摘要 (decision_digest)">
              <Digest value={decisionDigest} onCopy={copyDigest} />
            </Fact>
          )}
          {definitionSha256 && (
            <Fact full label="定义哈希 (definition_sha256)">
              <Digest value={definitionSha256} onCopy={copyDigest} />
            </Fact>
          )}
          <Fact label="实时文件系统验证 (live_filesystem_verified)">
            <span className={'nfc-v2-safety-tag' + (liveFilesystemVerified ? ' is-good' : '')}>
              {liveFilesystemVerified ? '已验证 (true)' : '未验证 (false)'}
            </span>
          </Fact>
          {effectiveSafetyPolicy && effectiveSafetyPolicy.protect_last_file !== undefined && (
            <Fact label="保留最后文件保护 (protect_last_file)"
              hint={getProtectLastFileDescription(effectiveSafetyPolicy.protect_last_file)}>
              <span className={'nfc-v2-safety-tag' +
                (effectiveSafetyPolicy.protect_last_file ? ' is-good' : '')}>
                {effectiveSafetyPolicy.protect_last_file ? '已启用 (true)' : '未启用 (false)'}
              </span>
            </Fact>
          )}
          {effectiveSafetyPolicy && (
            <Fact full label="隔离区根目录 (quarantine_root)">
              <CodePath value={formatQuarantineRootPresentation(effectiveSafetyPolicy.quarantine_root)} />
            </Fact>
          )}
          {effectiveSafetyPolicy?.allowed_roots && effectiveSafetyPolicy.allowed_roots.length > 0 && (
            <Fact full label="允许扫描根目录 (allowed_roots)">
              <div className="nfc-v2-safety-root-list">
                {effectiveSafetyPolicy.allowed_roots.map((root, idx) => (
                  <CodePath key={idx} value={formatAllowedRootPresentation(idx, root)} />
                ))}
              </div>
            </Fact>
          )}
        </dl>
      </div>
    </section>
  );
};
