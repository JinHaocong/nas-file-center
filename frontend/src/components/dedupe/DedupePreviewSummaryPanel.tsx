import React from 'react';
import { Card, Row, Col, Statistic, Typography, Table, Alert, Space, Tag } from 'antd';
import {
  FolderOutlined,
  FileTextOutlined,
  DeleteOutlined,
  SaveOutlined,
  CheckCircleOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons';
import { DedupeSummary, DedupeSelectionMode } from '../../types/dedupe';
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* 1. Metric Cards */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <Card size="small" bordered={false} style={{ background: '#f6ffed', borderRadius: 8 }}>
            <Statistic
              title="重复组数"
              value={summary.group_count ?? summary.actionable_group_count ?? 0}
              suffix="组"
              prefix={<FolderOutlined style={{ color: '#52c41a' }} />}
              valueStyle={{ color: '#389e0d', fontWeight: 'bold' }}
            />
            <div style={{ marginTop: 4, fontSize: 12, color: '#8c8c8c' }}>
              可处理: {summary.actionable_group_count ?? 0} | 跳过: {summary.skipped_group_count ?? 0}
            </div>
          </Card>
        </Col>

        <Col xs={24} sm={12} md={6}>
          <Card size="small" bordered={false} style={{ background: '#e6f7ff', borderRadius: 8 }}>
            <Statistic
              title="重复副本总数"
              value={summary.candidate_member_count ?? 0}
              suffix="个"
              prefix={<FileTextOutlined style={{ color: '#1890ff' }} />}
              valueStyle={{ color: '#096dd9', fontWeight: 'bold' }}
            />
            <div style={{ marginTop: 4, fontSize: 12, color: '#8c8c8c' }}>
              候选文件总数
            </div>
          </Card>
        </Col>

        <Col xs={24} sm={12} md={6}>
          <Card size="small" bordered={false} style={{ background: '#fff7e6', borderRadius: 8 }}>
            <Statistic
              title="计划隔离副本"
              value={summary.planned_quarantine_count ?? 0}
              suffix="个"
              prefix={<DeleteOutlined style={{ color: '#fa8c16' }} />}
              valueStyle={{ color: '#d46b08', fontWeight: 'bold' }}
            />
            <div style={{ marginTop: 4, fontSize: 12, color: '#8c8c8c' }}>
              执行后将移入隔离区
            </div>
          </Card>
        </Col>

        <Col xs={24} sm={12} md={6}>
          <Card size="small" bordered={false} style={{ background: '#f9f0ff', borderRadius: 8 }}>
            <Statistic
              title="预计释放容量"
              value={formatBytes(summary.expected_reclaim_bytes ?? 0)}
              prefix={<SaveOutlined style={{ color: '#722ed1' }} />}
              valueStyle={{ color: '#531dab', fontWeight: 'bold' }}
            />
            <div style={{ marginTop: 4, fontSize: 12, color: '#8c8c8c' }}>
              去重后净收益容量
            </div>
          </Card>
        </Col>
      </Row>

      {/* 2. Balancer Callout */}
      {mode === 'balanced_by_bytes' && (
        <Alert
          type="info"
          showIcon
          icon={<InfoCircleOutlined />}
          message="根目录字节平衡模式已生效"
          description="跨扫描根目录平衡容量释放；系统优先隔离占用容量较高根目录中的副本，以平衡各卷存储压力。"
        />
      )}

      {/* 3. Released Bytes by Scan Root */}
      {rootEntries.length > 0 && (
        <Card
          size="small"
          title={
            <Space>
              <span>各扫描根目录预计释放容量</span>
              <Tag color="blue">容量分布</Tag>
            </Space>
          }
          bordered={false}
          style={{ background: '#fafafa' }}
        >
          <Table
            dataSource={rootEntries}
            rowKey="rootIndex"
            size="small"
            pagination={false}
            columns={[
              {
                title: '扫描根目录',
                dataIndex: 'rootPath',
                key: 'rootPath',
                render: (val: string, r) => (
                  <Text strong>{formatScanRootLabel(r.rootIndex, val)}</Text>
                ),
              },
              {
                title: '预计释放大小',
                dataIndex: 'releasedBytes',
                key: 'releasedBytes',
                align: 'right',
                render: (bytes: number) => (
                  <Text strong style={{ color: bytes > 0 ? '#fa8c16' : '#8c8c8c' }}>
                    {formatBytes(bytes)}
                  </Text>
                ),
              },
            ]}
          />
        </Card>
      )}

      {/* 4. Safety Guarantee Callout */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <CheckCircleOutlined
          style={{
            color: policy?.protect_last_file ? '#52c41a' : '#faad14',
          }}
        />
        <Text type="secondary" style={{ fontSize: 12 }}>
          {policy?.protect_last_file
            ? '去重安全保护策略 (protect_last_file): 已启用 (true)，确保每个重复组保留至少 1 个副本。'
            : '去重安全保护策略 (protect_last_file): 未启用 (false)。'}
        </Text>
      </div>
    </div>
  );
};
