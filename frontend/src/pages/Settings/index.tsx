import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { settingsApi, dataLifecycleApi, auditApi, quarantineApi, resourcePolicyApi } from '../../api/domain';
import { authApi } from '../../api/auth';
import { getStructuredApiError } from '../../api/errors';
import { useAuth } from '../../contexts/AuthContext';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import type { SessionInfo, ResourcePolicyUpdate } from '../../types';
import {
  formatAuditRetention, getAuditRetentionApplyAvailability,
  getAuditRetentionSaveAvailability, getQuarantineRetentionSaveAvailability,
  validateRetentionDaysInput,
} from '../../components/settings/data_lifecycle';
import {
  COMMON_TIMEZONES, validateResourcePolicyUpdate, getProfileDisplay,
} from '../../components/settings/resource_policy';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { useConsoleToast } from '../../components/ui/ConsoleToast';

type Confirmation =
  | { kind: 'clear' }
  | { kind: 'retention'; days: number; deleteCount: number }
  | { kind: 'revoke'; sessionId: number; agent: string };

type StatusTone = 'success' | 'warning' | 'danger' | 'neutral';
const status = (tone: StatusTone, label: string) => (
  <span className={'nfc-v2-settings-status tone-' + tone}>{label}</span>
);
const failure = (error: unknown, fallback: string) =>
  getStructuredApiError(error).message || fallback;

/** Environment-authoritative security flags; no Web UI action can enable mutation or deletion. */
export const SettingsPage: React.FC = () => {
  useTitle('系统设置');
  const toast = useConsoleToast();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [retentionDaysInput, setRetentionDaysInput] = useState<number | null>(0);
  const [quarantineDaysInput, setQuarantineDaysInput] = useState(0);
  const [scanThreadsInput, setScanThreadsInput] = useState(2);
  const [hashThreadsInput, setHashThreadsInput] = useState(2);
  const [ioLimitInput, setIoLimitInput] = useState<'low' | 'normal' | 'unlimited'>('normal');
  const [jobPriorityInput, setJobPriorityInput] = useState<'normal' | 'background'>('normal');
  const [windowEnabledInput, setWindowEnabledInput] = useState(false);
  const [windowStartInput, setWindowStartInput] = useState('01:00');
  const [windowEndInput, setWindowEndInput] = useState('07:00');
  const [windowTimezoneInput, setWindowTimezoneInput] = useState('UTC');
  const [outsideModeInput, setOutsideModeInput] = useState<'limited' | 'pause'>('limited');
  const [prepareApplyPending, setPrepareApplyPending] = useState(false);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const pendingActions = useRef(new Set<string>());
  const prepareTicket = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      prepareTicket.current += 1;
    };
  }, []);

  const { data: settings, isError: settingsError, refetch: refetchSettings } = useQuery({
    queryKey: ['settings'], queryFn: settingsApi.getSettings,
  });
  const { data: lifecyclePolicy, isError: policyQueryError, refetch: refetchPolicy } = useQuery({
    queryKey: ['dataLifecyclePolicy'], queryFn: dataLifecycleApi.getPolicy,
  });
  const { data: retentionPreview, isLoading: previewLoading, isError: previewQueryError,
    refetch: refetchPreview } = useQuery({
    queryKey: ['auditRetentionPreview'], queryFn: auditApi.getRetentionPreview,
  });
  const { data: quarantinePolicy, refetch: refetchQuarantinePolicy } = useQuery({
    queryKey: ['quarantineRetentionPolicy'], queryFn: quarantineApi.getRetentionPolicy,
  });
  const { data: resourcePolicy, isLoading: policyLoading, refetch: refetchResourcePolicy } = useQuery({
    queryKey: ['resourcePolicy'], queryFn: resourcePolicyApi.getPolicy, enabled: !!isAdmin,
  });
  const { data: sessionsData, isLoading: sessionsLoading, isError: sessionsError,
    refetch: refetchSessions } = useQuery({
    queryKey: ['activeSessions'], queryFn: authApi.listSessions,
  });

  useEffect(() => {
    if (lifecyclePolicy) setRetentionDaysInput(lifecyclePolicy.audit_retention_days);
  }, [lifecyclePolicy]);
  useEffect(() => {
    if (quarantinePolicy) setQuarantineDaysInput(quarantinePolicy.quarantine_retention_days);
  }, [quarantinePolicy]);
  useEffect(() => {
    if (!resourcePolicy) return;
    setScanThreadsInput(resourcePolicy.scan_threads);
    setHashThreadsInput(resourcePolicy.hash_threads);
    setIoLimitInput(resourcePolicy.io_limit);
    setJobPriorityInput(resourcePolicy.job_priority);
    setWindowEnabledInput(resourcePolicy.active_window_enabled);
    setWindowStartInput(resourcePolicy.active_window_start || '01:00');
    setWindowEndInput(resourcePolicy.active_window_end || '07:00');
    setWindowTimezoneInput(resourcePolicy.active_window_timezone || 'UTC');
    setOutsideModeInput(resourcePolicy.outside_window_mode);
  }, [resourcePolicy]);

  const saveResourcePolicyMutation = useMutation({
    mutationFn: (payload: ResourcePolicyUpdate) => resourcePolicyApi.updatePolicy(payload),
    onSuccess: () => {
      toast.success('资源控制策略已更新');
      void queryClient.invalidateQueries({ queryKey: ['resourcePolicy'] });
    },
    onError: (error: unknown) => toast.error(failure(error, '更新资源控制策略失败')),
  });
  const saveQuarantinePolicyMutation = useMutation({
    mutationFn: (days: number) => quarantineApi.updateRetentionPolicy(days),
    onSuccess: () => {
      toast.success('隔离区保留策略已更新');
      void queryClient.invalidateQueries({ queryKey: ['quarantineRetentionPolicy'] });
      void queryClient.invalidateQueries({ queryKey: ['quarantineList'] });
    },
    onError: (error: unknown) => toast.error(failure(error, '更新隔离区保留策略失败')),
  });
  const savePolicyMutation = useMutation({
    mutationFn: (days: number) => dataLifecycleApi.updatePolicy(days),
    onSuccess: () => {
      toast.success('数据生命周期保留策略已更新');
      void queryClient.invalidateQueries({ queryKey: ['dataLifecyclePolicy'] });
      void queryClient.invalidateQueries({ queryKey: ['auditRetentionPreview'] });
    },
    onError: (error: unknown) => toast.error(failure(error, '更新保留策略失败')),
  });
  const applyRetentionMutation = useMutation({
    mutationFn: () => auditApi.applyRetention(),
    onSuccess: res => {
      toast.success('审计日志保留清理执行成功，已清理 ' + res.deleted_count +
        ' 条记录，剩余 ' + res.remaining_count + ' 条');
      void queryClient.invalidateQueries({ queryKey: ['auditRetentionPreview'] });
      void queryClient.invalidateQueries({ queryKey: ['dataLifecyclePolicy'] });
      void queryClient.invalidateQueries({ queryKey: ['auditEvents'] });
    },
    onError: (error: unknown) => toast.error(failure(error, '执行保留清理失败')),
  });
  const clearAuditMutation = useMutation({
    mutationFn: () => auditApi.clearHistory(),
    onSuccess: res => {
      toast.success('审计历史已清空，共删除 ' + res.deleted_count +
        ' 条；系统保留 1 条本次清空操作审计记录');
      void queryClient.invalidateQueries({ queryKey: ['auditRetentionPreview'] });
      void queryClient.invalidateQueries({ queryKey: ['auditEvents'] });
    },
    onError: (error: unknown) => toast.error(failure(error, '立即清空审计历史失败')),
  });
  const revokeMutation = useMutation({
    mutationFn: (sessionId: number) => authApi.revokeSession(sessionId),
    onSuccess: () => {
      toast.success('已成功注销该设备会话');
      void refetchSessions();
    },
    onError: (error: unknown) => toast.error(failure(error, '注销会话失败')),
  });

  const runOnce = async (key: string, action: () => Promise<unknown>) => {
    if (pendingActions.current.has(key)) return;
    pendingActions.current.add(key);
    try { await action(); }
    finally { pendingActions.current.delete(key); }
  };
  const rejectNonAdmin = (action: string) => {
    if (isAdmin) return false;
    toast.error('仅系统管理员允许' + action);
    return true;
  };

  const handleSaveResourcePolicy = () => {
    if (rejectNonAdmin('修改资源控制策略')) return;
    const payload: ResourcePolicyUpdate = {
      scan_threads: scanThreadsInput, hash_threads: hashThreadsInput,
      io_limit: ioLimitInput, job_priority: jobPriorityInput,
      active_window_enabled: windowEnabledInput,
      active_window_start: windowEnabledInput ? windowStartInput : null,
      active_window_end: windowEnabledInput ? windowEndInput : null,
      active_window_timezone: windowEnabledInput ? windowTimezoneInput : null,
      outside_window_mode: outsideModeInput,
    };
    const checked = validateResourcePolicyUpdate(payload);
    if (!checked.valid) { toast.error(checked.error || '资源策略校验失败'); return; }
    void runOnce('resource-save', () => saveResourcePolicyMutation.mutateAsync(payload)).catch(() => {});
  };
  const handleSavePolicy = () => {
    if (rejectNonAdmin('修改审计保留策略')) return;
    const checked = validateRetentionDaysInput(retentionDaysInput);
    if (!checked.valid || retentionDaysInput === null) {
      toast.error(checked.error || '保留天数无效');
      return;
    }
    prepareTicket.current += 1;
    setConfirmation(current => current?.kind === 'retention' ? null : current);
    void runOnce('audit-save', () => savePolicyMutation.mutateAsync(retentionDaysInput)).catch(() => {});
  };
  const handleSaveQuarantinePolicy = () => {
    if (rejectNonAdmin('修改隔离区保留策略')) return;
    if (![0, 7, 30, 90].includes(quarantineDaysInput)) {
      toast.error('隔离区保留天数仅支持 0、7、30 或 90 天');
      return;
    }
    void runOnce('quarantine-save', () =>
      saveQuarantinePolicyMutation.mutateAsync(quarantineDaysInput)).catch(() => {});
  };

  const auditSaveAvail = getAuditRetentionSaveAvailability(isAdmin, savePolicyMutation.isPending);
  const quarantineSaveAvail = getQuarantineRetentionSaveAvailability(isAdmin, saveQuarantinePolicyMutation.isPending);
  const availability = getAuditRetentionApplyAvailability(lifecyclePolicy, retentionPreview, {
    isSavingPolicy: savePolicyMutation.isPending,
    isPreparingApply: prepareApplyPending,
    isApplying: applyRetentionMutation.isPending,
    isQueryError: policyQueryError || previewQueryError,
    isAdmin,
  });

  const handlePrepareApply = async () => {
    if (rejectNonAdmin('执行审计日志清理')) return;
    if (!availability.canApply || pendingActions.current.has('audit-prepare') ||
        pendingActions.current.has('audit-save') || pendingActions.current.has('audit-action') ||
        confirmation !== null) return;
    const ticket = ++prepareTicket.current;
    pendingActions.current.add('audit-prepare');
    setPrepareApplyPending(true);
    try {
      // Do not trust a rendered preview. Re-fetch both saved policy and preview before confirmation.
      const [policyResult, previewResult] = await Promise.all([refetchPolicy(), refetchPreview()]);
      if (!mountedRef.current || ticket !== prepareTicket.current) return;
      const freshPolicy = policyResult.data;
      const freshPreview = previewResult.data;
      if (policyResult.isError || previewResult.isError || !freshPolicy || !freshPreview) {
        toast.error('无法获取最新保留策略或清理预览，请稍后重试');
        return;
      }
      if (freshPolicy.audit_retention_days === 0) {
        toast.info('当前策略为永久保留（0 天），没有可执行的保留期清理');
        return;
      }
      setConfirmation({ kind: 'retention',
        days: freshPolicy.audit_retention_days, deleteCount: freshPreview.delete_count });
    } catch (error: unknown) {
      if (mountedRef.current && ticket === prepareTicket.current) {
        toast.error(failure(error, '无法获取最新保留策略或清理预览，请重试'));
      }
    } finally {
      pendingActions.current.delete('audit-prepare');
      if (mountedRef.current) setPrepareApplyPending(false);
    }
  };

  const handleClearAuditHistory = () => {
    if (rejectNonAdmin('立即清空审计历史') || pendingActions.current.has('audit-action') ||
        prepareApplyPending || savePolicyMutation.isPending) return;
    setConfirmation({ kind: 'clear' });
  };
  const handleRevokeSession = (session: SessionInfo) => {
    if (rejectNonAdmin('注销设备会话') || session.is_current ||
        pendingActions.current.has('session-revoke')) return;
    setConfirmation({ kind: 'revoke', sessionId: session.id, agent: session.user_agent });
  };
  const handleConfirm = () => {
    if (!confirmation || !isAdmin) return;
    if (confirmation.kind === 'retention') {
      if (pendingActions.current.has('audit-save') || pendingActions.current.has('audit-prepare')) return;
      const captured = confirmation;
      // A policy revision during the dialog invalidates stale confirmation.
      if (lifecyclePolicy?.audit_retention_days !== captured.days) {
        setConfirmation(null);
        toast.error('已保存的保留策略发生变化，请重新获取最新预览');
        return;
      }
      void runOnce('audit-action', async () => {
        await applyRetentionMutation.mutateAsync();
        if (mountedRef.current) setConfirmation(null);
      }).catch(() => {});
    } else if (confirmation.kind === 'clear') {
      void runOnce('audit-action', async () => {
        await clearAuditMutation.mutateAsync();
        if (mountedRef.current) setConfirmation(null);
      }).catch(() => {});
    } else {
      const active = sessionsData?.sessions?.find(s => s.id === confirmation.sessionId);
      if (!active || active.is_current) {
        setConfirmation(null);
        toast.error('当前会话或已失效的会话不能在这里强制下线');
        return;
      }
      void runOnce('session-revoke', async () => {
        await revokeMutation.mutateAsync(active.id);
        if (mountedRef.current) setConfirmation(null);
      }).catch(() => {});
    }
  };
  const confirmBusy = applyRetentionMutation.isPending || clearAuditMutation.isPending ||
    revokeMutation.isPending || pendingActions.current.has('audit-action') ||
    pendingActions.current.has('session-revoke');
  const confirmationTitle = confirmation?.kind === 'retention'
    ? '确认执行审计日志保留清理？'
    : confirmation?.kind === 'clear' ? '立即清空全部审计历史？'
      : '确认强制注销该设备？';
  const confirmationText = confirmation?.kind === 'retention' ? '确认执行清理'
    : confirmation?.kind === 'clear' ? '立即清空' : '强制下线';

  const sessionActions = (session: SessionInfo) =>
    session.is_current ? <span className="nfc-v2-settings-muted">当前会话</span>
      : isAdmin ? <ConsoleButton size="sm" variant="danger"
        disabled={revokeMutation.isPending || confirmBusy}
        onClick={() => handleRevokeSession(session)}>强制下线</ConsoleButton>
        : <span className="nfc-v2-settings-muted">仅管理员可管理</span>;
  const deviceLabel = (session: SessionInfo) => (
    <div className="nfc-v2-settings-device">
      <ConsoleIcon name={session.user_agent.toLowerCase().includes('mobile') ? 'user' : 'terminal'} size={17} />
      <span className="nfc-session-user-agent">{session.user_agent}</span>
      {session.is_current && status('success', '当前设备')}
    </div>
  );
  const sessions = sessionsData?.sessions || [];

  return (
    <div className="nfc-operations-page nfc-settings-page nfc-system-controls-page nfc-page-layout-workbench nfc-v2-settings">
      <PageHeader title="系统设置与安全中心"
        description="集中查看文件安全开关、数据保留、资源控制与管理员会话。危险文件开关仍只能通过宿主机环境变量配置。"
        actions={<ActionBar compact>
          <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
            onClick={() => {
              void refetchSettings(); void refetchSessions(); void refetchPolicy();
              void refetchPreview(); void refetchQuarantinePolicy();
              if (isAdmin) void refetchResourcePolicy();
            }}>刷新全部</ConsoleButton>
        </ActionBar>}
      />

      <div className="nfc-settings-grid">
        <DataPanel title="全局文件安全运行参数"
          description="这些开关来自服务端运行环境，Web UI 只读展示，防止误触扩大文件修改权限。"
          className="nfc-panel-flush nfc-settings-panel-runtime">
          <div className="nfc-settings-panel-body">
            <div className="nfc-v2-settings-notice" role="note">
              <ConsoleIcon name="shield-check" size={19} />
              <div><strong>安全机制提示</strong>
                <p>为确保大容量核心数据安全，ALLOW_MUTATION、ALLOW_DELETE 等危险开关只能通过宿主机 Docker Compose 环境变量配置，禁止在 Web 界面一键开启。</p>
              </div>
            </div>
            {settingsError && <p role="alert" className="nfc-v2-settings-error">安全运行参数读取失败，请刷新重试。</p>}
          </div>
          <ResponsiveDescriptions items={[
            { label: '只读安全模式 (ALLOW_MUTATION)',
              value: settings ? settings.allow_mutation ? status('warning', '开启写入 (true)') : status('success', '只读保护 (false)') : '—' },
            { label: '永久删除开关 (ALLOW_DELETE)',
              value: settings ? settings.allow_delete ? status('danger', '允许永久删除 (true)') : status('success', '禁用删除 (false - 仅隔离)') : '—' },
            { label: '最后副本保护 (PROTECT_LAST_FILE)',
              value: settings ? settings.protect_last_file ? status('success', '已启用') : status('danger', '未启用') : '—' },
            { label: '去重校验哈希', value: <span className="nfc-kind-badge">{settings?.verification_hash?.toUpperCase() || 'SHA256'}</span> },
            { label: '隔离区根目录 (QUARANTINE_ROOT)', value: <CodePath value={settings?.quarantine_root} /> },
            { label: '允许访问路径白名单 (ALLOWED_ROOTS)',
              value: <div className="nfc-settings-path-list">
                {settings?.allowed_roots.map((root, idx) => <CodePath value={root} key={idx} />)}
              </div> },
          ]} />
        </DataPanel>

        <DataPanel title="数据生命周期与审计保留策略"
          description="保存策略不会自动删除数据；审计清理始终需要重新获取最新预览并显式确认。"
          className="nfc-settings-panel-lifecycle"
          action={<ActionBar compact>
            {lifecyclePolicy && <span className="nfc-kind-badge">Audit · {formatAuditRetention(lifecyclePolicy.audit_retention_days)}</span>}
            {quarantinePolicy && <span className="nfc-kind-badge">Quarantine · {quarantinePolicy.quarantine_retention_days === 0 ? '永久' : quarantinePolicy.quarantine_retention_days + ' 天'}</span>}
          </ActionBar>}>
          <div className="nfc-settings-stack">
            <div className="nfc-v2-settings-notice" role="note">
              <ConsoleIcon name="info" size={19} />
              <div><strong>数据生命周期安全原则</strong>
                <p>保存策略 ≠ 执行删除；0 天 = 永久保留；预览 ≠ 执行。只有点击执行审计清理并确认后才会真正清理符合条件的 Audit 历史。</p>
              </div>
            </div>
            <section className="nfc-settings-subpanel nfc-settings-policy-card">
              <div className="nfc-settings-subpanel-header">
                <div><strong>审计日志保留策略</strong><span>仅保存参数，不触发清理。</span></div>
              </div>
              <ActionBar>
                <label className="nfc-settings-inline-control">
                  <span>保留天数</span>
                  <input type="number" min={0} max={3650} step={1}
                    value={retentionDaysInput ?? ''}
                    disabled={savePolicyMutation.isPending}
                    onChange={event => setRetentionDaysInput(event.target.value === '' ? null : Number(event.target.value))} />
                </label>
                {[0, 30, 90, 180, 365].map(days => (
                  <ConsoleButton key={days} size="sm" disabled={savePolicyMutation.isPending}
                    onClick={() => setRetentionDaysInput(days)}>{days === 0 ? '永久保留' : days + ' 天'}</ConsoleButton>
                ))}
                <ConsoleButton variant="primary" size="sm" loading={savePolicyMutation.isPending}
                  disabled={!auditSaveAvail.canSave}
                  title={!isAdmin ? '仅系统管理员允许修改审计保留策略' : auditSaveAvail.disabledReason}
                  leadingIcon={<ConsoleIcon name="check" size={16} />}
                  onClick={handleSavePolicy}>保存策略</ConsoleButton>
              </ActionBar>
              <p className="nfc-settings-help">
                {retentionDaysInput === 0
                  ? '0 天表示永久保留全部审计日志。'
                  : '保存后按所选天数计算过期日志；保存动作本身不会删除历史记录。'}
                {lifecyclePolicy?.updated_at ? ' 上次保存：' + formatDateTime(lifecyclePolicy.updated_at) : ''}
              </p>
            </section>

            <section className="nfc-settings-subpanel nfc-settings-policy-card">
              <div className="nfc-settings-subpanel-header">
                <div><strong>文件隔离区保留策略</strong><span>仅记录到期元数据，不启动后台静默删除线程。</span></div>
              </div>
              <ActionBar>
                <label className="nfc-settings-inline-control">
                  <span>保留周期</span>
                  <select value={quarantineDaysInput} disabled={saveQuarantinePolicyMutation.isPending}
                    onChange={event => setQuarantineDaysInput(Number(event.target.value))}>
                    <option value={0}>永久保留 (0 天)</option>
                    <option value={7}>保留 7 天</option>
                    <option value={30}>保留 30 天</option>
                    <option value={90}>保留 90 天</option>
                  </select>
                </label>
                <ConsoleButton variant="primary" size="sm" loading={saveQuarantinePolicyMutation.isPending}
                  disabled={!quarantineSaveAvail.canSave}
                  title={!isAdmin ? '仅系统管理员允许修改隔离区保留策略' : quarantineSaveAvail.disabledReason}
                  leadingIcon={<ConsoleIcon name="check" size={16} />}
                  onClick={handleSaveQuarantinePolicy}>保存隔离区策略</ConsoleButton>
              </ActionBar>
              <p className="nfc-settings-help">
                {quarantineDaysInput === 0
                  ? '永久保留全部隔离文件；系统不会标记过期时间。'
                  : '新进入隔离区的文件将记录对应到期时间；过期后仍需管理员人工审阅并确认清除。'}
              </p>
            </section>

            <section className="nfc-settings-subpanel nfc-settings-subpanel-danger">
              <div className="nfc-settings-subpanel-header nfc-settings-retention-header">
                <div className="nfc-settings-retention-copy">
                  <strong>审计日志保留清理预览</strong>
                  <span>执行前会强制刷新策略与预览，最终删除数量以执行时数据为准。</span>
                </div>
                <ActionBar compact className="nfc-settings-retention-actions">
                  <ConsoleButton size="sm" loading={previewLoading}
                    leadingIcon={<ConsoleIcon name="refresh" size={16} />}
                    onClick={() => { void refetchPreview(); }}>刷新预览</ConsoleButton>
                  <ConsoleButton variant="danger" size="sm" loading={clearAuditMutation.isPending}
                    disabled={!isAdmin || !!confirmation || prepareApplyPending || savePolicyMutation.isPending}
                    title={!isAdmin ? '仅管理员可立即清空' : '忽略保留期，清空 Audit 历史，仅保留一条自审计'}
                    leadingIcon={<ConsoleIcon name="trash" size={16} />}
                    onClick={handleClearAuditHistory}>立即清空</ConsoleButton>
                  <ConsoleButton variant="danger" size="sm"
                    loading={applyRetentionMutation.isPending || prepareApplyPending}
                    disabled={!availability.canApply || !!confirmation}
                    title={!isAdmin ? '仅系统管理员允许执行审计日志清理' : availability.disabledReason}
                    leadingIcon={<ConsoleIcon name="trash" size={16} />}
                    onClick={() => { void handlePrepareApply(); }}>执行审计清理</ConsoleButton>
                </ActionBar>
              </div>
              <ResponsiveDescriptions items={[
                { label: '当前生效保留期', value: formatAuditRetention(retentionPreview?.retention_days ?? lifecyclePolicy?.audit_retention_days) },
                { label: '审计日志总数', value: String(retentionPreview?.total_count ?? 0), emphasis: true },
                { label: '清理截止时间点', value: retentionPreview?.cutoff ? formatDateTime(retentionPreview.cutoff) : '无（永久保留）' },
                { label: '拟删除记录数', value: String(retentionPreview?.delete_count ?? 0), emphasis: true },
                { label: '拟保留记录数', value: String(retentionPreview?.keep_count ?? retentionPreview?.total_count ?? 0), emphasis: true },
                { label: '最早记录时间', value: retentionPreview?.oldest_timestamp ? formatDateTime(retentionPreview.oldest_timestamp) : '—' },
                { label: '立即清空说明', value: '管理员可忽略保留期直接清空历史；系统固定保留 1 条 audit.clear 自审计记录' },
              ]} />
            </section>
          </div>
        </DataPanel>

        {isAdmin && (
          <DataPanel title="资源控制" className="nfc-settings-panel-resource"
            description="控制扫描/哈希并发和时间窗口；不会改变文件安全与变动任务的优先安全语义。"
            action={<ActionBar compact>
              <ConsoleButton loading={policyLoading} size="sm"
                leadingIcon={<ConsoleIcon name="refresh" size={16} />}
                onClick={() => { void refetchResourcePolicy(); }}>刷新</ConsoleButton>
              <ConsoleButton variant="primary" size="sm" disabled={!resourcePolicy}
                loading={saveResourcePolicyMutation.isPending}
                leadingIcon={<ConsoleIcon name="check" size={16} />}
                onClick={handleSaveResourcePolicy}>保存资源策略</ConsoleButton>
            </ActionBar>}>
            <div className="nfc-settings-stack">
              <div className="nfc-v2-settings-notice" role="note">
                <ConsoleIcon name="info" size={19} />
                <div><strong>资源控制说明</strong>
                  <p>I/O 压力与线程限制属于应用层并发节流；窗口外 Pause 只阻止资源型任务被 Worker 认领，不创建后台自动调度。文件变动任务不受该资源策略降级。</p>
                </div>
              </div>
              {resourcePolicy && (
                <section className="nfc-settings-subpanel nfc-settings-status-card">
                  <div className="nfc-settings-subpanel-header"><strong>当前生效状态</strong></div>
                  <ResponsiveDescriptions items={[
                    { label: '配置版本', value: 'rev.' + resourcePolicy.revision },
                    { label: '生效模式', value: (() => {
                      const display = getProfileDisplay(resourcePolicy.effective_now.profile);
                      const tone: StatusTone = display.color === 'success' ? 'success'
                        : display.color === 'warning' ? 'warning'
                          : display.color === 'error' ? 'danger' : 'neutral';
                      return status(tone, display.text);
                    })() },
                    { label: '有效并发线程上限', value: resourcePolicy.effective_now.effective_thread_cap + ' 线程', emphasis: true },
                    { label: '资源任务认领许可',
                      value: resourcePolicy.effective_now.resource_jobs_admitted
                        ? status('success', '允许认领') : status('danger', '队列保持 (Held)') },
                  ]} />
                </section>
              )}
              <div className="nfc-settings-control-grid nfc-settings-resource-controls">
                <label className="nfc-settings-control">
                  <span>扫描线程上限 (1..32)</span>
                  <input type="number" min={1} max={32} step={1}
                    disabled={saveResourcePolicyMutation.isPending} value={scanThreadsInput}
                    onChange={event => setScanThreadsInput(event.target.value === '' ? 0 : Number(event.target.value))} />
                </label>
                <label className="nfc-settings-control">
                  <span>哈希线程上限 (1..32)</span>
                  <input type="number" min={1} max={32} step={1}
                    disabled={saveResourcePolicyMutation.isPending} value={hashThreadsInput}
                    onChange={event => setHashThreadsInput(event.target.value === '' ? 0 : Number(event.target.value))} />
                </label>
                <label className="nfc-settings-control">
                  <span>I/O 压力模式</span>
                  <select disabled={saveResourcePolicyMutation.isPending} value={ioLimitInput}
                    onChange={event => setIoLimitInput(event.target.value as typeof ioLimitInput)}>
                    <option value="low">低压模式 (Low - 上限 1 线程)</option>
                    <option value="normal">标准模式 (Normal - 上限 2 线程)</option>
                    <option value="unlimited">无上限模式 (Unlimited - 上限 32 线程)</option>
                  </select>
                </label>
                <label className="nfc-settings-control">
                  <span>任务调度优先级</span>
                  <select disabled={saveResourcePolicyMutation.isPending} value={jobPriorityInput}
                    onChange={event => setJobPriorityInput(event.target.value as typeof jobPriorityInput)}>
                    <option value="normal">标准先进先出 (Normal FIFO)</option>
                    <option value="background">后台让步 (Background)</option>
                  </select>
                </label>
              </div>
              <section className="nfc-settings-subpanel nfc-settings-window-card">
                <div className="nfc-settings-window-header">
                  <div><strong>活跃时间窗口</strong><span>窗口外自动降速或暂停扫描/索引任务认领。</span></div>
                  <label className="nfc-v2-settings-switch">
                    <input type="checkbox" checked={windowEnabledInput}
                      disabled={saveResourcePolicyMutation.isPending}
                      onChange={event => setWindowEnabledInput(event.target.checked)}
                      aria-label="启用活跃时间窗口" role="switch" aria-checked={windowEnabledInput} />
                    <span>{windowEnabledInput ? '已启用' : '未启用'}</span>
                  </label>
                </div>
                {windowEnabledInput && (
                  <div className="nfc-settings-control-grid">
                    <label className="nfc-settings-control">
                      <span>窗口起始时间</span>
                      <input type="text" value={windowStartInput} placeholder="01:00"
                        disabled={saveResourcePolicyMutation.isPending}
                        onChange={event => setWindowStartInput(event.target.value)} />
                    </label>
                    <label className="nfc-settings-control">
                      <span>窗口结束时间</span>
                      <input type="text" value={windowEndInput} placeholder="07:00"
                        disabled={saveResourcePolicyMutation.isPending}
                        onChange={event => setWindowEndInput(event.target.value)} />
                    </label>
                    <label className="nfc-settings-control">
                      <span>时区</span>
                      <select value={windowTimezoneInput} disabled={saveResourcePolicyMutation.isPending}
                        onChange={event => setWindowTimezoneInput(event.target.value)}>
                        {COMMON_TIMEZONES.map(tz => <option key={tz} value={tz}>{tz}</option>)}
                      </select>
                    </label>
                    <label className="nfc-settings-control">
                      <span>窗口外行为模式</span>
                      <select value={outsideModeInput} disabled={saveResourcePolicyMutation.isPending}
                        onChange={event => setOutsideModeInput(event.target.value as typeof outsideModeInput)}>
                        <option value="limited">降速运行 (Limited)</option>
                        <option value="pause">暂停认领 (Pause)</option>
                      </select>
                    </label>
                  </div>
                )}
              </section>
            </div>
          </DataPanel>
        )}

        <DataPanel title="管理员活动会话"
          description="当前设备不可在此强制注销；其他会话可由管理员显式下线。"
          action={<span className="nfc-panel-count">{sessions.length} sessions</span>}
          className="nfc-panel-flush nfc-settings-panel-sessions" variant="dense">
          {sessionsError ? <ConsoleEmpty title="活动会话获取失败"
            description="请刷新后重试。当前会话尚未修改。"
            action={<ConsoleButton onClick={() => { void refetchSessions(); }}>重新加载</ConsoleButton>} />
            : sessionsLoading ? <div role="status" className="nfc-v2-settings-loading">正在加载设备会话…</div>
              : sessions.length === 0 ? <ConsoleEmpty title="暂无活动会话" />
                : <ResponsiveDataView
                  desktop={<div className="nfc-v2-settings-table-scroll">
                    <table className="nfc-v2-settings-table">
                      <caption>活动设备会话与强制下线操作</caption>
                      <thead><tr>
                        <th scope="col">登录设备 / User Agent</th>
                        <th scope="col">IP 地址</th>
                        <th scope="col">首次登录时间</th>
                        <th scope="col">最近活动时间</th>
                        <th scope="col">操作</th>
                      </tr></thead>
                      <tbody>{sessions.map(session => (
                        <tr key={session.id}>
                          <td>{deviceLabel(session)}</td>
                          <td><code>{session.ip_address}</code></td>
                          <td>{formatDateTime(session.created_at)}</td>
                          <td>{formatDateTime(session.last_seen_at)}</td>
                          <td>{sessionActions(session)}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  </div>}
                  mobile={<div className="nfc-mobile-record-list nfc-v2-settings-mobile">
                    {sessions.map(session => (
                      <article className="nfc-session-mobile-card" key={session.id}>
                        <div className="nfc-mobile-record-heading">{deviceLabel(session)}</div>
                        <div className="nfc-mobile-record-facts">
                          <span>IP <b className="nfc-mono">{session.ip_address}</b></span>
                          <span>首次登录 <b>{formatDateTime(session.created_at)}</b></span>
                          <span>最近活动 <b>{formatDateTime(session.last_seen_at)}</b></span>
                        </div>
                        {!session.is_current && <div className="nfc-mobile-record-actions">
                          {sessionActions(session)}
                        </div>}
                      </article>
                    ))}
                  </div>}
                />}
        </DataPanel>
      </div>

      <ConsoleConfirmDialog open={confirmation !== null}
        onOpenChange={open => { if (!open && !confirmBusy) setConfirmation(null); }}
        title={confirmationTitle} danger busy={confirmBusy} disabled={!isAdmin}
        confirmText={confirmationText}
        onConfirm={handleConfirm}
        description={confirmation?.kind === 'retention' ? (
          <div className="nfc-v2-settings-confirm-copy">
            <p>当前已保存策略：<strong>{formatAuditRetention(confirmation.days)}</strong></p>
            <p>当前最新预览：预计清理 <strong className="nfc-danger-text">{confirmation.deleteCount}</strong> 条 Audit 历史记录。</p>
            <p>提示：当前预览仅为预计结果。实际执行时将根据数据库中最新保存的保留策略以及执行时最新的审计数据重新计算，最终删除数量可能与当前预览不同。</p>
            <p>安全边界：本操作仅清理符合保留期条件的 Audit 历史记录。不会删除 NAS 上的真实文件或目录，也不会删除 Task、Scan、Plan 或 Index 数据。</p>
            <p className="nfc-danger-copy">审计历史清理不可撤销。</p>
          </div>
        ) : confirmation?.kind === 'clear' ? (
          <div className="nfc-v2-settings-confirm-copy">
            <p>该操作忽略全部保留期，立即删除现有 Audit 历史。</p>
            <p>系统保留一条 audit.clear 自审计记录；无法撤销。</p>
          </div>
        ) : (
          <div className="nfc-v2-settings-confirm-copy">
            <p>将强制注销设备：<strong>{confirmation?.agent || ''}</strong></p>
            <p>当前设备不可在这里强制下线。</p>
          </div>
        )} />
    </div>
  );
};
