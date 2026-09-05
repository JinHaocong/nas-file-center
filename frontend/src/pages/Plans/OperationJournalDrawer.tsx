import React, { useState } from 'react';
import {
  Drawer,
  Table,
  Tag,
  Typography,
  Space,
  Empty,
  Button,
  Descriptions,
} from 'antd';
import {
  HistoryOutlined,
  ReloadOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { plansApi } from '../../api/domain';
import { OperationJournalEntry } from '../../types';
import { formatBytes, formatDateTime } from '../../utils/format';

const { Text, Paragraph } = Typography;

interface Props {
  planId: number;
  open: boolean;
  onClose: () => void;
}

const OP_COLORS: Record<string, string> = {
  rename: 'cyan',
  move: 'purple',
  quarantine: 'orange',
  restore: 'green',
  touch: 'blue',
  delete: 'red',
};

export const OperationJournalDrawer: React.FC<Props> = ({ planId, open, onClose }) => {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['planOperationJournal', planId, page, pageSize],
    queryFn: () => plansApi.getOperationJournal(planId, page, pageSize),
    enabled: open && !!planId,
  });

  const columns = [
    {
      title: '序号',
      dataIndex: 'sequence',
      key: 'sequence',
      width: 70,
      render: (seq: number) => <Text strong>#{seq}</Text>,
    },
    {
      title: '操作类型',
      dataIndex: 'operation',
      key: 'operation',
      width: 100,
      render: (op: string) => <Tag color={OP_COLORS[op] || 'default'}>{op}</Tag>,
    },
    {
      title: '物理变更详情 (Before → After)',
      key: 'mutation_details',
      render: (_: any, record: OperationJournalEntry) => {
        const bPath = record.before?.path || record.before?.original_path || record.before?.quarantine_path || '-';
        const aPath = record.after?.path || record.after?.restored_path || record.after?.quarantine_path || '-';
        const bSize = record.before?.size != null ? formatBytes(record.before.size) : null;
        const aSize = record.after?.size != null ? formatBytes(record.after.size) : null;
        const bInode = record.metadata_before?.inode;
        const aInode = record.metadata_after?.inode;

        return (
          <Space direction="vertical" size={2} style={{ width: '100%' }}>
            <Space align="start" wrap>
              <Text code style={{ wordBreak: 'break-all' }}>
                {bPath}
              </Text>
              <ArrowRightOutlined style={{ color: '#1677ff', margin: '0 4px' }} />
              <Text code style={{ wordBreak: 'break-all', color: '#1677ff' }}>
                {aPath}
              </Text>
            </Space>

            <Space size="middle" wrap style={{ fontSize: 12, color: '#8c8c8c' }}>
              {(bSize || aSize) && (
                <span>
                  大小: {bSize || '-'} → {aSize || '-'}
                </span>
              )}
              {(bInode || aInode) && (
                <span>
                  inode: {bInode || '-'} → {aInode || '-'}
                </span>
              )}
            </Space>
          </Space>
        );
      },
    },
    {
      title: '执行时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 160,
      render: (val: string) => formatDateTime(val),
    },
  ];

  return (
    <Drawer
      title={
        <Space>
          <HistoryOutlined style={{ color: '#1677ff' }} />
          <span>计划 #{planId} 底层操作执行日志 (Operation Journal)</span>
        </Space>
      }
      placement="right"
      width={860}
      open={open}
      onClose={onClose}
      extra={
        <Button icon={<ReloadOutlined />} size="small" onClick={() => refetch()} loading={isLoading}>
          刷新日志
        </Button>
      }
    >
      <div style={{ marginBottom: 12 }}>
        <Paragraph type="secondary" style={{ margin: 0, fontSize: 13 }}>
          Operation Journal 记录 Worker 在真实文件系统执行的物理变更证据（包含变更前后的路径、大小、时间戳与 inode）。撤销计划（Undo Plan）即基于本日志逆向生成。
        </Paragraph>
      </div>

      <Table
        dataSource={data?.items || []}
        columns={columns}
        rowKey="id"
        loading={isLoading}
        size="middle"
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="当前计划暂无已完成的操作日志（计划执行中或完成后将自动记录每一项物理变更）"
            />
          ),
        }}
        expandable={{
          expandedRowRender: (record) => (
            <Descriptions bordered size="small" column={2} style={{ margin: 8 }}>
              <Descriptions.Item label="Before JSON" span={2}>
                <pre style={{ margin: 0, maxHeight: 120, overflow: 'auto', fontSize: 11 }}>
                  {JSON.stringify(record.before, null, 2)}
                </pre>
              </Descriptions.Item>
              <Descriptions.Item label="After JSON" span={2}>
                <pre style={{ margin: 0, maxHeight: 120, overflow: 'auto', fontSize: 11 }}>
                  {JSON.stringify(record.after, null, 2)}
                </pre>
              </Descriptions.Item>
              <Descriptions.Item label="Metadata Before Stat" span={1}>
                <pre style={{ margin: 0, maxHeight: 120, overflow: 'auto', fontSize: 11 }}>
                  {JSON.stringify(record.metadata_before, null, 2)}
                </pre>
              </Descriptions.Item>
              <Descriptions.Item label="Metadata After Stat" span={1}>
                <pre style={{ margin: 0, maxHeight: 120, overflow: 'auto', fontSize: 11 }}>
                  {JSON.stringify(record.metadata_after, null, 2)}
                </pre>
              </Descriptions.Item>
            </Descriptions>
          ),
        }}
        pagination={{
          current: page,
          pageSize,
          total: data?.total || 0,
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50'],
          onChange: (p, ps) => {
            setPage(p);
            setPageSize(ps);
          },
        }}
      />
    </Drawer>
  );
};
