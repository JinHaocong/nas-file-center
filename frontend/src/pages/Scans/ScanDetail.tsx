import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { scansApi } from '../../api/domain';
import { useTitle } from '../../hooks/useTitle';
import { formatBytes, formatDateTime } from '../../utils/format';
import type { DuplicateGroup } from '../../types';
import { DedupePlanModal } from './DedupePlanModal';
import { ScanDeleteButton } from '../../components/scans/ScanDeleteButton';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { ResponsiveDescriptions } from '../../components/ui/ResponsiveDescriptions';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { StatusBadge } from '../../components/ui/StatusBadge';
import { CodePath } from '../../components/ui/CodePath';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { DedupeDiagnosticModal } from '../../components/dedupe/DedupeDiagnosticModal';

export const ScanDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const scanId = Number(id);
  const validScanId = Number.isSafeInteger(scanId) && scanId > 0;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useConsoleToast();
  useTitle('扫描详情 #' + (validScanId ? scanId : '—'));

  const [planModalOpen, setPlanModalOpen] = useState(false);
  const [diagnosticOpen, setDiagnosticOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [expandedGroupIds, setExpandedGroupIds] = useState<number[]>([]);

  useEffect(() => {
    setPage(1);
    setExpandedGroupIds([]);
  }, [scanId]);

  const deleteScanMutation = useMutation({
    mutationFn: () => scansApi.deleteScan(scanId),
    onSuccess: () => {
      toast.success('扫描 #' + scanId + ' 已成功删除');
      queryClient.invalidateQueries({ queryKey: ['scansList'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardSummary'] });
      navigate('/scans');
    },
    onError: (err: Error) => toast.error(err.message || '删除扫描失败'),
  });

  const {
    data: scan, isLoading: scanLoading, isError: scanError,
    error: scanFetchError, isFetching: scanFetching, refetch: refetchScan,
  } = useQuery({
    queryKey: ['scanDetail', scanId],
    queryFn: () => scansApi.getScanDetail(scanId),
    enabled: validScanId,
    refetchInterval: query => {
      const status = query.state.data?.status;
      return status === 'queued' || status === 'running' ? 3000 : false;
    },
  });

  const {
    data: groupsData, isLoading: groupsLoading, isError: groupsError,
    error: groupsFetchError, refetch: refetchGroups,
  } = useQuery({
    queryKey: ['scanGroups', scanId, page, pageSize],
    queryFn: () => scansApi.getScanGroups(scanId, page, pageSize),
    enabled: validScanId && scan?.status === 'completed',
  });

  const changePage = (nextPage: number, nextSize: number) => {
    setExpandedGroupIds([]);
    if (nextSize !== pageSize) {
      setPageSize(nextSize);
      setPage(1);
    } else {
      setPage(nextPage);
    }
  };

  const toggleGroup = (groupId: number) => {
    setExpandedGroupIds(current => current.includes(groupId)
      ? current.filter(id => id !== groupId)
      : [...current, groupId]);
  };

  const memberTable = (group: DuplicateGroup) => (
    <div className="nfc-duplicate-member-table nfc-v2-duplicate-member-table">
      <table className="nfc-v2-group-member-table">
        <thead><tr>
          <th scope="col">Root</th>
          <th scope="col">相对路径</th>
          <th scope="col">完整路径</th>
          <th scope="col">大小</th>
        </tr></thead>
        <tbody>{group.members.map(member => (
          <tr key={member.id}>
            <td><span className="nfc-kind-badge">root #{member.root_id}</span></td>
            <td><CodePath value={member.relative_path} /></td>
            <td><CodePath value={member.path} /></td>
            <td className="nfc-v2-scan-number">{formatBytes(member.size)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );

  if (!validScanId || scanError || (!scanLoading && !scan)) {
    return (
      <div className="nfc-v2-scan-detail-error" role="alert">
        <h2>{!validScanId || (!scanLoading && !scan && !scanError)
          ? '扫描任务不存在' : '无法加载扫描详情'}</h2>
        <p>{scanFetchError instanceof Error ? scanFetchError.message
          : '未找到扫描任务 #' + (id || '—') + '，或扫描服务暂时不可用。'}</p>
        <ConsoleButton onClick={() => navigate('/scans')}>返回扫描列表</ConsoleButton>
        {validScanId && scanError && (
          <ConsoleButton onClick={() => refetchScan()}>重新加载</ConsoleButton>
        )}
      </div>
    );
  }

  if (scanLoading || !scan) {
    return <div className="nfc-centered-state nfc-v2-detail-loading" role="status">
      <span className="nfc-console-spinner" aria-hidden="true" /> 正在加载扫描详情…
    </div>;
  }

  const descriptionItems = [
    { label: '任务 ID', value: <span className="nfc-mono">#{scan.id}</span> },
    { label: '扫描模式', value: <span className="nfc-kind-badge">
      {scan.mode === 'isolate' ? 'A/B isolate' : 'standard'}
    </span> },
    { label: '创建时间', value: formatDateTime(scan.created_at) },
    { label: '开始时间', value: scan.started_at ? formatDateTime(scan.started_at) : '—' },
    { label: '完成时间', value: scan.finished_at ? formatDateTime(scan.finished_at) : '—' },
    { label: '发现重复组数', value: scan.total_groups.toLocaleString() + ' 组', emphasis: true },
    { label: '重复文件总数', value: scan.total_files_in_groups.toLocaleString() + ' 个', emphasis: true },
    { label: '预计可释放容量', value: formatBytes(scan.reclaimable_bytes), emphasis: true },
  ];

  const groupItems: DuplicateGroup[] = groupsError ? [] : groupsData?.items || [];
  const groupsTotal = groupsError ? null : groupsData?.total;

  return (
    <div className="nfc-operations-page nfc-scan-detail-page nfc-v2-scan-detail-page nfc-page-layout-detail">
      <PageHeader
        title={scan.name}
        description={
          <div className="nfc-plan-header-meta">
            <span className="nfc-mono">Scan #{scan.id}</span>
            <StatusBadge status={scan.status} />
            {scan.has_dependent_plan && <span className="nfc-kind-badge">dependent plan</span>}
          </div>
        }
        actions={
          <ActionBar compact>
            <ConsoleButton leadingIcon={<ConsoleIcon name="arrow-right" size={16} />}
              onClick={() => navigate('/scans')}>返回列表</ConsoleButton>
            <ConsoleButton leadingIcon={<ConsoleIcon name="refresh" size={16} />}
              onClick={() => {
                refetchScan();
                if (scan.status === 'completed') refetchGroups();
              }} loading={scanFetching}>刷新</ConsoleButton>
            <ConsoleButton leadingIcon={<ConsoleIcon name="search" size={16} />}
              onClick={() => setDiagnosticOpen(true)}>重复诊断</ConsoleButton>
            <ScanDeleteButton key={scan.id} scan={scan}
              onDelete={() => deleteScanMutation.mutate()}
              loading={deleteScanMutation.isPending}
              buttonText="删除扫描" type="default" />
            {scan.status === 'completed' && scan.total_groups > 0 && (
              <>
                <ConsoleButton leadingIcon={<ConsoleIcon name="list-checks" size={16} />}
                  onClick={() => setPlanModalOpen(true)}>经典去重计划</ConsoleButton>
                <ConsoleButton variant="primary" leadingIcon={<ConsoleIcon name="zap" size={16} />}
                  onClick={() => navigate('/scans/' + scan.id + '/dedupe')}>
                  高级去重 (Advanced Dedupe)
                </ConsoleButton>
              </>
            )}
          </ActionBar>
        }
      />

      {scan.error && (
        <div className="nfc-v2-detail-alert nfc-page-alert" role="alert">
          <strong>扫描执行失败</strong>
          <p>{scan.error}</p>
        </div>
      )}

      <DataPanel title="扫描摘要"
        description="扫描结果是只读快照；后续文件操作必须通过 Plan 生命周期。"
        className="nfc-panel-flush nfc-scan-summary">
        <ResponsiveDescriptions items={descriptionItems} />
        <div className="nfc-root-list">
          <span className="nfc-root-list-label">扫描根目录</span>
          <div className="nfc-root-list-values">
            {scan.roots.map((root, index) => <CodePath value={root} key={index} />)}
          </div>
        </div>
      </DataPanel>

      {scan.status === 'completed' && (
        <DataPanel title="重复文件组"
          description="展开组查看各个文件成员；数据只读，不会直接修改文件。"
          action={<span className="nfc-panel-count">{groupsTotal ?? '—'} groups</span>}
          className="nfc-panel-flush nfc-v2-groups-panel" variant="dense">
          {groupsError ? (
            <div className="nfc-v2-group-status" role="alert">
              <ConsoleEmpty title="重复文件组加载失败"
                description={groupsFetchError instanceof Error
                  ? groupsFetchError.message : '请检查连接或重新加载扫描结果。'}
                action={<ConsoleButton onClick={() => refetchGroups()}>重新加载</ConsoleButton>} />
            </div>
          ) : groupsLoading ? (
            <div className="nfc-v2-group-status" role="status">正在加载重复文件组…</div>
          ) : groupItems.length === 0 ? (
            <ConsoleEmpty title="暂无重复文件组"
              description="扫描已完成，但当前页没有发现重复组。" />
          ) : (
            <ResponsiveDataView
              desktop={
                <div className="nfc-v2-groups-table-scroll">
                  <table className="nfc-v2-groups-table">
                    <thead><tr>
                      <th scope="col">组 ID</th>
                      <th scope="col">内容哈希</th>
                      <th scope="col">单文件大小</th>
                      <th scope="col">重复副本</th>
                      <th scope="col">预计可释放</th>
                      <th scope="col">成员</th>
                    </tr></thead>
                    <tbody>{groupItems.map(group => {
                      const expanded = expandedGroupIds.includes(group.id);
                      return (
                        <React.Fragment key={group.id}>
                          <tr>
                            <td><strong className="nfc-mono">#{group.id}</strong></td>
                            <td><span className="nfc-mono nfc-hash-value"
                              title={group.content_hash}>{group.content_hash.slice(0, 18)}…</span></td>
                            <td>{formatBytes(group.file_size)}</td>
                            <td className="nfc-v2-scan-number">{group.member_count} 份</td>
                            <td><strong className="nfc-data-emphasis">
                              {formatBytes(group.reclaimable_bytes)}
                            </strong></td>
                            <td>
                              <button type="button" className="nfc-v2-group-expand"
                                aria-expanded={expanded}
                                aria-controls={'nfc-group-members-' + group.id}
                                onClick={() => toggleGroup(group.id)}>
                                <ConsoleIcon name="chevron-right" size={15} />
                                {expanded ? '收起成员' : '查看成员'}
                              </button>
                            </td>
                          </tr>
                          {expanded && (
                            <tr className="nfc-v2-group-member-row">
                              <td colSpan={6} id={'nfc-group-members-' + group.id}>
                                {memberTable(group)}
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}</tbody>
                  </table>
                </div>
              }
              mobile={
                <div className="nfc-mobile-record-list">
                  {groupItems.map(group => (
                    <article className="nfc-duplicate-group-mobile-card" key={group.id}>
                      <div className="nfc-mobile-record-heading">
                        <div>
                          <span className="nfc-mobile-record-title nfc-mono">Group #{group.id}</span>
                          <span className="nfc-kind-badge">{group.member_count} copies</span>
                        </div>
                        <span className="nfc-data-emphasis">{formatBytes(group.reclaimable_bytes)}</span>
                      </div>
                      <div className="nfc-mobile-record-facts">
                        <span>单文件大小 <b>{formatBytes(group.file_size)}</b></span>
                        <span>Hash <b className="nfc-mono" title={group.content_hash}>
                          {group.content_hash.slice(0, 14)}…
                        </b></span>
                      </div>
                      <details className="nfc-duplicate-member-list">
                        <summary>查看 {group.members.length} 个成员</summary>
                        <div>{group.members.map(member => (
                          <div className="nfc-duplicate-member" key={member.id}>
                            <span className="nfc-kind-badge">root #{member.root_id}</span>
                            <CodePath value={member.path} />
                            <span className="nfc-table-meta">{formatBytes(member.size)}</span>
                          </div>
                        ))}</div>
                      </details>
                    </article>
                  ))}
                </div>
              }
            />
          )}
          {!groupsError && !groupsLoading && (groupsData?.total || 0) > 0 && (
            <ConsolePagination page={page} pageSize={pageSize}
              total={groupsData?.total || 0} pageSizes={[10, 20, 50, 100]}
              onChange={changePage} />
          )}
        </DataPanel>
      )}

      <DedupePlanModal scanId={scanId} open={planModalOpen}
        onClose={() => setPlanModalOpen(false)} />
      <DedupeDiagnosticModal open={diagnosticOpen}
        onClose={() => setDiagnosticOpen(false)} scanJobId={scanId} />
    </div>
  );
};
