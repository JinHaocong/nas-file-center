import React from 'react';
import {
  Drawer,
  Descriptions,
  Tag,
  Typography,
  Table,
  Card,
  Alert,
  Space,
  Divider,
} from 'antd';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  InfoCircleOutlined,
  CompassOutlined,
} from '@ant-design/icons';
import { DedupePreviewMemberRow, FactorContribution } from '../../types/dedupe';
import {
  formatScanRootLabel,
  classifyMemberDecision,
  isBalancerContributionExcludedFromFactors,
} from '../../utils/dedupePreview';
import {
  formatOptionalGroupId,
  formatOptionalFileSize,
  findDuplicateGroupSiblings,
} from '../../utils/dedupePresentation';
import { formatBytes } from '../../utils/format';

const { Text } = Typography;

interface Props {
  open: boolean;
  onClose: () => void;
  member: DedupePreviewMemberRow | null;
  groupMembers?: DedupePreviewMemberRow[];
}

const renderBucketBytes = (value?: Record<string, number>) => {
  if (!value || Object.keys(value).length === 0) return <Text type="secondary">-</Text>;
  return (
    <Space direction="vertical" size={2}>
      {Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([bucket, bytes]) => (
          <Text key={bucket} code>
            {bucket}: {formatBytes(bytes)}
          </Text>
        ))}
    </Space>
  );
};

export const DedupeExplainDrawer: React.FC<Props> = ({
  open,
  onClose,
  member,
  groupMembers = [],
}) => {
  if (!member) {
    return null;
  }

  const decisionCls = classifyMemberDecision(member.member_decision, member.eligible_as_keep);
  const factorContributions = (member.contributions || []).filter(
    (c) => !isBalancerContributionExcludedFromFactors(c)
  );
  const balanceInfo = member.balance_info || member.group_balance_info;
  const siblings = findDuplicateGroupSiblings(member, groupMembers);

  return (
    <Drawer
      title={
        <Space>
          <span>去重决策分析 (Decision Explain)</span>
          <Tag color={decisionCls.color} style={{ fontWeight: 600 }}>
            {decisionCls.label}
          </Tag>
        </Space>
      }
      placement="right"
      width={680}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {member.incomplete && (
          <Alert
            type="warning"
            showIcon
            message="缺少详细指标分析数据"
            description="当前去重项缺少完整的后端 canonical 分析数据，无法展示详细的因子评分与决策依据。"
          />
        )}

        <Card size="small" title="文件基本信息" bordered={false} style={{ background: '#fafafa' }}>
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="绝对路径">
              <Text copyable strong style={{ wordBreak: 'break-all' }}>
                {member.absolute_path}
              </Text>
            </Descriptions.Item>
            {member.relative_path && (
              <Descriptions.Item label="相对路径">
                <Text style={{ wordBreak: 'break-all' }}>{member.relative_path}</Text>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="所属扫描根">
              <Tag color="cyan">{formatScanRootLabel(member.scan_root_index, member.scan_root_path)}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="单文件大小">
              <Text strong>{formatOptionalFileSize(member.group_file_size)}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="重复组 ID">
              <Tag color="purple">{formatOptionalGroupId(member.group_provenance_id)}</Tag>
            </Descriptions.Item>
          </Descriptions>
        </Card>

        <Card size="small" title="重复组级别摘要 (Group Summary)" bordered={false} style={{ background: '#fafafa' }}>
          <Descriptions column={1} size="small" bordered>
            {member.group_status && (
              <Descriptions.Item label="组状态 (group_status)">
                <Tag color={member.group_status === 'actionable' ? 'green' : 'orange'}>{member.group_status}</Tag>
              </Descriptions.Item>
            )}
            {member.group_skip_reason && (
              <Descriptions.Item label="组跳过原因 (group_skip_reason)">
                <Text type="warning">{member.group_skip_reason}</Text>
              </Descriptions.Item>
            )}
            {member.group_recommended_keep_path && (
              <Descriptions.Item label="组推荐保留路径 (group_recommended_keep_path)">
                <Text copyable strong style={{ wordBreak: 'break-all' }}>{member.group_recommended_keep_path}</Text>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="组可释放容量 (group_reclaimable_bytes)">
              <Text strong style={{ color: '#52c41a' }}>{formatOptionalFileSize(member.group_reclaimable_bytes)}</Text>
            </Descriptions.Item>
            {member.group_selection_reason && (
              <Descriptions.Item label="组选择原因 (group_selection_reason)">
                <Text>{member.group_selection_reason}</Text>
              </Descriptions.Item>
            )}
          </Descriptions>
        </Card>

        <Card size="small" title="决策与资格判定" bordered={false} style={{ background: '#fafafa' }}>
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="最终决策 (Decision)">
              <Space>
                <Tag color={decisionCls.color} style={{ fontWeight: 600 }}>{decisionCls.label}</Tag>
                {member.recommended_keep && <Tag color="green">推荐保留项</Tag>}
                {member.is_top_candidate && <Tag color="blue">最高候选者</Tag>}
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="可保留资格 (Eligible)">
              {member.eligible_as_keep === true ? (
                <Tag icon={<CheckCircleOutlined />} color="success">满足保留资格</Tag>
              ) : member.eligible_as_keep === false ? (
                <Tag icon={<CloseCircleOutlined />} color="warning">
                  受限不可保留 ({member.safety_reasons?.join(', ') || '安全策略排除'})
                </Tag>
              ) : (
                <Tag color="default">不可用 / -</Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="决策原因 / 说明">
              <Text>{member.selection_reason || member.group_selection_reason || '-'}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="总评分 (Total Score)">
              <Text strong style={{ fontSize: 16, color: '#1890ff' }}>
                {member.total_score !== undefined ? member.total_score.toLocaleString() : '-'}
              </Text>
            </Descriptions.Item>
            {member.candidate_balance_bucket && (
              <Descriptions.Item label="递归候选桶 (candidate_balance_bucket)">
                <Text code copyable>{member.candidate_balance_bucket}</Text>
              </Descriptions.Item>
            )}
            {member.recursive_last_file_protection_reason && (
              <Descriptions.Item label="最后文件保护原因 (recursive_last_file_protection_reason)">
                <Text type="warning">{member.recursive_last_file_protection_reason}</Text>
              </Descriptions.Item>
            )}
          </Descriptions>
        </Card>

        {!member.incomplete && (
          <Card
            size="small"
            title={
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>各因子打分明细 (Factor Contributions)</span>
                <Text type="secondary" style={{ fontSize: 12 }}>加权评分层</Text>
              </div>
            }
            bordered={false}
            style={{ background: '#fafafa' }}
          >
            {factorContributions.length === 0 ? (
              <Alert type="info" message="当前无单独计分因子贡献项。" />
            ) : (
              <Table<FactorContribution>
                dataSource={factorContributions}
                rowKey="factor"
                size="small"
                pagination={false}
                columns={[
                  { title: '因子名称', dataIndex: 'factor', key: 'factor', render: (f: string) => <Tag color="geekblue">{f}</Tag> },
                  { title: '配置权重', dataIndex: 'configured_weight', key: 'configured_weight', align: 'right', render: (w: number) => <Text>{w}</Text> },
                  { title: '实际贡献分', dataIndex: 'actual_contribution', key: 'actual_contribution', align: 'right', render: (c: number) => <Text strong style={{ color: c > 0 ? '#52c41a' : '#8c8c8c' }}>+{c.toLocaleString()}</Text> },
                  { title: '说明 / 命中规则', dataIndex: 'reason', key: 'reason', render: (r?: string) => <Text type="secondary">{r || '-'}</Text> },
                ]}
              />
            )}
          </Card>
        )}

        {!member.incomplete && balanceInfo && (
          <Card
            size="small"
            title={
              <Space>
                <CompassOutlined style={{ color: '#fa8c16' }} />
                <span>容量平衡器分析 (Capacity Balancer)</span>
              </Space>
            }
            bordered={false}
            style={{ background: '#fffbe6', border: '1px solid #ffe58f' }}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Alert
                type="warning"
                showIcon
                message={balanceInfo.lca ? '递归目录平衡器属于选择仲裁层，Recursive Last-File Protection 强制连续启用。' : '容量平衡器属于选择仲裁层，独立于因子权重计分之外。'}
                style={{ marginBottom: 8 }}
              />
              <Descriptions column={1} size="small" bordered style={{ background: '#fff' }}>
                {balanceInfo.balance_source && (
                  <Descriptions.Item label="平衡来源 (balance_source)"><Tag>{balanceInfo.balance_source}</Tag></Descriptions.Item>
                )}
                {balanceInfo.lca && (
                  <Descriptions.Item label="重复组 LCA (lca)"><Text code copyable>{balanceInfo.lca}</Text></Descriptions.Item>
                )}
                {balanceInfo.lca_depth !== undefined && (
                  <Descriptions.Item label="LCA 深度 (lca_depth)"><Text>{balanceInfo.lca_depth}</Text></Descriptions.Item>
                )}
                {balanceInfo.anchor_root && (
                  <Descriptions.Item label="锚定根 (anchor_root)"><Text code>{balanceInfo.anchor_root}</Text></Descriptions.Item>
                )}
                {balanceInfo.parent_bucket !== undefined && (
                  <Descriptions.Item label="父目录桶 (parent_bucket)"><Text code>{balanceInfo.parent_bucket || '-'}</Text></Descriptions.Item>
                )}
                {balanceInfo.recursive_last_file_protection && (
                  <Descriptions.Item label="Recursive Last-File Protection"><Tag color="warning">{balanceInfo.recursive_last_file_protection}</Tag></Descriptions.Item>
                )}
                {balanceInfo.bucket_released_bytes_before && (
                  <Descriptions.Item label="目录桶释放字节 (bucket_released_bytes_before)">{renderBucketBytes(balanceInfo.bucket_released_bytes_before)}</Descriptions.Item>
                )}
                {balanceInfo.bucket_released_bytes_after && (
                  <Descriptions.Item label="目录桶释放字节 (bucket_released_bytes_after)">{renderBucketBytes(balanceInfo.bucket_released_bytes_after)}</Descriptions.Item>
                )}
                {balanceInfo.spread_before !== undefined && (
                  <Descriptions.Item label="平衡前极差 (spread_before)"><Text strong>{formatBytes(balanceInfo.spread_before)}</Text></Descriptions.Item>
                )}
                {balanceInfo.spread_after !== undefined && (
                  <Descriptions.Item label="平衡后极差 (spread_after)"><Text strong>{formatBytes(balanceInfo.spread_after)}</Text></Descriptions.Item>
                )}
              </Descriptions>
            </div>
          </Card>
        )}

        {siblings.length > 0 && (
          <Card size="small" title={`同组其他副本成员 (${siblings.length} 个)`} bordered={false} style={{ background: '#fafafa' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {siblings.map((sib, idx) => {
                const sCls = classifyMemberDecision(sib.member_decision, sib.eligible_as_keep);
                return (
                  <div key={idx} style={{ background: '#fff', padding: 10, borderRadius: 6, border: '1px solid #f0f0f0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <Tag color={sCls.color}>{sCls.label}</Tag>
                      <Text strong style={{ color: sib.total_score !== undefined && sib.total_score > 0 ? '#1890ff' : '#595959' }}>
                        评分: {sib.total_score !== undefined ? sib.total_score : '-'}
                      </Text>
                    </div>
                    <Text ellipsis style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>{sib.absolute_path}</Text>
                    <div style={{ fontSize: 12, color: '#8c8c8c' }}>
                      <span>{formatScanRootLabel(sib.scan_root_index, sib.scan_root_path)}</span>
                      {sib.selection_reason && <><span style={{ margin: '0 6px' }}>|</span><span>{sib.selection_reason}</span></>}
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        )}

        <Divider style={{ margin: '8px 0' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <InfoCircleOutlined style={{ color: '#8c8c8c' }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            所有打分与决策数据均由后端去重引擎确定性产出，前端不进行任何打分计算。
          </Text>
        </div>
      </div>
    </Drawer>
  );
};
