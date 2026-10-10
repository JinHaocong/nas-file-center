import React from 'react';
import type { DedupePreviewMemberRow } from '../../types/dedupe';
import {
  formatScanRootLabel, classifyMemberDecision,
  isBalancerContributionExcludedFromFactors,
} from '../../utils/dedupePreview';
import {
  formatOptionalGroupId, formatOptionalFileSize, findDuplicateGroupSiblings,
} from '../../utils/dedupePresentation';
import { formatBytes } from '../../utils/format';
import { ConsoleSheet } from '../ui/ConsoleSheet';
import { ConsoleButton } from '../ui/ConsoleButton';
import { ConsoleIcon } from '../ui/ConsoleIcon';
import { useConsoleToast } from '../ui/ConsoleToast';

interface Props {
  open: boolean;
  onClose: () => void;
  member: DedupePreviewMemberRow | null;
  groupMembers?: DedupePreviewMemberRow[];
}

const DecisionTag: React.FC<{ decision?: string; eligible?: boolean; children?: React.ReactNode }> =
  ({ decision, eligible, children }) => {
    const cls = classifyMemberDecision(decision, eligible);
    return (
      <span className={'nfc-v2-dedupe-decision-tag is-' + cls.color}>
        {children || cls.label}
      </span>
    );
  };

const Section: React.FC<{ title: string; children: React.ReactNode; aside?: React.ReactNode }> =
  ({ title, children, aside }) => (
    <section className="nfc-dedupe-surface-card nfc-v2-dedupe-explain-section">
      <header className="nfc-v2-dedupe-explain-section-header">
        <h3>{title}</h3>{aside}
      </header>
      {children}
    </section>
  );

const Fact: React.FC<{ label: string; children: React.ReactNode }> =
  ({ label, children }) => (
    <div className="nfc-v2-dedupe-explain-fact">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );

const Notice: React.FC<{ children: React.ReactNode; warning?: boolean }> =
  ({ children, warning = false }) => (
    <div className={'nfc-v2-dedupe-explain-notice' + (warning ? ' is-warning' : '')} role="note">
      <ConsoleIcon name="shield-check" size={18} /> <span>{children}</span>
    </div>
  );

const renderBucketBytes = (value?: Record<string, number>) => {
  if (!value || Object.keys(value).length === 0) return <span className="nfc-table-muted">-</span>;
  return (
    <div className="nfc-v2-dedupe-explain-buckets">
      {Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([bucket, bytes]) => (
          <code key={bucket}>{bucket}: {formatBytes(bytes)}</code>
        ))}
    </div>
  );
};

/** Read-only explanation. Scores, reasons, eligibility and balance facts all come from the backend. */
export const DedupeExplainDrawer: React.FC<Props> = ({
  open, onClose, member, groupMembers = [],
}) => {
  const toast = useConsoleToast();
  if (!member) return null;

  const copyValue = (value: string) => {
    if (!navigator.clipboard?.writeText) {
      toast.error('当前浏览器不支持复制');
      return;
    }
    void navigator.clipboard.writeText(value)
      .then(() => toast.success('已复制'))
      .catch(() => toast.error('复制失败，请手动选择文本'));
  };
  const Copyable: React.FC<{ value: string }> = ({ value }) => (
    <span className="nfc-v2-dedupe-explain-copy">
      <code title={value}>{value}</code>
      <ConsoleButton variant="ghost" size="sm" aria-label="复制内容"
        onClick={() => copyValue(value)}>复制</ConsoleButton>
    </span>
  );

  const decisionCls = classifyMemberDecision(member.member_decision, member.eligible_as_keep);
  const factorContributions = (member.contributions || []).filter(
    c => !isBalancerContributionExcludedFromFactors(c)
  );
  const balanceInfo = member.balance_info || member.group_balance_info;
  const siblings = findDuplicateGroupSiblings(member, groupMembers);

  return (
    <ConsoleSheet open={open} onClose={onClose} title="去重决策分析"
      description="只读展示后端评分、资格、安全排除和容量平衡依据"
      eyebrow="Decision explain" className="nfc-v2-dedupe-explain-sheet nfc-dedupe-explain-drawer"
      titleAside={<DecisionTag decision={decisionCls.kind} eligible={member.eligible_as_keep} />}>
      <div className="nfc-overlay-stack nfc-dedupe-explain-stack nfc-v2-dedupe-explain">
        {member.incomplete && (
          <Notice warning>
            <strong>缺少详细指标分析数据。</strong>
            当前去重项缺少完整的后端 canonical 分析数据，无法展示详细的因子评分与决策依据。
          </Notice>
        )}

        <Section title="文件基本信息">
          <dl className="nfc-v2-dedupe-explain-facts">
            <Fact label="绝对路径"><Copyable value={member.absolute_path} /></Fact>
            {member.relative_path && (
              <Fact label="相对路径"><code>{member.relative_path}</code></Fact>
            )}
            <Fact label="所属扫描根">
              <span className="nfc-v2-dedupe-explain-tag">{formatScanRootLabel(member.scan_root_index, member.scan_root_path)}</span>
            </Fact>
            <Fact label="单文件大小"><strong>{formatOptionalFileSize(member.group_file_size)}</strong></Fact>
            <Fact label="重复组 ID"><span className="nfc-v2-dedupe-explain-tag">{formatOptionalGroupId(member.group_provenance_id)}</span></Fact>
          </dl>
        </Section>

        <Section title="重复组级别摘要 (Group Summary)">
          <dl className="nfc-v2-dedupe-explain-facts">
            {member.group_status && (
              <Fact label="组状态 (group_status)">
                <span className="nfc-v2-dedupe-explain-tag">{member.group_status}</span>
              </Fact>
            )}
            {member.group_skip_reason && (
              <Fact label="组跳过原因 (group_skip_reason)">
                <span className="nfc-v2-dedupe-explain-warning">{member.group_skip_reason}</span>
              </Fact>
            )}
            {member.group_recommended_keep_path && (
              <Fact label="组推荐保留路径 (group_recommended_keep_path)">
                <Copyable value={member.group_recommended_keep_path} />
              </Fact>
            )}
            <Fact label="组可释放容量 (group_reclaimable_bytes)">
              <strong>{formatOptionalFileSize(member.group_reclaimable_bytes)}</strong>
            </Fact>
            {member.group_selection_reason && (
              <Fact label="组选择原因 (group_selection_reason)">{member.group_selection_reason}</Fact>
            )}
          </dl>
        </Section>

        <Section title="决策与资格判定">
          <dl className="nfc-v2-dedupe-explain-facts">
            <Fact label="最终决策 (Decision)">
              <div className="nfc-v2-dedupe-explain-tags">
                <DecisionTag decision={member.member_decision} eligible={member.eligible_as_keep} />
                {member.recommended_keep && <span className="nfc-v2-dedupe-decision-tag is-success">推荐保留项</span>}
                {member.is_top_candidate && <span className="nfc-v2-dedupe-decision-tag is-default">最高候选者</span>}
              </div>
            </Fact>
            <Fact label="可保留资格 (Eligible)">
              {member.eligible_as_keep === true ? (
                <span className="nfc-v2-dedupe-decision-tag is-success">
                  <ConsoleIcon name="check-circle" size={15} /> 满足保留资格
                </span>
              ) : member.eligible_as_keep === false ? (
                <span className="nfc-v2-dedupe-decision-tag is-warning">
                  <ConsoleIcon name="shield-check" size={15} />
                  受限不可保留 ({member.safety_reasons?.join(', ') || '安全策略排除'})
                </span>
              ) : (
                <span className="nfc-v2-dedupe-decision-tag is-default">不可用 / -</span>
              )}
            </Fact>
            <Fact label="决策原因 / 说明">
              {member.selection_reason || member.group_selection_reason || '-'}
            </Fact>
            <Fact label="总评分 (Total Score)">
              <strong className="nfc-dedupe-score-value">
                {member.total_score !== undefined ? member.total_score.toLocaleString() : '-'}
              </strong>
            </Fact>
            {member.candidate_balance_bucket && (
              <Fact label="递归候选桶 (candidate_balance_bucket)">
                <Copyable value={member.candidate_balance_bucket} />
              </Fact>
            )}
            {member.recursive_last_file_protection_reason && (
              <Fact label="最后文件保护原因 (recursive_last_file_protection_reason)">
                <span className="nfc-v2-dedupe-explain-warning">{member.recursive_last_file_protection_reason}</span>
              </Fact>
            )}
          </dl>
        </Section>

        {member.storage_action && member.storage_action !== 'quarantine' && (
          <Section title="Storage Action 资格">
            <dl className="nfc-v2-dedupe-explain-facts">
              <Fact label="Storage Action">
                <span className="nfc-v2-dedupe-explain-tag">{member.storage_action.toUpperCase()}</span>
              </Fact>
              <Fact label="Metadata eligibility">
                <span className={'nfc-v2-dedupe-decision-tag ' +
                  (member.storage_metadata_compatible === true ? 'is-success' :
                    member.storage_metadata_compatible === false ? 'is-error' : 'is-default')}>
                  {member.storage_metadata_compatible === true ? 'ELIGIBLE' :
                    member.storage_metadata_compatible === false ? 'BLOCKED' : 'NOT APPLICABLE'}
                </span>
              </Fact>
              {member.storage_blocking_reason && (
                <Fact label="阻断原因">
                  <code className="nfc-v2-dedupe-explain-warning">{member.storage_blocking_reason}</code>
                </Fact>
              )}
              <Fact label="Preview capability">
                <code>{member.storage_capability || 'NOT_CHECKED'}</code>
              </Fact>
            </dl>
            <Notice>Preview 只做 metadata eligibility，不执行 filesystem capability probe。</Notice>
          </Section>
        )}

        {!member.incomplete && (
          <Section title="各因子打分明细 (Factor Contributions)"
            aside={<span className="nfc-table-meta">加权评分层</span>}>
            {factorContributions.length === 0 ? (
              <Notice>当前无单独计分因子贡献项。</Notice>
            ) : (
              <div className="nfc-v2-dedupe-explain-table-wrap">
                <table className="nfc-v2-dedupe-explain-table">
                  <thead><tr>
                    <th scope="col">因子名称</th>
                    <th scope="col">配置权重</th>
                    <th scope="col">实际贡献分</th>
                    <th scope="col">说明 / 命中规则</th>
                  </tr></thead>
                  <tbody>
                    {factorContributions.map((factor, idx) => (
                      <tr key={factor.factor + ':' + idx}>
                        <td><span className="nfc-v2-dedupe-explain-tag">{factor.factor}</span></td>
                        <td className="is-numeric">{factor.configured_weight}</td>
                        <td className="is-numeric"><strong>{factor.actual_contribution > 0 ? '+' : ''}{factor.actual_contribution.toLocaleString()}</strong></td>
                        <td>{factor.reason || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        )}

        {!member.incomplete && balanceInfo && (
          <Section title="容量平衡器分析 (Capacity Balancer)">
            <Notice warning>
              {balanceInfo.lca
                ? '递归目录平衡器属于选择仲裁层，Recursive Last-File Protection 强制连续启用。'
                : '容量平衡器属于选择仲裁层，独立于因子权重计分之外。'}
            </Notice>
            <dl className="nfc-v2-dedupe-explain-facts">
              {balanceInfo.balance_source && (
                <Fact label="平衡来源 (balance_source)">{balanceInfo.balance_source}</Fact>
              )}
              {balanceInfo.lca && (
                <Fact label="重复组 LCA (lca)"><Copyable value={balanceInfo.lca} /></Fact>
              )}
              {balanceInfo.lca_depth !== undefined && (
                <Fact label="LCA 深度 (lca_depth)">{balanceInfo.lca_depth}</Fact>
              )}
              {balanceInfo.anchor_root && (
                <Fact label="锚定根 (anchor_root)"><code>{balanceInfo.anchor_root}</code></Fact>
              )}
              {balanceInfo.parent_bucket !== undefined && (
                <Fact label="父目录桶 (parent_bucket)"><code>{balanceInfo.parent_bucket || '-'}</code></Fact>
              )}
              {balanceInfo.recursive_last_file_protection && (
                <Fact label="Recursive Last-File Protection">
                  <span className="nfc-v2-dedupe-decision-tag is-warning">{balanceInfo.recursive_last_file_protection}</span>
                </Fact>
              )}
              {balanceInfo.bucket_released_bytes_before && (
                <Fact label="目录桶释放字节 (bucket_released_bytes_before)">
                  {renderBucketBytes(balanceInfo.bucket_released_bytes_before)}
                </Fact>
              )}
              {balanceInfo.bucket_released_bytes_after && (
                <Fact label="目录桶释放字节 (bucket_released_bytes_after)">
                  {renderBucketBytes(balanceInfo.bucket_released_bytes_after)}
                </Fact>
              )}
              {balanceInfo.spread_before !== undefined && (
                <Fact label="平衡前极差 (spread_before)">
                  <strong>{formatBytes(balanceInfo.spread_before)}</strong>
                </Fact>
              )}
              {balanceInfo.spread_after !== undefined && (
                <Fact label="平衡后极差 (spread_after)">
                  <strong>{formatBytes(balanceInfo.spread_after)}</strong>
                </Fact>
              )}
            </dl>
          </Section>
        )}

        {siblings.length > 0 && (
          <Section title={'同组其他副本成员 (' + siblings.length + ' 个，当前预览页)'}>
            <div className="nfc-dedupe-sibling-list nfc-v2-dedupe-explain-siblings">
              {siblings.map((sib, idx) => (
                <div key={sib.absolute_path + ':' + idx} className="nfc-dedupe-sibling-card">
                  <div className="nfc-dedupe-sibling-heading">
                    <DecisionTag decision={sib.member_decision} eligible={sib.eligible_as_keep} />
                    <strong className={sib.total_score !== undefined && sib.total_score > 0 ? 'nfc-accent-text' : 'nfc-table-muted'}>
                      评分: {sib.total_score !== undefined ? sib.total_score : '-'}
                    </strong>
                  </div>
                  <code className="nfc-dedupe-sibling-path" title={sib.absolute_path}>{sib.absolute_path}</code>
                  <div className="nfc-dedupe-sibling-meta">
                    <span>{formatScanRootLabel(sib.scan_root_index, sib.scan_root_path)}</span>
                    {sib.selection_reason && <><span className="nfc-inline-separator">|</span><span>{sib.selection_reason}</span></>}
                  </div>
                </div>
              ))}
            </div>
          </Section>
        )}

        <div className="nfc-dedupe-explain-footnote nfc-v2-dedupe-explain-footnote">
          <ConsoleIcon name="shield-check" size={16} />
          所有打分与决策数据均由后端去重引擎确定性产出，前端不进行任何打分计算。
        </div>
      </div>
    </ConsoleSheet>
  );
};
