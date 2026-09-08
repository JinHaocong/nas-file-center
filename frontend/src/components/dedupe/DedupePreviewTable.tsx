import React, { useState, useMemo } from 'react';
import {
  Table,
  Tag,
  Button,
  Space,
  Input,
  Select,
  Typography,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  SearchOutlined,
  EyeOutlined,
  CopyOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import { DedupePreviewMemberRow, MemberDecision } from '../../types/dedupe';
import { formatScanRootLabel, classifyMemberDecision } from '../../utils/dedupePreview';
import { formatBytes } from '../../utils/format';

const { Text } = Typography;

interface Props {
  rows: DedupePreviewMemberRow[];
  loading?: boolean;
  onSelectMember?: (row: DedupePreviewMemberRow) => void;
  pagination?: {
    current: number;
    pageSize: number;
    total: number;
    onChange: (page: number, pageSize: number) => void;
  } | false;
  scanRoots?: string[];
}

export const DedupePreviewTable: React.FC<Props> = ({
  rows,
  loading = false,
  onSelectMember,
  pagination,
  scanRoots,
}) => {
  const [searchText, setSearchText] = useState('');
  const [decisionFilter, setDecisionFilter] = useState<string>('ALL');
  const [rootFilter, setRootFilter] = useState<number | 'ALL'>('ALL');

  // Filter rows locally (if no server pagination or within current page)
  const filteredRows = useMemo(() => {
    return rows.filter((r) => {
      if (searchText) {
        const text = searchText.toLowerCase();
        const matchAbs = r.absolute_path?.toLowerCase().includes(text);
        const matchRel = r.relative_path?.toLowerCase().includes(text);
        if (!matchAbs && !matchRel) return false;
      }
      if (decisionFilter !== 'ALL') {
        const cls = classifyMemberDecision(r.member_decision, r.eligible_as_keep);
        if (cls.kind !== decisionFilter) return false;
      }
      if (rootFilter !== 'ALL') {
        if (r.scan_root_index !== rootFilter) return false;
      }
      return true;
    });
  }, [rows, searchText, decisionFilter, rootFilter]);

  const copyPath = (path: string) => {
    navigator.clipboard.writeText(path);
  };

  const columns: ColumnsType<DedupePreviewMemberRow> = [
    {
      title: '决策 (Decision)',
      dataIndex: 'member_decision',
      key: 'member_decision',
      width: 140,
      render: (val: string | MemberDecision, record) => {
        const cls = classifyMemberDecision(val, record.eligible_as_keep);
        return (
          <Space direction="vertical" size={2}>
            <Tag color={cls.color} style={{ fontWeight: 600, margin: 0 }}>
              {cls.label}
            </Tag>
            {record.recommended_keep && (
              <Tag color="green" style={{ fontSize: 11, margin: 0 }}>
                推荐保留
              </Tag>
            )}
          </Space>
        );
      },
    },
    {
      title: '文件路径',
      dataIndex: 'absolute_path',
      key: 'absolute_path',
      ellipsis: true,
      render: (text: string, record) => {
        return (
          <div>
            <Space size={4}>
              <Text strong ellipsis style={{ maxWidth: 420 }}>
                {text}
              </Text>
              <Tooltip title="复制路径">
                <Button
                  type="text"
                  size="small"
                  icon={<CopyOutlined />}
                  onClick={() => copyPath(text)}
                />
              </Tooltip>
            </Space>
            <div style={{ fontSize: 12, color: '#8c8c8c' }}>
              <span>组 #{record.group_provenance_id}</span>
              <span style={{ margin: '0 8px' }}>|</span>
              <span>单文件大小: {formatBytes(record.group_file_size)}</span>
              {record.relative_path && (
                <>
                  <span style={{ margin: '0 8px' }}>|</span>
                  <span>相对: {record.relative_path}</span>
                </>
              )}
            </div>
          </div>
        );
      },
    },
    {
      title: '扫描根目录',
      key: 'scan_root',
      width: 220,
      render: (_, record) => {
        const label = formatScanRootLabel(record.scan_root_index, record.scan_root_path);
        return (
          <Tooltip title={label}>
            <Tag color="cyan" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {label}
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '评分 (Score)',
      dataIndex: 'total_score',
      key: 'total_score',
      width: 110,
      align: 'right',
      render: (score?: number) => {
        return (
          <Text strong style={{ color: score !== undefined && score > 0 ? '#1890ff' : '#595959' }}>
            {score !== undefined ? score.toLocaleString() : '-'}
          </Text>
        );
      },
    },
    {
      title: '保留资格',
      dataIndex: 'eligible_as_keep',
      key: 'eligible_as_keep',
      width: 110,
      align: 'center',
      render: (eligible: boolean, record) => {
        if (eligible) {
          return (
            <Tag icon={<CheckCircleOutlined />} color="success">
              符合资格
            </Tag>
          );
        }
        return (
          <Tooltip title={record.safety_reasons?.join('; ') || '不满足安全保护策略'}>
            <Tag icon={<CloseCircleOutlined />} color="warning">
              安全排除
            </Tag>
          </Tooltip>
        );
      },
    },
    {
      title: '决策原因 / 说明',
      dataIndex: 'selection_reason',
      key: 'selection_reason',
      width: 180,
      ellipsis: true,
      render: (reason: string | null, record) => {
        const text = reason || record.group_selection_reason || '-';
        return (
          <Tooltip title={text}>
            <Text type="secondary" style={{ fontSize: 13 }}>
              {text}
            </Text>
          </Tooltip>
        );
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 90,
      align: 'center',
      render: (_, record) => {
        return (
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => onSelectMember && onSelectMember(record)}
          >
            详情
          </Button>
        );
      },
    },
  ];

  return (
    <div>
      {/* Search and Filters */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
          marginBottom: 12,
        }}
      >
        <Space wrap>
          <Input
            prefix={<SearchOutlined />}
            placeholder="按绝对路径或相对路径过滤..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            allowClear
            style={{ width: 280 }}
          />
          <Select
            value={decisionFilter}
            onChange={setDecisionFilter}
            style={{ width: 140 }}
            options={[
              { label: '全部决策', value: 'ALL' },
              { label: '保留 (KEEP)', value: 'KEEP' },
              { label: '隔离 (QUARANTINE)', value: 'QUARANTINE' },
              { label: '安全排除', value: 'SAFETY_EXCLUDED' },
              { label: '已跳过 (SKIPPED)', value: 'SKIPPED' },
            ]}
          />
          {scanRoots && scanRoots.length > 0 && (
            <Select
              value={rootFilter}
              onChange={setRootFilter}
              style={{ width: 200 }}
              options={[
                { label: '全部扫描根', value: 'ALL' },
                ...scanRoots.map((r, idx) => ({
                  label: formatScanRootLabel(idx, r),
                  value: idx,
                })),
              ]}
            />
          )}
        </Space>
        <div>
          <Text type="secondary" style={{ fontSize: 13 }}>
            共显示 {filteredRows.length} 项成员
          </Text>
        </div>
      </div>

      <Table<DedupePreviewMemberRow>
        rowKey={(r) => `${r.group_provenance_id}_${r.absolute_path}`}
        columns={columns}
        dataSource={filteredRows}
        loading={loading}
        size="middle"
        bordered
        pagination={
          pagination === false
            ? false
            : pagination || {
                pageSize: 20,
                showSizeChanger: true,
                showQuickJumper: true,
              }
        }
      />
    </div>
  );
};
