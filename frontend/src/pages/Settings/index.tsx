import React, { useState, useEffect } from 'react';
import {
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
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';

const { Text } = Typography;

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

  const clearAuditMutation = useMutation({
    mutationFn: () => {
      if (!isAdmin) {
        throw new Error('仅系统管理员允许立即清空审计历史');
      }
      return auditApi.clearHistory();
    },
    onSuccess: (res) => {
      message.success(`审计历史已清空，共删除 ${res.deleted_count} 条；系统保留 1 条本次清空操作审计记录`);
      queryClient.invalidateQueries({ queryKey: ['auditRetentionPreview'] });
      queryClient.invalidateQueries({ queryKey: ['auditEvents'] });
    },
    onError: (err: any) => {
      message.error(err.message || '立即清空审计历史失败');
    },
  });

  const handleClearAuditHistory = () => {
    if (!isAdmin) {
      message.error('仅系统管理员允许立即清空审计历史');
      return;
    }
    Modal.confirm({
      title: '立即清空全部审计历史？',
      icon: <ExclamationCircleOutlined />,
      content: '该操作不受当前保留天数限制，会立即删除现有 Audit 历史。系统会保留 1 条 audit.clear 自审计记录，用于证明本次清空动作发生过。',
      okText: '立即清空',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => clearAuditMutation.mutateAsync(),
    });
  };

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
      className: 'nfc-settings-confirm-modal',
      title: '确认执行审计日志保留清理？',
      icon: <ExclamationCircleOutlined className="nfc-danger-icon" />,
      content: (
        <div>
          <p>
            当前已保存策略：<strong>{formatAuditRetention(freshPolicy.audit_retention_days)}</strong>
          </p>
          <p>
            当前最新预览：预计清理 <strong className="nfc-danger-text">{freshPreview.delete_count}</strong> 条 Audit 历史记录。
          </p>
          <p className="nfc-warning-copy">
            提示：当前预览仅为预计结果。实际执行时将根据数据库中最新保存的保留策略以及执行时最新的审计数据重新计算，最终删除数量可能与当前预览不同。
          </p>
          <p className="nfc-muted-copy">
            安全边界：本操作仅清理符合保留期条件的 Audit 历史记录。不会删除 NAS 上的真实文件或目录，也不会删除 Task、Scan、Plan 或 Index 数据。
          </p>
          <p className="nfc-danger-copy">
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
            <Text className="nfc-session-user-agent">{ua}</Text>
            {record.is_current && (
              <Tag color="green" className="nfc-current-session-tag">
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
    <div className="nfc-operations-page nfc-settings-page nfc-system-controls-page">
      <PageHeader
        eyebrow="System controls"
        title="系统设置与安全中心"
        description="集中查看文件安全开关、数据保留、资源控制与管理员会话。危险文件开关仍只能通过宿主机环境变量配置。"
        actions={
          <ActionBar compact>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => {
                refetchSettings();
                refetchSessions();
                refetchPolicy();
                refetchPreview();
                refetchQuarantinePolicy();
                if (isAdmin) refetchResourcePolicy();
              }}
            >
              刷新全部
            </Button>
          </ActionBar>
        }
      />

      <div className="nfc-settings-grid">
        <DataPanel
          title="全局文件安全运行参数"
          description="这些开关来自服务端运行环境，Web UI 只读展示，防止误触扩大文件修改权限。"
          className="nfc-panel-flush nfc-settings-panel-runtime"
        >
          <div className="nfc-settings-panel-body">
            <Alert
              message="安全机制提示"
              description="为确保大容量核心数据安全，ALLOW_MUTATION、ALLOW_DELETE 等危险开关只能通过宿主机 Docker Compose 环境变量配置，禁止在 Web 界面一键开启。"
              type="info"
              showIcon
            />
          </div>
          <ResponsiveDescriptions
            items={[
              {
                label: '只读安全模式 (ALLOW_MUTATION)',
                value: settings?.allow_mutation ? <Tag color="warning">开启写入 (true)</Tag> : <Tag color="success">只读保护 (false)</Tag>,
              },
              {
                label: '永久删除开关 (ALLOW_DELETE)',
                value: settings?.allow_delete ? <Tag color="error">允许永久删除 (true)</Tag> : <Tag color="success">禁用删除 (false - 仅隔离)</Tag>,
              },
              {
                label: '最后副本保护 (PROTECT_LAST_FILE)',
                value: settings?.protect_last_file ? <Tag color="success">已启用</Tag> : <Tag color="error">未启用</Tag>,
              },
              {
                label: '去重校验哈希',
                value: <span className="nfc-kind-badge">{settings?.verification_hash?.toUpperCase() || 'SHA256'}</span>,
              },
              {
                label: '隔离区根目录 (QUARANTINE_ROOT)',
                value: <CodePath value={settings?.quarantine_root} />,
              },
              {
                label: '允许访问路径白名单 (ALLOWED_ROOTS)',
                value: (
                  <div className="nfc-settings-path-list">
                    {settings?.allowed_roots.map((root, idx) => <CodePath value={root} key={idx} />)}
                  </div>
                ),
              },
            ]}
          />
        </DataPanel>

        <DataPanel
          title="数据生命周期与审计保留策略"
          description="保存策略不会自动删除数据；审计清理始终需要重新获取最新预览并显式确认。"
          className="nfc-settings-panel-lifecycle"
          action={
            <ActionBar compact>
              {lifecyclePolicy && <span className="nfc-kind-badge">Audit · {formatAuditRetention(lifecyclePolicy.audit_retention_days)}</span>}
              {quarantinePolicy && <span className="nfc-kind-badge">Quarantine · {quarantinePolicy.quarantine_retention_days === 0 ? '永久' : quarantinePolicy.quarantine_retention_days + ' 天'}</span>}
            </ActionBar>
          }
        >
          <div className="nfc-settings-stack">
            <Alert
              message="数据生命周期安全原则"
              description="保存策略 ≠ 执行删除；0 天 = 永久保留；预览 ≠ 执行。只有点击执行审计清理并确认后才会真正清理符合条件的 Audit 历史。"
              type="info"
              showIcon
            />

            <section className="nfc-settings-subpanel">
              <div className="nfc-settings-subpanel-header">
                <div>
                  <strong>审计日志保留策略</strong>
                  <span>仅保存参数，不触发清理。</span>
                </div>
              </div>
              <ActionBar>
                <label className="nfc-settings-inline-control">
                  <span>保留天数</span>
                  <InputNumber
                    min={0}
                    max={3650}
                    precision={0}
                    step={1}
                    value={retentionDaysInput}
                    onChange={(val) => setRetentionDaysInput(val)}
                    addonAfter="天"
                  />
                </label>
                <Button size="small" onClick={() => setRetentionDaysInput(0)}>永久保留</Button>
                <Button size="small" onClick={() => setRetentionDaysInput(30)}>30 天</Button>
                <Button size="small" onClick={() => setRetentionDaysInput(90)}>90 天</Button>
                <Button size="small" onClick={() => setRetentionDaysInput(180)}>180 天</Button>
                <Button size="small" onClick={() => setRetentionDaysInput(365)}>365 天</Button>
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
              </ActionBar>
              <p className="nfc-settings-help">
                {retentionDaysInput === 0
                  ? '0 天表示永久保留全部审计日志。'
                  : '保存后按所选天数计算过期日志；保存动作本身不会删除历史记录。'}
                {lifecyclePolicy?.updated_at ? ' 上次保存：' + formatDateTime(lifecyclePolicy.updated_at) : ''}
              </p>
            </section>

            <section className="nfc-settings-subpanel">
              <div className="nfc-settings-subpanel-header">
                <div>
                  <strong>文件隔离区保留策略</strong>
                  <span>仅记录到期元数据，不启动后台静默删除线程。</span>
                </div>
              </div>
              <ActionBar>
                <label className="nfc-settings-inline-control">
                  <span>保留周期</span>
                  <Select
                    value={quarantineDaysInput}
                    onChange={(val) => setQuarantineDaysInput(val)}
                    options={[
                      { label: '永久保留 (0 天)', value: 0 },
                      { label: '保留 7 天', value: 7 },
                      { label: '保留 30 天', value: 30 },
                      { label: '保留 90 天', value: 90 },
                    ]}
                  />
                </label>
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
              </ActionBar>
              <p className="nfc-settings-help">
                {quarantineDaysInput === 0
                  ? '永久保留全部隔离文件；系统不会标记过期时间。'
                  : '新进入隔离区的文件将记录对应到期时间；过期后仍需管理员人工审阅并确认清除。'}
              </p>
            </section>

            <section className="nfc-settings-subpanel nfc-settings-subpanel-danger">
              <div className="nfc-settings-subpanel-header">
                <div>
                  <strong>审计日志保留清理预览</strong>
                  <span>执行前会强制刷新策略与预览，最终删除数量以执行时数据为准。</span>
                </div>
                <ActionBar compact>
                  <Button size="small" icon={<ReloadOutlined />} loading={previewLoading} onClick={() => refetchPreview()}>
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
                  <Tooltip title={!isAdmin ? '仅系统管理员允许立即清空全部审计历史' : '忽略保留期，立即删除全部现有审计历史，并保留 1 条本次清空操作记录'}>
                    <span>
                      <Button
                        danger
                        icon={<DeleteOutlined />}
                        disabled={!isAdmin || clearAuditMutation.isPending}
                        loading={clearAuditMutation.isPending}
                        onClick={handleClearAuditHistory}
                      >
                        立即清空
                      </Button>
                    </span>
                  </Tooltip>
                </ActionBar>
              </div>
              <ResponsiveDescriptions
                items={[
                  { label: '当前生效保留期', value: formatAuditRetention(retentionPreview?.retention_days ?? lifecyclePolicy?.audit_retention_days) },
                  { label: '审计日志总数', value: String(retentionPreview?.total_count ?? 0), emphasis: true },
                  { label: '清理截止时间点', value: retentionPreview?.cutoff ? formatDateTime(retentionPreview.cutoff) : '无（永久保留）' },
                  { label: '拟删除记录数', value: String(retentionPreview?.delete_count ?? 0), emphasis: true },
                  { label: '拟保留记录数', value: String(retentionPreview?.keep_count ?? retentionPreview?.total_count ?? 0), emphasis: true },
                  { label: '最早记录时间', value: retentionPreview?.oldest_timestamp ? formatDateTime(retentionPreview.oldest_timestamp) : '—' },
                  { label: '立即清空说明', value: '管理员可忽略保留期直接清空历史；系统固定保留 1 条 audit.clear 自审计记录' },
                ]}
              />
            </section>
          </div>
        </DataPanel>

        {isAdmin && (
          <DataPanel
            title="资源控制"
            className="nfc-settings-panel-resource"
            description="控制扫描/哈希并发和时间窗口；不会改变文件安全与变动任务的优先安全语义。"
            action={
              <ActionBar compact>
                <Button icon={<ReloadOutlined />} loading={policyLoading} onClick={() => refetchResourcePolicy()}>
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
              </ActionBar>
            }
          >
            <div className="nfc-settings-stack">
              <Alert
                type="info"
                showIcon
                message="资源控制说明"
                description="I/O 压力与线程限制属于应用层并发节流；窗口外 Pause 只阻止资源型任务被 Worker 认领，不创建后台自动调度。文件变动任务不受该资源策略降级。"
              />

              {resourcePolicy && (
                <section className="nfc-settings-subpanel">
                  <div className="nfc-settings-subpanel-header"><strong>当前生效状态</strong></div>
                  <ResponsiveDescriptions
                    items={[
                      { label: '配置版本', value: 'rev.' + resourcePolicy.revision },
                      {
                        label: '生效模式',
                        value: (() => {
                          const disp = getProfileDisplay(resourcePolicy.effective_now.profile);
                          return <Tag color={disp.color}>{disp.text}</Tag>;
                        })(),
                      },
                      { label: '有效并发线程上限', value: resourcePolicy.effective_now.effective_thread_cap + ' 线程', emphasis: true },
                      {
                        label: '资源任务认领许可',
                        value: resourcePolicy.effective_now.resource_jobs_admitted ? <Tag color="success">允许认领</Tag> : <Tag color="error">队列保持 (Held)</Tag>,
                      },
                    ]}
                  />
                </section>
              )}

              <div className="nfc-settings-control-grid">
                <label className="nfc-settings-control">
                  <span>扫描线程上限 (1..32)</span>
                  <InputNumber min={1} max={32} value={scanThreadsInput} onChange={(v) => setScanThreadsInput(v || 1)} />
                </label>
                <label className="nfc-settings-control">
                  <span>哈希线程上限 (1..32)</span>
                  <InputNumber min={1} max={32} value={hashThreadsInput} onChange={(v) => setHashThreadsInput(v || 1)} />
                </label>
                <label className="nfc-settings-control">
                  <span>I/O 压力模式</span>
                  <Select
                    value={ioLimitInput}
                    onChange={setIoLimitInput}
                    options={[
                      { value: 'low', label: '低压模式 (Low - 上限 1 线程)' },
                      { value: 'normal', label: '标准模式 (Normal - 上限 2 线程)' },
                      { value: 'unlimited', label: '无上限模式 (Unlimited - 上限 32 线程)' },
                    ]}
                  />
                </label>
                <label className="nfc-settings-control">
                  <span>任务调度优先级</span>
                  <Select
                    value={jobPriorityInput}
                    onChange={setJobPriorityInput}
                    options={[
                      { value: 'normal', label: '标准先进先出 (Normal FIFO)' },
                      { value: 'background', label: '后台让步 (Background)' },
                    ]}
                  />
                </label>
              </div>

              <section className="nfc-settings-subpanel">
                <div className="nfc-settings-window-header">
                  <div>
                    <strong>活跃时间窗口</strong>
                    <span>窗口外自动降速或暂停扫描/索引任务认领。</span>
                  </div>
                  <Switch checked={windowEnabledInput} onChange={setWindowEnabledInput} />
                </div>
                {windowEnabledInput && (
                  <div className="nfc-settings-control-grid">
                    <label className="nfc-settings-control">
                      <span>窗口起始时间</span>
                      <Input value={windowStartInput} onChange={(e) => setWindowStartInput(e.target.value)} placeholder="01:00" />
                    </label>
                    <label className="nfc-settings-control">
                      <span>窗口结束时间</span>
                      <Input value={windowEndInput} onChange={(e) => setWindowEndInput(e.target.value)} placeholder="07:00" />
                    </label>
                    <label className="nfc-settings-control">
                      <span>时区</span>
                      <Select showSearch value={windowTimezoneInput} onChange={setWindowTimezoneInput} options={COMMON_TIMEZONES.map((tz) => ({ value: tz, label: tz }))} />
                    </label>
                    <label className="nfc-settings-control">
                      <span>窗口外行为模式</span>
                      <Select
                        value={outsideModeInput}
                        onChange={setOutsideModeInput}
                        options={[
                          { value: 'limited', label: '降速运行 (Limited)' },
                          { value: 'pause', label: '暂停认领 (Pause)' },
                        ]}
                      />
                    </label>
                  </div>
                )}
              </section>
            </div>
          </DataPanel>
        )}

        <DataPanel
          title="管理员活动会话"
          description="当前设备不可在此强制注销；其他会话可由管理员显式下线。"
          action={<span className="nfc-panel-count">{sessionsData?.sessions?.length ?? 0} sessions</span>}
          className="nfc-panel-flush nfc-settings-panel-sessions"
        >
          <ResponsiveDataView
            desktop={
              <Table
                dataSource={sessionsData?.sessions || []}
                columns={sessionColumns}
                rowKey="id"
                loading={sessionsLoading}
                pagination={false}
              />
            }
            mobile={
              <div className="nfc-mobile-record-list">
                {(sessionsData?.sessions || []).map((session) => (
                  <article className="nfc-session-mobile-card" key={session.id}>
                    <div className="nfc-mobile-record-heading">
                      <div>
                        {session.user_agent.toLowerCase().includes('mobile') ? <MobileOutlined /> : <DesktopOutlined />}
                        <strong className="nfc-session-device">{session.user_agent}</strong>
                      </div>
                      {session.is_current ? <Tag color="success">当前设备</Tag> : <span className="nfc-kind-badge">remote</span>}
                    </div>
                    <div className="nfc-mobile-record-facts">
                      <span>IP <b className="nfc-mono">{session.ip_address}</b></span>
                      <span>首次登录 <b>{formatDateTime(session.created_at)}</b></span>
                      <span>最近活动 <b>{formatDateTime(session.last_seen_at)}</b></span>
                    </div>
                    {!session.is_current && (
                      <div className="nfc-mobile-record-actions">
                        <Popconfirm
                          title="确认强制注销该设备？"
                          onConfirm={() => revokeMutation.mutate(session.id)}
                          okText="注销"
                          cancelText="取消"
                        >
                          <Button danger type="text" loading={revokeMutation.isPending}>强制下线</Button>
                        </Popconfirm>
                      </div>
                    )}
                  </article>
                ))}
              </div>
            }
          />
        </DataPanel>
      </div>
    </div>
  );
};
