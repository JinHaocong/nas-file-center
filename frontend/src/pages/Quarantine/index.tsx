import React, { useState } from 'react';
import {
  Table,
  Card,
  Input,
  Select,
  Tag,
  Button,
  Space,
  Typography,
  Tooltip,
  Alert,
} from 'antd';
import {
  ReloadOutlined,
  SearchOutlined,
  UndoOutlined,
  DeleteOutlined,
  LockOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { quarantineApi } from '../../api/quarantine';
import { settingsApi } from '../../api/domain';
import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import { QuarantineEntry, QuarantineState } from '../../types';
import { RestoreModal } from './RestoreModal';
import { PurgeConfirmModal } from './PurgeConfirmModal';

const { Title, Text } = Typography;

const STATE_CONFIG: Record<QuarantineState, { label: string; color: string }> = {
  preparing: { label: '准备中', color: 'default' },
  active: { label: '已隔离', color: 'orange' },
  restoring: { label: '恢复中', color: 'processing' },
  purging: { label: '清除中', color: 'processing' },
  restored: { label: '已恢复', color: 'success' },
  purged: { label: '已清除', color: 'default' },
  inconsistent: { label: '异常不一致', color: 'error' },
  abandoned: { label: '已废弃', color: 'error' },
  skipped: { label: '已跳过', color: 'warning' },
};

export const QuarantinePage: React.FC = () => {
  useTitle('文件隔离区');
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [stateFilter, setStateFilter] = useState<string>('all');
  const [searchInput, setSearchInput] = useState<string>('');
  const [activeSearch, setActiveSearch] = useState<string>('');

  const [restoreEntry, setRestoreEntry] = useState<QuarantineEntry | null>(null);
  const [restoreModalOpen, setRestoreModalOpen] = useState(false);

  const [purgeEntry, setPurgeEntry] = useState<QuarantineEntry | null>(null);
  const [purgeModalOpen, setPurgeModalOpen] = useState(false);

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.getSettings(),
  });

  const isSafeMode = !settings?.allow_mutation;
  const allowDelete = Boolean(settings?.allow_delete);

  const {
    data: quarantineData,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ['quarantineList', page, pageSize, stateFilter, activeSearch],
    queryFn: () =>
      quarantineApi.list({
        page,
        pageSize,
        state: stateFilter,
        query: activeSearch,
        search: activeSearch,
      }),
  });

  const handleSearch = () => {
    setActiveSearch(searchInput.trim());
    setPage(1);
  };

  const handleResetSearch = () => {
    setSearchInput('');
    setActiveSearch('');
    setPage(1);
  };

  const columns = [
    {
      title: '编号',
      dataIndex: 'id',
      key: 'id',
      width: 75,
      render: (id: number) => <Text strong>#{id}</Text>,
    },
    {
      title: '原始路径',
      dataIndex: 'original_path',
      key: 'original_path',
      render: (path: string) => (
        <Text code copyable style={{ wordBreak: 'break-all' }}>
          {path}
        </Text>
      ),
    },
    {
      title: '隔离区物理路径',
      dataIndex: 'quarantine_path',
      key: 'quarantine_path',
      render: (path: string) => (
        <Text code copyable style={{ wordBreak: 'break-all', color: '#8c8c8c' }}>
          {path}
        </Text>
      ),
    },
    {
      title: '文件大小',
      dataIndex: 'size',
      key: 'size',
      width: 110,
      render: (size: number) => (size > 0 ? formatBytes(size) : '-'),
    },
    {
      title: '状态',
      dataIndex: 'state',
      key: 'state',
      width: 110,
      render: (state: QuarantineState) => {
        const conf = STATE_CONFIG[state] || { label: state, color: 'default' };
        return <Tag color={conf.color}>{conf.label}</Tag>;
      },
    },
    {
      title: '隔离时间',
      dataIndex: 'quarantined_at',
      key: 'quarantined_at',
      width: 160,
      render: (val: string | null) => (val ? formatDateTime(val) : '-'),
    },
    {
      title: '过期时间',
      dataIndex: 'expires_at',
      key: 'expires_at',
      width: 160,
      render: (val: string | null) => (val ? formatDateTime(val) : <Text type="secondary">永久保留</Text>),
    },
    {
      title: '操作',
      key: 'action',
      width: 170,
      render: (_: any, record: QuarantineEntry) => {
        const canRestore = record.state === 'active';
        const canPurge = record.state === 'active';

        return (
          <Space size="small">
            {canRestore && (
              <Tooltip title={isSafeMode ? '只读保护模式 (ALLOW_MUTATION=false) 生效中，禁止恢复' : '恢复到原路径或指定路径'}>
                <Button
                  size="small"
                  type="primary"
                  ghost
                  icon={<UndoOutlined />}
                  disabled={isSafeMode}
                  onClick={() => {
                    setRestoreEntry(record);
                    setRestoreModalOpen(true);
                  }}
                >
                  恢复
                </Button>
              </Tooltip>
            )}

            {canPurge && (
              <Tooltip
                title={
                  !isAdmin
                    ? '仅系统管理员允许彻底清除'
                    : !allowDelete
                    ? '系统禁用永久删除 (ALLOW_DELETE=false)'
                    : '彻底从磁盘物理清除该文件'
                }
              >
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  disabled={!isAdmin || !allowDelete}
                  onClick={() => {
                    setPurgeEntry(record);
                    setPurgeModalOpen(true);
                  }}
                >
                  清除
                </Button>
              </Tooltip>
            )}

            {!canRestore && !canPurge && <Text type="secondary">-</Text>}
          </Space>
        );
      },
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            文件隔离区 (Quarantine)
          </Title>
          <Text type="secondary">
            安全隔离潜在重复或待处理文件。支持零覆盖恢复与管理员强确认物理清除。
          </Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => refetch()} loading={isLoading}>
          刷新
        </Button>
      </div>

      {isSafeMode && (
        <Alert
          message="只读安全保护模式生效中"
          description="系统当前以 ALLOW_MUTATION=false 运行。所有文件物理移动与写入已被锁定，恢复操作当前不可用。"
          type="info"
          showIcon
          icon={<LockOutlined />}
          style={{ marginBottom: 16 }}
        />
      )}

      <Card bordered={false} style={{ borderRadius: 12, marginBottom: 16 }}>
        <Space wrap style={{ width: '100%', justifyContent: 'space-between' }}>
          <Space wrap>
            <Input
              placeholder="搜索原始路径或隔离路径..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onPressEnter={handleSearch}
              style={{ width: 320 }}
              prefix={<SearchOutlined style={{ color: '#8c8c8c' }} />}
              allowClear
            />
            <Button type="primary" onClick={handleSearch}>
              搜索
            </Button>
            {activeSearch && <Button onClick={handleResetSearch}>重置</Button>}
          </Space>

          <Space wrap align="center">
            <Text>状态筛选：</Text>
            <Select
              value={stateFilter}
              onChange={(val) => {
                setStateFilter(val);
                setPage(1);
              }}
              style={{ width: 140 }}
              options={[
                { label: '全部状态', value: 'all' },
                { label: '已隔离 (active)', value: 'active' },
                { label: '已恢复 (restored)', value: 'restored' },
                { label: '已清除 (purged)', value: 'purged' },
                { label: '准备中 (preparing)', value: 'preparing' },
                { label: '异常 (inconsistent)', value: 'inconsistent' },
                { label: '已废弃 (abandoned)', value: 'abandoned' },
              ]}
            />
          </Space>
        </Space>
      </Card>

      <Card bordered={false} style={{ borderRadius: 12 }}>
        <Table
          dataSource={quarantineData?.items || []}
          columns={columns}
          rowKey="id"
          loading={isLoading}
          pagination={{
            current: page,
            pageSize,
            total: quarantineData?.total || 0,
            showSizeChanger: true,
            pageSizeOptions: ['10', '20', '50', '100'],
            onChange: (p, ps) => {
              setPage(p);
              setPageSize(ps);
            },
          }}
        />
      </Card>

      <RestoreModal
        entry={restoreEntry}
        open={restoreModalOpen}
        onClose={() => {
          setRestoreModalOpen(false);
          setRestoreEntry(null);
        }}
        onSuccess={() => refetch()}
        isSafeMode={isSafeMode}
      />

      <PurgeConfirmModal
        entry={purgeEntry}
        open={purgeModalOpen}
        onClose={() => {
          setPurgeModalOpen(false);
          setPurgeEntry(null);
        }}
        onSuccess={() => refetch()}
        isAdmin={isAdmin}
        allowDelete={allowDelete}
      />
    </div>
  );
};
