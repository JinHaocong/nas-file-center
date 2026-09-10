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
  Select,
  Modal,
  Tooltip,
  Switch,
  Input,
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
import { settingsApi, dataLifecycleApi, auditApi, quarantineApi, resourcePolicyApi } from '../../api/domain';
import { authApi } from '../../api/auth';
import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import { SessionInfo, ResourcePolicyUpdate } from '../../types';
import {
  formatAuditRetention,
  getAuditRetentionApplyAvailability,
  getAuditRetentionSaveAvailability,
  getQuarantineRetentionSaveAvailability,
  validateRetentionDaysInput,
} from '../../components/settings/data_lifecycle';
import {
  COMMON_TIMEZONES,
  validateResourcePolicyUpdate,
  getProfileDisplay,
} from '../../components/settings/resource_policy';

const { Title, Text } = Typography;

export const SettingsPage: React.FC = () => {
  useTitle('系统设置');
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [retentionDaysInput, setRetentionDaysInput] = useState<number | null>(0);
  const [prepareApplyPending, setPrepareApplyPending] = useState(false);

  const { data: settings, refetch: refetchSettings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => settingsApi.getSettings(),
  });

  const { data: lifecyclePolicy, isError: policyQueryError, refetch: refetchPolicy } = useQuery({
    queryKey: ['dataLifecyclePolicy'],
    queryFn: () => dataLifecycleApi.getPolicy(),
  });

  const { data: retentionPreview, isLoading: previewLoading, isError: previewQueryError, refetch: refetchPreview } = useQuery({
    queryKey: ['auditRetentionPreview'],
    queryFn: () => auditApi.getRetentionPreview(),
  });

  const [quarantineDaysInput, setQuarantineDaysInput] = useState<number>(0);

  const { data: quarantinePolicy, refetch: refetchQuarantinePolicy } = useQuery({
    queryKey: ['quarantineRetentionPolicy'],
    queryFn: () => quarantineApi.getRetentionPolicy(),
  });

  const { data: resourcePolicy, isLoading: policyLoading, refetch: refetchResourcePolicy } = useQuery({
    queryKey: ['resourcePolicy'],
    queryFn: () => resourcePolicyApi.getPolicy(),
    enabled: !!isAdmin,
  });

  const [scanThreadsInput, setScanThreadsInput] = useState<number>(2);
  const [hashThreadsInput, setHashThreadsInput] = useState<number>(2);
  const [ioLimitInput, setIoLimitInput] = useState<'low' | 'normal' | 'unlimited'>('normal');
  const [jobPriorityInput, setJobPriorityInput] = useState<'normal' | 'background'>('normal');
  const [windowEnabledInput, setWindowEnabledInput] = useState<boolean>(false);
  const [windowStartInput, setWindowStartInput] = useState<string>('01:00');
  const [windowEndInput, setWindowEndInput] = useState<string>('07:00');
  const [windowTimezoneInput, setWindowTimezoneInput] = useState<string>('UTC');
  const [outsideModeInput, setOutsideModeInput] = useState<'limited' | 'pause'>('limited');

  useEffect(() => {
    if (resourcePolicy) {
      setScanThreadsInput(resourcePolicy.scan_threads);
      setHashThreadsInput(resourcePolicy.hash_threads);
      setIoLimitInput(resourcePolicy.io_limit);
      setJobPriorityInput(resourcePolicy.job_priority);
      setWindowEnabledInput(resourcePolicy.active_window_enabled);
      setWindowStartInput(resourcePolicy.active_window_start || '01:00');
      setWindowEndInput(resourcePolicy.active_window_end || '07:00');
      setWindowTimezoneInput(resourcePolicy.active_window_timezone || 'UTC');
      setOutsideModeInput(resourcePolicy.outside_window_mode);
    }
  }, [resourcePolicy]);

  const saveResourcePolicyMutation = useMutation({
    mutationFn: (payload: ResourcePolicyUpdate) => {
      if (!isAdmin) {
        throw new Error('仅系统管理员允许修改资源控制策略');
      }
      return resourcePolicyApi.updatePolicy(payload);
    },
    onSuccess: () => {
      message.success('资源控制策略已更新');
      queryClient.invalidateQueries({ queryKey: ['resourcePolicy'] });
    },
    onError: (err: any) => {
      message.error(err.message || '更新资源控制策略失败');
    },
  });

  const handleSaveResourcePolicy = () => {
    if (!isAdmin) {
      message.error('仅系统管理员允许修改资源控制策略');
      return;
    }
    const payload: ResourcePolicyUpdate = {
      scan_threads: scanThreadsInput,
      hash_threads: hashThreadsInput,
      io_limit: ioLimitInput,
      job_priority: jobPriorityInput,
      active_window_enabled: windowEnabledInput,
      active_window_start: windowEnabledInput ? windowStartInput : null,
      active_window_end: windowEnabledInput ? windowEndInput : null,
      active_window_timezone: windowEnabledInput ? windowTimezoneInput : null,
      outside_window_mode: outsideModeInput,
    };
    const valResult = validateResourcePolicyUpdate(payload);
    if (!valResult.valid) {
      message.error(valResult.error || '资源策略校验失败');
      return;
    }
    saveResourcePolicyMutation.mutate(payload);
  };

  useEffect(() => {
    if (lifecyclePolicy) {
      setRetentionDaysInput(lifecyclePolicy.audit_retention_days);
    }
  }, [lifecyclePolicy]);

  useEffect(() => {
    if (quarantinePolicy) {
      setQuarantineDaysInput(quarantinePolicy.quarantine_retention_days);
    }
  }, [quarantinePolicy]);

  const saveQuarantinePolicyMutation = useMutation({
    mutationFn: (days: number) => {
      if (!isAdmin) {
        throw new Error('仅系统管理员允许修改隔离区保留策略');
      }
      if (![0, 7, 30, 90].includes(days)) {
        throw new Error('隔离区保留天数仅支持 0、7、30 或 90 天');
      }
      return quarantineApi.updateRetentionPolicy(days);
    },
    onSuccess: () => {
      message.success('隔离区保留策略已更新');
      queryClient.invalidateQueries({ queryKey: ['quarantineRetentionPolicy'] });
      queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
    },
    onError: (err: any) => {
      message.error(err.message || '更新隔离区保留策略失败');
    },
  });

  const savePolicyMutation = useMutation({
    mutationFn: (days: number) => {
      if (!isAdmin) {
        throw new Error('仅系统管理员允许修改审计保留策略');
      }
      return dataLifecycleApi.updatePolicy(days);
    },
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
    mutationFn: () => {
      if (!isAdmin) {
        throw new Error('仅系统管理员允许执行审计日志清理');
      }
      return auditApi.applyRetention();
    },
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
    if (!isAdmin) {
      message.error('仅系统管理员允许修改审计保留策略');
      return;
    }
    const valResult = validateRetentionDaysInput(retentionDaysInput);
    if (!valResult.valid) {
      message.error(valResult.error || '保留天数无效');
      return;
    }
    savePolicyMutation.mutate(retentionDaysInput!);
  };

  const auditSaveAvail = getAuditRetentionSaveAvailability(isAdmin, savePolicyMutation.isPending);
  const quarantineSaveAvail = getQuarantineRetentionSaveAvailability(isAdmin, saveQuarantinePolicyMutation.isPending);

  const availability = getAuditRetentionApplyAvailability(
    lifecyclePolicy,
    retentionPreview,
    {
      isSavingPolicy: savePolicyMutation.isPending,
      isPreparingApply: prepareApplyPending,
      isApplying: applyRetentionMutation.isPending,
      isQueryError: policyQueryError || previewQueryError,
      isAdmin,
    }
  );

  const showApplyConfirmation = (
    freshPolicy: { audit_retention_days: number },
    freshPreview: { delete_count: number; cutoff?: string | null }
  ) => {
    Modal.confirm({
      title: '确认执行审计日志保留清理？',
      icon: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
      content: (
        <div>
          <p>
            当前已保存策略：<strong>{formatAuditRetention(freshPolicy.audit_retention_days)}</strong>
          </p>
          <p>
            当前最新预览：预计清理 <strong style={{ color: '#ff4d4f' }}>{freshPreview.delete_count}</strong> 条 Audit 历史记录。
          </p>
          <p style={{ color: '#d48806', fontSize: 13 }}>
            提示：当前预览仅为预计结果。实际执行时将根据数据库中最新保存的保留策略以及执行时最新的审计数据重新计算，最终删除数量可能与当前预览不同。
          </p>
          <p style={{ fontSize: 13, color: '#595959' }}>
            安全边界：本操作仅清理符合保留期条件的 Audit 历史记录。不会删除 NAS 上的真实文件或目录，也不会删除 Task、Scan、Plan 或 Index 数据。
          </p>
          <p style={{ color: '#ff4d4f', fontWeight: 500, fontSize: 13 }}>
            审计历史清理不可撤销。
          </p>
        </div>
      ),
      okText: '确认执行清理',
      okType: 'danger',
      cancelText: '取消',
      onOk: () => applyRetentionMutation.mutateAsync(),
    });
  };

  const handlePrepareApply = async () => {
    if (!isAdmin) {
      message.error('仅系统管理员允许执行审计日志清理');
      return;
    }
    if (prepareApplyPending || applyRetentionMutation.isPending || savePolicyMutation.isPending) {
      return;
    }

    setPrepareApplyPending(true);

    try {
      const [policyResult, previewResult] = await Promise.all([
        refetchPolicy(),
        refetchPreview(),
      ]);

      const freshPolicy = policyResult.data;
      const freshPreview = previewResult.data;

      if (policyResult.isError || previewResult.isError || !freshPolicy || !freshPreview) {
        message.error('无法获取最新保留策略或清理预览，请稍后重试');
        return;
      }

      if (freshPolicy.audit_retention_days === 0) {
        message.info('当前策略为永久保留（0 天），没有可执行的保留期清理');
        return;
      }

      showApplyConfirmation(freshPolicy, freshPreview);
    } catch (err: any) {
      message.error(err.message || '无法获取最新保留策略或清理预览，请重试');
    } finally {
      setPrepareApplyPending(false);
    }
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
            refetchQuarantinePolicy();
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
                审计策略: {formatAuditRetention(lifecyclePolicy.audit_retention_days)}
              </Tag>
            )}
            {quarantinePolicy && (
              <Tag color={quarantinePolicy.quarantine_retention_days === 0 ? 'default' : 'orange'}>
                隔离区保留: {quarantinePolicy.quarantine_retention_days === 0 ? '永久保留' : `${quarantinePolicy.quarantine_retention_days} 天`}
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
            <Tooltip title={!auditSaveAvail.canSave ? auditSaveAvail.disabledReason : undefined}>
              <span>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  disabled={!auditSaveAvail.canSave}
                  loading={savePolicyMutation.isPending}
                  onClick={handleSavePolicy}
                >
                  保存策略
                </Button>
              </span>
            </Tooltip>
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

        {/* Quarantine Retention Policy Configuration */}
        <div style={{ background: '#fafafa', padding: '16px 20px', borderRadius: 8, marginBottom: 20, border: '1px solid #f0f0f0' }}>
          <div style={{ marginBottom: 12, fontWeight: 500 }}>文件隔离区保留策略配置 (Quarantine Retention)</div>
          <Space wrap align="center" style={{ marginBottom: 12 }}>
            <Text>保留周期：</Text>
            <Select
              value={quarantineDaysInput}
              onChange={(val) => setQuarantineDaysInput(val)}
              style={{ width: 180 }}
              options={[
                { label: '永久保留 (0 天)', value: 0 },
                { label: '保留 7 天 (7 days)', value: 7 },
                { label: '保留 30 天 (30 days)', value: 30 },
                { label: '保留 90 天 (90 days)', value: 90 },
              ]}
            />
            <Tooltip title={!quarantineSaveAvail.canSave ? quarantineSaveAvail.disabledReason : undefined}>
              <span>
                <Button
                  type="primary"
                  icon={<SaveOutlined />}
                  disabled={!quarantineSaveAvail.canSave}
                  loading={saveQuarantinePolicyMutation.isPending}
                  onClick={() => saveQuarantinePolicyMutation.mutate(quarantineDaysInput)}
                >
                  保存隔离区策略
                </Button>
              </span>
            </Tooltip>
          </Space>
          <div>
            <Text type="secondary" style={{ fontSize: 13 }}>
              {quarantineDaysInput === 0
                ? '提示：设置为 0 表示永久保留全部隔离文件，系统绝不标记过期时间。'
                : `提示：保存后新进入隔离区的文件将自动记录 ${quarantineDaysInput} 天后过期。`}
              {quarantinePolicy?.updated_at && (
                <span style={{ marginLeft: 12 }}>
                  (上次保存于: {formatDateTime(quarantinePolicy.updated_at)})
                </span>
              )}
            </Text>
            <div style={{ marginTop: 6, fontSize: 12, color: '#8c8c8c' }}>
              安全约束：保存策略仅记录元数据与到期时间戳，系统绝不启动后台静默自动删除线程。如需清理过期隔离文件，必须由管理员在文件隔离区页面人工审阅并确认清除。
            </div>
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
                <span>
                  <Button
                    danger
                    type="primary"
                    icon={<DeleteOutlined />}
                    disabled={!availability.canApply}
                    loading={applyRetentionMutation.isPending || prepareApplyPending}
                    onClick={handlePrepareApply}
                  >
                    执行审计清理
                  </Button>
                </span>
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

      {/* Resource Control */}
      {isAdmin && (
        <Card
          title="资源控制 / Resource Control"
          bordered={false}
          style={{ borderRadius: 12 }}
          extra={
            <Space>
              <Button
                icon={<ReloadOutlined />}
                loading={policyLoading}
                onClick={() => refetchResourcePolicy()}
              >
                刷新
              </Button>
              <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={saveResourcePolicyMutation.isPending}
                onClick={handleSaveResourcePolicy}
              >
                保存资源策略
              </Button>
            </Space>
          }
        >
          <div style={{ marginBottom: 20 }}>
            <Alert
              type="info"
              showIcon
              message="资源控制说明与约束提示"
              description={
                <div style={{ fontSize: 13, lineHeight: '20px' }}>
                  <div>• <strong>应用层并发控制：</strong>I/O 压力与线程限制为应用层并发节流控制，并非保证性的 MB/s 或 IOPS 硬件限速。</div>
                  <div>• <strong>无后台自动调度：</strong>窗口外暂停模式（Pause）不包含后台定时调度创建机制，仅在窗口外阻止排队的扫描/索引任务被 Worker 认领。</div>
                  <div>• <strong>安全降级：</strong>文件组织器、批量删除及隔离还原等变动任务不受资源策略限制，始终保证优先处理。</div>
                </div>
              }
              style={{ marginBottom: 20 }}
            />

            {resourcePolicy && (
              <div style={{ background: '#fafafa', padding: '16px 20px', borderRadius: 8, border: '1px solid #f0f0f0', marginBottom: 20 }}>
                <div style={{ fontWeight: 500, marginBottom: 12 }}>当前生效状态 (Effective Now)</div>
                <Descriptions bordered size="small" column={{ xs: 1, sm: 2, md: 4 }}>
                  <Descriptions.Item label="当前配置版本 (Revision)">
                    <Text strong>rev.{resourcePolicy.revision}</Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="当前生效模式 (Profile)">
                    {(() => {
                      const disp = getProfileDisplay(resourcePolicy.effective_now.profile);
                      return <Tag color={disp.color}>{disp.text}</Tag>;
                    })()}
                  </Descriptions.Item>
                  <Descriptions.Item label="有效并发线程上限">
                    <Text strong>{resourcePolicy.effective_now.effective_thread_cap}</Text> 线程
                  </Descriptions.Item>
                  <Descriptions.Item label="资源任务认领许可">
                    {resourcePolicy.effective_now.resource_jobs_admitted ? (
                      <Tag color="success">允许认领</Tag>
                    ) : (
                      <Tag color="error">队列保持 (Held)</Tag>
                    )}
                  </Descriptions.Item>
                </Descriptions>
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px' }}>
              <div>
                <Text strong style={{ display: 'block', marginBottom: 6 }}>扫描线程上限 (1..32):</Text>
                <InputNumber
                  min={1}
                  max={32}
                  value={scanThreadsInput}
                  onChange={(v) => setScanThreadsInput(v || 1)}
                  style={{ width: '100%' }}
                />
              </div>

              <div>
                <Text strong style={{ display: 'block', marginBottom: 6 }}>哈希线程上限 (1..32):</Text>
                <InputNumber
                  min={1}
                  max={32}
                  value={hashThreadsInput}
                  onChange={(v) => setHashThreadsInput(v || 1)}
                  style={{ width: '100%' }}
                />
              </div>

              <div>
                <Text strong style={{ display: 'block', marginBottom: 6 }}>I/O 压力模式 (IO Limit):</Text>
                <Select
                  value={ioLimitInput}
                  onChange={setIoLimitInput}
                  style={{ width: '100%' }}
                  options={[
                    { value: 'low', label: '低压模式 (Low - 上限 1 线程)' },
                    { value: 'normal', label: '标准模式 (Normal - 上限 2 线程)' },
                    { value: 'unlimited', label: '无上限模式 (Unlimited - 上限 32 线程)' },
                  ]}
                />
              </div>

              <div>
                <Text strong style={{ display: 'block', marginBottom: 6 }}>任务调度优先级 (Job Priority):</Text>
                <Select
                  value={jobPriorityInput}
                  onChange={setJobPriorityInput}
                  style={{ width: '100%' }}
                  options={[
                    { value: 'normal', label: '标准先进先出 (Normal FIFO)' },
                    { value: 'background', label: '后台让步 (Background - 优先变动任务)' },
                  ]}
                />
              </div>
            </div>

            <div style={{ marginTop: 24, padding: '16px 20px', borderRadius: 8, border: '1px solid #f0f0f0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                <div>
                  <div style={{ fontWeight: 500 }}>活跃时间窗口限制 (Active Window)</div>
                  <Text type="secondary" style={{ fontSize: 13 }}>
                    启用后，仅在指定时间窗口内全速执行；窗口外将自动降速或暂停扫描认领。
                  </Text>
                </div>
                <Switch
                  checked={windowEnabledInput}
                  onChange={setWindowEnabledInput}
                />
              </div>

              {windowEnabledInput && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '16px', marginTop: 12 }}>
                  <div>
                    <Text strong style={{ display: 'block', marginBottom: 6 }}>窗口起始时间 (HH:MM):</Text>
                    <Input
                      placeholder="01:00"
                      value={windowStartInput}
                      onChange={(e) => setWindowStartInput(e.target.value)}
                    />
                  </div>
                  <div>
                    <Text strong style={{ display: 'block', marginBottom: 6 }}>窗口结束时间 (HH:MM):</Text>
                    <Input
                      placeholder="07:00"
                      value={windowEndInput}
                      onChange={(e) => setWindowEndInput(e.target.value)}
                    />
                  </div>
                  <div>
                    <Text strong style={{ display: 'block', marginBottom: 6 }}>时区 (IANA Timezone):</Text>
                    <Select
                      showSearch
                      value={windowTimezoneInput}
                      onChange={setWindowTimezoneInput}
                      style={{ width: '100%' }}
                      options={COMMON_TIMEZONES.map((tz) => ({ value: tz, label: tz }))}
                    />
                  </div>
                  <div>
                    <Text strong style={{ display: 'block', marginBottom: 6 }}>窗口外行为模式 (Outside Mode):</Text>
                    <Select
                      value={outsideModeInput}
                      onChange={setOutsideModeInput}
                      style={{ width: '100%' }}
                      options={[
                        { value: 'limited', label: '降速运行 (Limited - 1 线程)' },
                        { value: 'pause', label: '暂停认领 (Pause - 队列等待)' },
                      ]}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        </Card>
      )}

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
