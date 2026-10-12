import React, { useEffect, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { filenameAuditApi, plansApi } from '../../api/domain';
import type { FilenameAuditPreview, FilenameAuditRow, FilenameIssue } from '../../api/domain';
import { getStructuredApiError } from '../../api/errors';
import {
  type FilenameAuditFilterMode, buildFilenameAuditRequest, buildFilenameAuditCsv,
  buildFilenameAuditPlanItems, canCreateFilenameAuditPlan,
  filterFilenameAuditRows, isFilenameAuditRepairable,
} from '../../utils/filenameAuditSafety';
import { DirectoryPicker } from '../../components/DirectoryPicker';
import { PageHeader } from '../../components/ui/PageHeader';
import { DataPanel } from '../../components/ui/DataPanel';
import { ActionBar } from '../../components/ui/ActionBar';
import { CodePath } from '../../components/ui/CodePath';
import { ResponsiveDataView } from '../../components/ui/ResponsiveDataView';
import { ConsoleButton } from '../../components/ui/ConsoleButton';
import { ConsoleIcon } from '../../components/ui/ConsoleIcon';
import { ConsoleEmpty } from '../../components/ui/ConsoleEmpty';
import { ConsolePagination } from '../../components/ui/ConsolePagination';
import { useConsoleToast } from '../../components/ui/ConsoleToast';
import { getPaginationState } from '../../components/ui/paginationModel';
import { useTitle } from '../../hooks/useTitle';

const labels: Record<FilenameIssue, string> = {
  edge_whitespace: '首尾空白字符',
  windows_trailing_dot_space: 'Windows 不支持的末尾句点/空格',
  windows_invalid_character: 'Windows 不兼容字符',
  windows_reserved_device: 'Windows 保留设备名',
  invisible_or_control: '控制或不可见字符',
  unicode_non_nfc: '非 NFC Unicode',
  long_name: '名称较长（超过 240 字节）',
  repeated_extension: '重复扩展名',
  suspicious_double_extension: '需人工检查的双扩展名',
};
const issueCodes = Object.keys(labels) as FilenameIssue[];

function exportReport(rows: readonly FilenameAuditRow[]): void {
  const csv = buildFilenameAuditCsv(rows);
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'nas-filename-audit.csv';
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Read-only Filename Audit -> explicit rename draft, never a filesystem executor. */
export const FilenameAuditPage: React.FC = () => {
  useTitle('文件名质量巡检');
  const navigate = useNavigate();
  const toast = useConsoleToast();
  const [parent, setParent] = useState('');
  const [result, setResult] = useState<FilenameAuditPreview | null>(null);
  const [filter, setFilter] = useState<FilenameAuditFilterMode>('all');
  const [selected, setSelected] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(30);
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
    setResult(null);
    setFilter('all');
    setSelected([]);
    setPage(1);
  };
  const patchParent = (next: string) => {
    if (planGuard.current) return;
    setParent(next);
    invalidatePreview();
  };

  const previewMutation = useMutation({ mutationFn: filenameAuditApi.preview });
  const planMutation = useMutation({ mutationFn: plansApi.createPlan });
  const busy = previewLoading || planLoading;
  const canPlan = canCreateFilenameAuditPlan(
    result, activePreviewKey.current, selected,
    busy || previewGuard.current || planGuard.current,
  );

  const runPreview = async () => {
    if (previewGuard.current || planGuard.current) return;
    const input = buildFilenameAuditRequest(parent);
    if (!input) {
      toast.error('请选择需要巡检的目录');
      return;
    }
    invalidatePreview();
    const ticket = requestTicket.current;
    const key = JSON.stringify(input);
    activePreviewKey.current = key;
    previewGuard.current = true;
    setPreviewLoading(true);
    try {
      const report = await previewMutation.mutateAsync(input);
      // The ticket also protects against an A -> B -> A directory ABA edit.
      if (!mountedRef.current || requestTicket.current !== ticket ||
          activePreviewKey.current !== key) return;
      setResult(report);
      toast.success('已检查 ' + report.checked_regular_files +
        ' 个普通文件，发现 ' + report.total + ' 个问题文件名');
    } catch (error: unknown) {
      if (mountedRef.current && requestTicket.current === ticket &&
          activePreviewKey.current === key) {
        invalidatePreview();
        toast.error(getStructuredApiError(error).message || '文件名巡检失败');
      }
    } finally {
      previewGuard.current = false;
      if (mountedRef.current) setPreviewLoading(false);
    }
  };

  const createDraft = async () => {
    if (planGuard.current || previewGuard.current || !canPlan || !result) return;
    const currentInput = buildFilenameAuditRequest(parent);
    const key = activePreviewKey.current;
    if (!currentInput || JSON.stringify(currentInput) !== key) return;
    const captured = result;
    const selectedPaths = [...selected];
    const ticket = requestTicket.current;
    planGuard.current = true;
    setPlanLoading(true);
    try {
      // Server always re-evaluates the original canonical parent and every selected suggestion.
      const fresh = await filenameAuditApi.preview({ parent: captured.parent });
      if (!mountedRef.current || requestTicket.current !== ticket ||
          activePreviewKey.current !== key) return;
      const items = buildFilenameAuditPlanItems(captured, fresh, selectedPaths);
      if (!items) {
        invalidatePreview();
        toast.info('源文件或目标建议已变化，请重新巡检并选择');
        return;
      }
      const created = await planMutation.mutateAsync({
        name: '文件名质量巡检：首尾空格修复',
        kind: 'rename',
        items,
      });
      if (!mountedRef.current || requestTicket.current !== ticket) return;
      toast.success('已创建文件名修复计划 #' + created.id + '，还需冻结与校验');
      navigate('/plans/' + created.id);
    } catch (error: unknown) {
      if (mountedRef.current && requestTicket.current === ticket) {
        toast.error(getStructuredApiError(error).message || '重新验证候选文件失败');
      }
    } finally {
      planGuard.current = false;
      if (mountedRef.current) setPlanLoading(false);
    }
  };

  const visible = filterFilenameAuditRows(result?.items || [], filter);
  const pagination = getPaginationState(page, pageSize, visible.length);
  const visiblePage = visible.slice((pagination.current - 1) * pageSize, pagination.current * pageSize);
  const pageReady = visiblePage.filter(isFilenameAuditRepairable);
  const allPageChecked = pageReady.length > 0 && pageReady.every(row => selected.includes(row.path));
  const somePageChecked = pageReady.some(row => selected.includes(row.path));

  const toggleSelected = (path: string, checked: boolean) => {
    if (planGuard.current) return;
    setSelected(previous => checked
      ? [...previous.filter(value => value !== path), path]
      : previous.filter(value => value !== path));
  };
  const togglePage = (checked: boolean) => {
    if (planGuard.current) return;
    const keys = new Set(pageReady.map(row => row.path));
    setSelected(previous => checked
      ? [...previous.filter(path => !keys.has(path)), ...keys]
      : previous.filter(path => !keys.has(path)));
  };

  const rowIssues = (row: FilenameAuditRow) => (
    <div className="nfc-v2-filename-issues">
      {row.issues.map(issue => (
        <span key={issue}
          className={'nfc-v2-filename-issue' +
            (issue === 'suspicious_double_extension' ? ' is-caution' : '')}>
          {labels[issue] || issue}
        </span>
      ))}
    </div>
  );
  const suggestion = (row: FilenameAuditRow) => isFilenameAuditRepairable(row)
    ? <CodePath value={row.suggested_target!} />
    : <span className="nfc-v2-filename-muted">
      {row.suggestion_block_reason || '仅报告，需手工判断'}
    </span>;

  return (
    <div className="nfc-operations-page nfc-filename-audit-page nfc-page-layout-workbench nfc-v2-filename-audit">
      <PageHeader title="文件名质量巡检"
        description="只读检查所选目录下一级普通文件的名称质量；检测结果不代表内容损坏或恶意文件。" />
      <DataPanel title="巡检目录"
        description="最多检查 10,000 个直接条目。不递归、不打开文件内容、跳过目录与符号链接。"
        className="nfc-complex-form-panel nfc-file-tool-form nfc-tool-workbench">
        <div className="nfc-v2-filename-form">
          <div className="nfc-v2-filename-field">
            <label id="nfc-filename-directory-label">目标目录</label>
            <div aria-labelledby="nfc-filename-directory-label">
              <DirectoryPicker value={parent} disabled={planLoading}
                placeholder="选择文件名质量巡检目录"
                onChange={value => patchParent(typeof value === 'string' ? value : value[0] || '')} />
            </div>
          </div>
          <ActionBar className="nfc-file-tool-primary-actions">
            <ConsoleButton variant="primary" loading={previewLoading} disabled={planLoading}
              leadingIcon={<ConsoleIcon name="file-search" size={17} />}
              onClick={() => { void runPreview(); }}>
              开始只读巡检
            </ConsoleButton>
          </ActionBar>
        </div>
      </DataPanel>
      <div className="nfc-v2-filename-notice nfc-page-alert" role="note">
        <ConsoleIcon name="info" size={19} />
        <div>
          <strong>巡检结果是风险提示，不自动修改 NAS 数据</strong>
          <p>重复扩展名、双扩展名、Unicode 和 Windows 兼容性问题需要人工判断。
            只对首尾普通空格提供修复建议，仍需创建 Rename Plan、冻结与校验后才能执行。</p>
        </div>
      </div>
      {result && (
        <DataPanel title="巡检报告" variant="dense"
          className="nfc-panel-flush nfc-file-tool-result-panel"
          description={'已扫描 ' + result.scanned + ' 项；普通文件 ' +
            result.checked_regular_files + ' 个；忽略 ' + result.ignored_entries +
            ' 项；问题 ' + result.issues_total + ' 处'}
          action={<span className="nfc-panel-count">{visible.length} / {result.total} 个文件</span>}>
          <ActionBar className="nfc-v2-filename-actions">
            <label className="nfc-v2-filename-filter">
              <span>筛选问题</span>
              <select value={filter} disabled={planLoading}
                onChange={event => { setFilter(event.target.value as FilenameAuditFilterMode); setPage(1); }}>
                <option value="all">全部问题</option>
                <option value="fixable">可建议修复</option>
                {issueCodes.map(code => <option key={code} value={code}>{labels[code]}</option>)}
              </select>
            </label>
            <ConsoleButton disabled={!visible.length || planLoading}
              leadingIcon={<ConsoleIcon name="arrow-down" size={17} />}
              onClick={() => exportReport(visible)}>导出 CSV（{visible.length}）</ConsoleButton>
            <ConsoleButton variant="primary" loading={planLoading} disabled={!canPlan}
              leadingIcon={<ConsoleIcon name="calendar" size={17} />}
              onClick={() => { void createDraft(); }}>
              生成修复 Plan（{selected.length}）
            </ConsoleButton>
          </ActionBar>
          <p className="nfc-v2-filename-selection-hint" role="status">
            已选 {selected.length} 个安全建议；仅勾选候选进入 Draft，切换筛选或分页保留选择。
          </p>
          {visible.length === 0 ? (
            <ConsoleEmpty title="未发现匹配的问题文件名"
              description="调整筛选或选择其他目录重新执行只读巡检。" />
          ) : (
            <ResponsiveDataView
              desktop={
                <div className="nfc-v2-filename-table-scroll">
                  <table className="nfc-v2-filename-table">
                    <caption>文件名巡检结果与安全修复建议</caption>
                    <thead><tr>
                      <th scope="col" className="nfc-v2-filename-select-col">
                        <input type="checkbox" aria-label="选择当前页可修复文件"
                          checked={allPageChecked} disabled={!pageReady.length || planLoading}
                          ref={element => { if (element) element.indeterminate = somePageChecked && !allPageChecked; }}
                          onChange={event => togglePage(event.target.checked)} />
                      </th>
                      <th scope="col">文件名（引号帮助识别空格）</th>
                      <th scope="col">问题类型</th>
                      <th scope="col">修复建议（仅首尾空格）</th>
                    </tr></thead>
                    <tbody>{visiblePage.map(row => (
                      <tr key={row.path}>
                        <td><input type="checkbox" aria-label={'选择文件 ' + row.name}
                          checked={selected.includes(row.path)}
                          disabled={!isFilenameAuditRepairable(row) || planLoading}
                          onChange={event => toggleSelected(row.path, event.target.checked)} /></td>
                        <td className="nfc-mono">{JSON.stringify(row.name)}</td>
                        <td>{rowIssues(row)}</td>
                        <td>{suggestion(row)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              }
              mobile={
                <div className="nfc-mobile-record-list nfc-v2-filename-mobile">
                  {visiblePage.map(row => (
                    <article className="nfc-rename-proposal-mobile-card" key={row.path}>
                      <div className="nfc-mobile-record-heading">
                        <span className="nfc-mono">{JSON.stringify(row.name)}</span>
                        {isFilenameAuditRepairable(row) && (
                          <label className="nfc-v2-filename-mobile-select">
                            <input type="checkbox" checked={selected.includes(row.path)}
                              disabled={planLoading} aria-label={'选择文件 ' + row.name}
                              onChange={event => toggleSelected(row.path, event.target.checked)} />
                            加入 Plan
                          </label>
                        )}
                      </div>
                      {rowIssues(row)}
                      <div className="nfc-v2-filename-mobile-suggestion">{suggestion(row)}</div>
                    </article>
                  ))}
                </div>
              }
            />
          )}
          <ConsolePagination page={pagination.current} pageSize={pageSize} total={visible.length}
            pageSizes={[10, 20, 30, 50, 100]}
            onChange={(nextPage, nextSize) => { setPage(nextPage); setPageSize(nextSize); }} />
        </DataPanel>
      )}
    </div>
  );
};
