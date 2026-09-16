import React from 'react';
import { Alert, Card, Descriptions, Divider, Drawer, Space, Table, Tag, Typography } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, CompassOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { BalanceInfo, DedupePreviewMemberRow, FactorContribution } from '../../types/dedupe';
import { classifyMemberDecision, formatScanRootLabel, isBalancerContributionExcludedFromFactors } from '../../utils/dedupePreview';
import { findDuplicateGroupSiblings, formatOptionalFileSize, formatOptionalGroupId } from '../../utils/dedupePresentation';
import { formatBytes } from '../../utils/format';

const { Text } = Typography;
interface Props { open: boolean; onClose: () => void; member: DedupePreviewMemberRow | null; groupMembers?: DedupePreviewMemberRow[]; }

const renderBucketMap = (value?: Record<string, number>) => {
  if (!value || Object.keys(value).length === 0) return <Text type="secondary">-</Text>;
  return <Space direction="vertical" size={2}>{Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([bucket, bytes]) => <Text key={bucket} code>{bucket}: {formatBytes(bytes)}</Text>)}</Space>;
};

const RecursiveBalanceDetails: React.FC<{ member: DedupePreviewMemberRow; balanceInfo?: BalanceInfo | null }> = ({ member, balanceInfo }) => {
  const hasRecursive = Boolean(
    member.candidate_balance_bucket ||
    member.recursive_last_file_protection_reason ||
    balanceInfo?.lca ||
    balanceInfo?.bucket_released_bytes_before ||
    balanceInfo?.bucket_released_bytes_after
  );
  if (!hasRecursive) return null;
  return <Card size="small" title={<Space><CompassOutlined /><span>递归目录容量平衡 (Recursive Directory Balance)</span></Space>} bordered={false} style={{ background: '#fffbe6', border: '1px solid #ffe58f' }}>
    <Alert type="warning" showIcon message="Recursive Last-File Protection — 强制连续保护" description="该安全约束由后端持续执行；前端只展示保护证据，不提供关闭开关。" style={{ marginBottom: 12 }} />
    <Descriptions column={1} size="small" bordered style={{ background: '#fff' }}>
      {balanceInfo?.balance_source && <Descriptions.Item label="平衡来源 (balance_source)"><Tag>{balanceInfo.balance_source}</Tag></Descriptions.Item>}
      {balanceInfo?.lca && <Descriptions.Item label="重复组 LCA (lca)"><Text code copyable>{balanceInfo.lca}</Text></Descriptions.Item>}
      {balanceInfo?.lca_depth !== undefined && <Descriptions.Item label="LCA 深度 (lca_depth)">{balanceInfo.lca_depth}</Descriptions.Item>}
      {member.candidate_balance_bucket && <Descriptions.Item label="候选目录桶 (candidate_balance_bucket)"><Text code copyable>{member.candidate_balance_bucket}</Text></Descriptions.Item>}
      {balanceInfo?.anchor_root && <Descriptions.Item label="锚定根 (anchor_root)"><Text code>{balanceInfo.anchor_root}</Text></Descriptions.Item>}
      {balanceInfo?.parent_bucket !== undefined && <Descriptions.Item label="父桶 (parent_bucket)"><Text code>{balanceInfo.parent_bucket || '-'}</Text></Descriptions.Item>}
      {member.recursive_last_file_protection_reason && <Descriptions.Item label="保护原因 (recursive_last_file_protection_reason)"><Text type="warning">{member.recursive_last_file_protection_reason}</Text></Descriptions.Item>}
      {balanceInfo?.recursive_last_file_protection && <Descriptions.Item label="保护状态 (recursive_last_file_protection)"><Tag color="warning">{balanceInfo.recursive_last_file_protection}</Tag></Descriptions.Item>}
      <Descriptions.Item label="目录桶释放字节 — before (bucket_released_bytes_before)">{renderBucketMap(balanceInfo?.bucket_released_bytes_before)}</Descriptions.Item>
      <Descriptions.Item label="目录桶释放字节 — after (bucket_released_bytes_after)">{renderBucketMap(balanceInfo?.bucket_released_bytes_after)}</Descriptions.Item>
      {balanceInfo?.spread_before !== undefined && <Descriptions.Item label="平衡前极差 (spread_before)"><Text strong>{formatBytes(balanceInfo.spread_before)}</Text></Descriptions.Item>}
      {balanceInfo?.spread_after !== undefined && <Descriptions.Item label="平衡后极差 (spread_after)"><Text strong>{formatBytes(balanceInfo.spread_after)}</Text></Descriptions.Item>}
    </Descriptions>
  </Card>;
};

export const DedupeExplainDrawer: React.FC<Props> = ({ open, onClose, member, groupMembers = [] }) => {
  if (!member) return null;
  const decision = classifyMemberDecision(member.member_decision, member.eligible_as_keep);
  const factorContributions = (member.contributions || []).filter((item) => !isBalancerContributionExcludedFromFactors(item));
  const balanceInfo = member.balance_info || member.group_balance_info;
  const siblings = findDuplicateGroupSiblings(member, groupMembers);
  return <Drawer title={<Space><span>去重决策分析 (Decision Explain)</span><Tag color={decision.color}>{decision.label}</Tag></Space>} placement="right" width={680} open={open} onClose={onClose} destroyOnClose>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {member.incomplete && <Alert type="warning" showIcon message="缺少详细指标分析数据" description="当前项缺少完整 canonical metadata，以下字段可能不完整。" />}
      <Card size="small" title="文件与决策" bordered={false} style={{ background: '#fafafa' }}>
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="绝对路径"><Text copyable strong style={{ wordBreak: 'break-all' }}>{member.absolute_path}</Text></Descriptions.Item>
          {member.relative_path && <Descriptions.Item label="相对路径"><Text>{member.relative_path}</Text></Descriptions.Item>}
          <Descriptions.Item label="扫描根"><Tag color="cyan">{formatScanRootLabel(member.scan_root_index, member.scan_root_path)}</Tag></Descriptions.Item>
          <Descriptions.Item label="重复组 ID"><Tag color="purple">{formatOptionalGroupId(member.group_provenance_id)}</Tag></Descriptions.Item>
          <Descriptions.Item label="单文件大小"><Text strong>{formatOptionalFileSize(member.group_file_size)}</Text></Descriptions.Item>
          <Descriptions.Item label="最终决策"><Space><Tag color={decision.color}>{decision.label}</Tag>{member.recommended_keep && <Tag color="green">推荐保留项</Tag>}{member.is_top_candidate && <Tag color="blue">最高候选者</Tag>}</Space></Descriptions.Item>
          <Descriptions.Item label="保留资格">{member.eligible_as_keep === true ? <Tag icon={<CheckCircleOutlined />} color="success">满足保留资格</Tag> : member.eligible_as_keep === false ? <Tag icon={<CloseCircleOutlined />} color="warning">不可保留</Tag> : <Tag>未知</Tag>}</Descriptions.Item>
          <Descriptions.Item label="选择原因"><Text>{member.selection_reason || member.group_selection_reason || '-'}</Text></Descriptions.Item>
          <Descriptions.Item label="总评分"><Text strong>{member.total_score ?? '-'}</Text></Descriptions.Item>
        </Descriptions>
      </Card>

      <RecursiveBalanceDetails member={member} balanceInfo={balanceInfo} />

      {balanceInfo && !balanceInfo.lca && <Card size="small" title={<Space><CompassOutlined /><span>根目录容量平衡器分析 (Capacity Balancer)</span></Space>} bordered={false} style={{ background: '#fffbe6' }}><Descriptions column={1} size="small" bordered>{balanceInfo.spread_before !== undefined && <Descriptions.Item label="spread_before">{formatBytes(balanceInfo.spread_before)}</Descriptions.Item>}{balanceInfo.spread_after !== undefined && <Descriptions.Item label="spread_after">{formatBytes(balanceInfo.spread_after)}</Descriptions.Item>}</Descriptions></Card>}

      {!member.incomplete && <Card size="small" title="各因子打分明细 (Factor Contributions)" bordered={false} style={{ background: '#fafafa' }}>
        {factorContributions.length === 0 ? <Alert type="info" message="当前无单独计分因子贡献项。" /> : <Table<FactorContribution> dataSource={factorContributions} rowKey={(row, index) => `${row.factor}-${index}`} size="small" pagination={false} columns={[
          { title: '因子', dataIndex: 'factor', key: 'factor', render: (value: string) => <Tag>{value}</Tag> },
          { title: '权重', dataIndex: 'configured_weight', key: 'configured_weight' },
          { title: '贡献', dataIndex: 'actual_contribution', key: 'actual_contribution' },
          { title: '说明', dataIndex: 'reason', key: 'reason', render: (value?: string) => value || '-' },
        ]} />}
      </Card>}

      {siblings.length > 0 && <Card size="small" title={`同组其他副本成员 (${siblings.length})`} bordered={false}>{siblings.map((sibling) => <div key={sibling.absolute_path} style={{ marginBottom: 8 }}><Tag color={classifyMemberDecision(sibling.member_decision, sibling.eligible_as_keep).color}>{classifyMemberDecision(sibling.member_decision, sibling.eligible_as_keep).label}</Tag><Text>{sibling.absolute_path}</Text></div>)}</Card>}
      <Divider style={{ margin: '4px 0' }} />
      <Space><InfoCircleOutlined /><Text type="secondary">所有打分、目录桶和平衡决策均由后端权威引擎产出，前端不重新计算。</Text></Space>
    </div>
  </Drawer>;
};
