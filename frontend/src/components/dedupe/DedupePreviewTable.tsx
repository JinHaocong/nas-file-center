import React, { useMemo, useState } from 'react';
import {
  Button,
  Input,
  Pagination,
  Select,
  Table,
  Tag,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  EyeOutlined,
  SearchOutlined,
} from '@ant-design/icons';
import { DedupePreviewMemberRow, MemberDecision } from '../../types/dedupe';
import { formatScanRootLabel, classifyMemberDecision } from '../../utils/dedupePreview';
import {
  getEligibilityPresentation,
  formatOptionalGroupId,
  formatOptionalFileSize,
} from '../../utils/dedupePresentation';
import { ActionBar } from '../ui/ActionBar';
import { ResponsiveDataView } from '../ui/ResponsiveDataView';
import { CodePath } from '../ui/CodePath';

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

  const filteredRows = useMemo(() => {
    return rows.filter((row) => {
      if (searchText) {
        const text = searchText.toLowerCase();
        const matchAbs = row.absolute_path?.toLowerCase().includes(text);
        const matchRel = row.relative_path?.toLowerCase().includes(text);
        if (!matchAbs && !matchRel) return false;
      }
      if (decisionFilter !== 'ALL') {
        const cls = classifyMemberDecision(row.member_decision, row.eligible_as_keep);
        if (cls.kind !== decisionFilter) return false;
      }
      if (rootFilter !== 'ALL' && row.scan_root_index !== rootFilter) return false;
      return true;
    });
  }, [rows, searchText, decisionFilter, rootFilter]);

  const columns: ColumnsType<DedupePreviewMemberRow> = [
    {
      title: '决策',
      dataIndex: 'member_decision',
      key: 'member_decision',
      width: 138,
      render: (value: string | MemberDecision, record) => {
        const cls = classifyMemberDecision(value, record.eligible_as_keep);
        return (
          <div className="nfc-inline-badges">
            <Tag color={cls.color}>{cls.label}</Tag>
            {record.recommended_keep && <Tag color="green">推荐保留</Tag>}
          </div>
        );
      },
    },
    {
      title: '文件路径',
      dataIndex: 'absolute_path',
      key: 'absolute_path',
      render: (value: string, record) => (
        <div className="nfc-dedupe-path-cell">
          <CodePath value={value} />
          <div className="nfc-table-meta">
            {formatOptionalGroupId(record.group_provenance_id)} · 单文件 {formatOptionalFileSize(record.group_file_size)}
            {record.relative_path ? ` · 相对 ${record.relative_path}` : ''}
          </div>
        </div>
      ),
    },
    {
      title: '扫描根目录',
      key: 'scan_root',
      width: 210,
      render: (_, record) => {
        const label = formatScanRootLabel(record.scan_root_index, record.scan_root_path);
        return (
          <Tooltip title={label}>
            <span className="nfc-kind-badge nfc-dedupe-root-badge">{label}</span>
          </Tooltip>
        );
      },
    },
    {
      title: '评分',
      dataIndex: 'total_score',
      key: 'total_score',
      width: 94,
      align: 'right',
      render: (score?: number) => <span className="nfc-mono">{score !== undefined ? score.toLocaleString() : '—'}</span>,
    },
    {
      title: '保留资格',
      dataIndex: 'eligible_as_keep',
      key: 'eligible_as_keep',
      width: 118,
      align: 'center',
      render: (_, record) => {
        const pres = getEligibilityPresentation(record.eligible_as_keep);
        if (pres.status === 'eligible') {
          return <Tag icon={<CheckCircleOutlined />} color="success">{pres.text}</Tag>;
        }
        if (pres.status === 'safety_excluded') {
          return (
            <Tooltip title={record.safety_reasons?.join('; ') || '不满足安全保护策略'}>
              <Tag icon={<CloseCircleOutlined />} color="warning">{pres.text}</Tag>
            </Tooltip>
          );
        }
        return <Tag>{pres.text}</Tag>;
      },
    },
    {
      title: '决策原因',
      dataIndex: 'selection_reason',
      key: 'selection_reason',
      width: 190,
      ellipsis: true,
      render: (reason: string | null, record) => {
        const text = reason || record.group_selection_reason || '—';
        return <Tooltip title={text}><span className="nfc-table-meta">{text}</span></Tooltip>;
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 86,
      align: 'center',
      render: (_, record) => (
        <Button
          type="text"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => onSelectMember?.(record)}
        >
          详情
        </Button>
      ),
    },
  ];

  const filters = (
    <ActionBar className="nfc-filter-bar nfc-dedupe-preview-filters">
      <Input
        prefix={<SearchOutlined />}
        placeholder="按绝对路径或相对路径过滤..."
        value={searchText}
        onChange={(e) => setSearchText(e.target.value)}
        allowClear
      />
      <Select
        value={decisionFilter}
        onChange={setDecisionFilter}
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
          options={[
            { label: '全部扫描根', value: 'ALL' },
            ...scanRoots.map((root, idx) => ({
              label: formatScanRootLabel(idx, root),
              value: idx,
            })),
          ]}
        />
      )}
      <span className="nfc-panel-count">{filteredRows.length} members</span>
    </ActionBar>
  );

  const mobilePagination = pagination ? (
    <div className="nfc-mobile-pagination">
      <Pagination
        current={pagination.current}
        pageSize={pagination.pageSize}
        total={pagination.total}
        showSizeChanger
        onChange={pagination.onChange}
      />
    </div>
  ) : null;

  return (
    <div className="nfc-dedupe-preview-table">
      {filters}
      <ResponsiveDataView
        desktop={
          <Table<DedupePreviewMemberRow>
            rowKey={(row) => `${row.group_provenance_id ?? 'ungrouped'}_${row.absolute_path}`}
            columns={columns}
            dataSource={filteredRows}
            loading={loading}
            size="small"
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
        }
        mobile={
          <>
            <div className="nfc-mobile-record-list">
              {filteredRows.map((row) => {
                const decision = classifyMemberDecision(row.member_decision, row.eligible_as_keep);
                const eligibility = getEligibilityPresentation(row.eligible_as_keep);
                return (
                  <article className="nfc-dedupe-member-mobile-card" key={`${row.group_provenance_id ?? 'ungrouped'}_${row.absolute_path}`}>
                    <div className="nfc-mobile-record-heading">
                      <div>
                        <span className={`nfc-operation-badge nfc-decision-${decision.kind.toLowerCase().replace(/_/g, '-')}`}>
                          {decision.label}
                        </span>
                        {row.recommended_keep && <span className="nfc-kind-badge">recommended</span>}
                      </div>
                      <span className="nfc-mono nfc-dedupe-score">{row.total_score ?? '—'}</span>
                    </div>

                    <div className="nfc-dedupe-mobile-path">
                      <CodePath value={row.absolute_path} />
                    </div>

                    <div className="nfc-mobile-record-facts">
                      <span>组 <b>{formatOptionalGroupId(row.group_provenance_id)}</b></span>
                      <span>单文件 <b>{formatOptionalFileSize(row.group_file_size)}</b></span>
                      <span>保留资格 <b>{eligibility.text}</b></span>
                      <span>扫描根 <b>{formatScanRootLabel(row.scan_root_index, row.scan_root_path)}</b></span>
                    </div>

                    <div className="nfc-mobile-record-actions">
                      <Button type="text" icon={<EyeOutlined />} onClick={() => onSelectMember?.(row)}>
                        解释决策
                      </Button>
                    </div>
                  </article>
                );
              })}
            </div>
            {mobilePagination}
          </>
        }
      />
    </div>
  );
};
