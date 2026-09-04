import React, { useState, useEffect } from 'react';
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
  InputNumber,
  Modal,
  Tooltip,
} from 'antd';
import {
  ReloadOutlined,
  DesktopOutlined,
  MobileOutlined,
  ExclamationCircleOutlined,
  SaveOutlined,
  DeleteOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { settingsApi, dataLifecycleApi, auditApi } from '../../api/domain';
import { authApi } from '../../api/auth';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { SessionInfo } from '../../types';
import {
  formatAuditRetention,
  getAuditRetentionApplyAvailability,
  validateRetentionDaysInput,
} from '../../components/settings/data_lifecycle';

const { Title, Text } = Typography;

export const SettingsPage: React.FC = () => {
  useTitle('系统设置');
  const queryClient = useQueryClient();
  const [retentionDaysInput, setRetentionDaysInput] = useState<number | null>(0);

  const { data: settings, refetch: refetchSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.getSettings(),
  });

  const { data: lifecyclePolicy, refetch: refetchPolicy } = useQuery({
    queryKey: ['dataLifecyclePolicy'],
    queryFn: () => dataLifecycleApi.getPolicy(),
  });

  const { data: retentionPreview, isLoading: previewLoading, refetch: refetchPreview } = useQuery({
    queryKey: ['auditRetentionPreview'],
    queryFn: () => auditApi.getRetentionPreview(),
  });

  useEffect(() => {
    if (lifecyclePolicy) {
      setRetentionDaysInput(lifecyclePolicy.audit_retention_days);
    }
  }, [lifecyclePolicy]);

  const savePolicyMutation = useMutation({
    mutationFn: (days: number) => dataLifecycleApi.updatePolicy(days),
    onSuccess: () => {
      message.success('数据生命周期保留策略已更新');
      queryClient.invalidateQueries({ queryKey: ['dataLifecyclePolicy'] });
      queryClient.invalidateQueries({ queryKey: ['auditRetentionPreview'] });
    },
    onError: (err: any) => {
      message.error(err.message || '更新保留策略失败');
    },
  });

  const applyRetentionMutation = useMutation({
    mutationFn: () => auditApi.applyRetention(),
    onSuccess: (res) => {
      message.success(`审计日志保留清理执行成功，已清理 ${res.deleted_count} 条记录，剩余 ${res.remaining_count} 条`);
      queryClient.invalidateQueries({ queryKey: ['auditRetentionPreview'] });
      queryClient.invalidateQueries({ queryKey: ['dataLifecyclePolicy'] });
      queryClient.invalidateQueries({ queryKey: ['auditEvents'] });
    },
    onError: (err: any) => {
      message.error(err.message || '执行保留清理失败');
    },
  });

  const handleSavePolicy = () => {
    const valResult = validateRetentionDaysInput(retentionDaysInput);
    if (!valResult.valid) {
      message.error(valResult.error || '保留天数无效');
      return;
    }
    savePolicyMutation.mutate(retentionDaysInput!);
  };

  const availability = getAuditRetentionApplyAvailability(lifecyclePolicy, retentionPreview);

  const handleConfirmApplyRetention = () => {
    if (!availability.canApply) {
      message.warning(availability.disabledReason || '当前策略不可执行清理');
      return;
    }

    Modal.confirm({
      title: '确认执行审计日志保留清理？',
      icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
      content: (
        <div>
          <p>
            将按照系统已保存的策略（<strong>{formatAuditRetention(lifecyclePolicy?.audit_retention_days)}</strong>），
            永久清理截止时间（<strong>{retentionPreview?.cutoff ? formatDateTime(retentionPreview.cutoff) : '计算中'}</strong>）之前的全部审计日志。
          </p>
          <p>
            拟删除记录数：<strong style={{ color: '#ff4d4f' }}>{retentionPreview?.delete_count ?? 0}</strong> 条。
          </p>
          <p style={{ color: '#ff4d4f' }}>此操作不可逆！清理操作执行后，系统将自动生成 1 条 audit.retention 自审计记录。</p>
        </div>
      ),
      okText: '确认执行清理',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => applyRetentionMutation.mutateAsync(),
    });
  };

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
        <Button
          icon={<ReloadOutlined />}
          onClick={() => {
            refetchSettings();
            refetchSessions();
            refetchPolicy();
            refetchPreview();
          }}
        >
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

      {/* Data Lifecycle & Audit Retention Card */}
      <Card
        title="数据生命周期与审计保留策略"
        bordered={false}
        style={{ borderRadius: 12, marginBottom: 20 }}
        extra={
          <Space>
            {lifecyclePolicy && (
              <Tag color={lifecyclePolicy.audit_retention_days === 0 ? 'default' : 'blue'}>
                当前策略: {formatAuditRetention(lifecyclePolicy.audit_retention_days)}
              </Tag>
            )}
          </Space>
        }
      >
        <Alert
          message="数据生命周期与保留安全原则"
          description={
            <div>
              <div>1. <strong>保存策略 ≠ 执行删除</strong>：保存保留策略仅将参数持久化至数据库，不会触发任何历史数据删除。</div>
              <div>2. <strong>0 天 = 永久保留</strong>：保留天数设置为 0 时表示永久保留全部审计日志，系统将禁止任何自动或手动清理。</div>
              <div>3. <strong>预览 ≠ 执行</strong>：清理预览仅根据已保存策略计算拟清理范围，点击“执行审计清理”并在弹窗确认后才会安全执行。</div>
            </div>
          }
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
        />

        <div style={{ background: '#fafafa', padding: '16px 20px', borderRadius: 8, marginBottom: 20, border: '1px solid #f0f0f0' }}>
          <div style={{ marginBottom: 12, fontWeight: 500 }}>审计日志保留策略配置</div>
          <Space wrap align="center" style={{ marginBottom: 12 }}>
            <Text>保留天数：</Text>
            <InputNumber
              min={0}
              max={3650}
              precision={0}
              step={1}
              value={retentionDaysInput}
              onChange={(val) => setRetentionDaysInput(val)}
              style={{ width: 140 }}
              addonAfter="天"
            />
            <Space wrap>
              <Button size="small" onClick={() => setRetentionDaysInput(0)}>永久保留 (0)</Button>
              <Button size="small" onClick={() => setRetentionDaysInput(30)}>30 天</Button>
              <Button size="small" onClick={() => setRetentionDaysInput(90)}>90 天</Button>
              <Button size="small" onClick={() => setRetentionDaysInput(180)}>180 天</Button>
              <Button size="small" onClick={() => setRetentionDaysInput(365)}>365 天</Button>
            </Space>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={savePolicyMutation.isPending}
              onClick={handleSavePolicy}
            >
              保存策略
            </Button>
          </Space>
          <div>
            <Text type="secondary" style={{ fontSize: 13 }}>
              {retentionDaysInput === 0
                ? '提示：设置为 0 表示永久保留全部审计日志，系统绝不主动或被动清理历史记录。'
                : `提示：保存后将以 ${retentionDaysInput} 天为周期计算过期日志（严格保留 ${retentionDaysInput} 天内及截止点时刻的记录）。`}
              {lifecyclePolicy?.updated_at && (
                <span style={{ marginLeft: 12 }}>
                  (上次保存于: {formatDateTime(lifecyclePolicy.updated_at)})
                </span>
              )}
            </Text>
          </div>
        </div>

        <div style={{ background: '#fafafa', padding: '16px 20px', borderRadius: 8, border: '1px solid #f0f0f0' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <div style={{ fontWeight: 500 }}>审计日志保留清理预览</div>
            <Space>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                loading={previewLoading}
                onClick={() => refetchPreview()}
              >
                刷新预览
              </Button>
              <Tooltip title={!availability.canApply ? availability.disabledReason : undefined}>
                <Button
                  danger
                  type="primary"
                  icon={<DeleteOutlined />}
                  disabled={!availability.canApply}
                  loading={applyRetentionMutation.isPending}
                  onClick={handleConfirmApplyRetention}
                >
                  执行审计清理
                </Button>
              </Tooltip>
            </Space>
          </div>

          <Descriptions bordered size="small" column={{ xs: 1, sm: 2, md: 3 }}>
            <Descriptions.Item label="当前生效保留期">
              {formatAuditRetention(retentionPreview?.retention_days ?? lifecyclePolicy?.audit_retention_days)}
            </Descriptions.Item>
            <Descriptions.Item label="审计日志总数">
              <Text strong>{retentionPreview?.total_count ?? 0}</Text> 条
            </Descriptions.Item>
            <Descriptions.Item label="清理截止时间点">
              {retentionPreview?.cutoff ? (
                <Text code>{formatDateTime(retentionPreview.cutoff)}</Text>
              ) : (
                <Tag>无（永久保留）</Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="拟删除记录数">
              <Text type={retentionPreview?.delete_count ? 'danger' : 'secondary'} strong>
                {retentionPreview?.delete_count ?? 0}
              </Text>{' '}
              条
            </Descriptions.Item>
            <Descriptions.Item label="拟保留记录数">
              <Text type="success" strong>
                {retentionPreview?.keep_count ?? retentionPreview?.total_count ?? 0}
              </Text>{' '}
              条
            </Descriptions.Item>
            <Descriptions.Item label="最早记录时间">
              {retentionPreview?.oldest_timestamp ? formatDateTime(retentionPreview.oldest_timestamp) : '-'}
            </Descriptions.Item>
          </Descriptions>
        </div>
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
