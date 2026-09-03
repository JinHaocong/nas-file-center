import React from 'react';
import {
  Card,
  Descriptions,
  Table,
  Tag,
  Button,
  Space,
  Typography,
  Alert,
  message,
  Popconfirm,
} from 'antd';
import {
  ReloadOutlined,
  DesktopOutlined,
  MobileOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation } from '@tanstack/react-query';
import { settingsApi } from '../../api/domain';
import { authApi } from '../../api/auth';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { SessionInfo } from '../../types';

const { Title, Text } = Typography;

export const SettingsPage: React.FC = () => {
  useTitle('系统设置');

  const { data: settings, refetch: refetchSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.getSettings(),
  });

  const { data: sessionsData, isLoading: sessionsLoading, refetch: refetchSessions } = useQuery({
    queryKey: ['activeSessions'],
    queryFn: () => authApi.listSessions(),
  });

  const revokeMutation = useMutation({
    mutationFn: (sessionId: number) => authApi.revokeSession(sessionId),
    onSuccess: () => {
      message.success('已成功注销该设备会话');
      refetchSessions();
    },
    onError: (err: any) => {
      message.error(err.message || '注销会话失败');
    },
  });

  const sessionColumns = [
    {
      title: '登录设备 / User Agent',
      dataIndex: 'user_agent',
      key: 'user_agent',
      render: (ua: string, record: SessionInfo) => (
        <Space>
          {ua.toLowerCase().includes('mobile') ? <MobileOutlined /> : <DesktopOutlined />}
          <div>
            <Text style={{ fontSize: 13 }}>{ua}</Text>
            {record.is_current && (
              <Tag color="green" style={{ marginLeft: 8 }}>
                当前设备
              </Tag>
            )}
          </div>
        </Space>
      ),
    },
    {
      title: 'IP 地址',
      dataIndex: 'ip_address',
      key: 'ip_address',
      width: 140,
      render: (ip: string) => <Text code>{ip}</Text>,
    },
    {
      title: '首次登录时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (val: string) => formatDateTime(val),
    },
    {
      title: '最近活动时间',
      dataIndex: 'last_seen_at',
      key: 'last_seen_at',
      width: 180,
      render: (val: string) => formatDateTime(val),
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: any, record: SessionInfo) =>
        record.is_current ? (
          <Text type="secondary">当前会话</Text>
        ) : (
          <Popconfirm
            title="确认强制注销该设备？"
            onConfirm={() => revokeMutation.mutate(record.id)}
            okText="注销"
            cancelText="取消"
          >
            <Button size="small" danger type="link" loading={revokeMutation.isPending}>
              强制下线
            </Button>
          </Popconfirm>
        ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <Title level={4} style={{ margin: 0 }}>
            系统设置与安全中心
          </Title>
          <Text type="secondary">查看安全模式策略及管理当前管理员活动会话</Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => { refetchSettings(); refetchSessions(); }}>
          刷新
        </Button>
      </div>

      {/* Safety Policy Display */}
      <Card title="全局文件安全运行参数" bordered={false} style={{ borderRadius: 12, marginBottom: 20 }}>
        <Alert
          message="安全机制提示"
          description="为确保几十 TB 核心数据安全，危险开关（如 ALLOW_MUTATION、ALLOW_DELETE）只能通过宿主机 Docker Compose 环境变量配置，禁止在 Web 界面一键开启，防止误触导致数据丢失。"
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />

        <Descriptions bordered column={{ xs: 1, sm: 2 }}>
          <Descriptions.Item label="只读安全模式 (ALLOW_MUTATION)">
            {settings?.allow_mutation ? (
              <Tag color="warning">开启写入 (true)</Tag>
            ) : (
              <Tag color="success">只读保护 (false)</Tag>
            )}
          </Descriptions.Item>

          <Descriptions.Item label="永久删除开关 (ALLOW_DELETE)">
            {settings?.allow_delete ? (
              <Tag color="error">允许永久删除 (true)</Tag>
            ) : (
              <Tag color="success">禁用删除 (false - 仅隔离)</Tag>
            )}
          </Descriptions.Item>

          <Descriptions.Item label="最后副本保护 (PROTECT_LAST_FILE)">
            {settings?.protect_last_file ? (
              <Tag color="success">已启用 (保留至少一份)</Tag>
            ) : (
              <Tag color="error">未启用</Tag>
            )}
          </Descriptions.Item>

          <Descriptions.Item label="去重校验哈希">
            <Tag color="blue">{settings?.verification_hash?.toUpperCase() || 'SHA256'}</Tag>
          </Descriptions.Item>

          <Descriptions.Item label="隔离区根目录 (QUARANTINE_ROOT)" span={2}>
            <Text code copyable>{settings?.quarantine_root}</Text>
          </Descriptions.Item>

          <Descriptions.Item label="允许访问路径白名单 (ALLOWED_ROOTS)" span={2}>
            <Space wrap>
              {settings?.allowed_roots.map((root, idx) => (
                <Tag key={idx} color="cyan">{root}</Tag>
              ))}
            </Space>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* Active Sessions */}
      <Card title="管理员活动会话管理" bordered={false} style={{ borderRadius: 12 }}>
        <Table
          dataSource={sessionsData?.sessions || []}
          columns={sessionColumns}
          rowKey="id"
          loading={sessionsLoading}
          pagination={false}
        />
      </Card>
    </div>
  );
};
