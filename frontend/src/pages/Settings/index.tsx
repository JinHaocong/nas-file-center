import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Laptop, Smartphone, Tablet } from 'lucide-react';
import { settingsApi, dataLifecycleApi, auditApi, quarantineApi, resourcePolicyApi } from '../../api/domain';
import { authApi } from '../../api/auth';
import { getStructuredApiError } from '../../api/errors';
import { useAuth } from '../../contexts/AuthContext';
import { useTheme, type ThemeMode } from '../../contexts/ThemeContext';
import { useTitle } from '../../hooks/useTitle';
import { formatDateTime } from '../../utils/format';
import type { SessionInfo, ResourcePolicy, ResourcePolicyUpdate } from '../../types';
import {
  formatAuditRetention, getAuditRetentionApplyAvailability,
  getAuditRetentionSaveAvailability, getQuarantineRetentionSaveAvailability,
  validateRetentionDaysInput,
} from '../../components/settings/data_lifecycle';
import {
  COMMON_TIMEZONES, validateResourcePolicyUpdate, getProfileDisplay,
} from '../../components/settings/resource_policy';
import { PageHeader } from '../../components/ui/PageHeader';
import { ZSpaceAuthorization } from '../../components/settings/ZSpaceAuthorization';
import { DatabaseMaintenance } from '../../components/settings/DatabaseMaintenance';
import { SettingsGroup, SettingsRow, SettingsStatus } from '../../components/settings/SettingsRows';
import { DataPanel } from '../../components/ui/DataPanel';
import { ThumbnailSwitch } from '../../components/ui/MediaThumbnail';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon, type ConsoleIconName } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleConfirmDialog } from '../../components/ui/ConsoleConfirmDialog';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { useResponsive } from '../../hooks/useResponsive';

type Confirmation =
  | { kind: 'clear' }
  | { kind: 'retention'; days: number; deleteCount: number }
  | { kind: 'revoke'; sessionId: SessionInfo['id']; agent: string };

type StatusTone = 'success' | 'warning' | 'danger' | 'neutral';
const status = (tone: StatusTone, label: string) => <SettingsStatus tone={tone}>{label}</SettingsStatus>;
const failure = (error: unknown, fallback: string) =>
  getStructuredApiError(error).message || fallback;

const settingsSections = [
  { id: 'appearance', label: '界面显示' },
  { id: 'safety', label: '安全与授权' },
  { id: 'retention', label: '保留与清理' },
  { id: 'database', label: '数据库维护', admin: true },
  { id: 'resources', label: '资源控制', admin: true },
  { id: 'sessions', label: '登录设备' },
] as const;

type SettingsSectionId = typeof settingsSections[number]['id'];

const settingsIcons: Record<Exclude<SettingsSectionId, 'sessions'>, ConsoleIconName> = {
  appearance: 'sun', safety: 'shield-check', retention: 'archive', database: 'database', resources: 'sliders',
};

const themeChoices: { mode: ThemeMode; label: string }[] = [
  { mode: 'light', label: '浅色' }, { mode: 'dark', label: '深色' }, { mode: 'system', label: '系统' },
];

/** 用易读的浏览器和平台名显示会话，原始标识仍保留在详情中。 */
function sessionDeviceName(agent: string) {
  const browser = /Edg\//i.test(agent) ? 'Edge' : /(?:Chrome|CriOS)\//i.test(agent) ? 'Chrome'
    : /(?:Firefox|FxiOS)\//i.test(agent) ? 'Firefox' : /Safari\//i.test(agent) ? 'Safari' : '';
  const platform = (agent.match(/iPhone|iPad|Android|Windows|Mac OS X|Linux/i)?.[0] ?? '').replace(/Mac OS X/i, 'macOS');
  return [browser, platform].filter(Boolean).join(' · ') || agent || '未知设备';
}

/** 以本地时间绘制活跃区间，跨午夜的时段拆成前后两段。 */
function ResourceWindowTrack({ start, end }: { start: string; end: string }) {
  const hours = (time: string) => {
    if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)) return NaN;
    const [hour, minute] = time.split(':').map(Number);
    return (hour * 60 + minute) * 100 / (24 * 60);
  };
  const [from, to] = [hours(start), hours(end)];
  const ranges = !Number.isFinite(from + to) || from === to ? [] : from < to ? [[from, to]] : [[0, to], [from, 100]];
  return <div className="nfc-settings-time-rule">
    <div className="nfc-settings-time-track" aria-hidden="true">{ranges.map(([left, right]) =>
      <i key={left} style={{ insetInlineStart: left + '%', width: (right - left) + '%' }} />)}</div>
    <div className="nfc-settings-time-labels"><span>00:00</span><strong>{start} – {end}</strong><span>24:00</span></div>
  </div>;
}

/** 方向键切换设置分区，Home 和 End 分别跳到首尾标签。 */
function handleSettingsTabKey(
  event: React.KeyboardEvent<HTMLButtonElement>,
  index: number,
  sections: ReadonlyArray<typeof settingsSections[number]>,
  onSelect: (id: SettingsSectionId) => void,
  vertical: boolean,
) {
  const last = sections.length - 1;
  const next = event.key === (vertical ? 'ArrowDown' : 'ArrowRight') ? (index === last ? 0 : index + 1)
    : event.key === (vertical ? 'ArrowUp' : 'ArrowLeft') ? (index === 0 ? last : index - 1)
    : event.key === 'Home' ? 0 : event.key === 'End' ? last : -1;
  if (next < 0) return;
  event.preventDefault();
  onSelect(sections[next].id);
  event.currentTarget.closest('[role=tablist]')?.querySelectorAll<HTMLButtonElement>('[role=tab]')[next]?.focus();
}

function SettingsSectionNav({ sections, active, onSelect }: {
  sections: ReadonlyArray<typeof settingsSections[number]>;
  active: SettingsSectionId;
  onSelect: (id: SettingsSectionId) => void;
}) {
  const { isDesktop } = useResponsive();
  const selectedTab = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (isDesktop) return;
    const tab = selectedTab.current;
    const list = tab?.parentElement;
    if (!tab || !list || list.scrollWidth <= list.clientWidth) return;
    const offset = tab.getBoundingClientRect().left - list.getBoundingClientRect().left;
    if (offset < 0 || offset + tab.offsetWidth > list.clientWidth) {
      list.scrollLeft += offset - (list.clientWidth - tab.offsetWidth) / 2;
    }
  }, [active, isDesktop]);
  return (
    <div className="nfc-settings-section-nav" role="tablist" aria-label="设置分区"
      aria-orientation={isDesktop ? 'vertical' : 'horizontal'}>
      {sections.map((section, index) => (
        <button key={section.id} id={'settings-tab-' + section.id} type="button" role="tab"
          aria-selected={active === section.id} aria-controls="nfc-settings-active-panel"
          ref={active === section.id ? selectedTab : undefined}
          tabIndex={active === section.id ? 0 : -1}
          onClick={() => onSelect(section.id)}
          onKeyDown={event => handleSettingsTabKey(event, index, sections, onSelect, isDesktop)}>
          {section.id === 'sessions' ? <Laptop size={17} strokeWidth={1.85} aria-hidden="true" />
            : <ConsoleIcon name={settingsIcons[section.id]} size={17} />}
          {section.label}
          {isDesktop && active === section.id && <ConsoleIcon name="chevron-right" className="nfc-settings-tab-arrow" size={13} />}
        </button>
      ))}
    </div>
  );
}

/** Environment-authoritative security flags; no Web UI action can enable mutation or deletion. */
export const SettingsPage: React.FC = () => {
  useTitle('系统设置');
  const toast = useConsoleToast();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const { mode: themeMode, setMode: setThemeMode } = useTheme();
  const isAdmin = user?.role === 'admin';
  const { pathname, search, hash } = useLocation();
  const navigate = useNavigate();
  const visibleSections = settingsSections.filter(section => !('admin' in section) || isAdmin);
  const activeSection = visibleSections.find(section => hash === '#' + section.id)?.id ?? 'appearance';

  /** 使用同一页面的 URL 片段保存当前标签，支持直达和浏览器前进后退。 */
  const selectSection = (id: SettingsSectionId) => {
    if (id !== activeSection) navigate({ pathname, search, hash: '#' + id });
  };

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

  /** 放弃本次清理预览，释放其准备状态并允许重新发起。 */
  function discardRetentionPreparation() {
    prepareTicket.current += 1;
    pendingActions.current.delete('audit-prepare');
    setPrepareApplyPending(false);
  }

  useLayoutEffect(() => {
    if (activeSection === 'retention') return;
    discardRetentionPreparation();
    if (!pendingActions.current.has('audit-action')) {
      setConfirmation(current => current?.kind === 'retention' ? null : current);
    }
  }, [activeSection]);

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
  const { data: resourcePolicy, isFetching: policyLoading, isError: resourcePolicyError, refetch: refetchResourcePolicy } = useQuery({
    queryKey: ['resourcePolicy'], queryFn: resourcePolicyApi.getPolicy, enabled: !!isAdmin,
  });
  const savedWindowTimezone = resourcePolicy?.active_window_timezone;
  const windowTimezones = savedWindowTimezone && !COMMON_TIMEZONES.includes(savedWindowTimezone)
    ? [...COMMON_TIMEZONES, savedWindowTimezone] : COMMON_TIMEZONES;
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
  /** 以服务端已保存的值恢复资源表单。 */
  function resetResourceDraft(policy: ResourcePolicy) {
    setScanThreadsInput(policy.scan_threads);
    setHashThreadsInput(policy.hash_threads);
    setIoLimitInput(policy.io_limit);
    setJobPriorityInput(policy.job_priority);
    setWindowEnabledInput(policy.active_window_enabled);
    setWindowStartInput(policy.active_window_start || '01:00');
    setWindowEndInput(policy.active_window_end || '07:00');
    setWindowTimezoneInput(policy.active_window_timezone || 'UTC');
    setOutsideModeInput(policy.outside_window_mode);
  }

  useEffect(() => { if (resourcePolicy) resetResourceDraft(resourcePolicy); }, [resourcePolicy]);

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

  const resourceDraft: ResourcePolicyUpdate = {
    scan_threads: scanThreadsInput, hash_threads: hashThreadsInput,
    io_limit: ioLimitInput, job_priority: jobPriorityInput,
    active_window_enabled: windowEnabledInput,
    active_window_start: windowEnabledInput ? windowStartInput : null,
    active_window_end: windowEnabledInput ? windowEndInput : null,
    active_window_timezone: windowEnabledInput ? windowTimezoneInput : null,
    outside_window_mode: outsideModeInput,
  };
  const resourceDirty = !!resourcePolicy && (Object.keys(resourceDraft) as (keyof ResourcePolicyUpdate)[])
    .some(key => resourceDraft[key] !== resourcePolicy[key]);

  const handleSaveResourcePolicy = () => {
    if (rejectNonAdmin('修改资源控制策略') || !resourceDirty) return;
    const payload = resourceDraft;
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
    discardRetentionPreparation();
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
      // 新预览可能已开始，只有当前请求能释放该准备状态。
      if (mountedRef.current && ticket === prepareTicket.current) {
        pendingActions.current.delete('audit-prepare');
        setPrepareApplyPending(false);
      }
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
    session.is_current ? status('success', '当前设备')
      : isAdmin ? <ConsoleButton size="sm"
        disabled={revokeMutation.isPending || confirmBusy}
        leadingIcon={<ConsoleIcon name="log-out" size={15} />}
        onClick={() => handleRevokeSession(session)}>注销设备</ConsoleButton>
        : <span className="nfc-v2-settings-muted">仅管理员可管理</span>;
  const deviceLabel = (session: SessionInfo) => {
    const DeviceIcon = /ipad|tablet/i.test(session.user_agent) ? Tablet
      : /mobile|iphone|android/i.test(session.user_agent) ? Smartphone : Laptop;
    return <div className="nfc-v2-settings-device">
      <span className="nfc-settings-device-icon"><DeviceIcon size={17} strokeWidth={1.85} aria-hidden="true" /></span>
      <span className="nfc-session-user-agent" title={session.user_agent}>{sessionDeviceName(session.user_agent)}</span>
    </div>;
  };
  const deviceFacts = (session: SessionInfo) => <div className="nfc-settings-device-facts">
    <span>{session.ip_address}</span>
    <span>最近活动 {formatDateTime(session.last_seen_at)}</span>
    <span>{formatDateTime(session.created_at)} 登录</span>
  </div>;
  const sessions = sessionsData?.sessions || [];
  const profile = resourcePolicy ? getProfileDisplay(resourcePolicy.effective_now.profile) : undefined;

  return (
    <div className="nfc-operations-page nfc-settings-page nfc-system-controls-page nfc-page-layout-workbench nfc-v2-settings nfc-tool-workspace nfc-settings-redesign">
      <PageHeader title="系统设置与安全中心"
        actions={<ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
          onClick={() => {
            void refetchSettings(); void refetchSessions(); void refetchPolicy();
            void refetchPreview(); void refetchQuarantinePolicy();
            if (isAdmin) {
              void refetchResourcePolicy();
              void queryClient.invalidateQueries({ queryKey: ['settings', 'database-maintenance'] });
              void queryClient.invalidateQueries({ queryKey: ['settings', 'zspace-authorization'] });
            }
          }}>刷新全部</ConsoleButton>}
      />

      <div className="nfc-tool-settings-layout">
        <SettingsSectionNav sections={visibleSections} active={activeSection} onSelect={selectSection} />
        <div className="nfc-settings-grid" id="nfc-settings-active-panel" key={activeSection}
          role="tabpanel" aria-labelledby={'settings-tab-' + activeSection} tabIndex={0}>
          {activeSection === 'appearance' && <DataPanel id="appearance" title="界面显示"
            className="nfc-settings-appearance" description="在当前浏览器保存外观和媒体显示偏好。">
            <div className="nfc-settings-groups">
              <SettingsGroup title="外观">
                <SettingsRow label="主题模式" description="选择浅色、深色或跟随系统。">
                  <div className="nfc-settings-theme-choices" role="group" aria-label="主题模式">
                    {themeChoices.map(({ mode, label }) => <button key={mode} type="button" aria-pressed={mode === themeMode}
                      onClick={() => setThemeMode(mode)}>
                      <span className={'nfc-settings-theme-example theme-' + mode} aria-hidden="true" />{label}
                    </button>)}
                  </div>
                </SettingsRow>
              </SettingsGroup>
              <SettingsGroup title="文件与预览">
                <SettingsRow label="媒体缩略图" description="应用于文件空间、媒体、目录选择和整理预览。">
                  <ThumbnailSwitch />
                </SettingsRow>
              </SettingsGroup>
            </div>
            <div className="nfc-settings-panel-footer">
              <span className="nfc-settings-footer-message"><ConsoleIcon name="check-circle" size={15} />偏好保存在当前浏览器</span>
            </div>
          </DataPanel>}

          {activeSection === 'safety' && <DataPanel id="safety" title="安全与授权"
            className="nfc-settings-panel-runtime" description="查看文件操作权限、访问范围和极空间授权状态。">
            <div className="nfc-settings-groups">
              {settingsError && <p role="alert" className="nfc-v2-settings-error">安全运行参数读取失败，请刷新重试。</p>}
              <SettingsGroup title="文件操作权限" action={<span title="通过宿主机 Docker Compose 环境变量配置"><SettingsStatus>宿主机配置</SettingsStatus></span>}>
                <SettingsRow label="文件写入" description="来自服务器运行配置。">
                  <span title="ALLOW_MUTATION">{settings ? settings.allow_mutation ? status('warning', '允许写入') : status('success', '只读保护') : '—'}</span>
                </SettingsRow>
                <SettingsRow label="永久删除" description="隔离区操作遵守当前安全策略。">
                  <span title="ALLOW_DELETE">{settings ? settings.allow_delete ? status('danger', '允许永久删除') : status('success', '已禁用') : '—'}</span>
                </SettingsRow>
                <SettingsRow label="最后副本保护" description="保持每组文件至少有一个副本。">
                  <span title="PROTECT_LAST_FILE">{settings ? settings.protect_last_file ? status('success', '已启用') : status('danger', '未启用') : '—'}</span>
                </SettingsRow>
              </SettingsGroup>
              <SettingsGroup title="目录与校验">
                <SettingsRow label="允许访问目录">
                  <div className="nfc-settings-path-list" title="ALLOWED_ROOTS">{settings?.allowed_roots.map(root => <CodePath key={root} value={root} />)}</div>
                </SettingsRow>
                <SettingsRow label="隔离区位置"><span title="QUARANTINE_ROOT"><CodePath value={settings?.quarantine_root} /></span></SettingsRow>
                <SettingsRow label="去重校验"><SettingsStatus>{settings?.verification_hash?.toUpperCase() || '—'}</SettingsStatus></SettingsRow>
              </SettingsGroup>
              {isAdmin && <ZSpaceAuthorization />}
            </div>
          </DataPanel>}

          {activeSection === 'retention' && <DataPanel id="retention" title="保留与清理" className="nfc-settings-panel-lifecycle"
            description="管理审计日志和文件隔离区的保留时间。清理时先核对预览。">
            <div className="nfc-settings-groups">
              <SettingsGroup title="保留时间">
                <SettingsRow label="审计日志" description={retentionDaysInput === 0
                  ? '0 天表示永久保留。' : '保存后按新的保留期计算清理预览。'}>
                  <label className="nfc-settings-number-field">
                    <input aria-label="审计日志保留天数" type="number" min={0} max={3650} step={1}
                      value={retentionDaysInput ?? ''} list="nfc-settings-audit-presets" disabled={savePolicyMutation.isPending}
                      onChange={event => setRetentionDaysInput(event.target.value === '' ? null : Number(event.target.value))} />
                    <span aria-hidden="true">天</span>
                  </label>
                  <datalist id="nfc-settings-audit-presets">
                    {[0, 30, 90, 180, 365].map(days => <option key={days} value={days}>{days === 0 ? '永久保留' : days + ' 天'}</option>)}
                  </datalist>
                  <ConsoleButton size="sm" loading={savePolicyMutation.isPending} disabled={!auditSaveAvail.canSave}
                    title={!isAdmin ? '仅系统管理员允许修改审计保留策略' : auditSaveAvail.disabledReason}
                    leadingIcon={<ConsoleIcon name="check" size={15} />} onClick={handleSavePolicy}>保存</ConsoleButton>
                </SettingsRow>
                <SettingsRow label="文件隔离区" description={quarantineDaysInput === 0
                  ? '保留期用于决定记录何时到期。' : '到期后仍需管理员审阅并确认清除。'}>
                  <select className="nfc-settings-select" aria-label="文件隔离区保留周期" value={quarantineDaysInput}
                    disabled={saveQuarantinePolicyMutation.isPending} onChange={event => setQuarantineDaysInput(Number(event.target.value))}>
                    <option value={0}>永久保留</option>
                    <option value={7}>7 天</option>
                    <option value={30}>30 天</option>
                    <option value={90}>90 天</option>
                  </select>
                  <ConsoleButton size="sm" loading={saveQuarantinePolicyMutation.isPending} disabled={!quarantineSaveAvail.canSave}
                    title={!isAdmin ? '仅系统管理员允许修改隔离区保留策略' : quarantineSaveAvail.disabledReason}
                    leadingIcon={<ConsoleIcon name="check" size={15} />} onClick={handleSaveQuarantinePolicy}>保存</ConsoleButton>
                </SettingsRow>
              </SettingsGroup>

              <SettingsGroup title="审计清理">
                <SettingsRow label="到期日志" description={retentionPreview?.cutoff
                  ? '截止于 ' + formatDateTime(retentionPreview.cutoff) : formatAuditRetention(lifecyclePolicy?.audit_retention_days)}>
                  {retentionPreview && status(retentionPreview.delete_count > 0 ? 'warning' : 'neutral', '可清理 ' +
                    retentionPreview.delete_count.toLocaleString('zh-CN') + ' 条')}
                  <ConsoleButton size="sm" variant="primary"
                    loading={applyRetentionMutation.isPending || prepareApplyPending}
                    disabled={!availability.canApply || !!confirmation}
                    title={!isAdmin ? '仅系统管理员允许执行审计日志清理' : availability.disabledReason}
                    leadingIcon={<ConsoleIcon name="arrow-right" size={15} />}
                    onClick={() => { void handlePrepareApply(); }}>查看清理预览</ConsoleButton>
                </SettingsRow>
                <SettingsRow label="当前日志总数" description={retentionPreview
                  ? '预计清理后保留 ' + retentionPreview.keep_count.toLocaleString('zh-CN') + ' 条。' : undefined}>
                  {retentionPreview && <strong className="nfc-settings-count">{retentionPreview.total_count.toLocaleString('zh-CN')} 条</strong>}
                  {(previewQueryError || policyQueryError) && <ConsoleButton size="sm" loading={previewLoading}
                    onClick={() => { void refetchPolicy(); void refetchPreview(); }}>重新读取</ConsoleButton>}
                </SettingsRow>
                {(previewQueryError || policyQueryError) &&
                  <p className="nfc-v2-settings-error" role="alert">保留策略或清理预览读取失败。</p>}
              </SettingsGroup>

              <div className="nfc-settings-danger-zone">
                <SettingsRow label="立即清空审计历史" description="执行前需要确认，系统保留一条清空操作记录。">
                  <ConsoleButton variant="danger" size="sm" loading={clearAuditMutation.isPending}
                    disabled={!isAdmin || !!confirmation || prepareApplyPending || savePolicyMutation.isPending}
                    title={!isAdmin ? '仅管理员可立即清空' : '忽略保留期，清空 Audit 历史，仅保留一条自审计'}
                    leadingIcon={<ConsoleIcon name="trash" size={15} />} onClick={handleClearAuditHistory}>立即清空</ConsoleButton>
                </SettingsRow>
              </div>
            </div>
          </DataPanel>}

          {activeSection === 'database' && isAdmin && <DatabaseMaintenance />}

          {activeSection === 'resources' && isAdmin && <DataPanel id="resources" title="资源控制" className="nfc-settings-panel-resource"
            description="设置扫描、哈希并发以及资源任务可运行的时间段。">
            <div className="nfc-settings-groups">
              {resourcePolicyError && <p className="nfc-v2-settings-error" role="alert">资源策略读取失败，请刷新重试。</p>}
              {resourcePolicy && profile && <SettingsGroup title="当前生效">
                <SettingsRow label={profile.text} description={'资源策略 rev.' + resourcePolicy.revision +
                  ' · 有效线程上限 ' + resourcePolicy.effective_now.effective_thread_cap}>
                  {resourcePolicy.effective_now.resource_jobs_admitted ? status('success', '允许认领') : status('warning', '暂停认领')}
                </SettingsRow>
              </SettingsGroup>}
              <SettingsGroup title="并发与调度">
                <SettingsRow label="扫描线程上限">
                  <label className="nfc-settings-number-field">
                    <input type="number" aria-label="扫描线程上限" min={1} max={32} step={1} value={scanThreadsInput || ''}
                      disabled={!resourcePolicy || saveResourcePolicyMutation.isPending}
                      onChange={event => setScanThreadsInput(event.target.value === '' ? 0 : Number(event.target.value))} />
                    <span aria-hidden="true">线程</span>
                  </label>
                </SettingsRow>
                <SettingsRow label="哈希线程上限">
                  <label className="nfc-settings-number-field">
                    <input type="number" aria-label="哈希线程上限" min={1} max={32} step={1} value={hashThreadsInput || ''}
                      disabled={!resourcePolicy || saveResourcePolicyMutation.isPending}
                      onChange={event => setHashThreadsInput(event.target.value === '' ? 0 : Number(event.target.value))} />
                    <span aria-hidden="true">线程</span>
                  </label>
                </SettingsRow>
                <SettingsRow label="I/O 压力">
                  <select className="nfc-settings-select" aria-label="I/O 压力" value={ioLimitInput}
                    disabled={!resourcePolicy || saveResourcePolicyMutation.isPending}
                    onChange={event => setIoLimitInput(event.target.value as typeof ioLimitInput)}>
                    <option value="low">低压模式</option>
                    <option value="normal">标准模式</option>
                    <option value="unlimited">无上限模式</option>
                  </select>
                </SettingsRow>
                <SettingsRow label="任务队列">
                  <select className="nfc-settings-select" aria-label="任务队列" value={jobPriorityInput}
                    disabled={!resourcePolicy || saveResourcePolicyMutation.isPending}
                    onChange={event => setJobPriorityInput(event.target.value as typeof jobPriorityInput)}>
                    <option value="normal">先进先出</option>
                    <option value="background">后台让步</option>
                  </select>
                </SettingsRow>
              </SettingsGroup>
              <SettingsGroup title="活跃时间窗口">
                <SettingsRow label="允许时段" description={windowEnabledInput
                  ? windowTimezoneInput + ' · 窗口外' + (outsideModeInput === 'limited' ? '降速运行' : '暂停认领')
                  : '开启后可限制扫描与索引任务的运行时间。'}>
                  {windowEnabledInput && <ResourceWindowTrack start={windowStartInput} end={windowEndInput} />}
                  <label className="nfc-settings-toggle">
                    <input type="checkbox" checked={windowEnabledInput} disabled={!resourcePolicy || saveResourcePolicyMutation.isPending}
                      onChange={event => setWindowEnabledInput(event.target.checked)}
                      aria-label="启用活跃时间窗口" role="switch" aria-checked={windowEnabledInput} />
                    <span aria-hidden="true" />
                  </label>
                </SettingsRow>
                {windowEnabledInput && <details className="nfc-settings-window-details">
                  <summary>编辑时段 <ConsoleIcon name="chevron-down" size={14} /></summary>
                  <div className="nfc-settings-window-fields">
                    <label>开始 <input type="time" value={windowStartInput} disabled={saveResourcePolicyMutation.isPending}
                      onChange={event => setWindowStartInput(event.target.value)} /></label>
                    <label>结束 <input type="time" value={windowEndInput} disabled={saveResourcePolicyMutation.isPending}
                      onChange={event => setWindowEndInput(event.target.value)} /></label>
                    <label>时区 <select value={windowTimezoneInput} disabled={saveResourcePolicyMutation.isPending}
                      onChange={event => setWindowTimezoneInput(event.target.value)}>
                      {windowTimezones.map(tz => <option key={tz} value={tz}>{tz}</option>)}
                    </select></label>
                    <label>窗口外 <select value={outsideModeInput} disabled={saveResourcePolicyMutation.isPending}
                      onChange={event => setOutsideModeInput(event.target.value as typeof outsideModeInput)}>
                      <option value="limited">降速运行</option>
                      <option value="pause">暂停认领</option>
                    </select></label>
                  </div>
                </details>}
              </SettingsGroup>
            </div>
            <div className="nfc-settings-panel-footer">
              <span className="nfc-settings-footer-message" role="status">
                {resourceDirty ? '有未保存的更改' : policyLoading ? '正在读取资源策略…' : resourcePolicy ? '资源策略已保存' : ''}
              </span>
              <ActionBar compact>
                <ConsoleButton size="sm" disabled={!resourcePolicy || !resourceDirty || saveResourcePolicyMutation.isPending}
                  onClick={() => { if (resourcePolicy) resetResourceDraft(resourcePolicy); }}>取消修改</ConsoleButton>
                <ConsoleButton size="sm" variant="primary" disabled={!resourceDirty} loading={saveResourcePolicyMutation.isPending}
                  leadingIcon={<ConsoleIcon name="check" size={15} />} onClick={handleSaveResourcePolicy}>保存资源策略</ConsoleButton>
              </ActionBar>
            </div>
          </DataPanel>}

          {activeSection === 'sessions' && <DataPanel id="sessions" title="登录设备" className="nfc-settings-panel-sessions"
            description="查看登录会话和最近活动时间。"
            action={<ConsoleButton size="sm" leadingIcon={<ConsoleIcon name="refresh" size={15} />}
              loading={sessionsLoading} onClick={() => { void refetchSessions(); }}>刷新会话</ConsoleButton>}>
            <div className="nfc-settings-groups">
              {sessionsError ? <ConsoleEmpty title="活动会话获取失败"
                action={<ConsoleButton onClick={() => { void refetchSessions(); }}>重新加载</ConsoleButton>} />
                : sessionsLoading ? <div role="status" className="nfc-v2-settings-loading">正在加载设备会话…</div>
                : sessions.length === 0 ? <ConsoleEmpty title="暂无活动会话" />
                  : <SettingsGroup title="活动会话">
                    <ResponsiveDataView
                      desktop={<table className="nfc-v2-settings-table nfc-settings-device-list">
                        <caption>活动设备会话与注销操作</caption>
                        <thead className="nfc-settings-sr-only"><tr><th scope="col">设备及最近活动</th><th scope="col">操作</th></tr></thead>
                        <tbody>{sessions.map(session => <tr key={session.id}>
                          <td>{deviceLabel(session)}{deviceFacts(session)}</td><td>{sessionActions(session)}</td>
                        </tr>)}</tbody>
                      </table>}
                      mobile={<div className="nfc-settings-device-list">
                        {sessions.map(session => <article className="nfc-session-mobile-card" key={session.id}>
                          <SettingsRow label={deviceLabel(session)} description={deviceFacts(session)}>
                            {sessionActions(session)}
                          </SettingsRow>
                        </article>)}
                      </div>} />
                  </SettingsGroup>}
              {isAdmin && sessions.some(session => !session.is_current) &&
                <div className="nfc-settings-inline-note"><ConsoleIcon name="shield-check" size={15} />注销其他设备前需要确认。</div>}
            </div>
          </DataPanel>}
        </div>
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
            {retentionPreview?.oldest_timestamp && <p>最早记录 {formatDateTime(retentionPreview.oldest_timestamp)}</p>}
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
