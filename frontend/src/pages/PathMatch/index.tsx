import React, { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { batchApi, plansApi } from '../../api/domain';
import type { PathMatchGroup, PathMatchPreviewResponse } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import { useTitle } from '../../hooks/useTitle';
import { splitLines } from '../../utils/format';
import {
  type PathMatchMode, buildPathMatchRequest, buildPathMatchPlanItems,
  canCreatePathMatchPlan,
} from '../../utils/pathMatchSafety';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { CodePath } from '../../components/ui/CodePath';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { getPaginationState } from '../../components/ui/paginationModel';

/** Path Match Preview is read-only; the only write here creates a guarded Plan Draft. */
export const PathMatchPage: React.FC = () => {
  useTitle('路径匹配');
  const navigate = useNavigate();
  const toast = useConsoleToast();
  const [roots, setRoots] = useState<string[]>([]);
  const [mode, setMode] = useState<PathMatchMode>('relative-path');
  const [normalizePattern, setNormalizePattern] = useState('');
  const [normalizeReplacement, setNormalizeReplacement] = useState('');
  const [report, setReport] = useState<PathMatchPreviewResponse | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [planLoading, setPlanLoading] = useState(false);
  const activePreviewKey = useRef<string | null>(null);
  const requestTicket = useRef(0);
  const previewGuard = useRef(false);
  const planGuard = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activePreviewKey.current = null;
      requestTicket.current += 1;
    };
  }, []);

  const invalidatePreview = () => {
    requestTicket.current += 1;
    activePreviewKey.current = null;
    setReport(null);
    setPage(1);
  };
  const changeRoots = (next: string | string[]) => {
    if (planGuard.current) return;
    setRoots(Array.isArray(next) ? [...next] : splitLines(next));
    invalidatePreview();
  };
  const changeMode = (next: PathMatchMode) => {
    if (planGuard.current) return;
    setMode(next);
    invalidatePreview();
  };
  const changePattern = (next: string) => {
    if (planGuard.current) return;
    setNormalizePattern(next);
    invalidatePreview();
  };
  const changeReplacement = (next: string) => {
    if (planGuard.current) return;
    setNormalizeReplacement(next);
    invalidatePreview();
  };

  const previewMutation = useMutation({ mutationFn: batchApi.previewPathMatch });
  const planMutation = useMutation({ mutationFn: plansApi.createPlan });
  const input = buildPathMatchRequest(roots, mode, normalizePattern, normalizeReplacement);
  const currentKey = input ? JSON.stringify(input) : null;
  const busy = previewLoading || planLoading || previewGuard.current || planGuard.current;
  const canPlan = canCreatePathMatchPlan(report, activePreviewKey.current, currentKey, busy);
  const groups = report?.groups || [];
  const pagination = getPaginationState(page, pageSize, groups.length);
  const visibleGroups = groups.slice(
    (pagination.current - 1) * pageSize, pagination.current * pageSize,
  );

  const handlePreview = async () => {
    if (previewGuard.current || planGuard.current) return;
    if (roots.length < 2) {
      toast.error('路径匹配至少需要选择或输入 2 个根目录进行比对');
      return;
    }
    const request = buildPathMatchRequest(roots, mode, normalizePattern, normalizeReplacement);
    if (!request) {
      toast.error(mode === 'normalized' && !normalizePattern.trim()
        ? 'normalized 模式必须输入正则查找 Pattern'
        : '请检查目录列表与匹配规则（不可重复选择根目录）');
      return;
    }
    invalidatePreview();
    const ticket = requestTicket.current;
    const key = JSON.stringify(request);
    activePreviewKey.current = key;
    previewGuard.current = true;
    setPreviewLoading(true);
    try {
      const fresh = await previewMutation.mutateAsync(request);
      if (!mountedRef.current || requestTicket.current !== ticket ||
          activePreviewKey.current !== key) return;
      setReport(fresh);
      toast.success('匹配完成，发现 ' + fresh.groups.length + ' 组匹配路径');
    } catch (error: unknown) {
      if (mountedRef.current && requestTicket.current === ticket &&
          activePreviewKey.current === key) {
        invalidatePreview();
        toast.error(getStructuredApiError(error).message || '路径匹配失败');
      }
    } finally {
      previewGuard.current = false;
      if (mountedRef.current) setPreviewLoading(false);
    }
  };

  const handleGeneratePlan = async () => {
    if (previewGuard.current || planGuard.current || !canPlan || !input || !report) return;
    const captured = report;
    const request = input;
    const key = activePreviewKey.current;
    const ticket = requestTicket.current;
    if (JSON.stringify(request) !== key) return;
    planGuard.current = true;
    setPlanLoading(true);
    try {
      // No digest in this legacy API: re-preview and compare each member/order/size/mtime.
      // A changed report fails closed. Freeze/Validate still enforce authoritative file identity.
      const fresh = await batchApi.previewPathMatch(request);
      if (!mountedRef.current || requestTicket.current !== ticket ||
          activePreviewKey.current !== key) return;
      const items = buildPathMatchPlanItems(captured, fresh);
      if (!items) {
        invalidatePreview();
        toast.error('候选路径或文件信息已变化，请重新进行只读比对');
        return;
      }
      const created = await planMutation.mutateAsync({
        name: '路径匹配去重计划',
        kind: 'path-match-dedupe',
        items,
      });
      if (!mountedRef.current || requestTicket.current !== ticket) return;
      toast.success('已创建路径匹配处理计划 #' + created.id + '，仍需冻结与校验');
      navigate('/plans/' + created.id);
    } catch (error: unknown) {
      if (mountedRef.current && requestTicket.current === ticket) {
        toast.error(getStructuredApiError(error).message || '生成计划失败');
      }
    } finally {
      planGuard.current = false;
      if (mountedRef.current) setPlanLoading(false);
    }
  };

  const memberList = (group: PathMatchGroup) => (
    <div className="nfc-path-match-members">
      {(group.members || []).map((member, index) => (
        <div className="nfc-path-match-member" key={member.path + '-' + index}>
          <StatusBadge status={index === 0 ? 'completed' : 'paused'}
            label={index === 0 ? '保留首选' : '副本 #' + index} />
          <span className="nfc-kind-badge">{member.root}</span>
          <CodePath value={member.path} />
        </div>
      ))}
    </div>
  );

  return (
    <div className="nfc-operations-page nfc-path-match-page nfc-page-layout-workbench nfc-v2-path-match">
      <PageHeader title="跨目录路径匹配"
        description="按相对路径、basename、stem 或正则归一化跨根目录匹配；Preview 只读，生成 Plan 后仍需完整生命周期校验。" />
      <DataPanel title="匹配规则"
        description="至少选择两个根目录；路径必须位于 ALLOWED_ROOTS。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench">
        <div className="nfc-path-match-form nfc-v2-path-match-form">
          <div className="nfc-v2-path-match-field">
            <label id="nfc-path-match-roots-label">比对根目录（至少 2 个）</label>
            <div aria-labelledby="nfc-path-match-roots-label">
              <DirectoryPicker multiple value={roots} disabled={planLoading}
                placeholder="点击选择或添加待比对根目录（至少 2 个）"
                onChange={value => changeRoots(value)} />
            </div>
          </div>
          <div className="nfc-v2-path-match-field">
            <label htmlFor="nfc-path-match-mode">匹配模式</label>
            <select id="nfc-path-match-mode" value={mode} disabled={planLoading}
              onChange={event => changeMode(event.target.value as PathMatchMode)}>
              <option value="relative-path">相对路径完全匹配 (Relative Path)</option>
              <option value="basename">文件名匹配 (Basename)</option>
              <option value="stem">去除后缀主名匹配 (Stem)</option>
              <option value="normalized">正则归一化路径匹配 (Normalized Regex)</option>
            </select>
          </div>
          {mode === 'normalized' && (
            <div className="nfc-form-grid">
              <div className="nfc-v2-path-match-field">
                <label htmlFor="nfc-path-match-pattern">归一化正则查找</label>
                <input id="nfc-path-match-pattern" value={normalizePattern}
                  disabled={planLoading} placeholder="例如：方括号内的版本号"
                  onChange={event => changePattern(event.target.value)} />
                <small>Pattern 必填；例如去除方括号标注或 _backup。</small>
              </div>
              <div className="nfc-v2-path-match-field">
                <label htmlFor="nfc-path-match-replacement">正则替换内容</label>
                <input id="nfc-path-match-replacement" value={normalizeReplacement}
                  disabled={planLoading} placeholder="替换为（默认留空清除）"
                  onChange={event => changeReplacement(event.target.value)} />
              </div>
            </div>
          )}
          <ActionBar className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={previewLoading} disabled={planLoading}
              leadingIcon={<ConsoleIcon name="play" size={17} />}
              onClick={() => { void handlePreview(); }}>开始只读比对</ConsoleButton>
            {report && groups.length > 0 && (
              <ConsoleButton leadingIcon={<ConsoleIcon name="calendar" size={17} />}
                disabled={!canPlan} loading={planLoading}
                onClick={() => { void handleGeneratePlan(); }}>
                生成去重 Plan（{groups.length} 组）
              </ConsoleButton>
            )}
          </ActionBar>
        </div>
      </DataPanel>
      <div className="nfc-v2-path-match-notice nfc-page-alert" role="note">
        <ConsoleIcon name="info" size={19} />
        <div>
          <strong>仅按路径/名称匹配，不代表文件内容相同</strong>
          <p>每组首个成员为 keep，其他成员仅作为 Quarantine Draft 候选。
            创建 Draft 前会重新比对；后续必须冻结与校验，页面不会直接隔离或删除文件。</p>
        </div>
      </div>
      {report && (
        <DataPanel title="路径匹配 Preview" variant="dense"
          className="nfc-panel-flush nfc-file-tool-result-panel"
          description="每组第一个成员作为 keep，后续成员作为 Quarantine Plan 候选；此处尚未修改文件。"
          action={<span className="nfc-panel-count">{groups.length} groups</span>}>
          {groups.length === 0 ? (
            <ConsoleEmpty title="未发现匹配组"
              description="可以调整根目录或匹配规则，再执行只读比对。" />
          ) : (
            <ResponsiveDataView
              desktop={<div className="nfc-v2-path-match-table-scroll">
                <table className="nfc-v2-path-match-table">
                  <caption>路径匹配候选，首个成员为保留项</caption>
                  <thead><tr><th scope="col">匹配键</th><th scope="col">匹配路径</th></tr></thead>
                  <tbody>{visibleGroups.map(group => (
                    <tr key={group.key}>
                      <td><span className="nfc-mono">{group.key}</span></td>
                      <td>{memberList(group)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>}
              mobile={<div className="nfc-mobile-record-list nfc-v2-path-match-mobile">
                {visibleGroups.map(group => (
                  <article className="nfc-path-match-mobile-card" key={group.key}>
                    <div className="nfc-mobile-record-heading">
                      <strong className="nfc-mobile-record-title nfc-mono">{group.key}</strong>
                      <span className="nfc-panel-count">{group.members.length} members</span>
                    </div>
                    {memberList(group)}
                  </article>
                ))}
              </div>}
            />
          )}
          <ConsolePagination page={pagination.current} pageSize={pageSize} total={groups.length}
            pageSizes={[10, 20, 50, 100]}
            onChange={(nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); }} />
        </DataPanel>
      )}
    </div>
  );
};
